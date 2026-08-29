'use strict';
/* review.js — 每日代码审查视图：GitLab 项目配置、手动触发、报告查看 */
import { $, el, setText, icon, act, post, toast } from './core.js';

const ROOT = () => $('#reviewRoot');
let cache = null;
let selectedDay = today();

function today() {
  const d = new Date();
  const p = n => String(n).padStart(2, '0');
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
}
async function getJSON(url) {
  const r = await fetch(url, { cache: 'no-store' });
  return r.json();
}
function iconBtn(name, title) {
  const b = el('button', 'ibtn');
  b.type = 'button'; b.title = title;
  b.setAttribute('aria-label', title);
  b.appendChild(icon(name, 15));
  return b;
}
function field(label, type, value, placeholder) {
  const wrap = el('label', 'rv-field');
  const span = el('span', 'rv-label'); span.textContent = label;
  const input = el('input', 'rv-input');
  input.type = type || 'text';
  input.value = value || '';
  if (placeholder) input.placeholder = placeholder;
  wrap.append(span, input);
  return { wrap, input };
}

export function initReview() { /* 视图按进入时机初始化（enterReviewView），无需预绑定。 */ }

export async function enterReviewView() {
  await refresh();
  await loadReports(selectedDay);
}

async function refresh() {
  try {
    const j = await getJSON('/api/review');
    if (j && j.ok !== false) { cache = j; render(); }
  } catch (e) { /* 后端暂不可达则不渲染，交由断连处理 */ }
}

function render() {
  const box = ROOT();
  if (!box) return;
  box.replaceChildren();
  box.appendChild(toolbar());
  box.appendChild(projectPanel());
  box.appendChild(reportPanel());
}

function toolbar() {
  const bar = el('div', 'rv-toolbar');
  const run = el('button', 'btn primary'); run.type = 'button';
  run.appendChild(icon('play', 14));
  run.appendChild(document.createTextNode('立即审查'));
  run.title = '抓取各项目当日提交并生成报告';
  run.addEventListener('click', runNow);
  const add = el('button', 'btn'); add.type = 'button';
  add.appendChild(icon('plus', 14));
  add.appendChild(document.createTextNode('添加项目'));
  add.addEventListener('click', () => togglePanel('add'));
  const conf = el('button', 'btn'); conf.type = 'button';
  conf.appendChild(icon('settings', 14));
  conf.appendChild(document.createTextNode('AI / 调度 / 推送'));
  conf.addEventListener('click', () => togglePanel('config'));
  const daySel = el('select', 'rv-select');
  daySel.title = '选择查看日期';
  const days = (cache && cache.days) || [];
  if (!days.some(d => d.day === selectedDay)) {
    const opt = el('option'); opt.value = selectedDay; opt.textContent = selectedDay + '（今日）';
    daySel.appendChild(opt);
  }
  for (const d of days) {
    const opt = el('option'); opt.value = d.day; opt.textContent = d.day;
    daySel.appendChild(opt);
  }
  daySel.value = selectedDay;
  daySel.addEventListener('change', async () => {
    selectedDay = daySel.value;
    await loadReports(selectedDay);
  });
  const spacer = el('span', 'rv-spacer');
  bar.append(run, add, conf, spacer, daySel);
  return bar;
}

async function runNow() {
  const run = ROOT().querySelector('.rv-toolbar .btn.primary');
  run.disabled = true;
  try {
    const r = await act(post('/api/review/run', {}));
    if (r && r.ok === false) {
      toast(r.error || '执行失败');
      return;
    }
    toast('审查完成');
    if (r && r.day) selectedDay = r.day;
    await refresh();
    await loadReports(selectedDay);
  } finally {
    run.disabled = false;
  }
}

function togglePanel(which) {
  const root = ROOT();
  const forms = root.querySelectorAll('.rv-form[data-panel]');
  for (const form of forms) {
    if (form.dataset.panel === which) {
      form.hidden = !form.hidden;
    } else {
      form.hidden = true;
    }
  }
}

