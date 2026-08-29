'use strict';
/* ============================================================
   config.js — 数据适配层（唯一需要为你的项目改动的文件）

   本文件把「页面里所有 /api/* 请求」统一改发到 API 后端。
   不改任何视图/交互代码；静态资源（./themes、./assets、./fonts、icons.js 等）
   使用相对路径，从页面自身同源加载。

   API 地址的解析顺序：
     1. 显式设置：在加载本文件之前设置
            window.__CONSOLE_CONFIG__ = { apiBase: 'http://127.0.0.1:9600' };
        （在 index.html 里 <script src="./config.js"> 之前加一段 <script>，
          或在宿主页面里先赋值再引入本应用。）
     2. 默认（零配置）：自动取「页面所在目录」——页面托管在站点根路径或
        任意子路径（如 https://你的站点/tools/console-ui/）都能直接工作，
        前提是你的后端在同一位置实现了 /api/* 接口。

   注意：
     - 跨源时你的后端需要支持 CORS（/api/* 响应带 Access-Control-Allow-Origin）；
       mock_server.py 已经带上了。
     - 应用图标 <img src="/icons/..."> 不走 fetch，子路径/跨源部署时请由
       后端在页面同源提供 /icons/*，或让 JSON 里的图标字段返回相对路径。
     - 本应用需要 http(s) 环境（ES Modules + fetch），不能双击 file:// 打开。
   ============================================================ */

window.__CONSOLE_CONFIG__ = window.__CONSOLE_CONFIG__ || {};

/* 显式配置优先；未配置时默认跟随页面所在目录 */
const configuredBase = String(window.__CONSOLE_CONFIG__.apiBase || '').trim();
const API_BASE = configuredBase
  ? configuredBase.replace(/\/+$/, '')
  : new URL('./', location.href).href.replace(/\/+$/, '');

/* ---- 登录令牌（与 js/login.js 共用键名） ---- */
const TOKEN_KEY = 'console-ui-token';
function getToken() {
  try { return localStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; }
}
function clearToken() {
  try { localStorage.removeItem(TOKEN_KEY); } catch (e) { /* 忽略 */ }
}
const isLoginPage = /(^|\/)login\.html($|[?#])/.test(location.pathname);

/* 单点拦截：所有字符串形式的 /api/* 请求统一加前缀并附带登录令牌。
   绝对 URL / Request / URL 对象不处理；非 /api/ 的静态路径也不处理。
   未登录或会话过期（401/403）时跳转到登录页；登录接口自身的 401
   （密码错误）由登录页自行处理，不跳转。 */
const originalFetch = window.fetch;
window.fetch = function (input, init) {
  if (typeof input === 'string' && input.startsWith('/api/')) {
    const isLoginRequest = input.startsWith('/api/login');
    init = init || {};
    const headers = new Headers(init.headers);
    const token = getToken();
    if (token) headers.set('Authorization', 'Bearer ' + token);
    init.headers = headers;
    return originalFetch.call(this, API_BASE + input, init).then(res => {
      if (!isLoginRequest && (res.status === 401 || res.status === 403) && !isLoginPage) {
        clearToken();
        location.href = new URL('./login.html', location.href).href;
      }
      return res;
    });
  }
  return originalFetch.call(this, input, init);
};

/* ---- 可选：品牌与文案（仅在你需要时设置） ---- */
/* 例如：
window.__CONSOLE_CONFIG__.appName = '我的控制台';   // 顶栏/标题等处的展示名
*/
