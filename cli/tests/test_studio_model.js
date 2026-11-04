'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const model=require('../../assets/mail-web/studio-model.js');
const fs=require('node:fs'),path=require('node:path');
async function standaloneModule(name){
 const source=fs.readFileSync(path.join(__dirname,'../../assets/mail-web/studio',name),'utf8');
 return import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
}
test('modular transport binds writes to the current instance and respects read-only mode',async()=>{
 const {createStudioApi}=await standaloneModule('api.js');
 let context={knowledge_base:'/kb/one',local_edit:false},sent=null;
 const api=createStudioApi({request:async(url,options)=>{sent={url,options};return{};}},()=>context);
 await assert.rejects(api.post('/api/studio/file',{text:'# Goal'}));
 assert.equal(sent,null);
 context={knowledge_base:'/kb/two',local_edit:true};
 await api.post('/api/studio/file',{text:'# Goal',expected_knowledge_base:'/wrong'});
 assert.equal(JSON.parse(sent.options.body).expected_knowledge_base,'/kb/two');
 assert.equal(sent.options.headers['Content-Type'],'application/json');
});
test('each Studio session owns its state without persisting knowledge copies',async()=>{
 const {createStudioState}=await standaloneModule('state.js');
 const first=createStudioState(),second=createStudioState();
 first.folds.add(3);first.selected='goal/one.md';
 assert.equal(second.folds.size,0);assert.equal(second.selected,'');
 assert.equal(first.view,null);assert.equal(first.context,null);
});
test('outline editing preserves frontmatter, line endings, references and notes',()=>{
 const text='---\r\ntitle: A\r\n---\r\n# Goal\r\n## Child\r\n- [ ] Step\r\n\r\n[[wiki/source]]\r\n';
 const changed=model.toggle(text,{kind:'heading',line:4},true);
 assert.equal(changed,text.replace('## Child','## [x] Child'));
 assert.equal(model.rename(changed,{kind:'heading',line:4},'Next'),changed.replace('Child','Next'));
 assert.equal(model.toggle(text,{kind:'task',line:5},true),text.replace('- [ ] Step','- [x] Step'));
 assert.throws(()=>model.toggle(text,{kind:'note',line:7},true));
 assert.throws(()=>model.toggle(text,{kind:'task',line:3},true));
});
test('expansion preserves source identity and never invents AI adoption or task completion',()=>{
 const view={nodes:[{id:'goal/a.md',type:'goal'}],edges:[],files:{'goal/a.md':{kind:'goal',outline:[
  {line:0,kind:'heading',level:1,text:'Root',parent:null},
  {line:2,kind:'heading',level:2,text:'Child',parent:0},
  {line:3,kind:'task',level:3,text:'Step',parent:2,checked:false},
  {line:5,kind:'note',level:3,text:'Description',parent:2}]}}};
 assert.equal(model.graph(view).nodes.length,1);
 const expanded=model.graph(view,true);
 assert.equal(expanded.nodes.length,3);
 assert.equal(expanded.edges[1].from,'goal/a.md#line-2');
 assert.equal(expanded.nodes[2].checked,false);
 assert.equal(view.nodes.length,1);
});
test('preview distinguishes budget saturation from monotonic memory decay',async()=>{
 const {memoryScore,budgetCap,changeLabel}=await standaloneModule('formulas.js');
 assert.equal(budgetCap({topn:4,perPage:1000,budget:2500}),2500);
 assert.equal(budgetCap({topn:1,perPage:1000,budget:2500}),1000);
 const input={importance:0.7,lambda:0.014,days:0,access:0};
 assert.ok(Math.abs(memoryScore(input)-0.84)<1e-12);
 assert.ok(memoryScore({...input,days:30})<memoryScore(input));
 assert.equal(memoryScore({...input,lambda:0,days:365}),memoryScore({...input,lambda:0}));
 assert.ok(memoryScore({...input,access:1})>memoryScore(input));
 assert.equal(changeLabel(10,8),'↓ 2');assert.equal(changeLabel(10,10),'—');
});
test('knowledge layers retain draft status and explicit counts without manufacturing adoption',async()=>{
 const {knowledgeTree,projectKnowledge,usageColor}=await standaloneModule('knowledge-model.js');
 const map={domains:[{id:'computing',label:'计算',clusters:[{id:'rl',label:'强化学习',points:[
  {id:'wiki/a.md',path:'wiki/a.md',title:'GRPO',kind:'wiki'},
  {id:'drafts/b.md',path:'drafts/b.md',title:'Reward',kind:'candidate'}]}]}],edges:[{a:'wiki/a.md',b:'drafts/b.md',type:'related'}]};
 const tree=knowledgeTree(map,{entries:[{slug:'a',count:4}]},{skills:[{path:'skill/book/SKILL.md',title:'book'}]});
 assert.equal(tree[0].uses,4);assert.equal(tree[1].children[0].type,'skill');
 assert.equal(projectKnowledge(tree).nodes.length,2);
 const full=projectKnowledge(tree,new Set(),3,'',map.edges);
 assert.equal(full.nodes.find(n=>n.id==='drafts/b.md').pending,true);
 assert.equal(full.nodes.find(n=>n.id==='wiki/a.md').uses,4);
 assert.equal(full.edges.filter(e=>e.type==='related').length,1);
 assert.equal(projectKnowledge(tree,new Set(),1,'',map.edges).edges.length,0);
 assert.equal(usageColor(9,9,true),usageColor(0,9,true));
 assert.notEqual(usageColor(0,9),usageColor(9,9));
});
test('graph search reveals matching evidence and its hierarchy without irrelevant siblings',async()=>{
 const {projectKnowledge}=await standaloneModule('knowledge-model.js');
 const roots=[{id:'d',title:'计算',children:[{id:'c',title:'RL',children:[{id:'a',title:'GRPO'},{id:'b',title:'SFT'}]}]}];
 const found=projectKnowledge(roots,new Set(),1,'GRPO');
 assert.deepEqual(found.nodes.map(n=>n.id),['d','c','a']);
 assert.equal(found.edges.length,2);
 assert.equal(projectKnowledge(roots,new Set(),1,'nothing').nodes.length,0);
});
test('context branches and query hits retain exact source identity',async()=>{
 const {knowledgeTree,mapQueryHits,revealNode,projectKnowledge}=await standaloneModule('knowledge-model.js');
 const roots=knowledgeTree({domains:[]},{entries:[]},{skills:[]},{entries:[
  {id:'profiles/projects/demo.md',path:'profiles/projects/demo.md',title:'Demo',type:'project',group:'profiles/projects'},
  {id:'goal/2026/11/04/demo.md',path:'goal/2026/11/04/demo.md',title:'Task',type:'goal',date:'2026-11-04'}]});
 const ambiguous=mapQueryHits(roots,[{slug:'demo'}]);assert.equal(ambiguous[0].nodeId,null);
 const exact=mapQueryHits(roots,[{source_path:'profiles/projects/demo.md'}]);assert.equal(exact[0].nodeId,'profiles/projects/demo.md');
 const opened=new Set();revealNode(roots,exact[0].nodeId,opened);
 assert.ok(projectKnowledge(roots,opened).nodes.some(n=>n.id===exact[0].nodeId));
 assert.equal(roots.find(n=>n.id==='context:goal').children[0].title,'2026-11-04');
});
test('query projection shows only exact hits and their ancestors',async()=>{
 const {projectQuery}=await standaloneModule('knowledge-model.js');
 const tree=[{id:'root',title:'R',children:[{id:'one',title:'One',children:[{id:'hit',title:'Hit'},{id:'other',title:'Other'}]},{id:'two',title:'Two'}]},{id:'unrelated',title:'U'}];
 const graph=projectQuery(tree,[{nodeId:'hit'}]);
 assert.deepEqual(graph.nodes.map(n=>n.id),['root','one','hit']);
 assert.equal(graph.edges.length,2);
});
