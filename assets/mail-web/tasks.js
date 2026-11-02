'use strict';
const $ = id => document.getElementById(id);
const node = (tag, text, className) => {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
};
const body = text => String(text || '').replace(/^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/, '').trim();
const title = (text, fallback) => {
  const header = String(text || '').match(/^---\r?\n([\s\S]*?)\r?\n---/);
  const match = header && header[1].match(/^title:\s*(.+)$/m);
  return match ? match[1].trim().replace(/^(['"])(.*)\1$/, '$2') : fallback;
};
let revision = 0;
function status(text, state = '') {
  $('status').textContent = text;
  $('status').dataset.state = state;
}
let artifactTicket = 0;
function wikiHref(path) { return '/#wiki-reader&path=' + encodeURIComponent(path); }
async function loadArtifact(task, item) {
  const ticket = ++artifactTicket;
  $('artifactStatus').textContent = '读取中…';
  $('artifactView').replaceChildren(node('p', '正在读取产物…', 'empty'));
  try {
    const params = new URLSearchParams({id: task.task_id, path: item.path, revision: String(item.revision)});
    const data = await get('/api/tasks/artifact?' + params);
    if (ticket !== artifactTicket) return;
    const changed = data.status === 'changed';
    $('artifactStatus').textContent = changed ? '显示当前文件；与历史记录不同，历史正文未保存' : data.status === 'unchanged' ? '与记录一致' : '状态待核对';
    $('artifactStatus').dataset.state = changed ? 'warning' : '';
    const meta = node('div', '', 'artifact-meta');
    meta.append(node('p', `${data.path} · 修订 ${data.revision}`));
    if (changed) meta.append(node('p', '当前显示磁盘文件内容，历史正文未保存。', 'file-warning'));
    const markdown = node('article', '', 'markdown-body');
    if (typeof data.body_html === 'string') markdown.innerHTML = data.body_html;
    else markdown.append(node('pre', data.text || '产物内容为空。', 'artifact-text'));
    const details = node('details', '', 'artifact-raw');
    details.append(node('summary', '原文与校验信息'), node('p', '格式：' + (data.format || '未提供')),
      node('p', '记录哈希：' + (data.expected_sha256 || item.sha256 || '未记录')),
      node('p', '当前文件哈希：' + (data.sha256 || '不可用')),
      node('pre', data.text || '产物内容为空。', 'artifact-text'));
    $('artifactView').replaceChildren(meta, markdown, details);
  } catch (error) {
    if (ticket !== artifactTicket) return;
    $('artifactStatus').textContent = error.message;
    $('artifactStatus').dataset.state = 'error';
    $('artifactView').replaceChildren(node('p', error.message, 'file-warning'));
  }
}
function renderArtifacts(task) {
  artifactTicket++;
  const versions = [
    ...task.history.map(entry => ({revision: entry.revision, artifacts: entry.artifacts || []})),
    {revision: task.revision, artifacts: task.artifacts || []}
  ];
  const items = versions.flatMap(version => version.artifacts.map(artifact => ({...artifact, revision: version.revision})));
  $('artifactList').replaceChildren();
  $('artifactStatus').textContent = '';
  $('artifactStatus').dataset.state = '';
  if (!items.length) {
    $('artifactList').append(node('p', '暂无已记录产物。', 'empty'));
    $('artifactView').replaceChildren(node('p', '检查 task checkpoint 是否关联了 artifact。', 'empty'));
    return;
  }
  for (const item of [...items].reverse()) {
    const button = node('button', '', 'artifact-choice');
    button.type = 'button';
    button.append(node('span', item.path.split('/').pop(), 'artifact-choice-name'), node('span', `修订 ${item.revision}`, 'artifact-choice-meta'));
    button.addEventListener('click', () => loadArtifact(task, item));
    $('artifactList').append(button);
  }
  loadArtifact(task, [...items].reverse()[0]);
}
function renderSources(task) {
  const sources = new Map();
  const add = (path, sha, titleText) => {
    if (typeof path !== 'string' || !path.startsWith('wiki/')) return;
    if (!sources.has(path)) sources.set(path, {path, sha, title: titleText || path.split('/').pop()});
  };
  for (const source of task.agreement.knowledge || []) add(source.path, source.sha256, source.title);
  for (const use of task.uses || []) add(use.source_path, use.source_sha256);
  for (const entry of task.history || []) {
    for (const source of entry.agreement?.knowledge || []) add(source.path, source.sha256, source.title);
    for (const use of entry.uses || []) add(use.source_path, use.source_sha256);
  }
  $('sources').replaceChildren();
  if (!sources.size) $('sources').append(node('p', '没有关联的 Wiki 来源。', 'empty'));
  for (const source of sources.values()) {
    const link = node('a', source.title, 'source-link');
    link.href = wikiHref(source.path);
    link.title = source.path;
    const item = node('div', '', 'source-item');
    const version = node('details', '', 'source-version');
    version.append(node('summary', '来源版本'), node('code', 'SHA-256 ' + (source.sha || '未记录')));
    item.append(link, node('code', source.path), version);
    $('sources').append(item);
  }
}
async function get(url) {
  return OksWorkspace.request(url);
}
function render(task) {
  const current = task.status === 'current';
  status(current ? `修订 ${task.revision} · 目标已同步` : '目标或来源有变化，请先确认', current ? '' : 'warning');
  $('title').textContent = title(task.agreement.goal.text, task.task_id);
  $('reviewLink').href = '/review?task=' + encodeURIComponent(task.task_id);
  $('goalState').textContent = current ? '目标' : '此前确认的目标';
  $('goal').textContent = body(task.agreement.goal.text);
  $('rawGoal').textContent = task.agreement.goal.text;
  $('progress').textContent = task.progress || '暂无进度记录';
  $('next').textContent = task.next_action || '尚未记录下一步';
  $('resume').textContent = current ? 'oks task select ' + task.task_id : `oks task refresh ${task.task_id} --revision ${task.revision} --accept-changes`;
  $('copy').disabled = false;
  $('copy').textContent = current ? '复制接手指令' : '复制确认更新指令';
  $('copyStatus').textContent = '';
  $('changes').replaceChildren();
  $('changes').hidden = current;
  if (!current) {
    const goalChanged = task.current_goal_text !== task.agreement.goal.text;
    $('changes').append(node('h3', goalChanged ? '新目标 · 待确认' : '关联来源待确认'), node('p', goalChanged ? body(task.current_goal_text) || '当前目标文件无法读取' : '请核对变化来源后继续。'));
    const paths = [...new Set(task.issues.map(issue => issue.path).filter(Boolean))];
    if (paths.length) $('changes').append(node('p', '变化来源：' + paths.join('、'), 'change-path'));
  }
  $('artifacts').replaceChildren();
  $('checks').replaceChildren();
  $('fileCount').textContent = task.artifacts.length || '';
  for (const artifact of task.artifacts) {
    const item = node('div', '', 'file');
    const segments = artifact.path.split('/');
    item.append(node('p', segments.pop(), 'file-name'), node('p', segments.join('/') || '/', 'file-path'));
    const issue = task.artifact_issues.find(value => value.path === artifact.path);
    if (issue) item.append(node('p', issue.code === 'artifact_changed' ? '文件已修改，待核对' : '文件不可用', 'file-warning'));
    $('artifacts').append(item);
    $('checks').append(node('p', artifact.path), node('code', artifact.sha256));
  }
  if (!task.artifacts.length) $('artifacts').append(node('p', '暂无产物', 'empty'));
  renderArtifacts(task);
  renderSources(task);
  $('decisions').replaceChildren();
  for (const source of task.agreement.knowledge) {
    const item = node('details', '', 'decision');
    item.append(node('summary', source.title), node('p', source.path), node('pre', JSON.stringify(source.options, null, 2)));
    $('decisions').append(item);
  }
  $('history').replaceChildren();
  $('historyCount').textContent = task.history.length ? `${task.history.length} 次修订` : '';
  for (const entry of [...task.history].reverse()) {
    const item = node('article', '', 'history-entry');
    item.append(node('h3', `修订 ${entry.revision}`), node('p', entry.progress || '任务建立'), node('p', entry.next_action ? '下一步：' + entry.next_action : ''));
    const goal = node('details', '');
    goal.append(node('summary', '当时的目标'), node('p', body(entry.agreement.goal.text)));
    item.append(goal);
    $('history').append(item);
  }
  if (!task.history.length) $('history').append(node('p', '暂无历史记录', 'empty'));
  document.querySelectorAll('#content details').forEach(detail => { detail.open = false; });
  $('content').hidden = false;
  history.replaceState(null, '', '?id=' + encodeURIComponent(task.task_id));
}
async function show() {
  const ticket = ++revision, id = $('taskSelect').value;
  $('content').hidden = true;
  $('copy').disabled = true;
  status(id ? '读取中…' : '请选择任务');
  if (!id) return;
  try {
    const task = await get('/api/tasks/show?id=' + encodeURIComponent(id));
    if (ticket === revision) render(task);
  } catch (error) { if (ticket === revision) status(error.message, 'error'); }
}
async function refresh() {
  const ticket = ++revision, selected = $('taskSelect').value || new URLSearchParams(location.search).get('id');
  $('refresh').disabled = true;
  $('content').hidden = true;
  status('读取中…');
  try {
    const data = await get('/api/tasks');
    if (ticket !== revision) return;
    $('taskSelect').replaceChildren(node('option', '请选择'));
    $('taskSelect').firstChild.value = '';
    for (const task of data.tasks) {
      const option = node('option', task.task_id);
      option.value = task.task_id;
      $('taskSelect').append(option);
    }
    if (data.tasks.some(task => task.task_id === selected)) {
      $('taskSelect').value = selected;
      await show();
    } else status(data.tasks.length ? '请选择任务' : '还没有任务，点击“创建任务”开始。');
  } catch (error) { if (ticket === revision) status(error.message, 'error'); }
  finally { $('refresh').disabled = false; }
}
$('copy').addEventListener('click', async () => {
  const ticket = revision;
  try {
    await navigator.clipboard.writeText($('resume').textContent);
    if (ticket === revision) $('copyStatus').textContent = $('resume').textContent.includes('refresh') ? '已复制。运行前先阅读上方变化并确认可接受。' : '已复制，在接手目录运行即可。';
  } catch {
    if (ticket !== revision) return;
    document.querySelector('.record-section').open = true;
    document.querySelector('.technical').open = true;
    $('copyStatus').textContent = '复制失败，请在技术详情中手动复制。';
  }
});
$('taskSelect').addEventListener('change', show);
$('refresh').addEventListener('click', refresh);
let taskOptions = {goals:[],wiki:[]}, goalPreview = null, goalTicket = 0, localEdit = false, creating = false;
function updateCreate() { $('createTask').disabled = creating || !localEdit || (!!$('goalChoice').value && !goalPreview); }
async function openCreate() {
  $('createPanel').hidden = false;
  $('newTaskId').value ||= 'task-' + Date.now().toString(36);
  $('createStatus').textContent = '读取目标与知识…';
  try {
    await OksWorkspace.ready;
    const context = OksWorkspace.context();
    localEdit = context?.local_edit === true;
    $('editGate').hidden = $('editCommand').hidden = localEdit;
    $('editGate').textContent = '创建任务需启用本地编辑。当前服务仍可只读查看。';
    $('editCommand').textContent = context?.commands.edit || `oks mail serve --path '<知识库路径>' --port ${location.port} --local-edit`;
    taskOptions = await get('/api/tasks/options');
    const selected = $('goalChoice').value;
    $('goalChoice').replaceChildren(node('option', '写一个新目标')); $('goalChoice').firstChild.value = '';
    for (const goal of taskOptions.goals) { const option = node('option', goal.title); option.value = goal.path; $('goalChoice').append(option); }
    if (taskOptions.goals.some(goal => goal.path === selected)) $('goalChoice').value = selected;
    $('wikiChoices').replaceChildren();
    for (const source of taskOptions.wiki) {
      const label = node('label', '', 'wiki-choice'), checkbox = document.createElement('input');
      checkbox.type = 'checkbox'; checkbox.value = source.path; checkbox.dataset.sha256 = source.sha256;
      label.append(checkbox, node('span', source.title)); $('wikiChoices').append(label);
    }
    if (!taskOptions.wiki.length) $('wikiChoices').append(node('p', '暂无可关联的已审核知识。', 'empty'));
    $('createStatus').textContent = taskOptions.truncated ? '显示前 100 项；更多资料可通过 CLI 选择。' : '';
    $('goalChoice').dispatchEvent(new Event('change'));
    updateCreate();
  } catch (error) { $('createStatus').textContent = error.message; }
}
$('newTask').addEventListener('click', openCreate);
$('closeCreate').addEventListener('click', () => { $('createPanel').hidden = true; });
$('goalChoice').addEventListener('change', async () => {
  const ticket = ++goalTicket, path = $('goalChoice').value; goalPreview = null;
  $('newGoalFields').hidden = !!path; $('existingGoalPreview').hidden = !path; updateCreate();
  if (!path) return;
  $('existingGoalPreview').textContent = '读取目标…';
  try { const data = await get('/api/tasks/goal?path=' + encodeURIComponent(path)); if (ticket === goalTicket) { goalPreview = data; $('existingGoalPreview').textContent = body(data.text); updateCreate(); } }
  catch (error) { if (ticket === goalTicket) $('createStatus').textContent = error.message; }
});
$('createForm').addEventListener('submit', async event => {
  event.preventDefault(); if (!localEdit || creating) return;
  const request = {expected_knowledge_base:OksWorkspace.context()?.knowledge_base, task_id:$('newTaskId').value.trim(), wiki:[...$('wikiChoices').querySelectorAll('input:checked')].map(item => ({path:item.value,sha256:item.dataset.sha256}))};
  if ($('goalChoice').value) {
    if (!goalPreview) return;
    request.goal_path = goalPreview.path; request.expected_goal_sha256 = goalPreview.sha256;
  } else {
    if (!$('newTitle').value.trim() || !$('newGoal').value.trim()) { $('createStatus').textContent = '请填写任务名称和目标。'; return; }
    request.new_goal = {title:$('newTitle').value.trim(),text:$('newGoal').value.trim()};
  }
  creating = true; updateCreate(); $('createStatus').textContent = '正在创建…';
  try {
    const task = await OksWorkspace.request('/api/tasks/create', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});
    $('createPanel').hidden = true;
    const option = node('option', task.task_id); option.value = task.task_id; $('taskSelect').append(option); $('taskSelect').value = task.task_id;
    ++revision; render(task); $('newTaskId').value = ''; $('newTitle').value = ''; $('newGoal').value = ''; $('createStatus').textContent = '';
  } catch (error) { $('createStatus').textContent = error.message; }
  finally { creating = false; updateCreate(); }
});
document.addEventListener('oks:reconnected', event => {
  localEdit = event.detail.context.local_edit === true;
  if (event.detail.changedRoot) {
    ++goalTicket; goalPreview = null; taskOptions = {goals:[],wiki:[]};
    $('content').hidden = true; $('createPanel').hidden = true; $('taskSelect').value = '';
    $('createForm').reset(); $('wikiChoices').replaceChildren();
    history.replaceState(null, '', '/tasks');
  }
  refresh(); updateCreate();
});
refresh();
