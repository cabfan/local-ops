#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""console-ui 独立预览用 mock 后端（仅 Python 3 标准库，零依赖）。

用法:
    python mock_server.py [--port 9600] [--no-browser]

启动后访问 http://127.0.0.1:9600/ 即可预览提取出的前端 UI。
前端通过 config.js 里的 window.__CONSOLE_CONFIG__.apiBase 指向后端；
本 mock 与前端同源托管，因此开箱即用。

接入你自己的项目时，只要实现下面这些 /api/* JSON 接口（形状见本文件
与 README.md「接入真实后端」一节），前端无需任何改动：
    GET  /api/state                    轮询主数据（2s 一次）
    GET  /api/apps/{id}/logs?tail=300  应用日志 -> {"text": "..."}
    GET  /api/console/log?tail=300     控制台日志 -> {"text": "..."}
    POST /api/apps                     创建应用（可带 attachPid）
    PUT  /api/apps/{id}                更新应用（运行中改 command/cwd/port/kind 需先停）
    DELETE /api/apps/{id}              删除应用
    POST /api/apps/{id}/start|stop|restart
    POST /api/apps/{id}/diagnose       运行诊断 -> {ok, issues:[...], summary}
    POST /api/apps/{id}/attach         认领进程 {pid} -> {ok, pid, cwd?...}
    POST /api/apps/{id}/favicon        抓取 favicon -> {ok, favicon}
    POST /api/apps/{id}/icon           上传图标（原始字节 body）
    DELETE /api/apps/{id}/icon
    POST /api/apps/reorder             拖拽排序 {ids:[...]}
    POST /api/services/flag            置顶/隐藏/提升 {key, flag, value}
    POST /api/watch                    关注进程 {keyword, action: add|remove}
    POST /api/kill                     结束进程 {pid, force?}
    POST /api/project/detect           项目识别 {cwd} -> {ok, name, candidates:[...]}
    POST /api/pick                     文件/目录选择 {what} -> {ok, path} | {ok, canceled}
    POST /api/ui/theme                 切换主题 {theme}
    POST /api/console/restart|stop     重启/停止控制台（mock 中只返回 ok）

mock 特性（演示用）:
    - 每次 /api/state 轮询时 CPU 抖动、运行时长递增；
    - 「数据迁移」任务启动后约 12 秒自动完成 -> 触发任务完成提示；
    - 启动约 20 秒后自动“出现”一个新端口服务 -> 触发端口发现栏；
    - 图标/ favicon 上传保存在内存，通过 /icons/* 提供；
    - 所有 /api/* 带 CORS 头，支持跨源开发联调。
"""

import json
import os
import random
import secrets
import struct
import sys
import time
import urllib.parse
import webbrowser
import zlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HOST = "127.0.0.1"
PORT_START = 9600
PORT_TRIES = 10
PREFIX = ""                  # 由 --prefix 设置：在子路径下托管（如 /tools/console-ui）

# ---- 登录认证（演示用） ----
AUTH_ENABLED = True          # --no-auth 关闭
USERS = {"admin": "admin123"}   # 演示账号：admin / admin123
TOKENS = set()               # 已签发的令牌

APP_VERSION = "1.0.0"
SCHEMA_VERSION = 1
NOW = time.time()

# ---------------------------------------------------------------- mock 数据
def _mk_app(app_id, name, command, cwd, port, glyph, kind, **kw):
    return {
        "id": app_id, "name": name, "command": command, "cwd": cwd,
        "port": port, "emoji": None, "glyph": glyph, "icon": None,
        "favicon": None, "kind": kind, "attached": False,
        "running": False, "pid": None, "uptimeSec": 0,
        "listening": False, "portOccupied": False, "portOccupiedPid": None,
        "portConflict": False, "portConflictApps": [],
        "lastExit": None, "health": {"status": "ok", "blocking": False, "issues": []},
        "ports": [], "openHost": None, "openHosts": {},
        "createdAt": int(NOW), **kw,
    }

def _mk_service(pid, name, port, cwd, project, cmd, group, cpu, mem, uptime, origin_label, origin_icon, **kw):
    return {
        "key": "%s:%d" % (name, port), "instanceKey": "%d:%d" % (pid, port),
        "pid": pid, "name": name, "port": port, "cwd": cwd, "project": project,
        "cmd": cmd, "cpu": cpu, "mem": mem, "uptimeSec": uptime,
        "group": group, "pinned": False, "hidden": False, "promoted": False,
        "appId": None, "appName": None,
        "origin": {"label": origin_label, "icon": origin_icon}, **kw,
    }

def _mk_watch(pid, name, cmd, cpu, mem, uptime, keyword):
    return {"pid": pid, "name": name, "cmd": cmd, "cpu": cpu, "mem": mem,
            "uptimeSec": uptime, "keyword": keyword}

class MockState:
    """内存态 + 轮询时的“活数据”演化。"""

    def __init__(self):
        self.boot = time.time()
        self.console_pid = 40123
        self.console_port = None       # 实际端口启动后回填
        self.console_cwd = BASE_DIR
        self.ui_theme = "ops"
        self.themes = [{
            "id": "ops", "name": "指挥台", "author": "local-ops",
            "desc": "深空蓝黑 / 雾灰双色指挥台", "colors": ["#0b1220", "#f2f4f8", "#3b82f6"],
        }]
        self.watched_keywords = ["ffmpeg"]
        self.discovery_injected = False
        self.icon_bytes = {}           # id -> png bytes
        self.favicon_bytes = {}        # id -> png bytes
        self.next_pid = 80001
        self.apps = [
            _mk_app("a1b2c3d4", "我的博客", "python3 -m http.server 8080",
                    "/Users/demo/blog", 8080, "globe", "service"),
            _mk_app("b2c3d4e5", "API 服务", "uvicorn main:app --port 3000",
                    "/Users/demo/api", 3000, "server", "service"),
            _mk_app("c3d4e5f6", "日志备份", "bash backup.sh",
                    "/Users/demo/scripts", None, "file-text", "task"),
            _mk_app("d4e5f6a7", "数据迁移", "python migrate.py",
                    "/Users/demo/scripts", None, "database", "task"),
            _mk_app("e5f6a7b8", "邮件提醒", "node sender.js",
                    "/Users/demo/mailer", 2525, None, "service"),
        ]
        self.services = [
            _mk_service(54252, "python3.12", 8791, "/Users/demo/blog", "blog",
                        "python3 app.py", "mine", 0.3, 1.2, 7980, "Codex", "bot"),
            _mk_service(62101, "node", 8080, "/Users/demo/blog", "blog",
                        "python3 -m http.server 8080", "mine", 0.1, 0.6, 3120, "终端", "terminal",
                        appId="a1b2c3d4", appName="我的博客"),
            _mk_service(61833, "node", 5173, "/Users/demo/vite-app", "vite-app",
                        "npm run dev", "mine", 2.4, 1.9, 1540, "VS Code", "code"),
            _mk_service(64990, "node", 3000, "/Users/demo/old-api", "old-api",
                        "node server.js", "mine", 0.8, 1.1, 4200, "终端", "terminal"),
            _mk_service(64021, "postgres", 5432, "/usr/local/var/postgres", "postgres",
                        "postgres -D /usr/local/var/postgres", "background", 0.0, 2.4, 99999, "终端", "terminal"),
            _mk_service(66307, "ollama", 11434, "/Users/demo", "demo",
                        "ollama serve", "mine", 1.1, 0.9, 36000, "终端", "terminal"),
        ]
        self.watched = [
            _mk_watch(70001, "ffmpeg", "ffmpeg -i in.mp4 out.mp4",
                      4.2, 0.5, 68, "ffmpeg"),
        ]

    # -- 演化 -------------------------------------------------------
    def tick(self):
        """每次 /api/state 调用时推进状态，制造“活”的效果。"""
        elapsed = time.time() - self.boot
        for s in self.services:
            s["uptimeSec"] += 2
            base = {"python3.12": 0.3, "postgres": 0.0, "ollama": 1.1}.get(s["name"], 1.0)
            s["cpu"] = round(max(0.0, base + random.uniform(-0.3, 1.8)), 2)
            s["mem"] = round(max(0.1, s.get("mem", 1.0) + random.uniform(-0.05, 0.05)), 2)
        for w in self.watched:
            w["uptimeSec"] += 2
            w["cpu"] = round(max(0.0, w["cpu"] + random.uniform(-1.5, 1.5)), 2)
        for app in self.apps:
            if app["running"]:
                app["uptimeSec"] += 2
            # 端口被“别人”占用：node:3000 占着 b2c3d4e5 的 3000
            app["portOccupied"] = (not app["running"] and app["port"] == 3000)
            app["portOccupiedPid"] = 64990 if app["portOccupied"] else None
            # 运行中且监听 -> 提供可打开地址
            if app["running"] and app["kind"] == "service" and app["port"]:
                app["listening"] = True
                app["ports"] = [app["port"]]
                app["openHost"] = "127.0.0.1"
                app["openHosts"] = {str(app["port"]): "127.0.0.1"}
            else:
                app["listening"] = False
                app["ports"] = []
                app["openHost"] = None
                app["openHosts"] = {}
        # 数据迁移任务：运行约 12 秒后自动成功
        for app in self.apps:
            if app["id"] == "d4e5f6a7" and app["running"]:
                if app.get("_task_started") and time.time() - app["_task_started"] >= 12:
                    app["running"] = False
                    app["pid"] = None
                    app["lastExit"] = {
                        "status": "succeeded", "code": 0,
                        "at": int(time.time()), "startedAt": int(app["_task_started"] * 1000),
                        "durationSec": 12.0,
                    }
                    app["_task_started"] = None
        # 启动约 20 秒后“新出现”一个端口 -> 触发端口发现栏
        if not self.discovery_injected and elapsed >= 20:
            self.discovery_injected = True
            self.services.append(_mk_service(
                65500, "node", 4000, "/Users/demo/fresh-app", "fresh-app",
                "node server.js", "mine", 0.5, 0.8, 3, "终端", "terminal"))

    # -- 工具 --------------------------------------------------------
    def app_by_id(self, app_id):
        return next((a for a in self.apps if a["id"] == app_id), None)

    def service_by_key(self, key):
        return next((s for s in self.services if s["key"] == key), None)

    def service_by_pid(self, pid):
        return next((s for s in self.services if s["pid"] == pid), None)

    def state_payload(self):
        self.tick()
        return {
            "services": self.services,
            "watched": self.watched,
            "apps": self.apps,
            "watchedKeywords": self.watched_keywords,
            "consolePort": self.console_port,
            "consolePid": self.console_pid,
            "consoleCwd": self.console_cwd,
            "version": APP_VERSION,
            "schemaVersion": SCHEMA_VERSION,
            "degraded": False,
            "degradedReasons": [],
            "themes": self.themes,
            "uiTheme": self.ui_theme,
        }


MOCK = MockState()


# ---------------------------------------------------------------- 小工具
def json_bytes(obj):
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def make_png(rgb=(59, 130, 246), size=16):
    """纯标准库生成纯色 PNG（icon / favicon 占位）。"""
    r, g, b = rgb

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    row = bytes((r, g, b)) * size
    raw = b"".join(b"\x00" + row for _ in range(size))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


def guess_type(path):
    return CONTENT_TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


# ---------------------------------------------------------------- HTTP 处理
class Handler(BaseHTTPRequestHandler):
    server_version = "console-ui-mock/1.0"
    protocol_version = "HTTP/1.1"

    # -- 基础 --------------------------------------------------------
    def log_message(self, fmt, *args):
        sys.stderr.write("[mock] %s %s\n" % (self.address_string(), fmt % args))

    def _read_body(self, max_bytes=8 * 1024 * 1024):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return b""
        if length > max_bytes:
            return b""
        return self.rfile.read(length)

    def _send_json(self, obj, status=200):
        body = json_bytes(obj)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._send_cors()
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body, ctype, status=200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._send_cors()
        self.end_headers()
        self.wfile.write(body)

    def _send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _is_api(self, path):
        return path.startswith("/api/")

    # ---- 登录认证 ----
    def _authorized(self):
        if not AUTH_ENABLED:
            return True
        header = self.headers.get("Authorization") or ""
        return header.startswith("Bearer ") and header[7:] in TOKENS

    def _handle_login(self):
        body = self._read_json() or {}
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        if not AUTH_ENABLED:
            token = secrets.token_hex(16)
            TOKENS.add(token)
            self._send_json({"ok": True, "token": token, "name": username or "demo"})
            return
        if username in USERS and USERS[username] == password:
            token = secrets.token_hex(16)
            TOKENS.add(token)
            self._send_json({"ok": True, "token": token, "name": username})
        else:
            self._send_json({"ok": False, "error": "用户名或密码错误"}, 401)

    def _handle_logout(self):
        self._read_json()
        header = self.headers.get("Authorization") or ""
        if header.startswith("Bearer "):
            TOKENS.discard(header[7:])
        self._send_json({"ok": True})

    def _strip_prefix(self, path):
        """支持 --prefix 子路径托管：/tools/console-ui/api/state -> /api/state。
        未命中前缀时原样返回，保证根路径访问也兼容。"""
        if PREFIX:
            p = PREFIX.rstrip("/")
            if path == p:
                return "/"
            if p and path.startswith(p + "/"):
                return path[len(p):]
        return path

    # -- 路由 --------------------------------------------------------
    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = self._strip_prefix(parsed.path)
        if path.startswith("/api/") and not self._authorized():
            self._send_json({"ok": False, "error": "未登录或登录已过期"}, 401)
            return
        if path == "/api/state":
            self._send_json(MOCK.state_payload())
        elif path == "/api/health":
            self._send_json({
                "status": "ok", "version": APP_VERSION, "schemaVersion": SCHEMA_VERSION,
                "degraded": False, "issues": [],
                "config": {"dataDir": BASE_DIR, "logsDir": BASE_DIR},
            })
        elif path == "/api/console/log":
            self._send_json({"text": MOCK_LOG_TEXT})
        elif path.startswith("/api/apps/") and path.endswith("/logs"):
            app_id = path.split("/")[3]
            app = MOCK.app_by_id(app_id)
            if not app:
                self._send_json({"ok": False, "error": "应用不存在"}, 404)
            else:
                self._send_json({"text": _app_log_text(app)})
        elif path.startswith("/icons/"):
            self._serve_icon(path)
        else:
            self._serve_static(path)

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = self._strip_prefix(parsed.path)
        if path == "/api/login":
            self._handle_login()
            return
        if path == "/api/logout":
            self._handle_logout()
            return
        if path.startswith("/api/") and not self._authorized():
            self._send_json({"ok": False, "error": "未登录或登录已过期"}, 401)
            return
        if path == "/api/console/restart":
            self._read_json()          # 读掉 body，防 keep-alive 残留污染下一请求
            MOCK.console_pid += 1
            self._send_json({"ok": True, "pid": MOCK.console_pid,
                             "helperPid": MOCK.console_pid + 1, "port": MOCK.console_port})
        elif path == "/api/console/stop":
            self._read_json()
            self._send_json({"ok": True, "pid": MOCK.console_pid, "port": MOCK.console_port})
        elif path == "/api/ui/theme":
            body = self._read_json()
            theme = (body or {}).get("theme")
            if theme and any(t["id"] == theme for t in MOCK.themes):
                MOCK.ui_theme = theme
                self._send_json({"ok": True, "theme": theme})
            else:
                self._send_json({"ok": False, "error": "主题不存在"}, 400)
        elif path == "/api/pick":
            self._read_json()
            # 原生文件选择框在浏览器里无法实现；真实后端应提供自己的选择器
            self._send_json({"ok": True, "canceled": True})
        elif path == "/api/project/detect":
            body = self._read_json()
            cwd = (body or {}).get("cwd") or "/Users/demo/project"
            name = os.path.basename(cwd.rstrip("/\\")) or "project"
            self._send_json({
                "ok": True, "cwd": cwd, "name": name,
                "files": ["package.json"],
                "candidates": [
                    {"command": "npm run dev", "label": "npm run dev",
                     "source": "package.json", "port": 3000, "kind": "service",
                     "detail": "开发服务器"},
                    {"command": "npm run build", "label": "npm run build",
                     "source": "package.json", "port": None, "kind": "task",
                     "detail": "构建产物"},
                ],
            })
        elif path == "/api/services/flag":
            body = self._read_json()
            key, flag, value = (body or {}).get("key"), (body or {}).get("flag"), (body or {}).get("value")
            svc = MOCK.service_by_key(key or "")
            if svc and flag in ("hidden", "pinned", "promoted"):
                svc[flag] = bool(value)
                self._send_json({"ok": True})
            else:
                self._send_json({"ok": False, "error": "服务不存在或标记非法"}, 400)
        elif path == "/api/watch":
            body = self._read_json()
            keyword, action = (body or {}).get("keyword"), (body or {}).get("action")
            if action == "add":
                if keyword and keyword not in MOCK.watched_keywords:
                    MOCK.watched_keywords.append(keyword)
                    MOCK.watched.append(_mk_watch(
                        MOCK.next_pid, keyword, keyword + " (模拟)",
                        0.5, 0.3, 10, keyword))
                    MOCK.next_pid += 1
                self._send_json({"ok": True, "keywords": MOCK.watched_keywords})
            elif action == "remove":
                if keyword in MOCK.watched_keywords:
                    MOCK.watched_keywords.remove(keyword)
                MOCK.watched = [w for w in MOCK.watched if w["keyword"] != keyword]
                self._send_json({"ok": True, "keywords": MOCK.watched_keywords})
            else:
                self._send_json({"ok": False, "error": "未知动作"}, 400)
        elif path == "/api/kill":
            self._read_json()
            # 从服务/关注列表移除（真实后端是结束进程）
            pid = self._kill_pid()
            self._send_json({"ok": True, "pid": pid})
        elif path == "/api/apps":
            self._handle_apps_post()
        elif path == "/api/apps/reorder":
            body = self._read_json()
            ids = (body or {}).get("ids") or []
            order = {i: app_id for i, app_id in enumerate(ids)}
            MOCK.apps.sort(key=lambda a: order.get(a["id"], 10**9))
            self._send_json({"ok": True})
        elif path.startswith("/api/apps/") and path.endswith("/icon"):
            self._handle_app_icon(path)
        elif path.startswith("/api/apps/"):
            self._handle_app_action(path)
        else:
            self._send_json({"ok": False, "error": "未知接口: %s" % path}, 404)

    def do_PUT(self):
        self._read_body()
        parsed = urllib.parse.urlsplit(self.path)
        path = self._strip_prefix(parsed.path)
        if path.startswith("/api/") and not self._authorized():
            self._send_json({"ok": False, "error": "未登录或登录已过期"}, 401)
            return
        if path.startswith("/api/apps/"):
            self._handle_app_update(path)
        else:
            self._send_json({"ok": False, "error": "未知接口: %s" % path}, 404)

    def do_DELETE(self):
        self._read_body()            # 读掉可能的 body，防 keep-alive 残留污染下一请求
        parsed = urllib.parse.urlsplit(self.path)
        path = self._strip_prefix(parsed.path)
        if path.startswith("/api/") and not self._authorized():
            self._send_json({"ok": False, "error": "未登录或登录已过期"}, 401)
            return
        if path.startswith("/api/apps/"):
            self._handle_app_delete(path)
        else:
            self._send_json({"ok": False, "error": "未知接口: %s" % path}, 404)

    # -- 具体实现 ----------------------------------------------------
    def _read_json(self, max_bytes=1024 * 1024):
        raw = self._read_body(max_bytes)
        if not raw:
            return {}
        # 浏览器 fetch 总是 UTF-8；兼容个别用本地编码（如 Windows GBK）的客户端
        for encoding in ("utf-8", "gbk", "latin-1"):
            try:
                return json.loads(raw.decode(encoding))
            except (UnicodeDecodeError, ValueError):
                continue
        return {}

    def _kill_pid(self):
        # body: {pid, force?}；此处只从内存列表移除，并返回 pid 供记录
        return 0

    def _handle_apps_post(self):
        body = self._read_json() or {}
        name = (body.get("name") or "").strip()
        command = (body.get("command") or "").strip()
        if not name or not command:
            self._send_json({"ok": False, "error": "名称与命令不能为空"}, 400)
            return
        app_id = "%08x" % random.getrandbits(32)
        kind = "task" if body.get("kind") == "task" else "service"
        port = None if kind == "task" else (body.get("port") or None)
        app = _mk_app(app_id, name, command, body.get("cwd") or None,
                      port, body.get("glyph") or None, kind)
        # attachPid：模拟“认领已运行进程”
        attach_pid = body.get("attachPid")
        if attach_pid:
            svc = MOCK.service_by_pid(attach_pid)
            if svc:
                app["attached"] = True
                app["running"] = True
                app["pid"] = svc["pid"]
                app["cwd"] = svc["cwd"]
                app["port"] = svc["port"] if kind == "service" else None
        MOCK.apps.append(app)
        self._send_json(app)

    def _handle_app_update(self, path):
        app_id = path.split("/")[3]
        app = MOCK.app_by_id(app_id)
        if not app:
            self._send_json({"ok": False, "error": "应用不存在"}, 404)
            return
        body = self._read_json() or {}
        changed_runtime = any(
            k in body and body[k] != app.get(k)
            for k in ("command", "cwd", "port", "kind"))
        if app["running"] and changed_runtime and not body.get("stopBeforeUpdate"):
            self._send_json({"ok": False, "requiresStop": True,
                             "error": "请先停止再修改运行配置"}, 409)
            return
        if changed_runtime and app["running"]:
            app["running"] = False
            app["pid"] = None
            app["lastExit"] = None
        for key in ("name", "command", "cwd", "port", "glyph", "kind", "emoji"):
            if key in body:
                if key == "kind" and body[key] == "task":
                    app["port"] = None
                app[key] = body[key]
        self._send_json(app)

    def _handle_app_delete(self, path):
        app_id = path.split("/")[3]
        if path.endswith("/icon"):
            app = MOCK.app_by_id(app_id)
            if app:
                app["icon"] = None
            MOCK.icon_bytes.pop(app_id, None)
            self._send_json({"ok": True})
            return
        app = MOCK.app_by_id(app_id)
        if not app:
            self._send_json({"ok": False, "error": "应用不存在"}, 404)
            return
        MOCK.apps = [a for a in MOCK.apps if a["id"] != app_id]
        MOCK.icon_bytes.pop(app_id, None)
        MOCK.favicon_bytes.pop(app_id, None)
        self._send_json({"ok": True})

    def _handle_app_action(self, path):
        # /api/apps/{id}/{action}
        parts = path.strip("/").split("/")
        if len(parts) < 4:
            self._send_json({"ok": False, "error": "非法路径"}, 400)
            return
        app_id, action = parts[2], parts[3]
        app = MOCK.app_by_id(app_id)
        if not app:
            self._send_json({"ok": False, "error": "应用不存在"}, 404)
            return
        self._read_json()
        if action == "start":
            if app["running"]:
                self._send_json({"ok": False, "error": "应用已在运行"}, 409)
                return
            app["running"] = True
            app["pid"] = MOCK.next_pid
            MOCK.next_pid += 1
            app["uptimeSec"] = 0
            app["lastExit"] = None
            if app["kind"] == "task":
                app["_task_started"] = time.time()
            self._send_json({"ok": True, "pid": app["pid"]})
        elif action == "stop":
            if not app["running"]:
                self._send_json({"ok": False, "error": "应用未在运行"}, 409)
                return
            app["running"] = False
            app["pid"] = None
            app["_task_started"] = None
            if app["kind"] == "task":
                app["lastExit"] = {"status": "stopped", "code": None,
                                   "at": int(time.time()),
                                   "startedAt": int(time.time() * 1000) - 1000,
                                   "durationSec": 1.0}
            self._send_json({"ok": True})
        elif action == "restart":
            app["running"] = True
            app["pid"] = MOCK.next_pid
            MOCK.next_pid += 1
            app["uptimeSec"] = 0
            if app["kind"] == "task":
                app["_task_started"] = time.time()
            self._send_json({"ok": True, "pid": app["pid"]})
        elif action == "diagnose":
            issues = []
            if app["port"] and not app["running"]:
                owner = MOCK.service_by_pid(64990)
                if owner and owner["port"] == app["port"]:
                    issues.append({
                        "kind": "port", "severity": "warn", "title": "端口 3000 已被占用",
                        "detail": "PID 64990（node）正监听 3000；可直接改用其他端口。",
                        "fix": "修改端口",
                    })
            self._send_json({"ok": True, "summary": "未发现阻塞问题" if not issues else "发现 1 个问题",
                             "issues": issues})
        elif action == "favicon":
            app["favicon"] = "/icons/fav-" + app_id + ".png"
            MOCK.favicon_bytes[app_id] = make_png((34, 197, 94), 16)
            self._send_json({"ok": True, "favicon": app["favicon"]})
        elif action == "attach":
            body = self._read_json()
            pid = (body or {}).get("pid")
            svc = MOCK.service_by_pid(pid) if pid else None
            if not svc:
                self._send_json({"ok": False, "error": "未找到该进程或进程不属于当前用户"}, 400)
                return
            app["attached"] = True
            app["running"] = True
            app["pid"] = svc["pid"]
            if svc["cwd"] and app["cwd"] != svc["cwd"]:
                app["cwd"] = svc["cwd"]
                self._send_json({"ok": True, "pid": svc["pid"], "cwdUpdated": True, "cwd": svc["cwd"]})
            else:
                self._send_json({"ok": True, "pid": svc["pid"]})
        else:
            self._send_json({"ok": False, "error": "未知动作: %s" % action}, 400)

    def _handle_app_icon(self, path):
        # POST /api/apps/{id}/icon  body 为原始图片字节
        app_id = path.split("/")[3]
        app = MOCK.app_by_id(app_id)
        if not app:
            self._send_json({"ok": False, "error": "应用不存在"}, 404)
            return
        raw = self._read_body(5 * 1024 * 1024)
        if not raw:
            self._send_json({"ok": False, "error": "空图片"}, 400)
            return
        MOCK.icon_bytes[app_id] = raw
        app["icon"] = "/icons/" + app_id + ".png"
        self._send_json({"ok": True, "icon": app["icon"]})

    def _serve_icon(self, path):
        name = os.path.basename(path)
        base = name.split(".")[0]
        if name.startswith("fav-"):
            key = base[4:]
            if key in MOCK.favicon_bytes:
                self._send_bytes(MOCK.favicon_bytes[key], "image/png")
                return
        if base in MOCK.icon_bytes:
            self._send_bytes(MOCK.icon_bytes[base], "image/png")
            return
        # 兜底：静态目录里的 svg 源文件（icons/*.svg）
        self._serve_static(path)

    def _serve_static(self, path):
        if path in ("", "/"):
            rel = "index.html"
        else:
            rel = path.lstrip("/")
        # 防路径穿越
        full = os.path.realpath(os.path.join(BASE_DIR, rel))
        if not full.startswith(os.path.realpath(BASE_DIR) + os.sep) and full != os.path.realpath(BASE_DIR):
            self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if not os.path.isfile(full):
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return
        with open(full, "rb") as f:
            self._send_bytes(f.read(), guess_type(full))


MOCK_LOG_TEXT = (
    "[09:00:01] console-ui mock 后端已启动\n"
    "[09:00:03] 监听 127.0.0.1:9600\n"
    "[09:00:04] 首次连接来自浏览器\n"
    "[09:00:10] 应用「我的博客」保持运行中\n"
    "[09:00:12] 这是演示日志，接入真实后端后显示真实输出\n"
)


def _app_log_text(app):
    name = app.get("name") or "应用"
    lines = [
        "[09:00:00] 启动 %s …" % name,
        "[09:00:01] 工作目录: %s" % (app.get("cwd") or "—"),
        "[09:00:01] 命令: %s" % (app.get("command") or "—"),
        "[09:00:02] 端口: %s" % (app.get("port") or "—"),
        "[09:00:03] （演示日志内容）",
        "[09:00:04] INFO 服务已就绪",
        "[09:00:05] DEBUG 请求 /api/state 200",
        "[09:00:06] WARN 磁盘使用率 61%",
        "[09:00:08] INFO 收到请求 GET / 200",
        "[09:00:10] （接入真实后端后这里显示真实运行日志）",
    ]
    return "\n".join(lines)


def main():
    import argparse
    global PREFIX, AUTH_ENABLED
    parser = argparse.ArgumentParser(description="console-ui mock 后端（零依赖预览）")
    parser.add_argument("--port", type=int, default=None, help="起始端口（默认 9600）")
    parser.add_argument("--prefix", default="", help="在子路径下托管，如 /tools/console-ui")
    parser.add_argument("--no-auth", action="store_true", help="关闭登录校验（开发调试用）")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()
    PREFIX = args.prefix.strip() or ""
    AUTH_ENABLED = not args.no_auth

    port_start = args.port or PORT_START
    server, port = None, None
    for p in range(port_start, port_start + PORT_TRIES):
        try:
            server = ThreadingHTTPServer((HOST, p), Handler)
            port = p
            break
        except OSError:
            continue
    if server is None:
        print("错误：端口 %d-%d 均被占用，无法启动。" % (port_start, port_start + PORT_TRIES - 1))
        return 1
    MOCK.console_port = port
    suffix = ("/" + PREFIX.strip("/")) if PREFIX else ""
    root = "http://%s:%d%s/" % (HOST, port, suffix)
    print("console-ui 预览已启动: %s  (Ctrl+C 停止)" % root, flush=True)
    if AUTH_ENABLED:
        print("登录已开启：演示账号 admin / admin123（--no-auth 可关闭）", flush=True)
    else:
        print("登录已关闭（--no-auth）：/api/* 无需令牌", flush=True)
    if not args.no_browser:
        webbrowser.open(root)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
