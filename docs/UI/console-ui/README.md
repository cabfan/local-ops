# console-ui — 可独立复用的「总控台」前端

从 [local-ops 总控台](https://github.com/laogou717/local-ops) 提取出的前端 UI：
**启动台 / 服务监控** 双视图、左侧图标导航轨、右侧实时信息栏、⌘K 命令面板、
模态/抽屉/端口诊断/端口发现、深浅色 + Ops 指挥台主题。原生 ES Modules，
**无框架、无构建、无 CDN**，零依赖即可跑起来。

> 提取版对原前端只做了两处适配，接口契约完全兼容：
> 1. 新增 `config.js` 数据适配层（唯一需要为你的项目改动的文件）；
> 2. 所有静态资源路径改为**相对路径**，可托管在站点根路径或任意子路径下。

## 目录结构

```
console-ui/
├── index.html          主界面入口（已插入 <script src="./config.js">）
├── login.html          登录页入口（风格与主界面一致）
├── config.js           ★ 数据适配层：API 地址 + 登录令牌 + 401 跳转登录页
├── login.css           登录页布局（令牌全部来自 themes/ops.css）
├── app.js             入口逻辑（轮询 / 视图切换 / 命令面板）
├── base.css           基础样式
├── icons.js           Lucide 图标（生成文件，勿手改）
├── js/                核心模块（core / launchpad / services / overlays / ports / widgets / login）
├── themes/            主题（ops.css + ops.json 注册表）
├── assets/ fonts/     品牌素材与 Geist Mono 字体
├── mock_server.py     零依赖 mock 后端（含登录演示，仅预览用，可直接删）
└── README.md
```

> ⚠️ **不要双击 `index.html` 用 `file://` 打开**：资源是相对路径没错，但
> 前端使用 ES Modules（`<script type="module">`）并轮询 `fetch('/api/state')`，
> 浏览器出于安全策略禁止 `file://` 加载模块脚本，也没有 HTTP 服务器可响应
> 数据请求。必须通过 http(s) 访问（起静态服务器或由你的后端托管）。

## 快速预览（无后端）

要求：Python 3（任意 3.8+，无需任何第三方包）。

```bash
python mock_server.py            # → http://127.0.0.1:9600/ （端口被占自动 +1）
# 模拟子路径托管（验证相对路径版本）：
python mock_server.py --port 9700 --prefix /tools/console-ui
#                                → http://127.0.0.1:9700/tools/console-ui/
```

预览自带"活数据"：CPU 负载抖动、运行时长递增、任务运行 12 秒后自动完成
（弹完成提示）、约 20 秒后"新出现"一个端口（触发端口发现栏）、图标/favicon
上传走内存、所有 `/api/*` 带 CORS 头。

**登录**：mock 默认开启登录校验（演示账号 `admin` / `admin123`），访问
`/` 会被重定向到 `/login.html`；开发调试可加 `--no-auth` 跳过登录。

## 登录与鉴权

前端自带登录页（`login.html`，风格与主界面一致），流程：

1. 打开 `/` 时若未登录，`/api/state` 返回 401 → `config.js` 自动跳转 `/login.html`；
2. 登录页 `POST /api/login` `{username, password}` → 后端返回
   `{ok: true, token: "..."}`，前端存入 `localStorage["console-ui-token"]`；
3. 此后 `config.js` 为所有 `/api/*` 请求自动附带
   `Authorization: Bearer <token>`；任何接口返回 401/403 都会回到登录页；
4. 设置中心提供「退出登录」（清除令牌并回到登录页）。

接入你的后端时实现两个接口即可（其余接口不变）：

- `POST /api/login` `{username, password}` → `{ok:true, token}`（失败 `401 {ok:false, error}`）
- 其余 `/api/*` 校验 `Authorization: Bearer <token>`，无效返回 `401`
  （`--no-auth` 模式下 mock 全部放行；`/api/logout` 可选实现，前端退出只清本地令牌）。

## 接入你自己的项目（推荐方式）

你的后端托管本目录静态文件，并实现下面的 JSON 接口。前端不改一行代码；
接口返回形状以 `mock_server.py` 为实现参考。

**托管位置与 API 地址**（`config.js` 决定）：
- **根路径**：`https://你的站点/` 返回 `index.html`，`/api/*` 由同源后端实现。
- **子路径**：`https://你的站点/tools/console-ui/` 返回 `index.html`，API 同样放在
  子路径下（`/tools/console-ui/api/state`）。`config.js` 默认自动取「页面所在目录」，
  因此**零配置**即可；若你的 API 在别处，显式设置
  `window.__CONSOLE_CONFIG__.apiBase` 即可（跨源需后端带 CORS 头）。

### 轮询主接口（必须）

`GET /api/state` — 前端每 2 秒轮询，返回：

```json
{
  "services": [{
    "key": "python3.12:8791", "instanceKey": "54252:8791",
    "pid": 54252, "name": "python3.12", "port": 8791,
    "cwd": "/path/to/blog", "project": "blog", "cmd": "python3 app.py",
    "cpu": 0.3, "mem": 1.2, "uptimeSec": 7980,
    "group": "mine", "pinned": false, "hidden": false, "promoted": false,
    "appId": null, "appName": null,
    "origin": {"label": "Codex", "icon": "bot"}
  }],
  "watched": [{"pid": 1, "name": "ffmpeg", "cmd": "...", "cpu": 0.0, "mem": 0.5, "uptimeSec": 60, "keyword": "ffmpeg"}],
  "apps": [{
    "id": "a1b2c3d4", "name": "我的博客", "command": "python3 -m http.server 8080",
    "cwd": "/path", "port": 8080, "emoji": null, "glyph": "rocket",
    "icon": null, "favicon": null, "kind": "service", "attached": false,
    "running": true, "pid": 1234, "uptimeSec": 120,
    "listening": true, "portOccupied": false, "portOccupiedPid": null,
    "portConflict": false, "portConflictApps": [],
    "lastExit": null,
    "health": {"status": "ok", "blocking": false, "issues": []},
    "ports": [8080], "openHost": "127.0.0.1", "openHosts": {"8080": "127.0.0.1"}
  }],
  "watchedKeywords": ["ffmpeg"],
  "consolePort": 9600, "consolePid": 123, "consoleCwd": "/path",
  "version": "1.0.0", "schemaVersion": 1,
  "degraded": false, "degradedReasons": [],
  "themes": [{"id": "ops", "name": "指挥台", "author": "", "desc": "", "colors": []}],
  "uiTheme": "ops"
}
```

### 其余接口（按需实现，缺了对应功能失效但不影响页面打开）

| 接口 | 说明 |
|---|---|
| `GET /api/apps/{id}/logs?tail=300`、`GET /api/console/log?tail=300` | 日志，返回 `{"text": "..."}` |
| `POST /api/apps` / `PUT /api/apps/{id}` / `DELETE /api/apps/{id}` | 应用增改删（可带 `attachPid`；运行中改 command/cwd/port/kind 需返回 `{ok:false, requiresStop:true}` 或带 `stopBeforeUpdate`） |
| `POST /api/apps/{id}/start` / `stop` / `restart` / `diagnose` / `attach` | 启停重启 / 诊断（`{ok, issues, summary}`）/ 认领进程 |
| `POST /api/apps/{id}/favicon`、`POST /api/apps/{id}/icon`（原始字节）、`DELETE /api/apps/{id}/icon` | 图标 |
| `POST /api/apps/reorder` | 拖拽排序 `{ids:[...]}` |
| `POST /api/services/flag` | 置顶/隐藏/提升 `{key, flag, value}` |
| `POST /api/watch` | 关注进程 `{keyword, action:"add"|"remove"}` |
| `POST /api/kill` | 结束进程 `{pid, force?}` |
| `POST /api/project/detect` | 项目识别 `{cwd}` → `{ok, name, candidates:[{command,label,source,port,kind,detail}]}` |
| `POST /api/pick` | 文件/目录选择（原版用 macOS osascript；你的后端可实现自己的选择器或返回 `{ok, canceled:true}`） |
| `POST /api/ui/theme` | 切换主题 `{theme}`（需与 `themes` 注册表一致） |
| `POST /api/console/restart` / `stop` | 控制台自身启停（`restart` 后 `consolePid` 变化即可） |

### 跨源开发（可选）

默认同源（后端托管本目录）。若前端和后端分开部署，在 `config.js` 加载前设置：

```html
<script>
  window.__CONSOLE_CONFIG__ = { apiBase: 'http://127.0.0.1:9600' };
</script>
<script src="/config.js" defer></script>
```

- 后端 `/api/*` 需带 CORS 头（`mock_server.py` 已示范）。
- 应用图标 `<img src="/icons/...">` 不走 fetch，跨源时仍从页面同源加载，
  建议由页面同源反向代理 `/icons/*`。

## 定制

- **API 地址**：改 `config.js` 里的 `window.__CONSOLE_CONFIG__.apiBase`。
- **品牌**：替换 `assets/brand-mark.png`、`assets/favicon-*.png`、`favicon.ico`；
  标题改 `index.html` 的 `<title>` 与顶栏文案。
- **主题**：`themes/` 放 `{id}.css` 整包样式 + `{id}.json` 清单，并在
  `/api/state` 的 `themes` / `uiTheme` 中声明；深浅色跟随系统并可手动切换。
- **默认视图 / 文案**：`js/app.js` 与 `js/core.js` 中有少量 `总控台` 字样。

## 已知限制（相对原版）

- 原版的 macOS 原生文件/目录选择框（`osascript`）与系统通知（任务完成）在
  浏览器环境需要后端配合或浏览器授权；mock 中 `pick` 直接返回取消。
- 路径展示里的 `~/Users/...` 缩写只处理 macOS 路径，其他平台原样显示。
- `localStorage` 键（`console-view` / `console-theme` / `console-ui-theme`）
  与原版共用；同一域名下部署多个实例会互相影响，如需隔离可改 `js/core.js`。
- 应用图标等 JSON 内返回的路径（如 `/icons/x.png`）由你的后端决定；
  子路径托管时建议返回相对路径，或由页面同源提供 `/icons/*`。
- 必须通过 http(s) 访问；不支持双击 `file://` 打开（ES Modules + fetch 限制）。

## 许可

提取自 [local-ops](https://github.com/laogou717/local-ops)，遵循其开源许可；
Geist 字体与 Lucide 图标的许可见上游仓库 `licenses/`。
