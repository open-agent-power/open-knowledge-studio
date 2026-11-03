'use strict';
// One cell is a count of retained observations about an exact source version.
// Reads are independent observations: they are never guessed from retrieval hits.
(function(root){
  const columns=[['retrieved','查到'],['emitted','输出上下文'],['read','读取内容'],['used','关联产物']];
  const array=value=>Array.isArray(value)?value:[];
  function build(data,{taskId='',query=''}={}){
    const rows=new Map(),seen=new Set();let ignored=0;
    const add=(source,phase,event)=>{
      const path=source?.source_path,sha=source?.source_sha256;
      if(typeof path!=='string'||!path.startsWith('wiki/')||typeof sha!=='string'||!/^[a-f0-9]{64}$/.test(sha)){ignored++;return;}
      const key=path+'@'+sha,id=key+'|'+phase+'|'+event.id;
      if(seen.has(id))return;seen.add(id);
      if(!rows.has(key))rows.set(key,{key,path,sha,title:source.title||path.split('/').pop(),kind:source.artifact_kind==='skill'?'Skill':'Wiki',events:Object.fromEntries(columns.map(([key])=>[key,[]]))});
      rows.get(key).events[phase].push(event);
    };
    for(const record of array(data.records)){
      const task=record.diagnostics?.task?.scope||record.diagnostics?.continuation?.task_id||'';
      if(taskId&&task!==taskId&&!array(record.usage).some(use=>use.task_id===taskId))continue;
      const hits=array(record.hits),event={id:record.id,recordId:record.id,at:record.at,taskId:task,kind:'query'};
      for(const hit of hits){
        add(hit,'retrieved',event);
        if(record.stage==='hook_emitted'&&array(record.emitted).some(item=>item.slug===hit.slug&&(!item.version||item.version===hit.source_sha256||item.version===hit.skill_version)))add(hit,'emitted',{...event,kind:'hook_output'});
      }
      for(const load of array(record.loads)){
        const hit=hits.find(hit=>hit.source_path===load.source_path&&hit.source_sha256===load.source_sha256);
        if(hit)add(hit,'read',{...event,id:record.id+'|'+load.source_path,at:load.at,kind:'cli_return'});
      }
      for(const use of array(record.usage)){
        if(taskId&&use.task_id!==taskId)continue;
        const hit=hits.find(hit=>hit.source_path===use.source_path&&hit.source_sha256===use.source_sha256);
        if(hit)add(hit,'used',{id:record.id+'|'+use.task_id+'|'+use.revision,recordId:record.id,taskId:use.task_id,revision:use.revision,kind:'caller_reported',artifacts:array(use.artifacts)});
      }
    }
    for(const read of array(data.native_reads)){
      if(taskId&&read.task_id!==taskId)continue;
      add(read,'read',{id:read.run_id+'|'+read.event_id,at:read.observed_at,taskId:read.task_id,revision:read.revision,runId:read.run_id,host:read.host,kind:'host_read'});
    }
    for(const use of array(data.native_uses)){
      if(taskId&&use.task_id!==taskId)continue;
      add(use,'used',{id:use.event_id,taskId:use.task_id,revision:use.revision,kind:'output_citation',artifacts:use.artifact?[use.artifact]:[]});
    }
    const all=[...rows.values()].map(row=>({...row,total:Object.values(row.events).reduce((sum,events)=>sum+events.length,0)}));
    const needle=query.trim().toLocaleLowerCase();
    const filtered=all.filter(row=>!needle||[row.title,row.path].some(value=>value.toLocaleLowerCase().includes(needle))).sort((a,b)=>b.total-a.total||a.path.localeCompare(b.path)||a.sha.localeCompare(b.sha));
    return {rows:filtered.slice(0,40),sourceCount:all.length,hidden:Math.max(0,filtered.length-40),ignored,columns,maximum:Math.max(1,...all.flatMap(row=>Object.values(row.events).map(events=>events.length)))};
  }
  const api={build,columns};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(root)root.OksKnowledgeHeatmap=api;
})(typeof window==='undefined'?null:window);
