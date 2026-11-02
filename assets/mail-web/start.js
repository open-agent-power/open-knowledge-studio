'use strict';
const $ = id => document.getElementById(id);
const el = (tag, text, className) => { const item = document.createElement(tag); item.textContent = text == null ? '' : String(text); if (className) item.className = className; return item; };
const valueText = value => typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value, null, 2);
async function request(url, options) {
  return OksWorkspace.request(url, options);
}
function pageStatus(text, state = '') { $('pageStatus').textContent = text; $('pageStatus').dataset.state = state; }
function wikiPath(row) {
  if (typeof row.source_path === 'string' && row.source_path.startsWith('wiki/')) return row.source_path;
  if (typeof row.uri === 'string' && row.uri.startsWith('oks://wiki/')) {
    try { return decodeURIComponent(row.uri.slice('oks://'.length)); } catch { return row.uri.slice('oks://'.length); }
  }
  return '';
}
function renderChecks(data) {
  $('knowledgeBase').textContent = data.knowledge_base || '未返回';
  $('instanceValid').textContent = data.instance_valid === true ? '可用' : data.instance_valid === false ? '需检查' : '未知';
  $('python').textContent = valueText(data.python) || '未返回';
  const host = $('checks'); host.replaceChildren();
  for (const check of data.checks || []) {
    const card = el('article', '', 'check-item'), header = el('div', '', 'check-head');
    const state = ({ok:'正常',warning:'需处理',failed:'未通过',missing:'未找到'})[check.status] || check.status || '未知';
    header.append(el('span', check.name || '检查项', 'check-name'), el('span', state, 'check-state'));
    card.append(header);
    if (check.detail) card.append(el('p', valueText(check.detail)));
    if (check.action) card.append(el('pre', valueText(check.action), 'check-action'));
    host.append(card);
  }
  if (!host.children.length) host.append(el('p', '没有返回检查项。', 'empty'));
  const retrieval = data.retrieval || {};
  $('retrievalStatus').textContent = retrieval.actual_backend === 'not_queried' ? '尚未运行查询。' : '当前检索状态已读取。';
  const commands = data.commands || {}, commandHost = $('commandList'); commandHost.replaceChildren();
  for (const key of ['init', 'serve', 'recall']) {
    if (!commands[key]) continue;
    const row = el('div', '', 'command-row'), code = el('code', valueText(commands[key]));
    row.prepend(el('span', ({init:'初始化',serve:'启动',recall:'查询'}[key] || key), 'command-title'));
    const copy = el('button', '复制'); copy.type = 'button';
    copy.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(valueText(commands[key])); copy.textContent = '已复制'; }
      catch { copy.textContent = '复制失败'; }
    });
    row.append(code, copy); commandHost.append(row);
  }
  if (!commandHost.children.length) commandHost.append(el('p', '没有返回可复制命令。', 'empty'));
  const schema = data.schema || data.schema_version;
  pageStatus(schema === 'workspace/v1' ? '检查完成' : '已读取，但响应schema与预期不同', schema === 'workspace/v1' ? '' : 'error');
}
function renderRecall(data) {
  const host = $('retrieval'); host.replaceChildren();
  const diagnostics = data.diagnostics || {};
  const backend = diagnostics.actual_backends || diagnostics.actual_backend || data.actual_backend || '未返回';
  const backendNames = {native:'内置检索',fts5:'全文检索',embedding:'向量检索'};
  const backendText = Array.isArray(backend) ? backend.map(value => backendNames[value] || value).join('、') : backendNames[backend] || backend;
  $('retrievalStatus').textContent = `查询完成 · 使用${valueText(backendText)}` + (diagnostics.fallback_reason ? ' · 已按当前环境回退' : '');
  {
    const section = el('section', '', 'result-block'); section.append(el('h3', '知识命中'));
    const rows = Array.isArray(data.knowledge) ? data.knowledge : [];
    for (const row of rows) {
      const card = el('article', '', 'result-card');
      const path = wikiPath(row), heading = el('h4', row.title || row.slug || path || '知识');
      if (path) { const link = el('a', row.title || row.slug || path); link.href = '/#wiki-reader&path=' + encodeURIComponent(path); heading.replaceChildren(link); }
      card.append(heading);
      if (row.body_preview || row.summary) card.append(el('p', row.body_preview || row.summary));
      section.append(card);
      if (row.artifact_kind === 'skill' && row.skill_id && row.skill_version) {
        const params = new URLSearchParams({id:row.skill_id,version:row.skill_version});
        request('/api/skills/bundled-diff?' + params).then(diff => {
          if (!diff.instructions_differ) return;
          const warning = el('p', '这份 Skill 说明与当前内置版本不同。', 'file-warning');
          const link = el('a', '查看说明差异'); link.href = '/versions?' + params + '&bundled=1';
          warning.append(document.createTextNode(' '), link); card.append(warning);
        }).catch(() => { /* Custom Skills need not have a bundled counterpart. */ });
      }
    }
    if (!rows.length) section.append(el('p', '没有命中。', 'empty'));
    host.append(section);
  }
  const details = el('details', '', 'result-block'), summary = el('summary', '检索诊断');
  details.append(summary, el('pre', JSON.stringify(data.diagnostics || {}, null, 2))); host.append(details);
  const full = el('details', '', 'result-block'); full.append(el('summary', '完整返回'), el('pre', JSON.stringify(data, null, 2))); host.append(full);
}
async function load() {
  $('refresh').disabled = true; pageStatus('正在检查…');
  try { renderChecks(await request('/api/workspace')); }
  catch (error) { pageStatus(error.message, 'error'); $('checks').replaceChildren(el('p', error.message, 'empty')); }
  finally { $('refresh').disabled = false; }
}
$('refresh').addEventListener('click', load);
$('queryForm').addEventListener('submit', async event => {
  event.preventDefault(); const query = $('query').value.trim(); if (!query) return;
  const button = $('querySubmit'); button.disabled = true; $('retrievalStatus').textContent = '正在运行查询…'; $('retrieval').replaceChildren();
  try { renderRecall(await request('/api/workspace/query', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query})})); }
  catch (error) { $('retrievalStatus').textContent = error.message; $('retrievalStatus').dataset.state = 'error'; }
  finally { button.disabled = false; }
});
load();
document.addEventListener('oks:reconnected', load);
