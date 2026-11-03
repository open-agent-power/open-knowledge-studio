'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const heatmap=require('../../assets/mail-web/knowledge-heatmap.js');
const source={slug:'page',title:'写作策略',source_path:'wiki/a.md',source_sha256:'a'.repeat(64)};
test('hits, output, CLI reads and host reads remain distinct and source-versioned',()=>{
 const record={id:'query',stage:'hook_emitted',hits:[source,source],emitted:[{slug:'page',version:source.source_sha256}],loads:[],usage:[]};
 const read={...source,event_id:'read',run_id:'run',task_id:'task',observed_at:'2026-10-29T12:00:00Z'};
 const result=heatmap.build({records:[record],native_reads:[read,read,{...read,event_id:'read2',source_sha256:'b'.repeat(64)}]});
 assert.equal(result.rows.length,2);
 const row=result.rows.find(row=>row.sha===source.source_sha256);
 assert.equal(row.events.retrieved.length,1);assert.equal(row.events.emitted.length,1);assert.equal(row.events.read.length,1);assert.equal(row.events.used.length,0);
 assert.equal(result.rows.find(row=>row.sha!==source.source_sha256).events.retrieved.length,0);
});
test('task filtering keeps exact task associations and never fabricates a usage time',()=>{
 const data={records:[{id:'q',hits:[source],diagnostics:{task:{scope:'one'}},usage:[{...source,task_id:'one',revision:2,artifacts:[{path:'out.md'}]}]}],native_reads:[{...source,event_id:'r',run_id:'run',task_id:'two'}]};
 const row=heatmap.build(data,{taskId:'one'}).rows[0];assert.equal(row.events.used.length,1);assert.equal(row.events.read.length,0);assert.equal(row.events.used[0].at,undefined);
 assert.equal(heatmap.build(data,{taskId:'absent'}).rows.length,0);
});
test('missing versions, outside paths and empty data do not turn into measurements',()=>{
 assert.equal(heatmap.build({}).rows.length,0);
 const result=heatmap.build({records:[{id:'q',hits:[{...source,source_path:'../secret.md'},{...source,source_sha256:null}]}]});
 assert.equal(result.rows.length,0);assert.equal(result.ignored,2);
});
test('explicit output citation joins its exact source version without inventing a read',()=>{
 const row=heatmap.build({native_uses:[{...source,event_id:'citation',task_id:'task',revision:4,artifact:{path:'outputs/run/a.md',sha256:'b'.repeat(64)}}]},{taskId:'task'}).rows[0];
 assert.equal(row.events.used.length,1);assert.equal(row.events.read.length,0);assert.equal(row.events.used[0].kind,'output_citation');assert.equal(row.events.used[0].artifacts[0].path,'outputs/run/a.md');
});
