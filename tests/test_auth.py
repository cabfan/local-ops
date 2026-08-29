import http.client
import json
import os
import tempfile
import threading
import unittest

import server


class AuthHttpHarness:
    """强制登录模式下基于回环 HTTP 的认证测试载具。

    与 test_hardening.HttpHarness 同构，但通过 config.auth.enforced=True
    在回环上也强制登录，从而覆盖登录业务接口全流程。
    """

    def __init__(self, enforced=True):
        self.tmp = tempfile.TemporaryDirectory()
        path = os.path.join(self.tmp.name, "config.json")
        self.config_path = path
        self.cfg = server.Config(path)
        if enforced:
            self.cfg.update(lambda c: c.setdefault("auth", {})
                            .update({"enforced": True}))
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
        result_headers = dict(response.getheaders())
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            payload = raw
        conn.close()
        return response.status, payload, result_headers

    def login_cookie(self):
        status, _, headers = self.request("POST", "/api/auth/setup",
                                          json.dumps({"password": "correctstaple"}))
        if status != 200:
            raise AssertionError("setup status=%r headers=%r" % (status, headers))
        value = headers.get("Set-Cookie", "")
        for part in value.split(","):
            if part.strip().startswith("console_login="):
                return part.strip().split(";", 1)[0]
        raise AssertionError("未在 Set-Cookie 中找到 console_login")


class AuthHttpSecurityTests(unittest.TestCase):
    def test_status_reports_forced_while_locked(self):
        h = AuthHttpHarness()
        try:
            status, body, _ = h.request("GET", "/api/auth/status",
                                        headers={"Content-Type": "application/json"})
            self.assertEqual(status, 200)
            self.assertTrue(body["ok"])
            self.assertTrue(body["forced"])
            self.assertFalse(body["loggedIn"])
            self.assertFalse(body["hasAccount"])
        finally:
            h.close()

    def test_state_is_blocked_without_session_when_forced(self):
        h = AuthHttpHarness()
        try:
            status, body, _ = h.request("GET", "/api/state")
            self.assertEqual(status, 401)
            self.assertFalse(body["ok"])
            self.assertEqual(body.get("auth"), "required")
        finally:
            h.close()

    def test_public_paths_reachable_while_locked(self):
        h = AuthHttpHarness()
        try:
            for path in ("/", "/base.css", "/app.js", "/themes/ops.css",
                         "/api/health", "/favicon.ico"):
                status, _, _ = h.request("GET", path)
                self.assertEqual(status, 200, path)
        finally:
            h.close()

    def test_setup_then_login_then_state(self):
        h = AuthHttpHarness()
        try:
            status, body, headers = h.request(
                "POST", "/api/auth/setup",
                json.dumps({"password": "correctstaple"}))
            self.assertEqual(status, 200)
            self.assertTrue(body["ok"])
            self.assertIn("HttpOnly", headers.get("Set-Cookie", ""))
            cookie = None
            for part in headers.get("Set-Cookie", "").split(","):
                if part.strip().startswith("console_login="):
                    cookie = part.strip().split(";", 1)[0]
                    break
            self.assertIsNotNone(cookie)

            status, body, _ = h.request("GET", "/api/auth/status",
                                        headers={"Cookie": cookie})
            self.assertTrue(body["loggedIn"])
            self.assertTrue(body["hasAccount"])

            status, _, _ = h.request("GET", "/api/state",
                                     headers={"Cookie": cookie})
            self.assertEqual(status, 200)
        finally:
            h.close()

    def test_wrong_password_is_rejected(self):
        h = AuthHttpHarness()
        try:
            h.request("POST", "/api/auth/setup",
                      json.dumps({"password": "correctstaple"}))
            status, body, _ = h.request(
                "POST", "/api/auth/login",
                json.dumps({"password": "wrong-password"}))
            self.assertEqual(status, 401)
            self.assertFalse(body["ok"])
        finally:
            h.close()

    def test_logout_revokes_session(self):
        h = AuthHttpHarness()
        try:
            cookie = h.login_cookie()
            status, _, _ = h.request("POST", "/api/auth/logout",
                                     json.dumps({}), headers={"Cookie": cookie})
            self.assertEqual(status, 200)
            status, body, _ = h.request("GET", "/api/state",
                                        headers={"Cookie": cookie})
            self.assertEqual(status, 401)
            self.assertEqual(body.get("auth"), "required")
        finally:
            h.close()

    def test_logout_does_not_leave_stale_body_on_keepalive(self):
        """浏览器用 keep-alive 长连接；POST logout 若不清空 {}/body，
        残留字节会把同连接的下一个 GET 污染成 '{}GET' → 501。"""
        h = AuthHttpHarness()
        try:
            h.request("POST", "/api/auth/setup",
                      json.dumps({"password": "correctstaple"}))
            conn = http.client.HTTPConnection(server.HOST, h.port, timeout=4)
            try:
                conn.request("POST", "/api/auth/logout",
                             body=b"{}",
                             headers={"Content-Type": "application/json"})
                resp = conn.getresponse()
                resp.read()
                self.assertEqual(resp.status, 200)

                conn.request("GET", "/")
                resp2 = conn.getresponse()
                resp2.read()
                self.assertEqual(resp2.status, 200)
            finally:
                conn.close()
        finally:
            h.close()

    def test_state_open_when_not_forced(self):
        h = AuthHttpHarness(enforced=False)
        try:
            status, body, _ = h.request("GET", "/api/auth/status")
            self.assertEqual(status, 200)
            self.assertFalse(body["forced"])
            status, _, _ = h.request("GET", "/api/state")
            self.assertEqual(status, 200)
        finally:
            h.close()


if __name__ == "__main__":
    unittest.main()