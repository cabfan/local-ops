/* markdown.js 纯函数行为测试（node --test，无 DOM 依赖）。
   锁定审查报告渲染的三条底线：先转义防注入、行内代码优先、
   块级结构（标题/列表/围栏/引用/分隔线）符合预期。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { renderMarkdown } from '../../static/js/markdown.js';

test('标题与加粗、斜体渲染', () => {
  const html = renderMarkdown('# 标题一\n## 本期概览\n**加粗** 和 *斜体*');
  assert.match(html, /<h1>标题一<\/h1>/);
  assert.match(html, /<h2>本期概览<\/h2>/);
  assert.match(html, /<strong>加粗<\/strong>/);
  assert.match(html, /<em>斜体<\/em>/);
});

test('HTML 输入被转义，不产生标签注入', () => {
  const html = renderMarkdown('<script>alert(1)<\/script>\n**<img src=x>**');
  assert.doesNotMatch(html, /<script>/);
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;script&gt;/);
});

test('行内代码内部不解析其它标记且被转义', () => {
  const html = renderMarkdown('使用 `**<b>x</b>**` 字段');
  assert.match(html, /<code>\*\*&lt;b&gt;x&lt;\/b&gt;\*\*<\/code>/);
  assert.doesNotMatch(html, /<strong>/);
});

test('无序与有序列表各自成块', () => {
  const html = renderMarkdown('- 甲\n- 乙\n1.（高）风险一\n2.（低）风险二');
  assert.match(html, /<ul>\s*<li>甲<\/li>\s*<li>乙<\/li>\s*<\/ul>/);
  assert.match(html, /<ol>\s*<li>[^<]*风险一<\/li>\s*<li>[^<]*风险二<\/li>\s*<\/ol>/);
});

test('围栏代码块整体转义且保留内部符号', () => {
  const html = renderMarkdown('```\n<a>&"\n```');
  assert.match(html, /<pre><code>&lt;a&gt;&amp;&quot;<\/code><\/pre>/);
});

test('表格渲染为 thead/tbody，单元格内支持行内标记', () => {
  const html = renderMarkdown(
    '| 分支 | 提交数 |\n|---|---|\n| main | **8** |\n| dev | `2` |');
  assert.match(html, /<table><thead><tr><th>分支<\/th><th>提交数<\/th><\/tr><\/thead>/);
  assert.match(html, /<tbody><tr><td>main<\/td><td><strong>8<\/strong><\/td><\/tr>/);
  assert.match(html, /<tr><td>dev<\/td><td><code>2<\/code><\/td><\/tr><\/tbody><\/table>/);
});

test('缺少分隔行的伪表格回退为段落文本', () => {
  const html = renderMarkdown('| a | b |\n| c | d |');
  assert.doesNotMatch(html, /<table>/);
  assert.match(html, /<p>/);
  assert.match(html, /a \| b/);
});

test('表格单元格内容被转义', () => {
  const html = renderMarkdown('| x |\n|---|\n| <b>注入</b> |');
  assert.doesNotMatch(html, /<b>注入/);
  assert.match(html, /&lt;b&gt;注入/);
});

test('引用、分隔线、链接', () => {
  const html = renderMarkdown('> 提示\n---\n[报告](https://x/a.md)');
  assert.match(html, /<blockquote>提示<\/blockquote>/);
  assert.match(html, /<hr>/);
  assert.match(html, /<a href="https:\/\/x\/a\.md"[^>]*>报告<\/a>/);
});
