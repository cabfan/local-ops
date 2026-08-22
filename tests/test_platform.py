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


class WindowsScanTests(unittest.TestCase):
    """Windows 平台解析器（用模拟命令输出在 Linux 上验证）。"""

    def test_parse_netstat_listeners(self):
        out = (
            "  Proto  Local Address          Foreign Address        State           PID\n"
            "  TCP    127.0.0.1:8080         0.0.0.0:0              LISTENING       1234\n"
            "  TCP    [::]:9600              [::]:0                 LISTENING       789\n"
            "  TCP    127.0.0.1:5432         0.0.0.0:0              LISTENING       2345\n"
            "  TCP    127.0.0.1:9999         0.0.0.0:0              TIME_WAIT       111\n"
        )
        got = server._parse_netstat_listeners(out)
        self.assertEqual(got[(1234, 8080)], {"127.0.0.1"})
        self.assertEqual(got[(789, 9600)], {"::"})
        self.assertEqual(got[(2345, 5432)], {"127.0.0.1"})
        self.assertNotIn((111, 9999), got)  # 非 LISTENING 行忽略

    def test_windows_ps_snapshot_parses_csv(self):
        proc_csv = (
            '"ProcessId","ParentProcessId","Name","CommandLine","EpochStart"\n'
            '"123","1","node.exe","node server.js","1700000000"\n'
            '"234","1","python.exe","python app.py","1700000001"\n')
        mem_csv = (
            '"Id","CPU","WorkingSet"\n'
            '"123","12.5","104857600"\n"234","0.75","52428800"\n')
        with mock.patch.object(server, "run_cmd",
                               side_effect=[proc_csv, mem_csv]):
            snap = server._ps_snapshot_windows()
        self.assertIn(123, snap)
        self.assertEqual(snap[123]["comm"], "node.exe")
        self.assertEqual(snap[123]["args"], "node server.js")
        self.assertEqual(snap[123]["cpu"], 12.5)
        self.assertEqual(snap[123]["mem"], 100.0)
        self.assertEqual(snap[123]["uid"], server.SELF_UID)
        self.assertGreaterEqual(snap[123]["etime"], 0)

    def test_windows_pgid_map_is_process_tree(self):
        proc_csv = (
            '"ProcessId","ParentProcessId","Name","CommandLine","EpochStart"\n'
            '"100","1","cmd.exe","cmd /c x","1700000000"\n'
            '"200","100","node.exe","node srv","1700000001"\n'
            '"300","200","node.exe","child","1700000002"\n')
        with mock.patch.object(server, "run_cmd", return_value=proc_csv):
            groups = server._pgid_members_map_windows()
        self.assertEqual(set(groups[100]), {100, 200, 300})
        self.assertEqual(set(groups[200]), {200, 300})
        self.assertEqual(set(groups[300]), {300})

    def test_windows_cwds_uses_exec_dir(self):
        # 注意：在 Linux 上 os.path.realpath 把反斜杠当普通字符，因而用平台无关
        # 的绝对路径来验证「取可执行文件所在目录」的逻辑。
        csv = '"ProcessId","ExecutablePath"\n"123","/opt/node/node.exe"\n'
        with mock.patch.object(server, "run_cmd", return_value=csv):
            got = server._lsof_cwds_windows([123])
        self.assertEqual(got[123], os.path.dirname("/opt/node/node.exe"))

    def test_windows_scan_listeners_dispatch(self):
        with mock.patch.object(server, "IS_WINDOWS", True), \
                mock.patch.object(server, "_scan_listeners_windows",
                                  return_value={(10, 80): {"0.0.0.0"}}):
            self.assertEqual(server.scan_listeners(), {(10, 80): {"0.0.0.0"}})

    def test_command_for_script_windows(self):
        with mock.patch.object(server, "IS_WINDOWS", True):
            self.assertEqual(server.command_for_script("/a/b/app.py"),
                             'python -- "/a/b/app.py"')
            self.assertEqual(
                server.command_for_script("/a/b/run.ps1"),
                'powershell -NoProfile -ExecutionPolicy Bypass -File "/a/b/run.ps1"')
            self.assertEqual(server.command_for_script("/a/b/x.js"),
                             'node -- "/a/b/x.js"')
            self.assertEqual(server.command_for_script("/a/b/t.cmd"),
                             '"/a/b/t.cmd"')

    def test_windows_default_dirs_use_localappdata(self):
        with mock.patch.object(server, "IS_WINDOWS", True), \
                mock.patch.dict(os.environ,
                                {"LOCALAPPDATA": r"C:\Users\x\AppData\Local"},
                                clear=False):
            self.assertTrue(server._default_data_dir().endswith("总控台"))
            self.assertTrue(server._default_logs_dir().endswith(
                os.path.join("总控台", "logs")))


class WindowsProcessDispatchTests(unittest.TestCase):
    """Windows 进程/停止操作的分发与存活判定。"""

    def test_stop_pid_tree_uses_taskkill(self):
        with mock.patch.object(server, "IS_WINDOWS", True), \
                mock.patch.object(server, "_taskkill",
                                  return_value=(True, None)) as tk:
            self.assertEqual(server.stop_pid_tree(123), (True, None))
        tk.assert_called_once()
        self.assertEqual(tk.call_args[0], (123,))
        self.assertEqual(tk.call_args[1]["tree"], True)
        self.assertEqual(tk.call_args[1]["force"], True)

    def test_stop_target_alive_group_uses_members(self):
        target = {"kind": "group", "id": 100, "members": [100, 200, 300]}
        with mock.patch.object(server, "IS_WINDOWS", True), \
                mock.patch.object(server, "_pid_alive_windows",
                                  side_effect=[False, False, True]):
            self.assertTrue(server.stop_target_alive(target))

    def test_stop_target_alive_pid(self):
        target = {"kind": "pid", "id": 55, "members": [55]}
        with mock.patch.object(server, "IS_WINDOWS", True), \
                mock.patch.object(server, "_pid_alive_windows",
                                  return_value=False):
            self.assertFalse(server.stop_target_alive(target))

    def test_kill_process_windows_dispatch(self):
        with mock.patch.object(server, "IS_WINDOWS", True), \
                mock.patch.object(server, "_process_uid_windows",
                                  return_value=server.SELF_UID), \
                mock.patch.object(server, "_taskkill",
                                  return_value=(True, None)) as tk:
            self.assertEqual(server.kill_process(999, False), (True, None))
        tk.assert_called_once()
        self.assertEqual(tk.call_args[1]["force"], False)
        self.assertEqual(tk.call_args[1]["tree"], False)


if __name__ == "__main__":
    unittest.main()
