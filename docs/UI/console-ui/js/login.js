'use strict';
/* ============================================================
   login.js — 登录页逻辑
   与 config.js 共用令牌键 console-ui-token；主题切换语义与
   js/core.js 一致（localStorage console-theme + 跟随系统）。
   ============================================================ */
import { icon } from './core.js';

const TOKEN_KEY = 'console-ui-token';
const $ = id => document.getElementById(id);

/* ---------------- 深浅色（与主界面一致） ---------------- */
const mq = window.matchMedia('(prefers-color-scheme: dark)');
function currentTheme() {
  try {
    return localStorage.getItem('console-theme') || (mq.matches ? 'dark' : 'light');
  } catch (e) {
    return mq.matches ? 'dark' : 'light';
  }
}
function applyTheme() {
  const t = currentTheme();
  document.documentElement.dataset.theme = t;
  const btn = $('themeBtn');
  if (btn) {
    btn.replaceChildren(icon(t === 'dark' ? 'sun' : 'moon', 15));
    btn.title = t === 'dark' ? '切换到浅色模式' : '切换到深色模式';
    btn.setAttribute('aria-label', btn.title);
  }
}
$('themeBtn').addEventListener('click', () => {
  try {
    localStorage.setItem('console-theme', currentTheme() === 'dark' ? 'light' : 'dark');
  } catch (e) { /* 忽略 */ }
  applyTheme();
});
applyTheme();

/* ---------------- 表单 ---------------- */
const form = $('loginForm');
const userEl = $('username');
const passEl = $('password');
const errorEl = $('loginError');
const submitBtn = $('loginSubmit');

function getToken() {
  try { return localStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; }
}
function setError(msg) {
  errorEl.textContent = msg || '';
  errorEl.hidden = !msg;
  userEl.classList.toggle('invalid', !!msg);
  passEl.classList.toggle('invalid', !!msg);
}

/* 已持有令牌则直接进入主界面；令牌失效（后端 401）时静默清除 */
(async function tryAutoEnter() {
  if (!getToken()) return;
  try {
    const r = await fetch('/api/state', { cache: 'no-store' });
    if (r.ok) {
      location.replace(new URL('./index.html', location.href).href);
      return;
    }
    if (r.status === 401 || r.status === 403) {
      try { localStorage.removeItem(TOKEN_KEY); } catch (e) { /* 忽略 */ }
    }
  } catch (e) {
    /* 后端未就绪：停留在登录页 */
  }
})();

form.addEventListener('submit', async e => {
  e.preventDefault();
  const username = userEl.value.trim();
  const password = passEl.value;
  if (!username || !password) {
    setError('请输入用户名和密码');
    return;
  }
  setError('');
  submitBtn.disabled = true;
  const label = submitBtn.textContent;
  submitBtn.textContent = '登录中…';
  try {
    const r = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    let data = null;
    try { data = await r.json(); } catch (err) { /* 非 JSON 响应 */ }
    if (r.ok && data && data.token) {
      try { localStorage.setItem(TOKEN_KEY, data.token); } catch (err) { /* 忽略 */ }
      location.replace(new URL('./index.html', location.href).href);
      return;
    }
    setError((data && data.error) || '登录失败，请稍后重试');
  } catch (err) {
    setError('无法连接后端，请确认服务已启动');
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = label;
  }
});

/* 聚焦第一个未填字段 */
(userEl.value ? passEl : userEl).focus();
