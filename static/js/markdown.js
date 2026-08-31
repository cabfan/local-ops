'use strict';
/* markdown.js — 极简 Markdown 渲染（代码审查报告展示用）。
   先整体 HTML 转义再逐块转换，天然防注入；支持标题/加粗/斜体/行内代码/
   围栏代码/无序与有序列表/引用/分隔线/链接，覆盖 agent 报告的常见输出。
   返回 HTML 字符串（纯函数，node --test 可直接测试，不依赖 DOM）。 */

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, ch => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

function inline(escaped) {
  /* 行内语法；行内代码先占位保护，内部不再解析其它标记。 */
  const codes = [];
  let s = escaped.replace(/`([^`]+)`/g, (_, c) => {
    codes.push('<code>' + c + '</code>');
    return '\x00' + (codes.length - 1) + '\x00';
  });
  s = s
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*\n]+)\*/g, '<em>$1</em>')
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return s.replace(/\x00(\d+)\x00/g, (_, i) => codes[+i]);
}

function splitRow(line) {
  let s = line.trim();
  if (s.startsWith('|')) s = s.slice(1);
  if (s.endsWith('|') && !s.endsWith('\\|')) s = s.slice(0, -1);
  return s.split(/(?<!\\)\|/).map(c => c.trim().replace(/\\\|/g, '|'));
}

function isSepRow(cells) {
  return cells.length > 0 && cells.every(
    c => c === '' || /^:?-{2,}:?$/.test(c));
}

function renderTable(tblLines) {
  /* 标准表格需要第二行是 |---|---| 分隔行；否则返回 null 回退段落。 */
  const rows = tblLines.map(splitRow);
  if (rows.length < 2 || !isSepRow(rows[1])) return null;
  const html = ['<table><thead><tr>'];
  html.push(...rows[0].map(c => '<th>' + inline(escapeHtml(c)) + '</th>'));
  html.push('</tr></thead><tbody>');
  for (const row of rows.slice(2)) {
    html.push('<tr>');
    html.push(...row.map(c => '<td>' + inline(escapeHtml(c)) + '</td>'));
    html.push('</tr>');
  }
  html.push('</tbody></table>');
  return html.join('');
}

export function renderMarkdown(text) {
  const lines = String(text || '').replace(/\r\n?/g, '\n').split('\n');
  const out = [];
  let listTag = null;
  let codeBuf = null;
  let para = [];
  const flushPara = () => {
    if (para.length) {
      out.push('<p>' + inline(escapeHtml(para.join(' '))) + '</p>');
      para = [];
    }
  };
  const closeList = () => {
    if (listTag) { out.push('</' + listTag + '>'); listTag = null; }
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const fence = line.match(/^```\s*\S*\s*$/);
    if (fence) {
      if (codeBuf !== null) {
        out.push('<pre><code>' + escapeHtml(codeBuf.join('\n')) + '</code></pre>');
        codeBuf = null;
      } else {
        flushPara(); closeList(); codeBuf = [];
      }
      continue;
    }
    if (codeBuf !== null) { codeBuf.push(line); continue; }
    if (/^\s*\|/.test(line)) {
      flushPara(); closeList();
      const tbl = [line];
      while (i + 1 < lines.length && /^\s*\|/.test(lines[i + 1])) {
        tbl.push(lines[++i]);
      }
      const html = renderTable(tbl);
      if (html) { out.push(html); continue; }
      /* 非标准表格：按普通段落文本处理 */
      para.push(...tbl.map(l => l.trim()));
      continue;
    }
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      flushPara(); closeList();
      const level = h[1].length;
      out.push('<h' + level + '>' + inline(escapeHtml(h[2])) + '</h' + level + '>');
      continue;
    }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
      flushPara(); closeList(); out.push('<hr>');
      continue;
    }
    const quote = line.match(/^>\s?(.*)$/);
    if (quote) {
      flushPara(); closeList();
      out.push('<blockquote>' + inline(escapeHtml(quote[1])) + '</blockquote>');
      continue;
    }
    const ul = line.match(/^\s*[-*]\s+(.*)$/);
    if (ul) {
      flushPara();
      if (listTag !== 'ul') { closeList(); out.push('<ul>'); listTag = 'ul'; }
      out.push('<li>' + inline(escapeHtml(ul[1])) + '</li>');
      continue;
    }
    const ol = line.match(/^\s*\d+[.、)]\s*(.*)$/);
    /* 中文习惯的「1.（中）」序号后常无空格，标记符后不强制 \s。 */
    if (ol) {
      flushPara();
      if (listTag !== 'ol') { closeList(); out.push('<ol>'); listTag = 'ol'; }
      out.push('<li>' + inline(escapeHtml(ol[1])) + '</li>');
      continue;
    }
    if (!line.trim()) { flushPara(); closeList(); continue; }
    para.push(line.trim());
  }
  if (codeBuf !== null) {
    out.push('<pre><code>' + escapeHtml(codeBuf.join('\n')) + '</code></pre>');
  }
  flushPara(); closeList();
  return out.join('\n');
}