function projectPanel() {
  const panel = el('section', 'panel');
  const head = el('div', 'sec-label');
  head.textContent = '审查项目（GitLab 仓库）';
  panel.appendChild(head);

  const addForm = buildAddForm();
  addForm.hidden = true; addForm.dataset.panel = 'add';
  panel.appendChild(addForm);

  const confForm = buildConfigForm();
  confForm.hidden = true; confForm.dataset.panel = 'config';
  panel.appendChild(confForm);

  const list = el('div', 'rv-list');
  const projects = (cache && cache.projects) || [];
  if (!projects.length) {
    const empty = el('div', 'rv-empty');
    empty.textContent = '还没有审查项目。点击「添加项目」配置 GitLab 仓库。';
    list.appendChild(empty);
  } else {
    for (const p of projects) list.appendChild(projectRow(p));
  }
  panel.appendChild(list);
  return panel;
}

function projectRow(p) {
  const row = el('div', 'rv-row');
  const main = el('div', 'rv-row-main');
  const name = el('div', 'rv-row-name');
  name.textContent = p.name || '未命名';
  const meta = el('div', 'rv-row-meta');
  meta.textContent = (p.remote || '') +
    (p.branch ? ' · ' + p.branch : '') +
    (p.last_ran_at ? ' · 上次 ' + p.last_ran_at : '');
  main.append(name, meta);

  const enable = el('button', 'ibtn');
  enable.appendChild(icon(p.enabled ? 'check' : 'x', 14));
  enable.title = p.enabled ? '已启用（点击停用）' : '已停用（点击启用）';
  enable.setAttribute('aria-label', enable.title);
  enable.addEventListener('click', async () => {
    await act(putReview(p.id, { enabled: !p.enabled }));
    await refresh();
  });

  const del = iconBtn('trash-2', '删除项目');
  del.addEventListener('click', async () => {
    if (!window.confirm('删除项目「' + p.name + '」？历史报告会保留。')) return;
    await act(delReview(p.id));
    await refresh();
  });

  row.append(main, enable, del);
  return row;
}

function buildAddForm() {
  const form = el('form', 'rv-form');
  const fName = field('项目名', 'text', '', 'order-api');
  const fRemote = field('Git 地址', 'text', '', 'https://gitlab.com/x/order-api.git');
  const fBranch = field('分支', 'text', 'main');
  const fAuth = el('label', 'rv-field');
  fAuth.appendChild(el('span', 'rv-label')).textContent = '认证方式';
  const sel = el('select', 'rv-input');
  sel.appendChild(el('option')).textContent = 'ssh（本机密钥）';
  sel.appendChild(el('option')).textContent = 'https token';
  fAuth.appendChild(sel);
  const fToken = field('Token（可留空）', 'password', '');
  const submit = el('button', 'btn primary'); submit.type = 'submit';
  submit.textContent = '保存项目';
  form.append(fName.wrap, fRemote.wrap, fBranch.wrap, fAuth, fToken.wrap, submit);
  form.addEventListener('submit', async ev => {
    ev.preventDefault();
    const body = {
      name: fName.input.value.trim(),
      remote: fRemote.input.value.trim(),
      branch: fBranch.input.value.trim() || 'main',
      auth_type: sel.selectedIndex === 1 ? 'token' : 'ssh',
      auth_token: sel.selectedIndex === 1 ? fToken.input.value.trim() : '',
    };
    const r = await act(post('/api/review/projects', body));
    if (r && r.ok === false) { toast(r.error || '添加失败'); return; }
    toast('已添加项目');
    form.hidden = true;
    await refresh();
  });
  return form;
}

