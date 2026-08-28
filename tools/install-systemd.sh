#!/bin/bash
# 总控台 — Linux systemd 用户服务安装。
# 用法：
#   ./tools/install-systemd.sh                 # 安装并启用后台用户服务
#   CONSOLE_HOST=0.0.0.0 CONSOLE_LAN_ALLOW=192.168.1.0/24 ./tools/install-systemd.sh
#
# 生成 ~/.config/systemd/user/local-ops-console.service 后：
#   systemctl --user enable --now local-ops-console
# 从而实现开机/登录后自动启动、保持后台运行；页面顶栏的“重启”会交给
# systemd 处理（server.py 已内置 local-ops-console 的托管识别）。
set -eu
umask 077

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_NAME="local-ops-console"
USER_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
SYSTEMD_USER_DIR="$USER_CONFIG_HOME/systemd/user"
UNIT_FILE="$SYSTEMD_USER_DIR/$UNIT_NAME.service"

if [ "$(uname -s)" != "Linux" ]; then
  echo "错误：systemd 用户服务仅支持 Linux。" >&2
  exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "错误：未找到 systemctl，无法安装 systemd 用户服务。" >&2
  exit 1
fi

if [ ! -f "$PROJECT_DIR/server.py" ]; then
  echo "错误：缺少 $PROJECT_DIR/server.py，请在总控台项目目录内运行本脚本。" >&2
  exit 1
fi

PYTHON_BIN="$(command -v python3 || true)"
if [ -z "$PYTHON_BIN" ]; then
  echo "错误：未找到 Python 3，请先安装 Python 3.12 或更高版本。" >&2
  exit 127
fi
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
  echo "错误：总控台需要 Python 3.12 或更高版本。" >&2
  exit 126
fi

mkdir -p "$SYSTEMD_USER_DIR"

# 保持服务在后台静默运行：systemd 启动时不自动打开浏览器。
# 默认与 start.sh 一致，开放局域网访问；如需仅本机访问：
#   CONSOLE_HOST=127.0.0.1 CONSOLE_LAN_ALLOW= ./tools/install-systemd.sh
# 如需自定义网段：
#   CONSOLE_HOST=0.0.0.0 CONSOLE_LAN_ALLOW=10.0.0.0/8 ./tools/install-systemd.sh
CONSOLE_HOST="${CONSOLE_HOST:-0.0.0.0}"
CONSOLE_LAN_ALLOW="${CONSOLE_LAN_ALLOW-192.168.1.0/24,11.254.3.0/24,11.254.2.149,11.254.2.186}"
ENV_LINES="
Environment=\"CONSOLE_HOST=$CONSOLE_HOST\""
if [ -n "$CONSOLE_LAN_ALLOW" ]; then
  ENV_LINES="$ENV_LINES
Environment=\"CONSOLE_LAN_ALLOW=$CONSOLE_LAN_ALLOW\""
fi

cat > "$UNIT_FILE" <<EOF
[Unit]
Description=总控台 (Local Ops Console)
Documentation=file:$PROJECT_DIR/README.md
After=network.target

[Service]
Type=simple
WorkingDirectory=$PROJECT_DIR
ExecStart=$PYTHON_BIN "$PROJECT_DIR/server.py" --no-browser
Restart=on-failure
RestartSec=3
Environment=PYTHONUNBUFFERED=1$ENV_LINES

[Install]
WantedBy=default.target
EOF

chmod 600 "$UNIT_FILE"

systemctl --user daemon-reload
systemctl --user enable "$UNIT_NAME"

# 启动/重启用户服务。已存在旧实例时由 systemd 接管，页面重启也会走 systemctl。
systemctl --user restart "$UNIT_NAME"

# 尝试开启 user lingering；若当前用户无权设置，跳过不影响服务在登录后启动。
if command -v loginctl >/dev/null 2>&1; then
  if ! loginctl show-user "$(id -un)" --property=Linger --value 2>/dev/null | grep -qx yes; then
    if ! loginctl enable-linger "$(id -un)" >/dev/null 2>&1; then
      echo "提示：未能开启 user lingering（可能需要 root/Polkit）。系统用户登录后仍会自动启动。"
    fi
  fi
fi

echo
echo "完成。已安装并启动 systemd 用户服务："
echo "  unit:    $UNIT_NAME.service"
echo "  file:    $UNIT_FILE"
echo "  project: $PROJECT_DIR"
echo
echo "常用命令："
echo "  systemctl --user status $UNIT_NAME"
echo "  journalctl --user -u $UNIT_NAME -f"
echo "  systemctl --user restart $UNIT_NAME"
echo "  systemctl --user disable --now $UNIT_NAME"
