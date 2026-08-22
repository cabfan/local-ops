import os
import shutil
import tempfile
import unittest
from unittest import mock

import server


class PlatformDirTests(unittest.TestCase):
    """平台相关的默认数据/日志目录。"""

    def test_linux_uses_xdg_data_home(self):
        with mock.patch.object(server, "IS_MACOS", False), \
                mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/tmp/xdg-data"},
                                clear=False):
            self.assertEqual(server._default_data_dir(), "/tmp/xdg-data/总控台")

    def test_linux_defaults_to_dotlocal_share_without_xdg(self):
        with mock.patch.object(server, "IS_MACOS", False), \
                mock.patch.dict(os.environ, {}, clear=False):
            expected = os.path.join(
                os.path.expanduser("~"), ".local", "share", "总控台")
            self.assertEqual(server._default_data_dir(), expected)

    def test_linux_uses_xdg_state_home_for_logs(self):
        with mock.patch.object(server, "IS_MACOS", False), \
                mock.patch.dict(os.environ, {"XDG_STATE_HOME": "/tmp/xdg-state"},
                                clear=False):
            self.assertEqual(server._default_logs_dir(), "/tmp/xdg-state/总控台")

    def test_macos_keeps_library_paths(self):
        with mock.patch.object(server, "IS_MACOS", True):
            self.assertTrue(server._default_data_dir().endswith(
                "Library/Application Support/总控台"))
            self.assertTrue(server._default_logs_dir().endswith(
                "Library/Logs/总控台"))


class ProcfsScanTests(unittest.TestCase):
    """lsof 之外的 Linux /proc 兜底。"""

    def test_decode_procfs_ipv4_little_endian(self):
        self.assertEqual(server._decode_procfs_ipv4("0100007F"), "127.0.0.1")
        self.assertEqual(server._decode_procfs_ipv4("00000000"), "0.0.0.0")
        self.assertEqual(server._decode_procfs_ipv4("3500007F"), "127.0.0.53")

    def test_decode_procfs_ipv6_loopback(self):
        # /proc/net/tcp6 里 ::1 的 kernel 表示（4 个 32 位小端 word）。
        self.assertEqual(
            server._decode_procfs_ipv6("00000000000000000000000001000000"),
            "::1")
        self.assertEqual(
            server._decode_procfs_ipv6("00000000000000000000000000000000"), "::")

    def test_lsof_results_do_not_trigger_procfs_fallback(self):
        output = ("COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
                  "node 10 user 1u IPv4 0x0 0t0 TCP 127.0.0.1:8080 (LISTEN)\n")
        with mock.patch.object(server, "run_cmd", return_value=output), \
                mock.patch.object(server, "_scan_listeners_procfs") as procfs:
            listeners = server.scan_listeners()
        self.assertEqual(listeners[(10, 8080)], {"127.0.0.1"})
        procfs.assert_not_called()

    def test_missing_lsof_falls_back_to_procfs_on_linux(self):
        with mock.patch.object(server, "IS_LINUX", True), \
                mock.patch.object(server, "run_cmd", return_value=""), \
                mock.patch.object(
                    server, "_scan_listeners_procfs",
                    return_value={(10, 80): {"127.0.0.1"}}):
            self.assertEqual(
                server.scan_listeners(), {(10, 80): {"127.0.0.1"}})


class PickPathTests(unittest.TestCase):
    """文件/目录选择框的跨平台分发。"""

    def test_linux_dispatches_to_linux_picker(self):
        with mock.patch.object(server, "IS_MACOS", False), \
                mock.patch.object(server, "_pick_path_linux",
                                  return_value=("/tmp/proj", False)):
            self.assertEqual(server.pick_path("dir"), ("/tmp/proj", False))

    def test_macos_dispatches_to_osascript(self):
        with mock.patch.object(server, "IS_MACOS", True), \
                mock.patch.object(server, "_pick_path_macos",
                                  return_value=(None, True)):
            self.assertEqual(server.pick_path("script"), (None, True))

    def test_linux_no_gui_tool_returns_error_not_cancel(self):
        # 没有 zenity/kdialog 且 tkinter 不可用 → 报“无法打开”而非误报取消。
        with mock.patch.object(server.shutil, "which", return_value=None), \
                mock.patch.object(
                    server, "_pick_path_tk", return_value=(None, False)):
            self.assertEqual(
                server._pick_path_linux("dir"), (None, False))


class DotnetTests(unittest.TestCase):
    """.NET 项目识别与运行环境（dotnet run / DOTNET_ROOT）。"""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="dotnet-test-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def _write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_detect_dotnet_run_uses_launchsettings_port(self):
        self._write("soei.csproj", '<Project Sdk="Microsoft.NET.Sdk.Web"/>')
        self._write("Properties/launchSettings.json",
                    '{"profiles":{"http":{"applicationUrl":"http://localhost:5006"},'
                    '"https":{"applicationUrl":"https://localhost:7007"}}}')
        result, err = server.detect_project(self.root)
        self.assertIsNone(err)
        self.assertTrue(any(
            c["command"] == "dotnet run" and c["port"] == 5006
            for c in result["candidates"]))

    def test_detect_dotnet_run_without_port(self):
        self._write("app.csproj", "<Project/>")
        result, err = server.detect_project(self.root)
        self.assertIsNone(err)
        self.assertTrue(any(
            c["command"] == "dotnet run" and c["port"] is None
            for c in result["candidates"]))

    def test_dotnet_project_port_chooses_min(self):
        self._write("Properties/launchSettings.json",
                    '{"profiles":{"a":{"applicationUrl":"http://localhost:5006"},'
                    '"b":{"applicationUrl":"http://localhost:8080;http://localhost:3000"}}}')
        self.assertEqual(server._dotnet_project_port(self.root), 3000)

    def test_ensure_dotnet_env_sets_root_when_dotnet_present(self):
        home = tempfile.mkdtemp(prefix="dotnet-home-")
        self.addCleanup(shutil.rmtree, home, True)
        dotnet_dir = os.path.join(home, ".dotnet")
        os.makedirs(dotnet_dir)
        dotnet_bin = os.path.join(dotnet_dir, "dotnet")
        with open(dotnet_bin, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(dotnet_bin, 0o755)
        # 隔离 PATH，避免命中本机真实 dotnet，从而确定性地命中 home/.dotnet。
        env = {"PATH": home}
        server._ensure_dotnet_env(env, home)
        self.assertEqual(env.get("DOTNET_ROOT"), dotnet_dir)
        self.assertEqual(env.get("DOTNET_ROOT_X64"), dotnet_dir)
        self.assertIn(dotnet_dir, env["PATH"])


if __name__ == "__main__":
    unittest.main()
