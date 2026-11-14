const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const helpers=import('data:text/javascript;base64,'+Buffer.from(fs.readFileSync(
  path.join(__dirname,'../../assets/mail-web/studio/graph-text.js'),'utf8',
)).toString('base64'));

test('real Wiki metadata keeps the complete authored title rather than an 18-character prefix',async()=>{
  const {labelText,wrapLabel}=await helpers;
  const title='OKS 明确要求真实接入时，先验收已授权的真实路径';
  const node={kind:'wiki',title,metadata:{title},summary:'在 OKS 产品工作中，用户明确要求真实接入时，先核对真实工作目录。'};
  assert.equal(labelText(node),title);
  const lines=wrapLabel(labelText(node),14);
  assert.ok(lines.length>=2 && lines.length<=3);
  assert.equal(lines.join('').replace(/\s/g,''),title.replace(/\s/g,''));
  assert.equal(node.title,title);
});

test('real Raw paragraph metadata yields an existing first sentence, without an AI summary',async()=>{
  const {labelText}=await helpers;
  const paragraph='我会沿用现有 Raw、草稿审核和查询链路，补上采集接入。当前发现两处关键缺口：普通阅读和讨论还不会自动沉淀；任务执行记录也没有完整呈现在讨论页。本轮会分别补齐，并明确显示采集来源、处理结果和失败原因。';
  const node={kind:'raw',title:paragraph,summary:paragraph,body:'',metadata:{schema_version:'raw-multimodal/v0.2'}};
  const before=JSON.stringify(node);
  assert.equal(labelText(node),'我会沿用现有 Raw、草稿审核和查询链路，补上采集接入。');
  assert.equal(JSON.stringify(node),before);
});

test('dense source captions use two lines without changing their complete document title',async()=>{
  const {labelText,wrapLabel}=await helpers;
  const title='来源记录保留完整的原文名称，同时在密集图谱中提供可扫读的两行摘要标题与清晰的关联节点信息。';
  const node={kind:'raw',title};
  const caption=wrapLabel(labelText(node),16,2);
  assert.equal(caption.length,2);
  assert.ok(caption[1].endsWith('…'));
  assert.ok(caption.every(line=>Array.from(line).length<=16));
  assert.equal(labelText(node),title);
  assert.equal(node.title,title);
});

test('the actual unavailable-summary placeholder never becomes a node caption',async()=>{
  const {labelText}=await helpers;
  const title='#97 的问题已复现：Windows 换行差异影响了内容去重，所需修复原本在后面的 Skill 层。我已把它提前放到 #97，并重基后续分支，相关 90 项测试通过；最终代码树未变，只调整了修复所属…';
  assert.equal(labelText({kind:'raw',title,summary:'这份知识还没有可显示的摘要，打开详情查看原文。'}),
    '#97 的问题已复现：Windows 换行差异影响了内容去重，所需修复原本在后面的 Skill 层。');
});

test('frontmatter and Markdown headings supply real names while markup is removed',async()=>{
  const {labelText}=await helpers;
  assert.equal(labelText({text:'---\ntitle: "**TCP** 与 [重试](https://example.test)"\nstatus: active\n---\n# Another heading'}),'TCP 与 重试');
  assert.equal(labelText({text:'---\nstatus: draft\n---\n```md\n# An example, not the title\n```\n# `oks recall` 的边界\nBody.'}),'oks recall 的边界');
  assert.equal(labelText({text:"---\ntitle: >\n  真实标题\n  的第二行\n---\nBody."}),'真实标题 的第二行');
});

test('an existing summary or the first body sentence precedes a file-stem fallback',async()=>{
  const {labelText}=await helpers;
  assert.equal(labelText({path:'wiki/transport-note.md',title:'transport note',summary:'**TCP** 需要明确重试边界。下一句不属于标签。'}),'TCP 需要明确重试边界。');
  assert.equal(labelText({path:'wiki/new-note.md',body:'---\nstatus: draft\n---\n> quoted example\n\n```js\nthrow new Error();\n```\n\n- 原始正文的第一句。后续说明。'}),'原始正文的第一句。');
  assert.equal(labelText({path:'raw/100%-source.md'}),'100% source');
  assert.equal(labelText({title:'未命名知识',path:'wiki/trusted-file-name.md'}),'trusted file name');
});

