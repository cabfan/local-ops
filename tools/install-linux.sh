#!/bin/bash
# 总控台 — Linux 桌面集成：安装 .desktop 入口和应用图标。
# 用法：./tools/install-linux.sh
# 把「总控台」加入系统应用菜单，可从桌面/启动器直接启动。
set -eu
umask 077

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
printf '%s\n' "项目目录: $PROJECT_DIR"

if [ ! -f "$PROJECT_DIR/start.sh" ]; then
  echo "错误：缺少 $PROJECT_DIR/start.sh" >&2
  exit 1
fi
chmod +x "$PROJECT_DIR/start.sh"

APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_BASE="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/512x512/apps"
mkdir -p "$APPS_DIR" "$ICON_BASE"

# 复制品牌图标为可被图标主题引用的固定名称。
ICON_SRC="$PROJECT_DIR/static/assets/console-app-icon.png"
if [ -f "$ICON_SRC" ]; then
  cp "$ICON_SRC" "$ICON_BASE/console.png"
  printf '%s\n' "应用图标 -> $ICON_BASE/console.png"
fi

DESKTOP_FILE="$APPS_DIR/总控台.desktop"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=总控台
Name[zh_CN]=总控台
Comment=本地服务监控与快速启动控制台
Comment[zh_CN]=本地服务监控与快速启动控制台
Exec=$PROJECT_DIR/start.sh
Icon=console
Terminal=false
StartupNotify=true
Categories=Development;Utility;
Keywords=console;dev;service;monitor;
EOF
chmod +x "$DESKTOP_FILE"
printf '%s\n' "菜单入口 -> $DESKTOP_FILE"

# 尽量刷新桌面数据库（不可用时忽略）。
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q "$(dirname "$ICON_BASE")" >/dev/null 2>&1 || true
fi

echo
echo "完成。现在可以在应用菜单里搜索「总控台」启动。"
echo "首次运行请确保已安装 python3（>= 3.12），并在需要时选择工作目录。"
