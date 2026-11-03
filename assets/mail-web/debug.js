'use strict';
const $=id=>document.getElementById(id);
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);if(cls)n.className=cls;return n;};
const array=x=>Array.isArray(x)?x:[];
const stages={retrieved:'检索命中',hook_emitted:'Hook 已输出',hook_skipped:'Hook 未输出'};
let data={records:[],deployments:[]};
function facts(values){const dl=el('dl',undefined,'facts');for(const [k,v] of values){dl.append(el('dt',k),el('dd',typeof v==='string'?v:JSON.stringify(v??'未记录')));}return dl;}
function taskRequirements(context){
 const box=el('div',undefined,'hit');box.append(el('h3','本次任务要求'));
 const statuses={not_requested:'未启用私人任务要求',scope_incomplete:'主体或项目未指定完整，未读取',agreement_required:'缺少当前任务约定，未读取',unavailable:'私人要求暂不可读，本次未带入',empty:'没有符合当前任务的已审核要求',selected:'已选择与当前任务约定匹配的已审核要求'};
 box.append(el('p',statuses[context.status]||'未记录选择状态'));
 box.append(el('p',`召回返回 ${context.selected_count||0} 项；Hook 输出 ${context.hook_emitted_count===undefined?'未记录':context.hook_emitted_count+' 项'}。宿主消费与执行仍未知。`,'meta'));
 const reasons={pending:'尚未审核',rejected:'审核已拒绝',invalidated:'反馈已撤回、修正或来源已失效',different_agreement:'属于其他任务约定版本',conflicting_feedback:'存在相反反馈'};
 for(const [reason,count] of Object.entries(context.excluded_counts||{}))box.append(el('p',`未采用 ${count} 项：${reasons[reason]||reason}`,'meta'));
 box.append(el('p','这里仅保存数量和排除原因；具体要求请在下方填写私人范围后查看。历史记录不证明这些要求现在仍然有效。','meta'));return box;
}
function render(){
 const q=$('filter').value.toLowerCase(),stage=$('stage').value,backend=$('backend').value;
 const records=array(data.records).filter(r=>(!stage||r.stage===stage)&&(!backend||array(r.diagnostics?.actual_backends).includes(backend))&&(!q||JSON.stringify(r.hits||[]).toLowerCase().includes(q)));
 $('records').replaceChildren();$('status').textContent=data.status==='error'?data.error:`显示 ${records.length} / ${array(data.records).length} 条记录。展开查看来源、版本与筛选结果。`;
 if(!records.length)$('records').append(el('div',data.status==='error'?'读取失败。记录已保留，请检查本地诊断文件后刷新。':data.records.length?'没有符合筛选条件的记录。':'还没有诊断记录。执行带 --debug-record 的查询，或启用 Hook 诊断后刷新。','empty'));
 for(const r of records){const d=r.diagnostics||{},card=el('details',undefined,'record'),head=el('summary');head.append(el('span',stages[r.stage]||r.stage,'badge'),el('span',new Date(r.at).toLocaleString('zh-CN'),'time'),el('span',array(d.actual_backends).join(' + ')||'后端未记录'),el('span',`${array(r.hits).length} 命中 · ${array(r.emitted).length} 输出`,'count'));card.append(head);
 const body=el('div',undefined,'record-body');body.append(facts([['检索策略',d.strategy],['请求后端',d.requested_backend],['降级 / 实验',d.fallback_reason||d.capability_fallback|| (d.experimental?'显式实验对照':'无记录')],['库内策略排除（含未匹配页）',d.corpus_excluded],['返回候选过滤',d.filtered],['Hook 跳过原因',r.skipped],['任务约定',d.task?`${d.task.status} · ${d.task.scope} · ${d.task.sha256}`:'未绑定'],['Goal 来源版本',d.task?`${d.task.goal_path} @ ${d.task.goal_sha256}`:'未绑定'],['宿主消费 / 执行','消费未知；未验证执行'],['查询指纹',r.query_sha256]]));
 if(d.task_context)body.append(taskRequirements(d.task_context));
 if(d.fallback_error||d.hook_error||d.retrieval_error||d.skill_error)body.append(el('p',`运行异常：${d.fallback_error||d.hook_error||d.retrieval_error||d.skill_error}`,'warning'));
 for(const h of array(r.hits)){const item=el('article',undefined,'hit');item.append(el('h3',h.title||h.slug),el('p',`${h.artifact_kind==='skill'?'Skill · '+h.skill_id:'Wiki'} · ${h.backend||'未标注后端'} · 相关分 ${h.relevance??'—'}`,'meta'));
 if(h.source_path&&h.source_path.startsWith('wiki/')){const link=el('a',h.source_path,'path');link.href='/api/mail/wiki-page?'+new URLSearchParams({path:h.source_path});link.target='_blank';link.rel='noopener noreferrer';item.append(link,el('p','打开当前文件；它可能已与该历史版本不同。','meta'));}
 if(h.score_components?.node)item.append(el('p','最佳匹配节点：'+JSON.stringify(h.score_components.node),'meta'));
 item.append(el('p','来源 SHA256：'+(h.source_sha256||'未记录'),'meta'));if(h.skill_version)item.append(el('p','Skill 版本：'+h.skill_version,'meta'));
 const emission=array(r.emitted).find(e=>e.slug===h.slug);item.append(el('p',emission?`Hook 输出：${emission.content}；消费未知`:'此记录未证明 Hook 输出','meta'));
 if(h.load_command)item.append(el('code',h.load_command));if(array(h.options).length){const options=el('details');options.append(el('summary','历史判断与候选方案（资料，不授予权限）'),el('pre',JSON.stringify(h.options,null,2)));item.append(options);}body.append(item);}
 card.append(body);$('records').append(card);}
}
async function refresh(){$('refresh').disabled=true;$('status').textContent='正在读取本地记录…';try{const response=await fetch('/api/retrieval/debug',{cache:'no-store'});if(!response.ok)throw new Error('HTTP '+response.status);const next=await response.json();if(!Array.isArray(next.records))throw new Error('记录格式不正确');data=next;$('total').textContent=data.records.length;$('emitted').textContent=data.records.filter(r=>r.stage==='hook_emitted').length;$('degraded').textContent=data.records.filter(r=>r.diagnostics?.fallback_reason||r.diagnostics?.experimental).length;$('deploymentsCount').textContent=array(data.deployments).length;$('deployments').replaceChildren();for(const d of array(data.deployments))$('deployments').append(el('div',`${d.host_skill} · ${d.version} · ${d.loaded_at}`,'deployment'));if(!array(data.deployments).length)$('deployments').append(el('p',data.deployment_error||'尚无受管 Skill 部署回执。','meta'));render();}catch(error){$('status').textContent=`读取失败：${error.message}。可点击刷新重试；已显示的记录保留。`;}finally{$('refresh').disabled=false;}}
$('refresh').addEventListener('click',refresh);for(const id of ['filter','stage','backend'])$(id).addEventListener('input',render);refresh();

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
