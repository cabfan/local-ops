import http.client
import json
import os
import tempfile
import threading
import unittest

import server


class ReviewHarness:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.tmp.name, "config.json")
        self.cfg = server.Config(self.config_path)
        self.httpd = server.ConsoleServer(
            (server.HOST, 0), server.Handler, self.cfg, 0)
        self.port = self.httpd.server_address[1]
        server.invalidate_state_cache()
        self.thread = threading.Thread(
            target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection(server.HOST, self.port, timeout=4)
        request_headers = dict(headers or {})
        if body is not None:
            if isinstance(body, str):
                body = body.encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=body, headers=request_headers)
        response = conn.getresponse()
        raw = response.read()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            payload = raw
        conn.close()
        return response.status, payload


class ReviewDataTests(unittest.TestCase):
    def setUp(self):
        self.h = ReviewHarness()

    def tearDown(self):
        self.h.close()

    def test_project_crud(self):
        cfg = self.h.cfg
        self.assertEqual(server.review_projects(cfg), [])
        pid, err = server.review_add_project(cfg, {
            "name": "order-api",
            "remote": "https://gitlab.example.com/team/order-api.git",
            "branch": "main",
        })
        self.assertIsNone(err)
        self.assertTrue(pid)
        projects = server.review_projects(cfg)
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["name"], "order-api")
        self.assertTrue(projects[0]["enabled"])

        # 重名拒绝
        pid2, err = server.review_add_project(cfg, {
            "name": "order-api",
            "remote": "https://x.git"})
        self.assertIsNone(pid2)
        self.assertIn("已存在", err)

        # 更新
        self.assertTrue(server.review_update_project(cfg, pid,
                                                     {"enabled": False, "branch": "develop"}))
        updated = server.review_get_project(cfg, pid)
        self.assertFalse(updated["enabled"])
        self.assertEqual(updated["branch"], "develop")

        # 删除
        server.review_delete_project(cfg, pid)
        self.assertEqual(server.review_projects(cfg), [])

    def test_report_and_push_payload(self):
        cfg = self.h.cfg
        db = server.auth_db_path(cfg)
        day = "2026-08-29"
        pid, _ = server.review_add_project(cfg, {
            "name": "svc-a", "remote": "https://x/svc-a.git"})
        project = server.review_get_project(cfg, pid)
        server.review_save_report(db, day, project, "# hello")
        server.review_save_summary(db, day, "# today summary")
        payload = server.review_push_payload(cfg, day)
        self.assertEqual(payload["day"], day)
        self.assertEqual(len(payload["projects"]), 1)
        self.assertEqual(payload["projects"][0]["project"], "svc-a")
        self.assertEqual(payload["projects"][0]["report"], "# hello")
        self.assertIn("today", payload["summary"])
        self.assertEqual(len(server.review_days(cfg)), 1)

    def test_http_state_and_report_endpoint(self):
        status, body = self.h.request("GET", "/api/review")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["projects"], [])
        self.assertEqual(body["days"], [])

    def test_http_create_list_delete(self):
        status, body = self.h.request("POST", "/api/review/projects", json.dumps({
            "name": "pay",
            "remote": "https://gitlab.example.com/t/pay.git",
            "branch": "main"}))
        self.assertEqual(status, 200, body)
        pid = body["id"]
        status, body = self.h.request("GET", "/api/review")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["projects"]), 1)
        status, body = self.h.request("DELETE", "/api/review/projects/%d" % pid)
        self.assertEqual(status, 200)
        status, body = self.h.request("GET", "/api/review")
        self.assertEqual(body["projects"], [])

    def test_config_save(self):
        status, body = self.h.request("POST", "/api/review/config", json.dumps({
            "schedule": {"enabled": True, "hour": 4, "minute": 30},
            "ai": {"baseUrl": "https://llm/v1", "model": "qwen"},
            "push": {"endpoint": "https://cloud/api/reports"}}))
        self.assertEqual(status, 200, body)
        self.assertTrue(body["review"]["schedule"]["enabled"])
        status, body = self.h.request("GET", "/api/review")
        self.assertEqual(body["schedule"]["hour"], 4)
        self.assertTrue(body["configured"])


    def test_public_project_hides_token(self):
        cfg = self.h.cfg
        pid, _ = server.review_add_project(cfg, {
            "name": "sec", "remote": "https://gitlab.example.com/t/sec.git",
            "auth_type": "token", "auth_token": "glpat-secret123"})
        self.assertTrue(pid)
        pub = server._review_public_project(server.review_get_project(cfg, pid))
        self.assertNotIn("auth_token", pub)
        self.assertTrue(pub["has_token"])
        self.assertNotIn("glpat-secret123", json.dumps(pub))
        # 未配置 token 的项目 has_token 为 False
        pid2, _ = server.review_add_project(cfg, {
            "name": "plain", "remote": "https://gitlab.example.com/t/p.git"})
        pub2 = server._review_public_project(server.review_get_project(cfg, pid2))
        self.assertFalse(pub2["has_token"])

    def test_update_with_blank_token_keeps_existing(self):
        cfg = self.h.cfg
        pid, _ = server.review_add_project(cfg, {
            "name": "keep", "remote": "https://gitlab.example.com/t/keep.git",
            "auth_type": "token", "auth_token": "glpat-keep"})
        # 空 token 只在显式带上时视为保留，编辑其它字段不会清掉凭证
        self.assertTrue(server.review_update_project(
            cfg, pid, {"branch": "dev", "auth_token": ""}))
        updated = server.review_get_project(cfg, pid)
        self.assertEqual(updated["auth_token"], "glpat-keep")
        self.assertEqual(updated["branch"], "dev")

    def test_mask_token(self):
        self.assertEqual(
            server._review_mask_token(
                "fatal: unable to access 'https://glpat-x@gitlab.example.com/t.git/'",
                "glpat-x"),
            "fatal: unable to access 'https://***@gitlab.example.com/t.git/'")
        # token 为空时原样返回
        self.assertEqual(server._review_mask_token("plain message", ""), "plain message")

    def test_http_state_hides_token(self):
        status, _ = self.h.request("POST", "/api/review/projects", json.dumps({
            "name": "hides",
            "remote": "https://gitlab.example.com/t/hides.git",
            "auth_type": "token", "auth_token": "glpat-net-secret"}))
        self.assertEqual(status, 200)
        status, body = self.h.request("GET", "/api/review")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["projects"]), 1)
        self.assertNotIn("auth_token", body["projects"][0])
        self.assertTrue(body["projects"][0]["has_token"])
        self.assertNotIn("glpat-net-secret", json.dumps(body))


if __name__ == "__main__":
    unittest.main()