#!/bin/bash
# 总控台 — Linux 启动脚本（等价于 macOS 的 start.command）。
# 直接运行即可：会在后台监听 0.0.0.0:9600，并自动打开浏览器。
set -u
umask 077
cd "$(dirname "$0")"

# 局域网访问配置：
#   CONSOLE_HOST        = 绑定地址。0.0.0.0 允许局域网访问；改回 127.0.0.1 则仅本机。
#   CONSOLE_LAN_ALLOW   = 允许访问的网段/IP（逗号分隔，支持 CIDR）。默认含 192.168.1.0/24、11.254.3.0/24 和 11.254.2.186。
# 恢复仅本机：把两行改为 CONSOLE_HOST=127.0.0.1 并删除 CONSOLE_LAN_ALLOW。
export CONSOLE_HOST=0.0.0.0
export CONSOLE_LAN_ALLOW=${CONSOLE_LAN_ALLOW:-192.168.1.0/24,11.254.3.0/24,11.254.2.186}

if ! command -v python3 >/dev/null 2>&1; then
  echo "错误：未找到 Python 3，请先安装 Python 3.12 或更高版本。" >&2
  exit 127
fi
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
  echo "错误：总控台需要 Python 3.12 或更高版本。" >&2
  exit 126
fi

# --launcher：若已在运行则弹“打开控制台 / 重新启动 / 取消”选择（需 zenity 或 kdialog）；
# 否则退回普通启动，进程锁会自动去重并打开浏览器。
if command -v zenity >/dev/null 2>&1 || command -v kdialog >/dev/null 2>&1; then
  exec python3 server.py --launcher
fi
exec python3 server.py
