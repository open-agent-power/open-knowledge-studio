'use strict';
const $ = id => document.getElementById(id);
const el = (tag, value, cls) => { const n = document.createElement(tag); n.textContent = value == null ? '' : String(value); if (cls) n.className = cls; return n; };
function status(text, state = '') { $('status').textContent = text; $('status').dataset.state = state; }
async function get(url) { return OksWorkspace.request(url); }
let versions = [], versionSequence=0;
const labels = {
  pending_review: '待审核', reviewed: '已审核', superseded: '已被新版本替代', archived: '已归档', unreviewed: '未审核', inactive: '不可用',
  ok: '文件检查通过', failed: '文件检查未通过', added: '新增', modified: '修改', deleted: '删除',
  current: '当前版本可用', needs_review: '建议复核', unknown: '状态未知',
  bound_to_old_version: '仍在使用版本一', not_loaded: '未加载', unchanged_managed: '本地副本与记录一致',
  modified_managed: '本地副本已修改', modified_or_unreadable: '本地副本已修改或无法读取',
  unmanaged_existing: '本地副本不是由 OKS 管理', unavailable: '状态不可读取',
  caller_reported: '由记录方填写',
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
    'Skill instructions differ from immutable package; re-import source as a new package': '知识卡指令与文件包不一致，请从源文件生成新版本并审核。',
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
    card.append(el('h2', `版本 ${version.version.slice(0, 12)}…`), el('p', `审核：${label(version.review_state)} · 文件检查：${label(version.integrity)}`));
    const fullVersion = el('details', '', 'full-version');
    fullVersion.append(el('summary', '查看完整版本标识'), el('code', version.version));
    card.append(fullVersion);
    for (const item of version.cards || []) {
      const cardInfo = el('p', `${item.slug} · ${label(item.review_state)} · ${label(item.integrity)}${item.integrity_issue ? ' · ' + integrityIssue(item.integrity_issue) : ''}`, item.integrity === 'failed' ? 'warning' : '');
      if (item.integrity === 'failed') card.append(cardInfo);
      else fullVersion.append(cardInfo);
      if (item.review_state === 'pending_review' && item.file_path) {
        const link = el('a', '查看待审核建议');
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
    const requested=new URLSearchParams(location.search).get('version');
    const approved=versions.findIndex(item=>item.review_state==='reviewed'&&item.integrity==='ok');
    $('fromVersion').selectedIndex = requested&&versions.some(item=>item.version===requested)?versions.findIndex(item=>item.version===requested):Math.max(0,approved);
    status(`找到 ${versions.length} 个版本。`);
  } else { $('compareControls').hidden = true; status('没有找到这个技能的版本。', 'warning'); }
}
function renderDiff(data) {
  $('results').hidden = false;
  for (const [target, item] of [['fromSummary', data.from], ['toSummary', data.to]]) {
    $(target).replaceChildren(el('span', `${item.version.slice(0, 12)}… · ${label(item.review_state)}`));
    const details = el('details', '', 'full-version');
    details.append(el('summary', '查看完整版本标识'), el('code', item.version));
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
    const taskLink = el('a', `${task.task_id} · ${label(task.comparison_status)}`);
    taskLink.href = '/tasks?id=' + encodeURIComponent(task.task_id);
    taskLink.className = 'task-link';
    article.append(taskLink);
    article.append(el('p', `任务：${label(task.task_status)} · ${label(task.binding)}`));
    const refs = el('details', '', 'full-version'); refs.append(el('summary', '查看来源与修订详情'));
    for (const path of task.source_paths || []) refs.append(el('code', path));
    for (const use of task.uses || []) refs.append(el('p', `使用情况记录：${use.source_path} · 版本 ${use.skill_version ? use.skill_version.slice(0, 12) + '…' : '未记录'}。由记录方填写，未验证是否执行。`));
    if ((task.source_paths || []).length || (task.uses || []).length) article.append(refs);
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
  if (!id) return status('请输入技能名称。', 'warning');
  const ticket=++versionSequence;resetPersonal();
  $('results').hidden = true;
  try { status('正在查找版本…');const data=await get('/api/skills/versions?id=' + encodeURIComponent(id));if(ticket!==versionSequence||$('skillId').value!==id)return;renderVersions(data);await loadPersonalSource(); }
  catch (error) { status(error.message, 'error'); }
}
async function compare() {
  const id = $('skillId').value.trim(), from = $('fromVersion').value, to = $('toVersion').value;
  if (!id || !from || !to) return status('先查找技能，再选择两个版本。', 'warning');
  try { status('正在比较版本…'); renderDiff(await get('/api/skills/diff?' + new URLSearchParams({id, from, to}))); status('版本变化已列出。'); }
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
  if (!id || !version) { $('bundledStatus').textContent = '请先查找技能版本。'; return; }
  $('bundledStatus').textContent = '正在比较技能说明…';
  try {
    const data = await get('/api/skills/bundled-diff?' + new URLSearchParams({id,version}));
    if (ticket !== bundleSequence || id !== $('skillId').value.trim() || version !== $('fromVersion').value) return;
    bundled = data; $('bundledResult').hidden = false;
    $('bundledStatus').textContent = data.instructions_differ ? '说明内容有变化；本次查询使用的检索方式以查询诊断为准。' : '说明内容一致；其他文件仍需单独审核。';
    $('bundledDiff').textContent = data.unified_diff || '说明没有文本差异。';
    $('bundledFiles').replaceChildren(...data.bundled_files.map(path => el('code', path)));
    await OksWorkspace.ready; const context = OksWorkspace.context();
    $('prepareBundled').disabled = context?.local_edit !== true;
    $('bundledGate').textContent = context?.local_edit ? '准备后仍需审核，现有内容不会被替换。' : '需要启用本地编辑后才能准备审核建议。';
    $('bundledEditDetails').hidden = context?.local_edit === true;
    $('bundledEditCommand').textContent = context?.commands.edit || 'oks mail serve --path <知识库> --local-edit';
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
    const link = el('a', result.path.startsWith('drafts/') ? '查看待审核建议' : '查看已有知识');
    link.href = result.path.startsWith('drafts/') ? '/review?draft=' + encodeURIComponent(result.path) : '/#wiki-reader&path=' + encodeURIComponent(result.path);
    $('bundledNext').replaceChildren(el('p', result.duplicate ? '这份版本记录已存在，原状态保留。' : '审核建议已准备。现有知识与任务来源保持不变。'), link);
  } catch (error) { $('bundledStatus').textContent = error.message; }
  finally { preparing = false; $('prepareBundled').disabled = !bundled || OksWorkspace.context()?.local_edit !== true; }
});
document.addEventListener('oks:reconnected', () => { ++bundleSequence; bundled = null; $('bundledResult').hidden = true; loadVersions(); });
let personalSource=null,personalSequence=0,personalSaving=false,mergePlan=null,mergeSaving=false;
const mergeChoices=new Map();
function personalError(error){const text=String(error.message||error);if(/not reviewed|not approved|reviewed version|human.reviewed/i.test(text))return '请选择已审核且文件完整的版本。';if(/digest|stale|plan changed|changed since/i.test(text))return '版本或预览已变化，请重新查看上游变化。';if(/conflict|resolution/i.test(text))return '请逐项明确解决冲突，再准备更新。';if(/lineage|not derived/i.test(text))return '这份技能没有可核对的上游记录。';if(/no.change|unchanged result/i.test(text))return '结果与当前版本相同，已保留当前版本。';return text;}
function resetPersonal(){++personalSequence;personalSource=null;mergePlan=null;mergeChoices.clear();$('personalPanel').hidden=true;$('mergePanel').hidden=true;$('preparePersonal').disabled=true;$('personalNext').replaceChildren();$('mergeNext').replaceChildren();$('mergeFiles').replaceChildren();$('prepareMerge').hidden=true;}
async function postSkill(route,payload,expectedRoot){
  const context=OksWorkspace.context();if(context?.local_edit!==true)throw Error('当前只读，请启用此知识库的本地编辑。');
  if(expectedRoot&&expectedRoot!==context.knowledge_base)throw Error('知识库已变化，请重新查看后再准备。');
  const text=JSON.stringify({...payload,expected_knowledge_base:context.knowledge_base});
  if(new TextEncoder().encode(text).length>60000)throw Error('调整内容过长，请缩短后再准备。');
  return OksWorkspace.request(route,{method:'POST',headers:{'Content-Type':'application/json'},body:text});
}
function showPrepared(host,result){host.replaceChildren(el('p','已准备待审版本，审核后才可查询和加载。'));if(result.draft_path){const link=el('a','阅读并审核这个版本');link.href=OksNavigation.fromTask('/review?draft='+encodeURIComponent(result.draft_path));host.append(link);}}
async function loadPersonalSource(){
  const id=$('skillId').value,version=$('fromVersion').value,ticket=++personalSequence;
  personalSource=null;mergePlan=null;$('personalPanel').hidden=!version;$('mergePanel').hidden=true;$('preparePersonal').disabled=true;$('personalStatus').textContent='读取基础说明…';
  if(!id||!version)return;
  const inspected=versions.find(item=>item.version===version);
  if(inspected?.integrity==='failed'){$('personalStatus').textContent='所选版本完整性检查未通过，请查看版本记录中的原因。';return;}
  try{
    const source=await get('/api/skills/source?'+new URLSearchParams({id,version}));
    if(ticket!==personalSequence||id!==$('skillId').value||version!==$('fromVersion').value)return;
    personalSource=source;$('personalBase').textContent=source.instructions;$('personalStatus').textContent=OksWorkspace.context()?.local_edit?'基于所选已审核版本':'当前只读';$('preparePersonal').disabled=OksWorkspace.context()?.local_edit!==true;
    const url=new URL(location.href);url.searchParams.set('id',id);url.searchParams.set('version',version);history.replaceState(null,'',url);
    if(source.lineage?.upstream_base){
      const upstream=source.lineage.upstream_base,data=await get('/api/skills/versions?id='+encodeURIComponent(upstream.id));
      if(ticket!==personalSequence)return;
      $('upstreamVersion').replaceChildren();
      for(const item of data.versions||[])if(item.review_state==='reviewed'&&item.integrity==='ok'){const option=el('option','已审核 · '+item.version.slice(0,12));option.value=item.version;$('upstreamVersion').append(option);}
      $('mergePanel').hidden=false;$('previewMerge').disabled=!$('upstreamVersion').options.length;$('mergeStatus').textContent=$('upstreamVersion').options.length?'':'尚未找到可用的已审核上游版本。';
    }
  }catch(error){if(ticket===personalSequence){$('personalStatus').textContent=personalError(error);$('personalBase').textContent='';}}
}
$('fromVersion').addEventListener('change',()=>{resetPersonal();loadPersonalSource();});
$('skillId').addEventListener('change',()=>{resetPersonal();loadVersions();});
$('personalForm').addEventListener('submit',async event=>{
  event.preventDefault();const source=personalSource,notes=$('personalNotes').value.trim();if(!source||!notes||personalSaving)return;
  personalSaving=true;$('preparePersonal').disabled=true;$('personalStatus').textContent='准备个人版本…';
  try{const result=await postSkill('/api/skills/derive',{base:{id:source.ref.id,version:source.ref.version},changes:{'SKILL.md':source.instructions+'\n\n## 我的补充要求\n\n'+notes+'\n'}},source.knowledge_base);if(source!==personalSource)return;showPrepared($('personalNext'),result);$('personalStatus').textContent='待人工审核';}
  catch(error){if(source===personalSource)$('personalStatus').textContent=personalError(error);}
  finally{personalSaving=false;$('preparePersonal').disabled=!personalSource||OksWorkspace.context()?.local_edit!==true;}
});
function updateMergeAction(){const ready=!!mergePlan&&(mergePlan.conflicts||[]).every(path=>{const entry=mergeChoices.get(path);return !!entry&&entry.select.value&&(entry.select.value!=='text'||entry.text.value.trim());});$('prepareMerge').disabled=!ready||mergeSaving||OksWorkspace.context()?.local_edit!==true;}
function renderMerge(plan){
  mergeChoices.clear();$('mergeFiles').replaceChildren();const conflicts=new Set(plan.conflicts||[]);
  const names={unchanged:'未变',ours:'保留我的修改',theirs:'采用上游',merged:'已合并',conflict:'需要选择',added:'新增',deleted:'删除'};
  for(const item of plan.files||[]){
    const row=el('details','','merge-file');row.open=conflicts.has(item.path);const summary=el('summary',item.path+' · '+(conflicts.has(item.path)?'需要选择':names[item.status]||'变化已整理'));if(conflicts.has(item.path))summary.className='merge-conflict';row.append(summary);
    const columns=el('div','','merge-comparison');for(const [label,key] of [['共同基础','base'],['我的版本','ours'],['上游版本','theirs']]){const cell=el('div');cell.append(el('strong',label),el('pre',item[key]?.text??(item[key]?.binary?'二进制文件':'文件不存在')));columns.append(cell);}row.append(columns);
    if(conflicts.has(item.path)){
      const select=el('select'),text=el('textarea','','merge-edit');select.setAttribute('aria-label',item.path+'的处理方式');text.setAttribute('aria-label',item.path+'的合并内容');text.rows=8;text.hidden=true;text.value=item.ours?.text||'';
      for(const [value,label] of [['','选择如何处理'],['ours','保留我的修改'],['theirs','采用上游版本'],['text','手动编辑合并结果'],['delete','删除这个文件']]){const option=el('option',label);option.value=value;if(value==='text'&&(item.ours?.binary||item.theirs?.binary)||value==='delete'&&item.path==='SKILL.md')option.disabled=true;select.append(option);}
      select.addEventListener('change',()=>{text.hidden=select.value!=='text';updateMergeAction();});text.addEventListener('input',updateMergeAction);mergeChoices.set(item.path,{select,text});row.append(select,text);
    }else if(item.merged?.text)row.append(el('pre',item.merged.text,'merge-preview'));
    $('mergeFiles').append(row);
  }
  $('mergeStatus').textContent=conflicts.size?`${conflicts.size} 个文件需要你选择。`:'变化可合并，个人修改会保留。';$('prepareMerge').hidden=false;updateMergeAction();
}
$('upstreamVersion').addEventListener('change',()=>{mergePlan=null;$('mergeFiles').replaceChildren();$('prepareMerge').hidden=true;$('mergeNext').replaceChildren();$('mergeStatus').textContent='请重新查看上游变化。';});
$('previewMerge').addEventListener('click',async()=>{
  const source=personalSource,version=$('upstreamVersion').value;if(!source?.lineage||!version)return;
  mergePlan=null;$('prepareMerge').hidden=true;$('previewMerge').disabled=true;$('mergeStatus').textContent='比较共同基础、个人修改和上游变化…';
  try{const plan=await get('/api/skills/merge-preview?'+new URLSearchParams({id:source.ref.id,version:source.ref.version,upstream_id:source.lineage.upstream_base.id,upstream_version:version}));if(source!==personalSource||version!==$('upstreamVersion').value)return;mergePlan=plan;renderMerge(plan);}
  catch(error){if(source===personalSource)$('mergeStatus').textContent=personalError(error);}
  finally{$('previewMerge').disabled=false;}
});
$('prepareMerge').addEventListener('click',async()=>{
  const plan=mergePlan;if(!plan||mergeSaving)return;const resolutions={};for(const [path,entry] of mergeChoices){resolutions[path]={choice:entry.select.value};if(entry.select.value==='text')resolutions[path].text=entry.text.value;}
  mergeSaving=true;updateMergeAction();$('mergeStatus').textContent='准备待审更新…';
  try{const result=await postSkill('/api/skills/merge-prepare',{ours:{id:plan.ours.id,version:plan.ours.version},theirs:{id:plan.theirs.id,version:plan.theirs.version},expected_plan_digest:plan.plan_digest,resolutions},plan.knowledge_base);if(plan!==mergePlan)return;showPrepared($('mergeNext'),result);$('mergeStatus').textContent='更新已准备，待人工审核。';}
  catch(error){if(plan===mergePlan)$('mergeStatus').textContent=personalError(error);}
  finally{mergeSaving=false;updateMergeAction();}
});
async function loadCatalog(){
  const initial=new URLSearchParams(location.search),requested=initial.get('id');
  try{const data=await get('/api/skills/catalog');$('skillId').replaceChildren();for(const item of data.items||[]){const option=el('option',item.title||item.id);option.value=item.id;$('skillId').append(option);}if(requested&&!Array.from($('skillId').options).some(option=>option.value===requested)){const option=el('option',requested);option.value=requested;$('skillId').append(option);}if(requested)$('skillId').value=requested;if($('skillId').value){await loadVersions();if(initial.get('bundled')==='1')compareBundled();}else status('当前知识库尚无技能。先导入并审核一份方法。');}
  catch(error){status('技能列表暂时无法读取，请刷新重试。','error');}
}
OksWorkspace.ready.then(loadCatalog);
