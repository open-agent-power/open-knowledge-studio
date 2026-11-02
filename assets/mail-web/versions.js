'use strict';
const $ = id => document.getElementById(id);
const el = (tag, value, cls) => { const n = document.createElement(tag); n.textContent = value == null ? '' : String(value); if (cls) n.className = cls; return n; };
function status(text, state = '') { $('status').textContent = text; $('status').dataset.state = state; }
async function get(url) { return OksWorkspace.request(url); }
let versions = [];
const labels = {
  pending_review: '待审核', reviewed: '已审核', superseded: '已被新版本替代', archived: '已归档', unreviewed: '未审核', inactive: '不可用',
  ok: '校验通过', failed: '校验失败', added: '新增', modified: '修改', deleted: '删除',
  current: '当前有效', needs_review: '需要复核', unknown: '状态未知',
  bound_to_old_version: '仍引用旧版本', not_loaded: '未加载', unchanged_managed: '由 OKS 管理且未修改',
  modified_managed: '由 OKS 管理但已修改', modified_or_unreadable: '已修改或无法读取',
  unmanaged_existing: '已有非托管副本', unavailable: '状态不可读取',
  caller_reported: '调用方报告',
};
const label = value => labels[value] || value || '未知';
function omittedReason(value) {
  if (!value) return '';
  if (value.includes('one side exceeds 64 KiB')) return '新旧文件至少一侧超过 64 KiB，已省略文本差异';
  if (value.includes('line diff limit')) return '文件行数超过上限，已省略文本差异';
  if (value.includes('256 KiB total')) return '差异总量超过 256 KiB，已省略后续文本';
  if (value === 'binary file') return '二进制文件不显示文本差异';
  if (value === 'file is not UTF-8 text') return '文件不是 UTF-8 文本，无法显示差异';
  return value;
}
function integrityIssue(value) {
  return ({
    'Skill snapshot was modified after import': '导入后快照文件已变化',
    'Skill manifest does not match the card identity/version': '清单与卡片身份或版本不匹配',
    'Skill archive exceeds size limits': '压缩包超过大小限制',
    'Invalid Skill archive': '压缩包无效',
    'Skill assets do not match their manifest': '资产与清单校验不一致',
    'Skill version does not identify captured files': '版本号与文件内容不匹配',
    'Unsafe path in Skill package metadata': '包元数据中的路径不安全',
    'Symlink or junction is not allowed in Skill assets': '资产中不允许符号链接或联接',
    'Skill asset path escapes the knowledge instance': '资产路径超出知识库范围',
    'Skill assets must be captured under raw/': '资产必须保存在 raw/ 下',
    'Skill snapshot exceeds size limits': '快照超过大小限制',
    FileNotFoundError: '快照文件缺失', OSError: '快照文件无法读取',
    'Skill snapshot failed validation': '快照校验失败',
  })[value] || value;
}
function renderVersions(data) {
  versions = data.versions || [];
  $('versionList').hidden = false;
  $('versionList').replaceChildren();
  $('fromVersion').replaceChildren(); $('toVersion').replaceChildren();
  for (const version of versions) {
    const optionLabel = `${version.version.slice(0, 12)}… · ${label(version.review_state)} · ${label(version.integrity)}`;
    const card = el('article', '', 'version-card');
    card.append(el('h2', `${version.version.slice(0, 12)}…`), el('p', `审核：${label(version.review_state)} · 完整性：${label(version.integrity)}`));
    const fullVersion = el('details', '', 'full-version');
    fullVersion.append(el('summary', '查看完整版本号'), el('code', version.version));
    card.append(fullVersion);
    for (const item of version.cards || []) {
      const cardInfo = el('p', `${item.slug} · ${label(item.review_state)} · ${label(item.integrity)}${item.integrity_issue ? ' · ' + integrityIssue(item.integrity_issue) : ''}`, item.integrity === 'failed' ? 'warning' : '');
      card.append(cardInfo);
      if (item.review_state === 'pending_review' && item.file_path) {
        const link = el('a', '打开待审核草稿');
        link.href = '/review?draft=' + encodeURIComponent(item.file_path);
        link.className = 'review-link';
        card.append(link);
      }
    }
    $('versionList').append(card);
    for (const select of [$('fromVersion'), $('toVersion')]) { const option = el('option', optionLabel); option.value = version.version; select.append(option); }
  }
  if (versions.length) {
    $('compareControls').hidden = false;
    $('toVersion').selectedIndex = 0;
    $('fromVersion').selectedIndex = Math.min(1, versions.length - 1);
    status(`${versions.length} 个版本已读取。`);
  } else { $('compareControls').hidden = true; status('没有找到该 Skill 的版本。', 'warning'); }
}
function renderDiff(data) {
  $('results').hidden = false;
  for (const [target, item] of [['fromSummary', data.from], ['toSummary', data.to]]) {
    $(target).replaceChildren(el('span', `${item.version.slice(0, 12)}… · ${label(item.review_state)}`));
    const details = el('details', '', 'full-version');
    details.append(el('summary', '查看完整版本号'), el('code', item.version));
    $(target).append(details);
  }
  $('changeCount').textContent = `${data.change_count} 项` + (data.files_truncated ? ` · 另有 ${data.files_truncated} 个路径未列出` : '');
  $('versionList').hidden = true;
  $('changes').replaceChildren();
  if (!(data.changes || []).length) $('changes').append(el('p', '两个快照没有文件差异。', 'empty'));
  for (const change of data.changes || []) {
    const article = el('article', '', 'change-card');
    article.append(el('h3', `${label(change.status)} · ${change.path}`));
    const hashes = el('details', '', 'file-hashes');
    hashes.append(el('summary', '查看文件哈希'), el('code', `旧版：${change.from_sha256 || '不存在'}\n新版：${change.to_sha256 || '不存在'}`));
    article.append(hashes);
    if (change.unified_diff) article.append(el('pre', change.unified_diff, 'diff-text'));
    else if (change.diff_omitted_reason) article.append(el('p', `未显示文本差异：${omittedReason(change.diff_omitted_reason)}`, 'warning'));
    $('changes').append(article);
  }
  $('tasks').replaceChildren();
  if (!(data.affected_tasks || []).length) $('tasks').append(el('p', '没有发现直接引用旧版卡片的当前任务。', 'empty'));
  for (const task of data.affected_tasks || []) {
    const article = el('article', '', 'task-card');
    const taskLink = el('a', `${task.task_id} · 修订 ${task.revision} · ${label(task.comparison_status)}`);
    taskLink.href = '/tasks?id=' + encodeURIComponent(task.task_id);
    taskLink.className = 'task-link';
    article.append(taskLink);
    article.append(el('p', `任务状态：${label(task.task_status)} · ${label(task.binding)}`));
    for (const path of task.source_paths || []) article.append(el('code', path));
    for (const use of task.uses || []) article.append(el('p', `使用记录：${use.source_path} · ${use.skill_version ? use.skill_version.slice(0, 12) + '…' : '版本未记录'} · ${label(use.verification)} · 执行未验证`));
    $('tasks').append(article);
  }
  $('loadCommand').replaceChildren();
  if (data.recovery.load_command) $('loadCommand').append(el('code', data.recovery.load_command));
  else $('loadCommand').append(el('p', '旧版本没有可加载的已审核卡片；先通过人工审核流程。', 'warning'));
  $('hostStates').replaceChildren();
  const visibleHosts = (data.recovery.hosts || []).filter(host => host.state !== 'not_loaded');
  if (!visibleHosts.length) {
    $('hostStates').append(el('p', '没有发现已加载的宿主副本。', 'empty'));
  } else {
    const details = el('details', '', 'host-details');
    details.append(el('summary', '宿主副本'));
    const rows = el('div', '', 'host-rows');
    for (const host of visibleHosts) {
    const row = el('article', '', 'host-card');
    const hostNames = {agents: '通用 Agent', claude: 'Claude Code', qoder: 'Qoder', codebuddy: 'CodeBuddy'};
    row.append(el('h3', `${hostNames[host.host] || host.host || '宿主'} · ${label(host.state)}`));
    if (host.note) row.append(el('p', '本地内容已修改或目录不受 OKS 管理；保留现状，不覆盖。', 'warning'));
    for (const command of host.recovery_commands || []) row.append(el('code', command));
      rows.append(row);
    }
    details.append(rows);
    $('hostStates').append(details);
  }
}
async function loadVersions() {
  const id = $('skillId').value.trim();
  if (!id) return status('请输入 Skill ID。', 'warning');
  $('results').hidden = true;
  try { status('正在读取版本…'); renderVersions(await get('/api/skills/versions?id=' + encodeURIComponent(id))); }
  catch (error) { status(error.message, 'error'); }
}
async function compare() {
  const id = $('skillId').value.trim(), from = $('fromVersion').value, to = $('toVersion').value;
  if (!id || !from || !to) return status('先读取版本并选择两个快照。', 'warning');
  try { status('正在比较…'); renderDiff(await get('/api/skills/diff?' + new URLSearchParams({id, from, to}))); status('对照已完成。'); }
  catch (error) { status(error.message, 'error'); }
}
$('loadVersions').addEventListener('click', loadVersions);
$('refresh').addEventListener('click', loadVersions);
$('compare').addEventListener('click', compare);
$('skillId').addEventListener('keydown', event => { if (event.key === 'Enter') loadVersions(); });
let bundled = null, bundleSequence = 0, preparing = false;
async function compareBundled() {
  const id = $('skillId').value.trim(), version = $('fromVersion').value, ticket = ++bundleSequence;
  bundled = null; $('prepareBundled').disabled = true; $('bundledNext').replaceChildren();
  if (!id || !version) { $('bundledStatus').textContent = '请先读取 Skill 版本。'; return; }
  $('bundledStatus').textContent = '正在对照内置说明…';
  try {
    const data = await get('/api/skills/bundled-diff?' + new URLSearchParams({id,version}));
    if (ticket !== bundleSequence || id !== $('skillId').value.trim() || version !== $('fromVersion').value) return;
    bundled = data; $('bundledResult').hidden = false;
    $('bundledStatus').textContent = data.instructions_differ ? '说明存在差异；实际检索后端以本次查询诊断为准。' : '说明内容一致；其他内置文件仍需按草稿审核。';
    $('bundledDiff').textContent = data.unified_diff || '说明没有文本差异。';
    $('bundledFiles').replaceChildren(...data.bundled_files.map(path => el('code', path)));
    await OksWorkspace.ready; const context = OksWorkspace.context();
    $('prepareBundled').disabled = context?.local_edit !== true;
    $('bundledGate').textContent = context?.local_edit ? '草稿准备后，仍需单独审核。' : '准备草稿需启用本地编辑：' + (context?.commands.edit || 'oks mail serve --path <知识库> --local-edit');
  } catch (error) { if (ticket === bundleSequence) $('bundledStatus').textContent = error.message; }
}
$('compareBundled').addEventListener('click', compareBundled);
$('fromVersion').addEventListener('change', () => { ++bundleSequence; bundled = null; $('bundledResult').hidden = true; });
$('skillId').addEventListener('input', () => { ++bundleSequence; bundled = null; $('bundledResult').hidden = true; });
$('prepareBundled').addEventListener('click', async () => {
  if (!bundled || preparing || OksWorkspace.context()?.local_edit !== true) return;
  const inspected = bundled; preparing = true; $('prepareBundled').disabled = true;
  try {
    const result = await OksWorkspace.request('/api/skills/import-bundled', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_knowledge_base:OksWorkspace.context()?.knowledge_base,id:inspected.skill_id,version:inspected.version,expected_bundled_version:inspected.bundled_version})});
    if (bundled !== inspected) return;
    const link = el('a', result.path.startsWith('drafts/') ? '打开待审核草稿' : '查看已有 Wiki 版本');
    link.href = result.path.startsWith('drafts/') ? '/review?draft=' + encodeURIComponent(result.path) : '/#wiki-reader&path=' + encodeURIComponent(result.path);
    $('bundledNext').replaceChildren(el('p', result.duplicate ? '此版本已存在，保留原状态。' : '草稿已准备。旧 Wiki 与任务绑定保留原状。'), link);
  } catch (error) { $('bundledStatus').textContent = error.message; }
  finally { preparing = false; $('prepareBundled').disabled = !bundled || OksWorkspace.context()?.local_edit !== true; }
});
document.addEventListener('oks:reconnected', () => { ++bundleSequence; bundled = null; $('bundledResult').hidden = true; loadVersions(); });
const initial = new URLSearchParams(location.search);
if (initial.get('id')) {
  $('skillId').value = initial.get('id');
  loadVersions().then(() => {
    if (versions.some(item => item.version === initial.get('version'))) $('fromVersion').value = initial.get('version');
    if (initial.get('bundled') === '1') compareBundled();
  });
}
