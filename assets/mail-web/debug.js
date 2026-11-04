'use strict';
const $ = id => document.getElementById(id);
const el = (tag, text, cls) => { const n=document.createElement(tag); if(text!==undefined)n.textContent=String(text); if(cls)n.className=cls; return n; };
const array = value => Array.isArray(value) ? value : [];
const stages = {retrieved:'查询',hook_emitted:'Hook 输出',hook_skipped:'Hook 跳过'};
let data={records:[],deployments:[]}, stale=false;
let heatLoaded=false;
const debugParams=new URLSearchParams(location.search), taskId=debugParams.get('task')||'';
const eventNames={query:'查询命中',hook_output:'Hook 已输出上下文',cli_return:'CLI 已返回内容',host_read:'宿主读取了文件',caller_reported:'调用者关联了产物',output_citation:'产物明确引用了此来源'};
function taskHref(id,artifact,revision){return '/tasks?'+new URLSearchParams({id,...(artifact?{artifact}:{}),...(revision?{artifact_revision:revision}:{})});}
function chooseHeat(row,phase){const url=new URL(location.href);url.searchParams.set('source',row.path);url.searchParams.set('version',row.sha);url.searchParams.set('phase',phase);history.pushState(null,'',url);renderHeatmap();}
function renderHeatmap(){
 const host=$('heatmapGrid');host.replaceChildren();
 if(!heatLoaded){$('heatmapStatus').textContent=stale?'无法读取知识记录，请重试。':'正在读取记录…';return;}
 const model=OksKnowledgeHeatmap.build(data,{taskId,query:$('heatSearch').value}),params=new URLSearchParams(location.search);
 $('heatmapStatus').textContent=stale?'刷新失败，保留上次记录。':`${$('heatSearch').value.trim()?(model.rows.length+model.hidden)+' / ':''}${model.sourceCount} 个来源版本 · ${taskId?'当前目标':'当前保留记录'}${model.hidden?' · 筛选后显示前40项':''}${data.status==='error'?' · 查询日志读取失败':''}`;
 const table=el('table',undefined,'heatmap-table'),thead=el('thead'),heads=el('tr');heads.append(el('th','知识来源'));
 for(const [key,label]of model.columns){const th=el('th',({retrieved:'查到',emitted:'输出',read:'读取',used:'关联产物'})[key]);th.scope='col';th.title=label;heads.append(th);}thead.append(heads);table.append(thead);const tbody=el('tbody');
 for(const row of model.rows){
  const tr=el('tr'),heading=el('th'),name=el('button',row.title,'heatmap-source');heading.scope='row';name.type='button';name.title=row.path;
  name.addEventListener('click',()=>chooseHeat(row,model.columns.find(([key])=>row.events[key].length)?.[0]||'retrieved'));heading.append(name,el('small',row.kind));tr.append(heading);
  for(const [key,label]of model.columns){
   const td=el('td'),count=row.events[key].length,cell=el('button',count?count:'—','heatmap-cell');cell.type='button';cell.disabled=!count;cell.dataset.level=count?String(Math.min(4,Math.max(1,Math.ceil(count/model.maximum*4)))):'0';
   cell.setAttribute('aria-label',`${row.title} · ${label} · ${count?count+'条记录':'未记录'}`);
   cell.setAttribute('aria-pressed',String(params.get('source')===row.path&&params.get('version')===row.sha&&params.get('phase')===key));cell.addEventListener('click',()=>chooseHeat(row,key));td.append(cell);tr.append(td);
  }tbody.append(tr);
 }
 table.append(tbody);host.append(table);
 if(!model.rows.length)host.append(el('p',$('heatSearch').value?'没有匹配的知识。':'尚未记录到知识。可先完成一次查询或在已接入的任务中读取知识。','empty'));
 const row=model.rows.find(row=>row.path===params.get('source')&&row.sha===params.get('version')),phase=params.get('phase'),detail=$('heatmapDetail');detail.replaceChildren();
 if(!row||!row.events[phase]){detail.append(el('p','选择一个有记录的格子，查看来源和对应任务。','meta'));return;}
 const heading=el('div',undefined,'heatmap-detail-heading');heading.append(el('h3',row.title),el('span',model.columns.find(([key])=>key===phase)[1]+' · '+row.events[phase].length+' 条','meta'));detail.append(heading);
 const source=el('a','阅读当前知识 →');source.href='/#wiki-reader&path='+encodeURIComponent(row.path);detail.append(source);
 for(const event of row.events[phase].slice(0,20)){
  const item=el('article',undefined,'heatmap-event');item.append(el('strong',eventNames[event.kind]),el('span',event.at?new Date(event.at).toLocaleString('zh-CN'):'时间未记录','meta'));
  if(event.taskId){const link=el('a','查看目标与产物 →');link.href=taskHref(event.taskId);item.append(link);}
  if(event.recordId){const link=el('button','查看本次查询');link.type='button';link.addEventListener('click',()=>{$('queryHistory').open=true;const card=$('query-'+event.recordId);if(card){card.open=true;card.scrollIntoView({behavior:'smooth',block:'start'});}});item.append(link);}
  for(const artifact of array(event.artifacts)){const link=el('a',artifact.path.split('/').pop());link.href=taskHref(event.taskId,artifact.path,event.revision);item.append(link);}
  const metadata=el('details');metadata.append(el('summary','查看记录与版本'),facts([['记录类型',eventNames[event.kind]],['来源',row.path],[event.kind==='host_read'?'文件版本（记录时）':'来源版本',row.sha],['任务',event.taskId||'未关联'],['运行',event.runId||'未记录'],['记录标识',event.id]]));item.append(metadata);detail.append(item);
 }
 if(row.events[phase].length>20)detail.append(el('p','显示前20条记录。','meta'));
}
$('heatSearch').value=debugParams.get('q')||'';
$('heatSearch').addEventListener('input',()=>{const url=new URL(location.href);if($('heatSearch').value)url.searchParams.set('q',$('heatSearch').value);else url.searchParams.delete('q');history.replaceState(null,'',url);renderHeatmap();});
window.addEventListener('popstate',()=>{$('heatSearch').value=new URLSearchParams(location.search).get('q')||'';renderHeatmap();});
$('heatmapDetail').addEventListener('click',event=>{const link=event.target.closest('a[href]');if(link&&/^\/(?:tasks(?:\?|$)|#)/.test(link.getAttribute('href')))link.href=OksNavigation.fromTask(link.href);});
if(taskId){const context=$('debugTask');context.hidden=false;const link=el('a','查看本次目标与产物 →');link.href=OksNavigation.origin?.startsWith('/tasks')?OksNavigation.origin:taskHref(taskId);context.append(link);}
function facts(values) {
 const list=el('dl',undefined,'facts');
 for(const [key,value] of values) list.append(el('dt',key),el('dd',typeof value==='string'?value:JSON.stringify(value??'未记录')));
 return list;
}
function taskRequirements(context) {
 const box=el('div',undefined,'task-context');
 const labels={not_requested:'未启用',scope_incomplete:'范围不完整',agreement_required:'缺少任务约定',unavailable:'读取失败',empty:'无匹配要求',selected:'已选择'};
 box.append(el('h3','任务要求'),el('p',`${labels[context.status]||'未记录'} · ${context.selected_count||0} 项`));
 const reasons={pending:'待审核',rejected:'已拒绝',invalidated:'已失效',different_agreement:'约定版本不同',conflicting_feedback:'反馈冲突'};
 for(const [reason,count] of Object.entries(context.excluded_counts||{})) box.append(el('p',`${reasons[reason]||reason}：${count}`,'meta'));
 return box;
}
function render() {
 renderHeatmap();
 const q=$('filter').value.toLowerCase(),stage=$('stage').value,backend=$('backend').value;
 const records=array(data.records).filter(r=>(!stage||r.stage===stage)&&(!backend||array(r.diagnostics?.actual_backends).includes(backend))&&(!q||JSON.stringify(r.hits||[]).toLowerCase().includes(q)));
 $('records').replaceChildren();
 $('status').textContent=stale?'刷新失败，当前显示上次记录。':data.status==='error'?'记录暂时无法读取，请重试。':`${records.length} 条记录`;
 if(!records.length) $('records').append(el('div',data.status==='error'?'记录读取失败，原文件已保留。':data.records.length?'没有匹配结果。':'暂无记录。完成一次带诊断的查询后，这里会显示结果。','empty'));
 records.forEach((record,index)=>{
  const d=record.diagnostics||{},hits=array(record.hits),emitted=array(record.emitted),card=el('details',undefined,'record'),summary=el('summary');
  card.id='query-'+record.id;
  summary.append(el('span',stages[record.stage]||record.stage,'stage-label'),el('span',hits[0]?.title||d.task?.scope||'无知识命中','record-title'),el('span',new Date(record.at).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}),'time'),el('span',`${hits.length} 项`,'count'));
  card.append(summary);card.open=index===0;
  const body=el('div',undefined,'record-body'),flow=el('div',undefined,'flow');
  const loads=array(record.loads),usage=array(record.usage);
  for(const [label,value] of [['查到',`${hits.length} 项知识`],['Hook 输出',record.stage==='hook_emitted'?`${emitted.length} 项知识`:record.stage==='hook_skipped'?'未输出':'未记录'],['Skill 读取',loads.length?`${loads.length} 项`:'未记录'],['使用声明',usage.length?`${usage.length} 项`:'未记录']]) {
   const step=el('div');step.append(el('span',label),el('strong',value));flow.append(step);
  }
  body.append(flow);
  const measure = d.measurements;
  if (measure && Number.isFinite(measure.total_ms)) {
   const panel=el('section',undefined,'measurements');
   panel.append(el('p',`本次 OKS 查询 ${measure.total_ms.toFixed(1)} ms`,'measurement-title'));
   const names={task_check:'任务检查',episodic:'资料检索',knowledge:'Wiki / Skill 检索',requirements:'要求筛选'};
   const phases=el('div',undefined,'measured-phases'),maximum=Math.max(1,...Object.values(measure.phase_ms||{}).filter(Number.isFinite));
   for(const [key,value] of Object.entries(measure.phase_ms||{}))if(Number.isFinite(value)&&value>=0){
    const row=el('div',undefined,'measured-phase'),bar=el('span',undefined,'measured-bar');bar.style.width=Math.max(1,value/maximum*100)+'%';
    row.append(el('span',names[key]||key),el('strong',value.toFixed(1)+' ms'),bar);phases.append(row);
   }
   panel.append(phases,el('p',`查询 ${measure.query_utf8_bytes} B · 返回上下文 JSON ${measure.context_utf8_bytes} B`,'meta'),el('p','仅测量 OKS 查询；模型 Token 与宿主执行耗时未记录。','meta'));body.append(panel);
  } else body.append(el('p','该记录未测量耗时。','meta'));
  if(d.memory_validity?.would_exclude)body.append(el('p',d.memory_validity.mode==='shadow'?`时间条件对照：库内 ${d.memory_validity.would_exclude} 项暂不适用，当前仅评估。`:`时间条件已启用：库内 ${d.memory_validity.would_exclude} 项暂不适用。`,'meta'));
  if(d.task_warning) body.append(el('p',d.task_warning.status==='needs_review'?'任务来源有变化，请先核对目标。':'部分任务反馈已失效或冲突，未纳入上下文。','warning'));
  const grouped=new Map();
  for(const use of usage) {
   const key=JSON.stringify([use.task_id,use.revision,use.artifacts]);
   if(!grouped.has(key)) grouped.set(key,{...use,sources:[]});
   grouped.get(key).sources.push(use.source_path);
  }
  for(const use of grouped.values()) {
   const item=el('div',undefined,'hit'),link=el('a',`${use.task_id} · 修订 ${use.revision}`);
   link.href='/tasks?'+new URLSearchParams({id:use.task_id});item.append(link);
   for(const artifact of array(use.artifacts)) item.append(el('p',artifact.path+' · '+({unchanged:'文件未变',changed:'文件已变，需复核',unavailable:'文件不可用'}[artifact.status]||'未核验'),'meta'));
   const sources=el('details',undefined,'source-detail');sources.append(el('summary',`${use.sources.length} 条来源 · 调用者声明`));
   for(const path of use.sources) sources.append(el('p',path,'path'));
   sources.append(el('p','文件匹配不证明执行或内容正确。','meta'));item.append(sources);body.append(item);
  }
  if(record.stage==='hook_emitted'&&!emitted.length) body.append(el('p','本次 Hook 输出可能仅含任务上下文，详见技术详情。','meta'));
  if(!hits.length) body.append(el('p','本次没有 Wiki 或 Skill 命中。','meta'));
  if(d.fallback_error||d.hook_error||d.retrieval_error||d.skill_error) body.append(el('p','运行异常：'+(d.fallback_error||d.hook_error||d.retrieval_error||d.skill_error),'warning'));
  for(const hit of hits) {
   const item=el('article',undefined,'hit'),heading=el('div',undefined,'hit-heading');
   const output=emitted.find(value=>value.slug===hit.slug);
   const loaded=loads.some(value=>value.source_path===hit.source_path&&value.source_sha256===hit.source_sha256);
   heading.append(el('h3',hit.title||hit.slug),el('span',output?'Hook 已输出':loaded?'已读取':'已命中',output||loaded?'selected':'meta'));item.append(heading);
   const score=typeof hit.relevance==='number'&&Number.isFinite(hit.relevance)?hit.relevance.toFixed(2):'未记录';
   item.append(el('p',`${hit.artifact_kind==='skill'?'Skill':'Wiki'} · ${hit.backend||'检索'} · 相关度 ${score}`,'meta'));
   if(loaded) item.append(el('p','已读取固定版本','meta'));
   if(hit.source_path?.startsWith('wiki/')) {
    const link=el('a','打开来源 ↗','path');link.href='/api/mail/wiki-page?'+new URLSearchParams({path:hit.source_path});link.target='_blank';link.rel='noopener noreferrer';link.title='打开当前文件，可能与记录版本不同';item.append(link);
   }
   const reason=record.skipped?.[hit.slug];
   const reasons={topn:'未进入输出名额',threshold_or_policy:'未达到阈值或被策略排除'};
   if(reason) item.append(el('p','未输出：'+(reasons[reason]||reason),'meta'));
   const detail=el('details',undefined,'source-detail');detail.append(el('summary','匹配依据与版本'));
   detail.append(facts([['来源路径',hit.source_path||'未记录'],['相关度依据',hit.score_components||'未记录'],['来源版本',hit.source_sha256||'未记录'],['Skill 版本',hit.skill_version||'不适用']]));
   if(hit.load_command)detail.append(el('code',hit.load_command));
   if(array(hit.options).length)detail.append(el('pre',JSON.stringify(hit.options,null,2)));
   item.append(detail);body.append(item);
  }
  const technical=el('details',undefined,'technical');technical.append(el('summary','技术详情'));
  technical.append(facts([['检索策略',d.strategy],['请求后端',d.requested_backend],['降级 / 实验',d.fallback_reason||d.capability_fallback||(d.experimental?'实验对照':'无')],['库内排除',d.corpus_excluded],['返回过滤',d.filtered],['Hook 跳过',record.skipped],['任务约定',d.task],['当前进度标识',d.continuation],['来源版本',d.task?.goal_sha256],['查询指纹',record.query_sha256],['使用证据','未记录宿主消费或执行；命中、输出和部署不能代替执行证据。']]));
  if(d.task_context)technical.append(taskRequirements(d.task_context));
  if(d.memory_validity)technical.append(facts([['记忆时间条件',d.memory_validity]]));
  body.append(technical);card.append(body);$('records').append(card);
 });
}
async function refresh() {
 $('refresh').disabled=true;$('status').textContent='读取中…';
 try {
  const response=await fetch('/api/retrieval/debug'+(taskId?'?'+new URLSearchParams({task:taskId}):''),{cache:'no-store'});
  if(!response.ok)throw Error('HTTP '+response.status);
  const next=await response.json();if(!Array.isArray(next.records))throw Error('记录格式错误');data=next;stale=false;heatLoaded=true;
  $('total').textContent=data.records.length;$('emitted').textContent=data.records.filter(r=>r.stage==='hook_emitted').length;
  $('degraded').textContent=data.records.filter(r=>r.diagnostics?.fallback_reason||r.diagnostics?.experimental).length;
  $('deploymentsCount').textContent=array(data.deployments).length;$('deployments').replaceChildren();
  for(const receipt of array(data.deployments))$('deployments').append(el('div',`${receipt.host_skill} · ${receipt.version} · ${receipt.loaded_at}`,'deployment'));
  if(!array(data.deployments).length)$('deployments').append(el('p',data.deployment_error||'暂无部署记录。','meta'));
  render();
 } catch(error) {stale=true;$('status').textContent='刷新失败，当前显示上次记录。请重试。';renderHeatmap();}
 finally {$('refresh').disabled=false;}
}
$('refresh').addEventListener('click',refresh);
for(const id of ['filter','stage','backend'])$(id).addEventListener('input',render);
refresh();
function revealFeedback() { if(location.hash==='#feedback') $('feedback').open=true; }
window.addEventListener('hashchange',revealFeedback);revealFeedback();

// No scope history or private results are written to localStorage or shared logs.
let feedbackRevision=0;
const feedbackScope=()=>({subject:$('feedbackSubject').value,project:$('feedbackProject').value,task:$('feedbackTask').value});
function clearFeedback(message='范围已改变，请重新读取。'){feedbackRevision++;$('feedbackResults').replaceChildren();$('feedbackStatus').textContent=message;}
for(const id of ['feedbackSubject','feedbackProject','feedbackTask'])$(id).addEventListener('input',()=>clearFeedback());
$('feedbackClear').addEventListener('click',()=>{$('feedbackForm').reset();clearFeedback('已清空显示；本地反馈文件未删除。');});
$('feedbackForm').addEventListener('submit',async event=>{
 event.preventDefault();clearFeedback('正在读取此范围…');const revision=feedbackRevision,scope=feedbackScope();$('feedbackRead').disabled=true;
 try{const response=await fetch('/api/feedback/inspect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scope}),cache:'no-store'});const result=await response.json();if(revision!==feedbackRevision)return;if(!response.ok)throw new Error(result.error||'读取失败');
 const host=$('feedbackResults');host.replaceChildren();$('feedbackStatus').textContent=`${array(result.events).length} 条显式反馈 · ${array(result.candidates).length} 个学习候选。读取状态不代表任务已执行。`;
 const labels={observed:'观察到',adopted:'采用',revised:'修改',rejected:'拒绝',active:'有效',corrected:'已修正',withdrawn:'已撤回',pending:'待审核',approved:'已审核',invalidated:'已失效'};
 for(const e of array(result.events)){const card=el('details',undefined,'record');card.append(el('summary',`${labels[e.payload.action]||e.payload.action} · ${e.event_id} · ${labels[e.status]||e.status}`));const body=el('div',undefined,'record-body');body.append(el('p',e.payload.reason),facts([['反馈来源',e.payload.source+'（调用者标注，非认证身份）'],['资产版本',e.payload.asset.path+' @ '+e.payload.asset.sha256],['任务约定',e.payload.agreement.sha256],['替代事件',e.payload.replaces||'无']]));card.append(body);host.append(card);}
 for(const c of array(result.candidates)){const card=el('details',undefined,'record');card.append(el('summary',`${labels[c.effective_status]||c.effective_status} · ${c.title}`));const body=el('div',undefined,'record-body');body.append(el('p',c.summary),facts([['候选 ID',c.candidate_id],['来源反馈',c.event_ids],['候选修订',c.revision],['失效原因',c.issues],['审核说明',c.review_comment||'尚未审核']]));card.append(body);host.append(card);}
 if(array(result.conflicts).length)host.append(el('p','存在相反选择，相关候选暂不消费：'+result.conflicts.join('、'),'warning'));
 if(!array(result.events).length&&!array(result.candidates).length)host.append(el('div','此范围暂无反馈或候选。','empty'));
 }catch(error){if(revision===feedbackRevision){$('feedbackResults').replaceChildren();$('feedbackStatus').textContent='读取失败：'+error.message;}}finally{$('feedbackRead').disabled=false;}
});