function buildConfigForm() {
  const form = el('form', 'rv-form rv-config');
  const review = (cache && cache.reviewRoot) || {};
  const ai = (cache && cache.ai) || {};
  const sched = (cache && cache.schedule) || {};
  const pushEndpoint = (cache && cache.pushEndpoint) || '';

  const fBase = field('AI 接口(baseUrl)', 'text', ai.baseUrl || '', 'https://llm.example.com/v1');
  const fModel = field('模型', 'text', ai.model || '');
  const fKeyEnv = field('Key 环境变量', 'text', ai.apiKeyEnv || 'REVIEW_AI_KEY');
  const fHour = field('每日时刻(HH)', 'text', String(sched.hour != null ? sched.hour : 3));
  const fMinute = field('(mm)', 'text', String(sched.minute != null ? sched.minute : 0));
  const fPush = field('推送端点', 'text', pushEndpoint);
  const fEnabled = el('label', 'rv-check');
  const checkbox = el('input', ''); checkbox.type = 'checkbox'; checkbox.checked = !!sched.enabled;
  fEnabled.append(checkbox, document.createTextNode('启用每日定时'));
  const submit = el('button', 'btn primary'); submit.type = 'submit';
  submit.textContent = '保存配置';
  const rowLine = el('div', 'rv-rowline');
  rowLine.append(fHour.wrap, fMinute.wrap);
  form.append(fBase.wrap, fModel.wrap, fKeyEnv.wrap, rowLine, fPush.wrap, fEnabled, submit);
  form.addEventListener('submit', async ev => {
    ev.preventDefault();
    const r = await act(post('/api/review/config', {
      ai: { baseUrl: fBase.input.value.trim(), model: fModel.input.value.trim(),
            apiKeyEnv: fKeyEnv.input.value.trim() },
      schedule: { enabled: checkbox.checked,
                  hour: Number(fHour.input.value) || 3,
                  minute: Number(fMinute.input.value) || 0 },
      push: { endpoint: fPush.input.value.trim() },
    }));
    if (r && r.ok === false) { toast(r.error || '保存失败'); return; }
    toast('已保存配置');
    form.hidden = true;
    await refresh();
  });
  return form;
}

function reportPanel() {
  const panel = el('section', 'panel');
  const head = el('div', 'sec-label');
  head.textContent = '代码审查报告 · ' + selectedDay;
  panel.appendChild(head);
  panel.appendChild(el('div', 'rv-reports'));
  return panel;
}

async function loadReports(day) {
  if (!day) day = selectedDay;
  let node = ROOT() && ROOT().querySelector('.rv-reports');
  if (!node) return;
  node.replaceChildren();
  if ((cache && cache.days && cache.days.length === 0 && day === today())) {
    const empty = el('div', 'rv-empty');
    empty.textContent = '今天还没有报告。点击「立即审查」生成。';
    node.appendChild(empty);
    return;
  }
  const loading = el('div', 'rv-empty');
  loading.textContent = '加载中…';
  node.appendChild(loading);
  try {
    const j = await getJSON('/api/review/reports?day=' + encodeURIComponent(day));
    node.replaceChildren();
    if (!j || j.ok === false || !j.summary) {
      const empty = el('div', 'rv-empty');
      empty.textContent = '该日期暂无报告。';
      node.appendChild(empty);
      return;
    }
    const summary = el('pre', 'rv-markdown');
    summary.textContent = j.summary.summary || '';
    node.appendChild(summary);
    for (const rep of (j.reports || [])) {
      const box = el('div', 'rv-item');
      const h = el('div', 'rv-item-head');
      h.textContent = rep.project_name;
      const pre = el('pre', 'rv-markdown');
      pre.textContent = rep.summary || '';
      box.append(h, pre);
      node.appendChild(box);
    }
    const logs = (j.pushLogs || []).slice(0, 3);
    if (logs.length) {
      const pushBox = el('div', 'rv-push');
      logs.forEach(l => {
        const line = el('div', 'rv-push-line');
        line.textContent = '推送 ' + (l.status || '—') +
          ' · ' + (l.http_code != null ? l.http_code + ' ' : '') + (l.attempted_at || '');
        pushBox.appendChild(line);
      });
      node.appendChild(pushBox);
    }
  } catch (e) {
    const empty = el('div', 'rv-empty');
    empty.textContent = '加载失败';
    node.appendChild(empty);
  }
}

const putReview = (id, body) => fetch('/api/review/projects/' + id, {
  method: 'PUT',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
}).then(r => r.status === 204 ? { ok: true } : r.json());
const delReview = id => fetch('/api/review/projects/' + id, {
  method: 'DELETE',
}).then(r => r.json());