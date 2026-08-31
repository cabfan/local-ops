import http.client
import json
import os
import tempfile
import threading
import time
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

    def test_rerun_replaces_same_day_report(self):
        cfg = self.h.cfg
        db = server.auth_db_path(cfg)
        day = "2026-08-29"
        pid, _ = server.review_add_project(cfg, {
            "name": "svc-a", "remote": "https://x/svc-a.git"})
        project = server.review_get_project(cfg, pid)
        # 同日重复执行审查：报告与汇总都只保留最新一份
        server.review_save_report(db, day, project, "# 第一遍")
        server.review_save_report(db, day, project, "# 第二遍")
        server.review_save_summary(db, day, "# 汇总一")
        server.review_save_summary(db, day, "# 汇总二")
        reports = server.review_reports_for_day(cfg, day)
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["summary"], "# 第二遍")
        self.assertEqual(server.review_summary_for_day(cfg, day)["summary"],
                         "# 汇总二")

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

    def test_delete_day_clears_reports(self):
        cfg = self.h.cfg
        db = server.auth_db_path(cfg)
        day = "2026-08-29"
        pid, _ = server.review_add_project(cfg, {
            "name": "svc-a", "remote": "https://x/svc-a.git"})
        project = server.review_get_project(cfg, pid)
        server.review_save_report(db, day, project, "# hello")
        server.review_save_summary(db, day, "# summary")
        server._auth_exec(db,
                          "INSERT INTO review_push_logs(day, endpoint, "
                          "status, http_code, message, attempted_at) "
                          "VALUES(?,?,?,?,?,?)",
                          (day, "https://cloud/api/reports", "ok", 200, "",
                           "2026-08-29T03:00:00"))
        self.assertEqual(len(server.review_reports_for_day(cfg, day)), 1)
        self.assertTrue(server.review_delete_day(cfg, day))
        self.assertEqual(server.review_reports_for_day(cfg, day), [])
        self.assertIsNone(server.review_summary_for_day(cfg, day))
        self.assertEqual(server.review_push_logs(cfg, day), [])
        self.assertEqual(server.review_days(cfg), [])
        # 项目本身不受影响
        self.assertEqual(server.review_get_project(cfg, pid)["name"], "svc-a")

    def test_http_delete_reports(self):
        cfg = self.h.cfg
        db = server.auth_db_path(cfg)
        day = "2026-08-29"
        pid, _ = server.review_add_project(cfg, {
            "name": "svc-b", "remote": "https://x/svc-b.git"})
        server.review_save_report(db, day, server.review_get_project(cfg, pid),
                                  "# hello")
        # 日期格式非法 → 400
        status, _ = self.h.request("DELETE", "/api/review/reports/not-a-day")
        self.assertEqual(status, 400)
        # 合法日期 → 200 且数据被清除
        status, body = self.h.request("DELETE",
                                      "/api/review/reports/%s" % day)
        self.assertEqual(status, 200, body)
        self.assertTrue(body["ok"])
        self.assertIsNone(server.review_summary_for_day(cfg, day))
        self.assertEqual(server.review_reports_for_day(cfg, day), [])

    def test_parse_hermes_sections(self):
        text = ("引言\n## 项目：a\nA 内容\n## 项目：b\nB 内容\n"
                "## 跨项目风险\nX")
        sections = server._parse_hermes_sections(text)
        self.assertEqual([n for n, _ in sections], ["a", "b"])
        self.assertIn("A 内容", sections[0][1])
        self.assertIn("X", sections[1][1])
        # 跨项目风险不是独立项目分节
        self.assertNotIn("c", [n for n, _ in sections])
        self.assertEqual(server._parse_hermes_sections("没有分节"), [])

    def test_hermes_run_day_splits_sections(self):
        cfg = self.h.cfg
        day = "2026-08-29"
        pid1, _ = server.review_add_project(cfg, {
            "name": "alpha", "remote": "https://x/alpha.git"})
        pid2, _ = server.review_add_project(cfg, {
            "name": "beta", "remote": "https://x/beta.git"})
        markdown = ("## 项目：alpha\nalpha 报告内容\n"
                    "## 项目：beta\nbeta 报告内容\n## 跨项目风险\n共性问题")

        def fake_fetch(remote, branch, workdir, project):
            return "/data/review/" + server._review_safe_name(
                project["name"])

        original = (server._review_fetch, server._hermes_review,
                    server.REVIEW_WORK_DIR)
        server._review_fetch = fake_fetch
        server._hermes_review = lambda wd, p: markdown
        server.REVIEW_WORK_DIR = self.h.tmp.name
        try:
            text = server.review_run_day(cfg, day)
        finally:
            (server._review_fetch, server._hermes_review,
             server.REVIEW_WORK_DIR) = original
        self.assertIn("跨项目风险", text)
        reports = {r["project_name"]: r
                   for r in server.review_reports_for_day(cfg, day)}
        self.assertEqual(set(reports), {"alpha", "beta"})
        self.assertEqual(reports["alpha"]["project_id"], pid1)
        self.assertEqual(reports["beta"]["project_id"], pid2)
        self.assertIn("beta 报告内容", reports["beta"]["summary"])
        self.assertIsNotNone(server.review_summary_for_day(cfg, day))

    def test_review_job_tracked(self):
        cfg = self.h.cfg
        original = server.review_run_day
        calls = []
        server.review_run_day = lambda c, d: calls.append(d)
        try:
            self.assertTrue(server.review_run_tracked(cfg, "2026-08-29"))
            job = server.review_job_status()
            self.assertFalse(job["running"])
            self.assertTrue(job["ok"])
            self.assertEqual(job["day"], "2026-08-29")
            self.assertEqual(calls, ["2026-08-29"])

            def boom(c, d):
                raise RuntimeError("x")
            server.review_run_day = boom
            self.assertFalse(server.review_run_tracked(cfg, "2026-08-30"))
            job = server.review_job_status()
            self.assertFalse(job["running"])
            self.assertFalse(job["ok"])
            self.assertIn("x", job["error"])
        finally:
            server.review_run_day = original

    def _wait_job_idle(self):
        for _ in range(200):
            if not server.review_job_status()["running"]:
                return
            time.sleep(0.02)

    def test_review_start_async_mutex(self):
        cfg = self.h.cfg
        started = threading.Event()
        release = threading.Event()

        def slow_run(c, d):
            started.set()
            release.wait(2)

        original = server.review_run_day
        server.review_run_day = slow_run
        try:
            self.assertTrue(server.review_start_async(cfg, "2026-08-29"))
            self.assertTrue(started.wait(2))
            # 任务执行中再次启动被拒绝
            second = server.review_start_async(cfg, "2026-08-30")
            self.assertFalse(second)
            release.set()
            self._wait_job_idle()
            job = server.review_job_status()
            self.assertFalse(job["running"])
            self.assertTrue(job["ok"])
        finally:
            release.set()
            server.review_run_day = original

    def test_http_review_status(self):
        status, body = self.h.request("GET", "/api/review/status")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertIn("running", body["job"])

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