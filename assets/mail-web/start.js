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
function renderHome(data) {
  $('workspaceName').textContent = (data.name || '本地知识库') + (data.storage_kind === 'temporary' ? ' · 临时实例' : '');
  $('storageStatus').textContent = data.storage_kind === 'temporary' ? '临时目录中的验收实例' : '独立本地文件夹';
  const counts = data.counts || {}, known = value => Number.isInteger(value) && value >= 0;
  $('goalCount').textContent = known(counts.active_tasks) ? counts.active_tasks + ' 项未结束 →' : '查看目标 →';
  $('knowledgeCount').textContent = known(counts.reviewed_knowledge) ? counts.reviewed_knowledge + ' 份已确认知识 →' : '阅读知识 →';
  $('reviewLink').textContent = known(counts.pending_drafts) ? '待审 ' + counts.pending_drafts + ' 条 →' : '学习审核 →';
  const host = $('nextTasks'); host.replaceChildren();
  for (const task of data.next_tasks || []) {
    const link = el('a', '', 'daily-task'); link.href = '/tasks?id=' + encodeURIComponent(task.task_id);
    link.append(el('strong', task.title || '未命名目标'), el('small', task.awaiting_confirmation ? '待你确认' : '继续 →'),
      el('p', task.next_action || task.progress || '打开目标，补充下一步。')); host.append(link);
  }
  if (!host.children.length) {
    host.append(el('p', known(counts.active_tasks) ? '还没有需要继续的目标。写清要做的事和完成标准，就可以开始。' : '目标暂时无法完整读取，请刷新后再试。', 'empty'));
  }
  const drafts = $('pendingDrafts'); drafts.replaceChildren();
  for (const item of data.pending_drafts || []) {
    const row = el('div', '', 'pending-row'), link = el('a', item.title || '待审建议');
    link.href = '/review?draft=' + encodeURIComponent(item.path) + '&return_to=%2Fstart';
    row.append(link, el('small', item.kind === 'skill' ? '方法 · 待审核' : '经验 · 待审核')); drafts.append(row);
  }
  if (!drafts.children.length) drafts.append(el('p', known(counts.pending_drafts) ? '暂时没有待审建议。完成工作后，再留下真正值得复用的经验。' : '建议暂时无法完整读取，请刷新后再试。', 'empty'));
  const partial = (data.errors || []).length || Object.values(data.truncated || {}).some(Boolean);
  pageStatus(partial ? '部分记录未能完整读取；已读内容仍可查看。' : '已连接 · 记录保存在当前知识库', partial ? 'error' : '');
}
function renderDaily(data) {
  const summary=$('dailyCaptureSummary'), list=$('dailyCaptureEntries'); summary.replaceChildren(); list.replaceChildren();
  if (!data || data.schema_version !== 'daily-workspace/v1') { summary.append(el('p','日常记录暂时无法读取。','empty')); return; }
  const sources=Array.isArray(data.sources)?data.sources:[], counts=data.counts||{}, processor=data.processor||{};
  const line=el('p',`${sources.length} 个已连接来源 · ${Number.isInteger(counts.captured)?counts.captured:'—'} 条已记录 · ${Number.isInteger(counts.pending)?counts.pending:'—'} 条待处理`,'daily-capture-count');
  summary.append(line);
  const details=el('details','daily-source-details'); details.append(el('summary',sources.length?'查看接入范围':'尚未接入来源'));
  const sourceStates={connected:'已连接',checked:'已检查',captured:'已采集',partial:'部分完成',error:'接入异常',failed:'接入失败',disabled:'已停用'};
  for(const src of sources){const row=el('div','daily-source-row');row.append(el('strong',src.label||src.host||'来源'),el('span',src.error?'接入异常':sourceStates[src.status]||'状态未知',src.error?'daily-error':''));const ws=el('small',src.workspace||'工作区未返回');row.append(ws);if(src.error)row.append(el('small','采集问题：'+src.error,'daily-error'));details.append(row);}
  if(!sources.length)details.append(el('p','连接具体工作区后，新的讨论和资料阅读才会出现在这里。','empty'));
  summary.append(details);
  const state=processor.error?'学习处理异常':processor.running?(processor.learning_status==='waiting_for_reply'?'记录持续采集，回复结束或暂时无新增记录后提炼':'记录采集运行中'):counts.pending?'等待处理':processor.updated_at?'处理器空闲':'等待首次记录';
  summary.append(el('p',state+(processor.error?` · ${processor.error}`:''),'daily-processor'+(processor.error?' daily-error':'')));
  if(processor.learning_error)summary.append(el('p','学习处理问题：'+processor.learning_error,'daily-processor daily-error'));
  const hookErrors=sources.filter(src=>src.error).map(src=>`${src.label||src.host||'来源'}：${src.error}`);
  if(hookErrors.length)summary.append(el('p','采集 Hook 问题：'+hookErrors.join('；'),'daily-processor daily-error'));
  const entries=Array.isArray(data.entries)?data.entries.slice(0,5):[];
  for(const item of entries){const a=el('a','','daily-capture-entry');a.href='/#collaboration&entry='+encodeURIComponent(item.id);a.append(el('strong',item.title||'日常记录'),el('small',`${item.role==='user'?'你':item.role==='assistant'?'Agent':'资料'} · ${({drafted:'已生成待审建议',failed:'处理失败',processing:'处理中',skipped:'未生成建议',pending:'待处理'})[item.learning_status]||'状态未知'}`),el('p',item.preview||'（没有可显示的预览）'));if(item.learning_error)a.append(el('small','学习处理问题：'+item.learning_error,'daily-error'));list.append(a);}
  if(!entries.length)list.append(el('p','尚无新记录。采集会从连接后的新事件开始，不回填历史。','empty'));
}
async function refreshDaily(){try{renderDaily(await request('/api/daily/overview'));}catch{renderDaily(null);}}
function renderAudit(data) {
  const host = $('retrievalAudit'); host.replaceChildren();
  host.append(el('p', '当前配置：' + (data.configured_backend || '未知') + '。此处只显示入口规则。', 'audit-status'));
  const labels = {
    'cli-recall':['普通查询','按知识库配置或显式参数选择','显式 Native / Fusion 时参与'],
    'skill-search':['方法查询','固定 FTS5；可重试正文','不调用 Native'],
    'prompt-hook':['会话自动召回','沿用普通查询配置','同普通查询'],
    'workspace-query':['页面查询','沿用普通查询配置','同普通查询'],
    'vfs-find':['文件查找','逐文件按文字匹配','不调用检索后端'],
    'fts5-runtime':['FTS5 不可用','退到 LIKE 文字查询','不因此改用 Native'],
    'fusion-native':['Fusion 对照','明确选择时融合排序','会运行 Native']
  };
  const table = el('table', '', 'audit-table'), head = el('tr');
  for (const text of ['入口','选择方式','Native 参与条件']) head.append(el('th',text)); table.append(head);
  for (const item of data.entries || []) {
    const row = el('tr'); for (const text of labels[item.id] || [item.title, '查看完整规则', '未标注']) row.append(el('td',text)); table.append(row);
  }
  host.append(table);
  const details = el('details'); details.append(el('summary','完整规则与代码依据'),el('pre',JSON.stringify(data,null,2))); host.append(details);
}
function renderChecks(data) {
  $('knowledgeBase').textContent = data.knowledge_base || '未返回';
  $('instanceValid').textContent = data.instance_valid === true ? '已连接' : data.instance_valid === false ? '需要处理' : '状态未知';
  $('python').textContent = valueText(data.python) || '未返回';
  const host = $('checks'); host.replaceChildren();
  for (const check of data.checks || []) {
    const card = el('article', '', 'check-item'), header = el('div', '', 'check-head');
    const state = ({ok:'正常',warning:'需处理',failed:'未通过',missing:'未找到'})[check.status] || check.status || '未知';
    const names = {'全文检索':'知识查询','接入方式':'当前连接'};
    const normal = {'知识库':'资料保存在独立的知识库中。','全文检索':'已找到按关键词查找知识所需的组件。','接入方式':'当前页面已连接到此知识库。'};
    header.append(el('span', names[check.name] || check.name || '检查项', 'check-name'), el('span', state, 'check-state'));
    card.append(header);
    if (check.status === 'ok' && normal[check.name]) {
      card.append(el('p',normal[check.name]));
      const details = el('details','','technical-details'); details.append(el('summary','检查详情'));
      if (check.detail) details.append(el('p',valueText(check.detail)));
      if (check.action) details.append(el('pre',valueText(check.action),'check-action'));
      card.append(details);
    } else if (check.detail) card.append(el('p', valueText(check.detail)));
    if (check.action && !(check.status === 'ok' && normal[check.name])) {
      const details = el('details', '', 'technical-details');
      details.append(el('summary', '查看处理命令'), el('pre', valueText(check.action), 'check-action'));
      card.append(details);
    }
    host.append(card);
  }
  if (!host.children.length) host.append(el('p', '没有返回检查项。', 'empty'));
  const retrieval = data.retrieval || {};
  $('retrievalStatus').textContent = retrieval.actual_backend === 'not_queried' ? '尚未查询知识。' : '查询状态已读取。';
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
  if (schema !== 'workspace/v1') throw new Error('检查结果格式需要核对。');
}
function renderRecall(data) {
  const host = $('retrieval'); host.replaceChildren();
  const diagnostics = data.diagnostics || {};
  const backends = Array.isArray(diagnostics.actual_backends) ? diagnostics.actual_backends.join('、') : '';
  $('retrievalStatus').textContent = (diagnostics.fallback_reason ? '查询完成（已使用备用方式）。' : '查询完成。') + (backends ? ' 本次方式：' + backends : ' 实际查询方式未返回。');
  {
    const section = el('section', '', 'result-block'); section.append(el('h3', '相关知识'));
    const rows = Array.isArray(data.knowledge) ? data.knowledge : [];
    for (const row of rows) {
      const card = el('article', '', 'result-card');
      if (row.artifact_kind === 'skill') card.append(el('div', '可复用方法 · Skill', 'result-kind'));
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
  const details = el('details', '', 'result-block'), summary = el('summary', '技术详情：查询诊断');
  details.append(summary, el('pre', JSON.stringify(data.diagnostics || {}, null, 2))); host.append(details);
  const full = el('details', '', 'result-block'); full.append(el('summary', '技术详情：完整查询结果'), el('pre', JSON.stringify(data, null, 2))); host.append(full);
}
async function load() {
  $('refresh').disabled = true; pageStatus('正在检查…');
  try {
    const checks = await Promise.allSettled([
      request('/api/workspace').then(renderChecks),
      request('/api/workspace/overview').then(renderHome),
      request('/api/workspace/retrieval').then(renderAudit),
      request('/api/daily/overview').then(renderDaily)
    ]);
    checks.forEach((result,index) => { if (result.status !== 'rejected') return;
      if (index === 0) $('checks').replaceChildren(el('p',result.reason.message,'empty'));
      if (index === 1) { $('nextTasks').replaceChildren(el('p','工作记录读取失败，请刷新重试。','empty')); $('pendingDrafts').replaceChildren(el('p','待审建议未能读取。','empty')); }
      if (index === 2) $('retrievalAudit').replaceChildren(el('p','查询规则暂时无法读取。','empty'));
      if (index === 3) renderDaily(null);
    });
    if (checks.some(item => item.status === 'rejected')) pageStatus('部分内容未能读取，可刷新重试。','error');
  }
  catch (error) { pageStatus(error.message, 'error'); }
  finally { $('refresh').disabled = false; }
}
$('refresh').addEventListener('click', load);
$('queryForm').addEventListener('submit', async event => {
  event.preventDefault(); const query = $('query').value.trim(); if (!query) return;
  $('retrievalStatus').dataset.state = '';
  const button = $('querySubmit'); button.disabled = true; $('retrievalStatus').textContent = '正在查询知识…'; $('retrieval').replaceChildren();
  try { renderRecall(await request('/api/workspace/query', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query})})); }
  catch (error) { $('retrievalStatus').textContent = error.message; $('retrievalStatus').dataset.state = 'error'; }
  finally { button.disabled = false; }
});
$('copyConnection').addEventListener('click',async()=>{
  const button=$('copyConnection');button.disabled=true;
  try { const data=await request('/api/connection-guide'), guide=data.guide||data.instructions;
    if(!guide)throw new Error('接入说明未返回，请查看安装命令。');
    await navigator.clipboard.writeText(typeof guide==='string'?guide:JSON.stringify(guide,null,2));
    $('connectionStatus').textContent='已复制，可交给当前使用的 Agent。';
  } catch(error) { $('connectionStatus').textContent=error.message||'复制失败，请查看安装命令。'; }
  finally {button.disabled=false;}
});
load();
document.addEventListener('oks:reconnected', load);
setInterval(refreshDaily, 7000);