test('ordinary long names wrap across three lines and only extreme overflow gets an ellipsis',async()=>{
  const {wrapLabel}=await helpers;
  const ordinary='每个节点保留真实文档标题并在原图谱中分行显示';
  assert.equal(wrapLabel(ordinary,10).join(''),ordinary);
  const long='这是极长的原文摘要内容'.repeat(20);
  const result=wrapLabel(long,18);
  assert.equal(result.length,3);
  assert.ok(result[2].endsWith('…'));
  assert.ok(result.every(line=>Array.from(line).length<=18));
  assert.equal(long,'这是极长的原文摘要内容'.repeat(20));
});

test('wrapping never splits surrogate pairs and respects English word boundaries where available',async()=>{
  const {wrapLabel}=await helpers;
  const lines=wrapLabel('知识🙂节点🙂标题保持完整字符并换行',8);
  assert.ok(lines.every(line=>!/[\uD800-\uDBFF]$/.test(line) && !/^[\uDC00-\uDFFF]/.test(line)));
  assert.deepEqual(wrapLabel('A short title for knowledge',14),['A short title','for knowledge']);
});

const overlaps=(a,b)=>a.left<b.right && a.right>b.left && a.top<b.bottom && a.bottom>b.top;
const rectangle=(label,position)=>({left:position.x-label.width/2,right:position.x+label.width/2,
  top:position.y,bottom:position.y+label.height});

test('caption y is the top of its measured multi-line box and the initial preference is above its node',async()=>{
  const {placeCaptions}=await helpers;
  const label={id:'one',x:200,y:200,width:120,height:42,priority:5};
  const positions=placeCaptions([label],500,400);
  assert.deepEqual(positions.get('one'),{x:200,y:144});
});

test('expanded collision search labels all 21 visible nodes using real multi-line heights',async()=>{
  const {placeCaptions}=await helpers;
  const nodes=Array.from({length:21},(_,index)=>({id:String(index),x:430+(index%3)*12,
    y:300+Math.floor(index/3)*9,width:112,height:36,priority:21-index}));
  const obstacles=[{left:760,right:900,top:520,bottom:700},
    ...nodes.map(node=>({left:node.x-9,right:node.x+9,top:node.y-9,bottom:node.y+9}))];
  const before=JSON.stringify({nodes,obstacles});
  const positions=placeCaptions(nodes,900,700,obstacles);
  assert.equal(positions.size,21);
  const boxes=nodes.map(node=>rectangle(node,positions.get(node.id)));
  for(const [index,box] of boxes.entries()) {
    assert.ok(box.left>=0 && box.right<=900 && box.top>=0 && box.bottom<=700);
    assert.ok(!obstacles.some(obstacle=>overlaps(box,obstacle)));
    assert.ok(!boxes.slice(index+1).some(other=>overlaps(box,other)));
  }
  assert.equal(JSON.stringify({nodes,obstacles}),before);
});

test('cached relative caption positions stay stable until a real obstacle blocks them',async()=>{
  const {placeCaptions}=await helpers;
  const label={id:'one',x:150,y:150,width:100,height:30,priority:1};
  const previous=new Map([['one',{dx:10,dy:-80}]]);
  const first=placeCaptions([label],600,400,[],previous).get('one');
  assert.deepEqual(first,{x:160,y:70});
  const obstacle={left:100,right:220,top:50,bottom:110};
  const moved=placeCaptions([label],600,400,[obstacle],previous).get('one');
  assert.ok(!overlaps(rectangle(label,moved),obstacle));
  assert.deepEqual(previous.get('one'),{dx:10,dy:-80});
});

test('physically insufficient space keeps a finite fallback for every visible node instead of hiding captions',async()=>{
  const {placeCaptions}=await helpers;
  const labels=Array.from({length:4},(_,index)=>({id:String(index),x:30+index,y:25,width:120,height:70,priority:0}));
  const positions=placeCaptions(labels,90,50);
  assert.equal(positions.size,4);
  for(const value of positions.values()) assert.ok(Number.isFinite(value.x) && Number.isFinite(value.y));
  assert.equal(placeCaptions([{id:'offscreen',x:-30,y:20,width:30,height:14}],90,50).size,0);
});
