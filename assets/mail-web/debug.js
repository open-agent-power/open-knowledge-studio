'use strict';
const $ = id => document.getElementById(id);
const el = (tag, text, cls) => { const n=document.createElement(tag); if(text!==undefined)n.textContent=String(text); if(cls)n.className=cls; return n; };
const array = value => Array.isArray(value) ? value : [];
const stages = {retrieved:'查询',hook_emitted:'Hook 输出',hook_skipped:'Hook 跳过'};
let data={records:[],deployments:[]}, stale=false;
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
 const q=$('filter').value.toLowerCase(),stage=$('stage').value,backend=$('backend').value;
 const records=array(data.records).filter(r=>(!stage||r.stage===stage)&&(!backend||array(r.diagnostics?.actual_backends).includes(backend))&&(!q||JSON.stringify(r.hits||[]).toLowerCase().includes(q)));
 $('records').replaceChildren();
 $('status').textContent=stale?'刷新失败，当前显示上次记录。':data.status==='error'?'记录暂时无法读取，请重试。':`${records.length} 条记录`;
 if(!records.length) $('records').append(el('div',data.status==='error'?'记录读取失败，原文件已保留。':data.records.length?'没有匹配结果。':'暂无记录。完成一次带诊断的查询后，这里会显示结果。','empty'));
 records.forEach((record,index)=>{
  const d=record.diagnostics||{},hits=array(record.hits),emitted=array(record.emitted),card=el('details',undefined,'record'),summary=el('summary');
  summary.append(el('span',stages[record.stage]||record.stage,'stage-label'),el('span',hits[0]?.title||d.task?.scope||'无知识命中','record-title'),el('span',new Date(record.at).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}),'time'),el('span',`${hits.length} 项`,'count'));
  card.append(summary);card.open=index===0;
  const body=el('div',undefined,'record-body'),flow=el('div',undefined,'flow');
  const loads=array(record.loads),usage=array(record.usage);
  for(const [label,value] of [['查到',`${hits.length} 项知识`],['Hook 输出',record.stage==='hook_emitted'?`${emitted.length} 项知识`:record.stage==='hook_skipped'?'未输出':'未记录'],['Skill 读取',loads.length?`${loads.length} 项`:'未记录'],['使用声明',usage.length?`${usage.length} 项`:'未记录']]) {
   const step=el('div');step.append(el('span',label),el('strong',value));flow.append(step);
  }
  body.append(flow);
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
  body.append(technical);card.append(body);$('records').append(card);
 });
}
async function refresh() {
 $('refresh').disabled=true;$('status').textContent='读取中…';
 try {
  const response=await fetch('/api/retrieval/debug',{cache:'no-store'});
  if(!response.ok)throw Error('HTTP '+response.status);
  const next=await response.json();if(!Array.isArray(next.records))throw Error('记录格式错误');data=next;stale=false;
  $('total').textContent=data.records.length;$('emitted').textContent=data.records.filter(r=>r.stage==='hook_emitted').length;
  $('degraded').textContent=data.records.filter(r=>r.diagnostics?.fallback_reason||r.diagnostics?.experimental).length;
  $('deploymentsCount').textContent=array(data.deployments).length;$('deployments').replaceChildren();
  for(const receipt of array(data.deployments))$('deployments').append(el('div',`${receipt.host_skill} · ${receipt.version} · ${receipt.loaded_at}`,'deployment'));
  if(!array(data.deployments).length)$('deployments').append(el('p',data.deployment_error||'暂无部署记录。','meta'));
  render();
 } catch(error) {stale=true;$('status').textContent='刷新失败，当前显示上次记录。请重试。';}
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
