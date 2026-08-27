# 总控台 (Console)

本地服务监控与启动控制台。**零依赖**：`server.py` 单文件后端（仅 Python 3.12 标准库）+ 无构建原生 JS 前端（ES Modules，禁框架/CDN）。平台差异（目录、`ps/lsof`↔`/proc`↔`netstat/taskkill`、选择器）在 `server.py` 内按 `IS_MACOS`/`IS_LINUX`/`IS_WINDOWS` 分支处理；文档见 `README.md`，发布流程见 `RELEASE_CHECKLIST.md`。

## 命令

- 运行：`python3 server.py` — 绑定 `127.0.0.1`（可用 `CONSOLE_HOST` 覆盖），端口 9600 起被占 +1（最多试 10 个），启动后自动开浏览器。
- **验证：`make check`** = `python3 tools/check_project.py`。它不只是语法检查——包含必要文件清单、VERSION 一致性、主题注册表、静态资源引用、生成图标同步、素材台账，并跑全部测试：
  - 后端：`python3 -m unittest discover -s tests -p 'test_*.py' -v`
  - 前端纯函数：`node --test tests/js/*.test.mjs`（node 仅用于此，运行时无 node）
  - 跳过测试只查结构：`make syntax`
- 生成物再生成：`make generate-icons`（由 `static/icons/*.svg` 重生成 `icons.js`，勿手改 icons.js）、`make generate-brand`（favicon/AppIcon 等）。Pillow 是唯一 dev 依赖（`make dev-setup`），只为资产再生成。
- 发布：`make release-check` / `make release` / `make release-verify`（`tools/build_release.py`）。CI 在 macos-15 + Python 3.12 上连续 build 两次并 `cmp` zip——**发布构建必须确定性**（`SOURCE_DATE_EPOCH` 固定）；`--release` 还检查 Git 边界与 `ASSET_PROVENANCE.md` 台账状态。

## 环境变量

| 变量 | 含义 |
|---|---|
| `CONSOLE_HOST` | 绑定地址，默认 `127.0.0.1` |
| `CONSOLE_LAN_ALLOW` | 局域网白名单（逗号分隔 IP/CIDR）。空 = 仅回环；设置后才放开非回环，非法 Host → 421 |
| `CONSOLE_DATA_DIR` / `CONSOLE_LOG_DIR` | 显式覆盖数据/日志目录（覆盖时不再自动迁移旧 `data/`） |

数据/日志默认 macOS 在 `~/Library/{Application Support,Logs}/总控台`，Linux 遵循 XDG（`~/.local/share|state/总控台`），Windows 由 `server.py` 分支决定。

## 结构

- `static/app.js` 入口 + `static/js/{core,launchpad,services,overlays,ports,widgets}.js`。`core.js` 承载工具/API/浮层/主题注册；模块间用 `window.__poll()` 共享轮询入口。
- 前端每 2s 只轮询 `GET /api/state`（完整 API 契约见 README 与下文要点）；DOM 按 key 原地更新，禁整列表重绘。
- 样式：`base.css` 承载布局 v2 结构（左导航轨 + 顶栏 + 内容/信息栏网格），主题包只是皮肤；当前单一主题 `ops`（`DEFAULT_UI_THEME = "ops"`）。深浅色切换用 localStorage `console-theme`，UI 零 emoji。
- 图标层级：上传 icon > glyph > favicon > 名称首字。

## 后端铁律（易错点）

- **keep-alive 陷阱**：不读 body 的 POST handler 必须 `discard_body()`——前端对 start/stop 会发 `{}` body，残留字节会把同连接下一个请求污染成 `{}GET` → 501 断连横幅。
- **进程身份**：running 判定走 runToken+进程组(`lastPgid`)+UID 三重校验；不用"端口有监听者"当运行依据。旧版兼容认领需 lastPid+端口+UID+真实 cwd 四重一致。`attached` 卡片允许监听子进程换 PID 重关联，但必须端口+UID+cwd 唯一命中。
- **绝不按端口杀进程**：停止只对该受控进程组 SIGTERM；多卡允许保存同一端口。`POST /api/apps/{id}/attach {pid}` 是把外部进程认领为受管的唯一通道（四重校验，失败不留半成品卡片）。
- **任务退出码协议**：一次性任务取消 = exit 130、成功 = 0、其余失败；不要用日志文字猜状态。
- **配置写入**：线程锁 + 临时文件 `os.replace` + `.bak` 备份；主配与备份都不可读时进入只读保护，不得覆盖原文件。
- **keep-alive 之外的探查**：端口扫描 lsof，Linux 缺失时回落 `/proc/net/tcp{,6}`+fd inode 匹配；cwd 用 lsof `-d cwd`，Linux 回落 `/proc/<pid>/cwd`。
- Linux 若检测到 systemd 用户服务 `local-ops-console`（unit 名常量 `SYSTEMD_CONSOLE_UNIT`），页面重启改走 `systemctl --user restart`。

## 前端行为约定

- 危险操作（结束进程/删除应用）必须确认；新端口发现静默建立基线（首次加载/断线/后台/降级时不提醒）。
- 「加入启动台」必须带 `attachPid` 由后端原子完成认领，项目识别完成前不得保存卡片。
- 编辑运行中服务时面板内先显示「停止服务」，stop 不关面板不清草稿。
- 动效遵守 `prefers-reduced-motion` 降级。
