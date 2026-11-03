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
let overviewData = null, taskFilter = 'open', currentTask = null, lifecycleSaving = false;
let reviewTicket = 0, reviewData = null, sourceSaving = false, progressSaving = false, copyingHandoff = false;
const lifecycleNames = {active:'进行中',completed:'已完成',cancelled:'已取消'};
function needsAttention(task) { return task.status !== 'current' || task.artifact_issue_count > 0 || task.reminders?.review_count > 0 || task.reminders?.status === 'unavailable'; }
function renderOverview() {
  if (!overviewData) return;
  const counts = overviewData.counts;
  $('overviewSummary').textContent = `${counts.active} 项进行中 · ${counts.needs_review} 项待确认 · ${counts.due} 项到期提醒`;
  $('overviewNotice').textContent = [overviewData.truncated ? '仅显示前 100 项，数量按当前列表统计。' : '', counts.unavailable ? `${counts.unavailable} 项记录无法读取，请核对原文件。` : ''].filter(Boolean).join(' ');
  const query = $('taskSearch').value.trim().toLocaleLowerCase();
  const matches = overviewData.tasks.filter(task => {
    const open = task.lifecycle === 'active';
    return (taskFilter === 'all' || taskFilter === 'open' && open || taskFilter === 'closed' && ['completed','cancelled'].includes(task.lifecycle) || taskFilter === 'review' && (open && needsAttention(task) || task.status === 'unavailable'))
      && [task.title,task.task_id,task.next_action].some(text=>String(text || '').toLocaleLowerCase().includes(query));
  });
  $('taskRows').replaceChildren();
  for (const task of matches) {
    const row = node('article', '', 'task-row'), content = node('div', '', 'task-row-main');
    if (task.status === 'unavailable') content.append(node('h2',task.title),node('p','记录无法读取，原文件保留。','file-warning'));
    else {
      const link = node('a', task.title); link.href = '/tasks?id=' + encodeURIComponent(task.task_id);
      const heading = node('h2',''); heading.append(link); content.append(heading);
      content.append(node('p',task.lifecycle === 'active' ? task.next_action || '尚未记录下一步' : '历史与产物已保留','task-row-next'));
      const reminder = task.reminders || {};
      for (const due of reminder.due || []) content.append(node('p',`到期 · ${due.note}`,'task-row-due'));
      const notes = [task.status !== 'current' ? '目标或来源有变化' : '',task.artifact_issue_count ? '产物有变化' : '',reminder.review_count ? '提醒待确认' : '',reminder.status === 'unavailable' ? '提醒无法读取' : ''].filter(Boolean);
      if (notes.length) content.append(node('p',notes.join(' · '),'file-warning'));
    }
    row.append(content,node('span',lifecycleNames[task.lifecycle] || '待核对','task-row-state'));
    $('taskRows').append(row);
  }
  if (!matches.length) $('taskRows').append(node('p',query ? '没有匹配的任务。' : overviewData.tasks.length ? '这里暂无任务。' : '还没有任务。点击“创建任务”开始。','empty'));
}
function status(text, state = '') {
  $('status').textContent = text;
  $('status').dataset.state = state;
}
let workflowTicket = 0, workflowRoot = null, workflowLoading = false;
function workflowBusy() { return progressSaving || sourceSaving || lifecycleSaving || copyingHandoff || correctionSaving || reminderSaving; }
const workflowStatusNames = {running:'进行中',working:'工作中',active:'进行中',returned:'已返回',completed:'已结束',stopped:'已结束',partial:'部分完成',source_changed:'来源有变化',failed:'未完成',error:'未完成',unknown:'状态未知'};
const workflowPhaseNames = {working:'工作中',returned:'已返回',partial:'部分完成'};
const learningStatusNames = {pending_review:'待人工审核',rejected:'已拒绝',not_proposed:'尚无学习候选',private_scope:'仅保留在私人范围',source_changed:'来源已变化，待核对',error:'候选生成未完成'};
function renderWorkflow(data, task) {
  if (currentTask !== task || OksWorkspace.context()?.knowledge_base !== workflowRoot) return;
  const runs = $('workflowRuns'), drafts = $('workflowDrafts'); runs.replaceChildren(); drafts.replaceChildren();
  if (!data.enabled) { $('workflowStatus').textContent = '自动归档未启用'; runs.append(node('p','接入检查页可查看启用命令。','empty')); }
  else if (!data.runs?.length) $('workflowStatus').textContent = '等待本次工作记录';
  if (data.runs?.length) {
    $('workflowStatus').textContent = '按宿主事件更新';
    for (const run of data.runs) {
      const card = node('article','','workflow-run'), head = node('div','','workflow-run-head');
      const label = ({return_observed:'已收到返回',output_observed:'已记录产物',handoff_observed:'已记录交接',partial:'有未完成的记录'})[run.evidence_state] || (run.status === 'returned' ? '已收到返回' : '已记录宿主事件');
      head.append(node('strong', (run.host || '工作会话') + (run.role === 'main' ? ' · 主会话' : run.role === 'collaborator' ? ' · 协作成员' : '')), node('span', label, 'workflow-state'));
      card.append(head);
      const candidate = data.drafts?.find(item => item.path === run.draft_path);
      const learned = candidate?.status === 'promoted';
      if (!data.learning_groups?.length && learningStatusNames[run.learning_status]) card.append(node('p', '学习：' + learningStatusNames[run.learning_status]));
      if (run.warning) card.append(node('p',run.warning,'file-warning'));
      const artifacts = Array.isArray(run.artifacts) ? run.artifacts : [];
      if (artifacts.length) {
        const list = node('ul','','workflow-artifacts');
        for (const item of artifacts) { const row = node('li',''), link = node('button', item.path.split('/').pop() || item.path); link.type = 'button'; link.title = item.path; link.addEventListener('click', () => { loadArtifact(task,{...item,revision:task.revision}); $('artifactReader').scrollIntoView({behavior:'smooth',block:'start'}); }); row.append(link); list.append(row); }
        card.append(list);
      } else card.append(node('p','尚未归档产物。','empty'));
      if (run.thread_id) { const link = node('a','查看通信记录'); link.href = '/#collaboration&thread=' + encodeURIComponent(run.thread_id); link.className = 'workflow-thread'; card.append(link); }
      if (run.draft_path && !data.learning_groups?.length) { const link = node('a',learned ? '阅读已入库的经验' : '查看学习候选并审核'); link.href = learned ? wikiHref(candidate.wiki_path) : '/review?draft=' + encodeURIComponent(run.draft_path); link.className = 'workflow-draft-link'; card.append(link); }
      runs.append(card);
    }
  }
  if (data.connections?.length) {
    const history=node('details','','workflow-connections');history.append(node('summary',`仅接入记录 · ${data.connections.length} 条`),node('p','这些记录没有产物、交接或返回证据，不表示仍在运行。'));
    for(const row of data.connections)history.append(node('p',`${row.host || '宿主'} · ${new Date(row.updated_at).toLocaleString('zh-CN')} · 原记录保留`));
    runs.append(history);
  }
  if(data.unreadable_records)runs.append(node('p',`${data.unreadable_records} 条记录暂时无法读取，原文件保留。`,'file-warning'));
  if (data.learning_groups?.length) {
    drafts.append(node('h3','学习建议'));
    for(const group of data.learning_groups){
      const card=node('section','','workflow-learning'),variants=group.variants || [];
      const pending=variants.filter(item=>item.status==='draft').length,approved=variants.filter(item=>item.status==='promoted').length,rejected=variants.filter(item=>item.status==='rejected').length;
      card.append(node('p',`${variants.length} 条建议 · ${approved} 条已入库 · ${pending} 条待审`+(rejected?` · ${rejected} 条已拒绝`:'')));
      if(variants.length>1)card.append(node('p','来自同一份产物，每条建议分别审核。','scope-help'));
      for(const item of variants){
        const row=node('div','','workflow-variant'),name=item.role==='main'?'主会话建议':'协作成员建议';
        const label=({draft:'待人工审核',promoted:'已加入知识库',rejected:'已拒绝',missing:'原文不可用',ambiguous:'审核来源待核对'})[item.status] || '待核对';
        row.append(node('span',name),node('span',label));
        if(item.status==='draft' || item.status==='promoted'){
          const link=node('a',item.status==='draft'?'阅读并审核':'查看审核记录');link.href='/review?'+new URLSearchParams({draft:item.path,...(item.status==='promoted' && item.reviewed_sha256?{revision:item.reviewed_sha256}:{})});row.append(link);
        }
        if(item.status==='promoted' && item.wiki_path){const link=node('a','阅读知识');link.href=wikiHref(item.wiki_path);row.append(link);}
        card.append(row);
      }
      drafts.append(card);
    }
  } else if (data.drafts?.length) {
    drafts.append(node('h3','学习候选'));
    for (const draft of data.drafts) { const row = node('p','','workflow-draft'); const link = node('a',draft.title || draft.path); link.href = draft.status === 'promoted' ? wikiHref(draft.wiki_path) : '/review?draft=' + encodeURIComponent(draft.path); const state = ({draft:'待人工审核',promoted:'已加入知识库',rejected:'已拒绝',missing:'草稿不可用'})[draft.status] || '状态待核对'; row.append(link,node('span',state)); drafts.append(row); }
  }
}
async function loadWorkflow(task, quiet = false) {
  if (workflowLoading || workflowBusy()) return;
  const ticket = ++workflowTicket, root = OksWorkspace.context()?.knowledge_base; workflowRoot = root;
  if (!task || !root) return;
  workflowLoading = true;
  if (!quiet) $('workflowStatus').textContent = '正在读取…';
  try {
    const [workflowResult, taskResult] = await Promise.allSettled([
      get('/api/tasks/workflow?id=' + encodeURIComponent(task.task_id)),
      get('/api/tasks/show?id=' + encodeURIComponent(task.task_id))
    ]);
    if (ticket !== workflowTicket || currentTask !== task || workflowBusy() || OksWorkspace.context()?.knowledge_base !== root) return;
    const latestTask = taskResult.status === 'fulfilled' ? taskResult.value : task;
    if (latestTask.knowledge_base === root && latestTask.task_id === task.task_id) {
      currentTask = latestTask.revision === task.revision && latestTask.status === task.status && latestTask.lifecycle === task.lifecycle ? task : latestTask;
      $('progress').textContent = latestTask.progress || '暂无进度记录';
      $('next').textContent = (latestTask.lifecycle || 'active') === 'active' ? latestTask.next_action || '尚未记录下一步' : latestTask.lifecycle_reason || '任务已结束。';
      if ($('progressText').value === (task.progress || '')) $('progressText').value = latestTask.progress || '';
      if ($('nextText').value === (task.next_action || '')) $('nextText').value = latestTask.next_action || '';
      if (latestTask.artifacts?.length !== task.artifacts?.length || latestTask.artifacts?.some((item,index)=>item.path!==task.artifacts?.[index]?.path || item.sha256!==task.artifacts?.[index]?.sha256)) renderArtifacts(latestTask, true);
      updateTaskEditors();
    }
    if (workflowResult.status === 'rejected') throw workflowResult.reason;
    renderWorkflow(workflowResult.value, currentTask);
  } catch (error) {
    if (ticket === workflowTicket && currentTask?.task_id === task.task_id && OksWorkspace.context()?.knowledge_base === root) $('workflowStatus').textContent = '暂时无法连接，正在重试';
  } finally { workflowLoading = false; }
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
    for (const ref of markdown.querySelectorAll('.md-ref[title]')) {
      const original = ref.getAttribute('title');
      if (!original || /^[a-z][a-z0-9+.-]*:|^\/\//i.test(original)) continue;
      const source = data.source_links?.[original];
      if (!source) continue;
      if (!/^(raw|wiki|reports|outputs|artifacts)\//.test(source)) continue;
      const link = node('button',ref.textContent,'source-link'); link.type='button';
      link.addEventListener('click',async()=>{
        const sourceTicket=++artifactTicket;
        try {
          const query=new URLSearchParams({id:task.task_id,path:item.path,revision:String(item.revision),source});
          const document=await get('/api/tasks/source?'+query);
          if(sourceTicket!==artifactTicket)return;
          const back=node('button','← 返回产物');back.type='button';back.addEventListener('click',()=>loadArtifact(task,item));
          const reading=node('article','','markdown-body');reading.innerHTML=document.body_html;
          $('artifactStatus').textContent=document.notice;
          $('artifactView').replaceChildren(back,node('p',document.path,'artifact-meta'),reading);
        } catch(error){if(sourceTicket===artifactTicket)$('artifactStatus').textContent=error.message;}
      });ref.replaceWith(link);
    }
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
function renderArtifacts(task, preserveReader = false) {
  if (!preserveReader) artifactTicket++;
  const versions = [
    ...task.history.map(entry => ({revision: entry.revision, artifacts: entry.artifacts || []})),
    {revision: task.revision, artifacts: task.artifacts || []}
  ];
  const items = versions.flatMap(version => version.artifacts.map(artifact => ({...artifact, revision: version.revision})));
  $('artifactList').replaceChildren();
  if (!preserveReader) { $('artifactStatus').textContent = ''; $('artifactStatus').dataset.state = ''; }
  if (!items.length) {
    $('artifactList').append(node('p', '暂无已记录产物。', 'empty'));
    if (!preserveReader) $('artifactView').replaceChildren(node('p', '可在“记录进度”中关联已有产物。', 'empty'));
    return;
  }
  for (const item of [...items].reverse()) {
    const button = node('button', '', 'artifact-choice');
    button.type = 'button';
    button.append(node('span', item.path.split('/').pop(), 'artifact-choice-name'), node('span', `修订 ${item.revision}`, 'artifact-choice-meta'));
    button.addEventListener('click', () => loadArtifact(task, item));
    $('artifactList').append(button);
  }
  if (!preserveReader) { const requested=new URLSearchParams(location.search).get('artifact'); loadArtifact(task,[...items].reverse().find(item=>item.path===requested) || [...items].reverse()[0]); }
}
let sourcesTicket = 0;
async function renderSources(task) {
  const ticket = ++sourcesTicket;
  $('sources').replaceChildren(node('p','读取来源版本…','empty'));
  try {
    const data = await get('/api/tasks/sources?' + new URLSearchParams({id:task.task_id,revision:task.revision}));
    if (ticket !== sourcesTicket || currentTask !== task) return;
    if (data.knowledge_base !== task.knowledge_base) throw new Error('实例已变化，请刷新任务。');
    $('sources').replaceChildren();
    if (!data.sources.length) $('sources').append(node('p','尚未选择任务依据。','empty'));
    const names = {agreement:'当前依据',use:'本轮使用记录',replaced:'已更换',history:'历史记录'};
    for (const source of data.sources) {
      const link = node('a',source.title,'source-link'); link.href = wikiHref(source.path); link.title = source.path;
      const item = node('div','','source-item'), version = node('details','','source-version');
      const historical = ['replaced','history'].includes(source.relation);
      version.append(node('summary','查看来源记录'),node('code',source.path),node('code','SHA-256 ' + source.sha256),node('small','关联修订：' + source.revisions.join('、')));
      if (source.use_revisions.length) version.append(node('small','使用声明所在修订：' + source.use_revisions.join('、') + '；内容未验收。'));
      item.append(node('small',names[source.relation],'source-relation'),link);
      if (source.relation === 'use') item.append(node('small','由填写者记录，内容尚未验收。'));
      if (historical) item.append(node('small','打开的是当前文件，旧版正文未保存。'));
      item.append(version); $('sources').append(item);
    }
  } catch (error) {
    if (ticket === sourcesTicket && currentTask === task) $('sources').replaceChildren(node('p',taskFlowError(error),'file-warning'));
  }
}
let correctionSaving = false, correctionId = null, correctionSources = [];
function renderCorrection(task) {
  correctionId = null; $('correctionForm').reset(); $('correctionStatus').textContent = ''; $('correctionReview').hidden = true;
  $('correctionFields').disabled = correctionSaving;
  const hint = OksWorkspace.scopeHint();
  $('correctionSubject').value = hint?.subject || ''; $('correctionProject').value = hint?.project || '';
  const versions = new Map();
  for (const ref of task.agreement.knowledge) versions.set(ref.path + ':' + ref.sha256,{path:ref.path,sha256:ref.sha256,title:ref.title});
  for (const use of task.uses || []) {
    const key = use.source_path + ':' + use.source_sha256;
    if (!versions.has(key)) versions.set(key,{path:use.source_path,sha256:use.source_sha256,title:use.source_path.split('/').pop()});
  }
  correctionSources = [...versions.values()]; $('correctionSource').replaceChildren();
  correctionSources.forEach((ref,index) => { const option = node('option',ref.title); option.value = index; $('correctionSource').append(option); });
  $('correctionArtifact').replaceChildren(node('option','不关联产物')); $('correctionArtifact').firstChild.value = '';
  task.artifacts.forEach((ref,index) => { const option = node('option',ref.path); option.value = index; $('correctionArtifact').append(option); });
}
$('correctionForm').addEventListener('input',() => { correctionId = null; $('correctionReview').hidden = true; $('correctionStatus').textContent = ''; });
$('correctionForm').addEventListener('submit',async event => {
  event.preventDefault(); const task = currentTask, context = OksWorkspace.context();
  if (!task || correctionSaving || !context?.local_edit || context.knowledge_base !== task.knowledge_base || task.status !== 'current' || task.lifecycle !== 'active') return;
  const ref = correctionSources[Number($('correctionSource').value)]; if (!ref) return;
  const scope = {subject:$('correctionSubject').value.trim(),project:$('correctionProject').value.trim(),task:task.task_id};
  correctionId ||= crypto.randomUUID(); const identifier = correctionId;
  const request = {expected_knowledge_base:task.knowledge_base,task_id:task.task_id,expected_revision:task.revision,
    expected_agreement_sha256:task.agreement.sha256,request_id:identifier,scope,source:{path:ref.path,sha256:ref.sha256},
    artifact:$('correctionArtifact').value === '' ? null : task.artifacts[Number($('correctionArtifact').value)],
    reason:$('correctionReason').value.trim(),summary:$('correctionSummary').value.trim()};
  correctionSaving = true; $('correctionFields').disabled = true; updateTaskEditors(); $('correctionStatus').textContent = '保存中…';
  try {
    const result = await OksWorkspace.request('/api/tasks/correction',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});
    if (currentTask !== task || OksWorkspace.context()?.knowledge_base !== task.knowledge_base) return;
    $('correctionStatus').textContent = result.status === 'partial' ? result.message : result.candidate_status === 'pending' ? '已保存，等待审核。' : '该建议已记录，请到审核页查看当前状态。';
    if (result.status !== 'partial') { OksWorkspace.rememberScope(scope); $('correctionReview').href = result.review_path; $('correctionReview').hidden = false; }
  } catch (error) { if (currentTask === task) $('correctionStatus').textContent = taskFlowError(error); }
  finally { correctionSaving = false; $('correctionFields').disabled = false; updateTaskEditors(); }
});
async function get(url) {
  return OksWorkspace.request(url);
}
function render(task) {
  currentTask = task;
  ++reviewTicket; reviewData = null;
  $('goalComparison').replaceChildren(); $('sourceComparisons').replaceChildren(); $('reviewWikiChoices').replaceChildren();
  $('sourceReviewStatus').textContent = ''; $('confirmSources').checked = false; $('acceptSources').disabled = true;
  $('handoffText').hidden = true; $('handoffText').value = '';
  $('progressText').value = task.progress || ''; $('nextText').value = task.next_action || '';
  $('progressArtifacts').value = task.artifacts.map(item=>item.path).join('\n');
  $('progressStatus').textContent = ''; $('progressSave').disabled = true;
  OksWorkspace.ready.then(() => { if (currentTask === task) updateTaskEditors(); });
  $('workbench').hidden = true;
  loadReminders(task);
  const current = task.status === 'current';
  const active = (task.lifecycle || 'active') === 'active';
  const timeInvalid = (task.issues || []).some(issue => ['source_expired','source_not_yet_valid','source_invalid_time'].includes(issue.code));
  status(lifecycleNames[task.lifecycle || 'active'] + (current ? '' : ' · 目标或依据有变化'), current ? '' : 'warning');
  $('title').textContent = title(task.agreement.goal.text, task.task_id);
  $('reviewLink').href = '/review?task=' + encodeURIComponent(task.task_id);
  $('goalState').textContent = current ? '目标' : '此前确认的目标';
  $('goal').textContent = body(task.agreement.goal.text);
  $('rawGoal').textContent = task.agreement.goal.text;
  $('progress').textContent = task.progress || '暂无进度记录';
  $('nextLabel').textContent = active ? '下一步' : '结束说明';
  $('next').textContent = active ? task.next_action || '尚未记录下一步' : task.lifecycle_reason || '任务已结束。';
  $('resume').textContent = current && active ? 'oks task select ' + task.task_id : timeInvalid || !active ? 'oks task show --task-id ' + task.task_id : `oks task refresh ${task.task_id} --revision ${task.revision} --accept-changes`;
  $('copy').disabled = false;
  $('copy').textContent = current && active ? '复制接手命令' : timeInvalid || !active ? '复制核对命令' : '复制更新命令';
  $('lifecycleTitle').textContent = active ? '结束任务' : '重新打开任务';
  $('lifecycleAction').replaceChildren();
  for (const [value,label] of active ? [['complete','已完成'],['cancel','已取消']] : [['reopen','重新打开']]) { const option = node('option',label); option.value = value; $('lifecycleAction').append(option); }
  $('lifecycleReason').value = ''; $('lifecycleStatus').textContent = '';
  $('lifecycleSave').textContent = active ? '保存结束状态' : '重新打开';
  $('lifecycleSave').disabled = true;
  OksWorkspace.ready.then(() => { if (currentTask === task) {
    $('lifecycleSave').disabled = !OksWorkspace.context()?.local_edit || lifecycleSaving;
    if (!OksWorkspace.context()?.local_edit) $('lifecycleStatus').textContent = '修改状态需启用本地编辑。';
  }});
  $('copyStatus').textContent = '';
  $('changes').replaceChildren();
  $('changes').hidden = current;
  if (!current) {
    const goalChanged = task.current_goal_text !== task.agreement.goal.text;
    $('changes').append(node('h3', goalChanged ? '新目标 · 待确认' : '关联来源待确认'), node('p', goalChanged ? body(task.current_goal_text) || '当前目标文件无法读取' : '请核对变化来源后继续。'));
    if (timeInvalid) $('changes').append(node('p','来源的时间条件暂不适用。请在下方核对并移除或更换来源。'));
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
  renderCorrection(task);
  loadWorkflow(task);
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
    item.append(node('h3', `修订 ${entry.revision} · ${lifecycleNames[entry.lifecycle || 'active']}`), node('p', entry.lifecycle_reason || entry.progress || '任务建立'), node('p', entry.next_action ? '下一步：' + entry.next_action : ''));
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
  ++reviewTicket; reviewData = null;
  currentTask = null; ++reminderTicket; reminderTask = null; $('reminderForm').reset();
  $('content').hidden = true;
  $('workbench').hidden = !!id;
  $('copy').disabled = true;
  status(id ? '读取中…' : '请选择任务');
  if (!id) {
    history.replaceState(null, '', '/tasks');
    try { const data = await get('/api/tasks/overview'); if (ticket === revision) { overviewData = data; renderOverview(); status(''); } }
    catch (error) { if (ticket === revision) status(error.message,'error'); }
    return;
  }
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
    const data = await get('/api/tasks/overview');
    if (ticket !== revision) return;
    overviewData = data; renderOverview();
    $('taskSelect').replaceChildren(node('option', '请选择'));
    $('taskSelect').firstChild.value = '';
    for (const task of data.tasks) {
      if (task.status === 'unavailable') continue;
      const option = node('option', task.title || task.task_id);
      option.value = task.task_id;
      $('taskSelect').append(option);
    }
    if (data.tasks.some(task => task.task_id === selected)) {
      $('taskSelect').value = selected;
      await show();
    } else { currentTask = null; $('workbench').hidden = false; history.replaceState(null, '', '/tasks'); status(''); }
  } catch (error) { if (ticket === revision) status(error.message, 'error'); }
  finally { $('refresh').disabled = false; }
}
$('copy').addEventListener('click', async () => {
  const ticket = revision;
  try {
    await navigator.clipboard.writeText($('resume').textContent);
    if (ticket === revision) $('copyStatus').textContent = $('resume').textContent.includes('refresh') ? '已复制。运行前先阅读上方变化并确认可接受。' : $('resume').textContent.includes('show') ? '已复制核对指令；不会恢复任务或接受来源变化。' : '已复制，在接手目录运行即可。';
  } catch {
    if (ticket !== revision) return;
    document.querySelector('.record-section').open = true;
    document.querySelector('.technical').open = true;
    $('copyStatus').textContent = '复制失败，请在技术详情中手动复制。';
  }
});
$('taskSelect').addEventListener('change', show);
$('refresh').addEventListener('click', refresh);
function updateTaskEditors() {
  const task = currentTask, context = OksWorkspace.context();
  const writable = !!task && context?.local_edit === true && task.knowledge_base === context.knowledge_base && (task.lifecycle || 'active') === 'active';
  $('progressSave').disabled = !writable || task.status !== 'current' || progressSaving;
  $('correctionSave').disabled = !writable || task.status !== 'current' || correctionSaving || !correctionSources.length;
  $('correctionFields').disabled = $('correctionSave').disabled;
  if (!writable || task?.status !== 'current' || !correctionSources.length) $('correctionStatus').textContent = !task ? '' : task.lifecycle !== 'active' ? '任务已结束。' : task.status !== 'current' ? '请先核对目标与来源。' : !correctionSources.length ? '请先关联本次使用的已审核 Wiki 来源。' : '记录修正需启用当前实例的本地编辑。';
  $('acceptSources').disabled = !writable || sourceSaving || !reviewData || reviewData.revision !== task.revision || !reviewData.goal.current?.eligible || !$('confirmSources').checked || !!$('reviewWikiChoices').querySelector('input:checked[data-eligible="false"]');
  if (task && !writable) $('progressStatus').textContent = task.lifecycle !== 'active' ? '任务已结束，重开后才可记录进度。' : '记录进度需启用当前实例的本地编辑。';
  else if (task?.status !== 'current') $('progressStatus').textContent = '请先核对并更新目标与来源。';
}
function taskFlowError(error) {
  const text = String(error.message || error);
  if (/Sources? changed|revision changed|agreement changed/i.test(text)) return '目标、依据或任务已变化，请重新读取后再保存。';
  if (/Correction scope differs/.test(text)) return '建议所属任务与当前任务不同，请刷新后再提交。';
  if (/Choose an inspected current task source/.test(text)) return '请选择当前任务中关联的知识。';
  if (/already has different content/.test(text)) return '内容与已保存记录不同，请重新填写后提交；旧记录保留。';
  if (/not applicable/.test(text)) return '所选来源暂不适用，请移除或更换后再确认。';
  if (/closed/.test(text)) return '任务已结束，请先核对并明确重开。';
  if (/Artifact missing|canonical KB-relative/.test(text)) return '产物不可用，请核对知识库内路径；原记录保留。';
  return text;
}
function decisionColumn(label, values) {
  const section = node('section',''); section.append(node('h3',label));
  if (!Array.isArray(values) || !values.length) section.append(node('p','未记录判断。','empty'));
  else for (const option of values) {
    const item = node('article','','review-decision');
    const state = option.chosen === true ? '已选择' : option.chosen === false ? '未选择' : option.status === 'unresolved' ? '未决' : '未标明选择';
    item.append(node('p',option.id + ' · ' + state));
    if (option.rationale) item.append(node('p','依据：' + option.rationale));
    if (option.rejected_because) item.append(node('p','未选原因：' + option.rejected_because));
    section.append(item);
  }
  return section;
}
async function loadSourceReview() {
  const task = currentTask; if (!task) return;
  const ticket = ++reviewTicket; reviewData = null; $('confirmSources').checked = false; updateTaskEditors();
  $('sourceReviewStatus').textContent = '正在读取当前目标与来源…';
  $('goalComparison').replaceChildren(); $('sourceComparisons').replaceChildren(); $('reviewWikiChoices').replaceChildren();
  try {
    const data = await get('/api/tasks/review?id=' + encodeURIComponent(task.task_id));
    if (ticket !== reviewTicket || currentTask !== task) return;
    if (data.knowledge_base !== task.knowledge_base) throw Error('知识库已切换，请重新连接后查看任务。');
    reviewData = data;
    $('sourceReviewStatus').textContent = data.revision !== task.revision ? '任务已变化，请先刷新任务。' : data.lifecycle !== 'active' ? '任务已结束；可以查看，不能更新约定。' : '';
    for (const [label,value] of [['此前确认',data.goal.before],['当前文件',data.goal.current]]) {
      const section = node('section',''); section.append(node('h3',label));
      if (value) {
        section.append(node('p',body(value.text),'review-goal-body'));
        const raw = node('details',''); raw.append(node('summary','原文与版本'),node('pre',value.text),node('code',value.sha256)); section.append(raw);
        if (value.eligible === false) section.append(node('p','目标格式不可用，请修正后重新读取。','file-warning'));
      } else section.append(node('p','目标无法读取，请恢复文件后重试。','file-warning'));
      $('goalComparison').append(section);
    }
    for (const source of data.sources) {
      const details = node('details','','source-change'), previous = source.before, latest = source.current;
      details.append(node('summary',(previous.title || source.path) + (latest?.sha256 === previous.sha256 ? ' · 未变' : ' · 有变化')));
      details.append(node('p',source.path,'file-path'));
      details.append(node('p','此前版本：' + previous.sha256,'file-path'));
      if (!source.historical_bytes_available) details.append(node('p','旧正文未保存；下方只显示当前文件。','file-warning'));
      const options = node('details',''), columns = node('div','','goal-comparison');
      columns.append(decisionColumn('此前',previous.options),decisionColumn('当前',latest?.options));
      const rawOptions = node('details','');rawOptions.append(node('summary','完整记录'),node('pre',JSON.stringify({此前:previous.options,当前:latest?.options ?? null},null,2)));
      options.append(node('summary','判断记录对照'),columns,rawOptions);details.append(options);
      if (latest) {
        details.append(node('p','当前版本：' + latest.sha256,'file-path'));
        const current = node('details',''); current.append(node('summary','当前正文'),node('pre',latest.text));details.append(current);
      } else details.append(node('p','当前文件不可用；更新前请明确移除此来源，或恢复文件。','file-warning'));
      $('sourceComparisons').append(details);
    }
    const selected = new Set(data.sources.map(item=>item.path));
    const choices = new Map(data.choices.map(item=>[item.path,item]));
    for (const source of data.sources) if (!choices.has(source.path)) choices.set(source.path,{path:source.path,title:source.before.title,sha256:source.before.sha256,eligible:false,reason:'unavailable'});
    const reasons = {not_reviewed:'未审核',expired:'已过期',not_yet_valid:'尚未生效',invalid_time:'时间需核对',unavailable:'文件不可用'};
    for (const choice of choices.values()) {
      const row = node('div','','review-choice'), label = node('label',''), input = document.createElement('input');
      input.type = 'checkbox'; input.value = choice.path; input.dataset.sha256 = choice.sha256; input.dataset.eligible = String(choice.eligible); input.checked = selected.has(choice.path);
      input.disabled = !choice.eligible && !input.checked;
      input.addEventListener('change',()=>{ if (!choice.eligible) input.disabled = !input.checked; $('confirmSources').checked = false; updateTaskEditors(); });
      const timeNote = !choice.time_enforced && ['expired','not_yet_valid','invalid_time'].includes(choice.time_status) ? ' · 观察：' + reasons[choice.time_status] : '';
      label.append(input,node('span',choice.title + (!choice.eligible ? ' · ' + (reasons[choice.reason] || '暂不适用') : timeNote)));
      const link = node('a','查看'); link.href = wikiHref(choice.path); link.target = '_blank'; link.rel = 'noopener';
      row.append(label,link); $('reviewWikiChoices').append(row);
    }
    $('reviewChoicesNote').textContent = (data.truncated ? '新来源只列前 100 项，已固定项完整保留。更多来源可用 CLI 选择。' : '仅更新本任务使用的来源，不修改 Wiki 审核状态。') +
      (data.sources.some(source=>!source.current?.eligible) ? ' 暂不适用的已选项需明确移除或更换。' : '') +
      (data.memory_validity_mode === 'shadow' && data.choices.some(choice=>['expired','not_yet_valid','invalid_time'].includes(choice.time_status)) ? ' 当前只观察时间条件，尚未启用时间拦截。' : '') +
      (!OksWorkspace.context()?.local_edit ? ' 当前只读；修改需启用本地编辑。' : '');
    updateTaskEditors();
  } catch (error) { if (ticket === reviewTicket && currentTask === task) { reviewData = null; $('sourceReviewStatus').textContent = taskFlowError(error); updateTaskEditors(); } }
}
$('sourceReviewPanel').addEventListener('toggle',()=>{ if ($('sourceReviewPanel').open && !reviewData) loadSourceReview(); });
$('reloadSources').addEventListener('click',loadSourceReview);
$('confirmSources').addEventListener('change',updateTaskEditors);
$('acceptSources').addEventListener('click',async()=>{
  const task = currentTask, inspected = reviewData;
  if ($('acceptSources').disabled || !task || !inspected) return;
  const ticket = revision; sourceSaving = true; updateTaskEditors();
  const chosen = [...$('reviewWikiChoices').querySelectorAll('input:checked')].map(input=>({path:input.value,sha256:input.dataset.sha256}));
  try {
    const result = await OksWorkspace.request('/api/tasks/accept-sources',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      expected_knowledge_base:inspected.knowledge_base,task_id:task.task_id,expected_revision:inspected.revision,
      expected_goal_sha256:inspected.goal.current.sha256,wiki:chosen,accept_changes:true})});
    if (ticket === revision && currentTask === task) render(result);
  } catch (error) { if (ticket === revision && currentTask === task) { $('sourceReviewStatus').textContent = taskFlowError(error); $('confirmSources').checked = false; } }
  finally { sourceSaving = false; updateTaskEditors(); }
});
$('progressForm').addEventListener('submit',async event=>{
  event.preventDefault(); const task = currentTask;
  if ($('progressSave').disabled || !task) return;
  const ticket = revision; progressSaving = true; updateTaskEditors();
  const artifacts = $('progressArtifacts').value.split(/\r?\n/).map(text=>text.trim()).filter(Boolean);
  try {
    const result = await OksWorkspace.request('/api/tasks/progress',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      expected_knowledge_base:task.knowledge_base,task_id:task.task_id,expected_revision:task.revision,expected_agreement_sha256:task.agreement.sha256,
      progress:$('progressText').value.trim(),next_action:$('nextText').value.trim(),artifacts})});
    if (ticket === revision && currentTask === task) render(result);
  } catch (error) { if (ticket === revision && currentTask === task) $('progressStatus').textContent = taskFlowError(error); }
  finally { progressSaving = false; updateTaskEditors(); }
});
$('copyHandoff').addEventListener('click',async()=>{
  const task = currentTask, ticket = revision; if (!task || copyingHandoff) return;
  copyingHandoff = true; $('copyHandoff').disabled = true;
  try {
    const data = await get('/api/tasks/handoff?id=' + encodeURIComponent(task.task_id) + '&revision=' + task.revision);
    if (ticket !== revision || currentTask !== task) return;
    if (data.knowledge_base !== task.knowledge_base) throw Error('知识库已切换，请刷新后查看。');
    $('handoffText').value = data.text;
    try { await navigator.clipboard.writeText(data.text); if (ticket === revision) $('copyStatus').textContent = '已复制交接内容；没有发送消息或改变任务选择。'; }
    catch { if (ticket === revision) { $('handoffText').hidden = false; $('copyStatus').textContent = '请手动复制下方交接内容。'; } }
  } catch (error) { if (ticket === revision && currentTask === task) $('copyStatus').textContent = taskFlowError(error); }
  finally { copyingHandoff = false; $('copyHandoff').disabled = false; }
});
$('taskSearch').addEventListener('input', renderOverview);
$('taskFilters').addEventListener('click', event => {
  const button = event.target.closest('button[data-filter]'); if (!button) return;
  taskFilter = button.dataset.filter;
  for (const option of $('taskFilters').querySelectorAll('button')) option.setAttribute('aria-pressed',String(option === button));
  renderOverview();
});
$('lifecycleForm').addEventListener('submit', async event => {
  event.preventDefault(); const task = currentTask, context = OksWorkspace.context();
  if (!task || !context?.local_edit || lifecycleSaving || !$('lifecycleReason').value.trim()) return;
  const ticket = revision; lifecycleSaving = true; $('lifecycleSave').disabled = true;
  try {
    const result = await OksWorkspace.request('/api/tasks/lifecycle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      expected_knowledge_base:context.knowledge_base,task_id:task.task_id,expected_revision:task.revision,action:$('lifecycleAction').value,reason:$('lifecycleReason').value.trim()})});
    if (ticket === revision && currentTask === task) render(result);
  } catch (error) { if (ticket === revision && currentTask === task) $('lifecycleStatus').textContent = /revision|lifecycle changed/.test(error.message) ? '任务已变化，请刷新后再操作。' : error.message; }
  finally { lifecycleSaving = false; $('lifecycleSave').disabled = !currentTask || !OksWorkspace.context()?.local_edit; }
});
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
    request.start_now = true;
    const task = await OksWorkspace.request('/api/tasks/create', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});
    $('createPanel').hidden = true;
    const option = node('option', task.task_id); option.value = task.task_id; $('taskSelect').append(option); $('taskSelect').value = task.task_id;
    ++revision; render(task); $('newTaskId').value = ''; $('newTitle').value = ''; $('newGoal').value = ''; $('createStatus').textContent = '';
  } catch (error) { $('createStatus').textContent = error.message; }
  finally { creating = false; updateCreate(); }
});
document.addEventListener('oks:reconnected', event => {
  ++reviewTicket; reviewData = null;
  localEdit = event.detail.context.local_edit === true;
  if (event.detail.changedRoot) {
    currentTask = null; overviewData = null;
    ++sourcesTicket; correctionId = null; correctionSources = []; $('correctionForm').reset();
    ++goalTicket; goalPreview = null; taskOptions = {goals:[],wiki:[]};
    $('content').hidden = true; $('createPanel').hidden = true; $('taskSelect').value = '';
    $('createForm').reset(); $('wikiChoices').replaceChildren();
    history.replaceState(null, '', '/tasks');
  }
  refresh(); updateCreate();
});
refresh();
let overviewPolling = false;
setInterval(async () => {
  if (document.hidden || OksWorkspace.isReconnecting?.()) return;
  if (currentTask) { loadWorkflow(currentTask, true); return; }
  if (overviewPolling || $('content').hidden === false) return;
  overviewPolling = true;
  const root = OksWorkspace.context()?.knowledge_base;
  try {
    const data = await get('/api/tasks/overview');
    if (!currentTask && root === OksWorkspace.context()?.knowledge_base) { overviewData = data; renderOverview(); status(''); }
  } catch { if (!currentTask && root === OksWorkspace.context()?.knowledge_base) status('列表暂时无法连接，保留当前内容并自动重试。','warning'); }
  finally { overviewPolling = false; }
}, 12000);

