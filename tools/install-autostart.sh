#!/bin/bash
# 总控台 — Linux 开机自启动安装/移除
#
# 用法：
#   ./tools/install-autostart.sh          安装当前用户的开机自启动项
#   ./tools/install-autostart.sh --remove 移除已安装的开机自启动项
#
# 自动登录图形会话后启动 start.sh；start.sh 已支持 CONSOLE_NO_LAUNCHER=1，
# 因此自启动时不会弹出“总控台已在运行”的交互选择框，重复启动由进程锁去重。
set -eu
umask 077

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
printf '%s\n' "项目目录: $PROJECT_DIR"

if [ ! -f "$PROJECT_DIR/start.sh" ]; then
  echo "错误：缺少 $PROJECT_DIR/start.sh" >&2
  exit 1
fi
chmod +x "$PROJECT_DIR/start.sh"

AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
DESKTOP_FILE="$AUTOSTART_DIR/总控台.desktop"

if [ "${1:-}" = "--remove" ]; then
  rm -f "$DESKTOP_FILE"
  printf '%s\n' "已移除开机自启动项 -> $DESKTOP_FILE"
  exit 0
fi

if [ $# -gt 0 ] && [ "${1:-}" != "--remove" ]; then
  echo "用法：$0 [--remove]" >&2
  exit 2
fi

mkdir -p "$AUTOSTART_DIR"

# 安装应用图标，保证自启动列表和启动器里都能显示品牌图标。
ICON_SRC="$PROJECT_DIR/static/assets/console-app-icon.png"
ICON_BASE="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/512x512/apps"
if [ -f "$ICON_SRC" ]; then
  mkdir -p "$ICON_BASE"
  cp "$ICON_SRC" "$ICON_BASE/console.png"
  printf '%s\n' "应用图标 -> $ICON_BASE/console.png"
fi

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=总控台
Name[zh_CN]=总控台
Comment=本地服务监控与快速启动控制台
Comment[zh_CN]=本地服务监控与快速启动控制台
Exec=env CONSOLE_NO_LAUNCHER=1 "$PROJECT_DIR/start.sh"
Icon=console
Terminal=false
StartupNotify=false
Categories=Development;Utility;
Keywords=console;dev;service;monitor;
X-GNOME-Autostart-enabled=true
EOF
chmod 644 "$DESKTOP_FILE"
printf '%s\n' "开机自启动项 -> $DESKTOP_FILE"

# 刷新 GNOME/KDE 等桌面环境可识别的 autostart 数据库（不可用时忽略）。
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$(dirname "$DESKTOP_FILE")" >/dev/null 2>&1 || true
fi

echo
echo "完成。下次登录桌面时会自动启动总控台。"
echo "如需取消，运行：$0 --remove"