let reminderTicket = 0, reminderTask = null, reminderSaving = false;
const reminderNames = {due:'已到时间',scheduled:'待提醒',needs_review:'任务或来源有变化，待确认',task_closed:'任务已结束，暂停提醒',completed:'已完成',cancelled:'已取消'};
function reminderError(error) {
  const text = String(error.message || error);
  if (/Reminder changed|already completed|already exists/.test(text)) return '提醒状态已变化，请刷新后再操作。';
  if (/Task sources changed|current task agreement/.test(text)) return '任务约定已变化，请先查看并确认当前目标。';
  if (/future time/.test(text)) return '请选择未来的提醒时间。';
  return text;
}
async function saveReminder(request, task) {
  if (reminderSaving || !task?.canEdit) return;
  reminderSaving = true; $('reminderAdd').disabled = true;
  try {
    await OksWorkspace.request('/api/tasks/reminders', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      ...request,task_id:task.task_id,expected_agreement_sha256:task.agreement.sha256,expected_knowledge_base:task.instance})});
    if (reminderTask === task) { $('reminderForm').reset(); await loadReminders(task); }
  } catch (error) { if (reminderTask === task) $('reminderStatus').textContent = reminderError(error); }
  finally { reminderSaving = false; if (reminderTask) $('reminderAdd').disabled = !reminderTask.canEdit || reminderTask.status !== 'current' || (reminderTask.lifecycle || 'active') !== 'active'; }
}
async function loadReminders(task) {
  const ticket = ++reminderTicket;
  $('reminderList').replaceChildren(); $('reminderStatus').textContent = '读取中…'; $('reminderAdd').disabled = true;
  try {
    await OksWorkspace.ready;
    const context = OksWorkspace.context();
    const data = await get('/api/tasks/reminders?id=' + encodeURIComponent(task.task_id));
    if (ticket !== reminderTicket) return;
    reminderTask = {...task,canEdit:context?.local_edit === true,instance:context?.knowledge_base};
    const current = reminderTask;
    const active = (current.lifecycle || 'active') === 'active';
    $('reminderAdd').disabled = !current.canEdit || current.status !== 'current' || !active;
    $('reminderGate').hidden = current.canEdit && current.status === 'current' && active;
    $('reminderGate').textContent = !current.canEdit ? '设置提醒需启用本地编辑。' : !active ? '任务已结束，保留提醒记录。重开后需明确确认沿用。' : '请先核对变化并确认任务约定。';
    for (const item of data.items) {
      const card = node('article', '', 'reminder-item');
      card.append(node('p', item.note), node('small', `${reminderNames[item.status] || '待核对'} · ${new Date(item.due_at).toLocaleString('zh-CN')}`));
      const actions = node('div', '', 'reminder-actions');
      if (item.state === 'pending') {
        const addAction = (label, action, extra) => {
          const button = node('button', label); button.type = 'button'; button.disabled = !current.canEdit;
          button.addEventListener('click', () => saveReminder({id:item.id,expected_revision:item.revision,action,...(extra ? extra() : {})}, current));
          actions.append(button); return button;
        };
        addAction('完成','complete'); addAction('取消','cancel');
        if (item.status === 'task_closed') {
          // Completion/cancellation remains explicit; no scheduling on closed tasks.
        } else if (item.status === 'needs_review') {
          addAction('确认沿用','confirm').disabled = !current.canEdit || current.status !== 'current';
        } else {
          const at = document.createElement('input'); at.type = 'datetime-local'; at.setAttribute('aria-label', '稍后时间：' + item.note);
          actions.append(at); const snooze = addAction('稍后','snooze', () => ({due_at:new Date(at.value).toISOString()}));
          snooze.disabled = true; at.disabled = !current.canEdit;
          at.addEventListener('input', () => { snooze.disabled = !current.canEdit || !at.value || Number.isNaN(Date.parse(at.value)); });
        }
      }
      card.append(actions); $('reminderList').append(card);
    }
    if (!data.items.length) $('reminderList').append(node('p', '暂无提醒。', 'empty'));
    $('reminderStatus').textContent = '';
  } catch (error) { if (ticket === reminderTicket) { reminderTask = null; $('reminderStatus').textContent = reminderError(error); } }
}
$('reminderForm').addEventListener('submit', event => {
  event.preventDefault(); const task = reminderTask;
  if (!task || !task.canEdit || !$('reminderAt').value) return;
  const at = new Date($('reminderAt').value); if (Number.isNaN(at.valueOf())) return;
  saveReminder({action:'add',id:'rem-' + Date.now().toString(36),note:$('reminderNote').value.trim(),due_at:at.toISOString()}, task);
});
document.addEventListener('oks:reconnected', () => { ++reminderTicket; reminderTask = null; $('reminderList').replaceChildren(); $('reminderForm').reset(); });
