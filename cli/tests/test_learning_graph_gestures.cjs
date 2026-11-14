const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {Element,pointer}=require('./test_learning_graph.cjs');
const root=path.resolve(__dirname,'../..');
const readModule=file=>import('data:text/javascript;base64,'+Buffer.from(fs.readFileSync(file,'utf8')).toString('base64'));
const helpers=Promise.all([
  readModule(path.join(root,'assets/mail-web/studio/knowledge-model.js')),
  readModule(path.join(root,'assets/mail-web/studio/graph-text.js')),
  readModule(path.join(root,'assets/mail-web/studio/graph-camera.js')),
  readModule(path.join(root,'assets/mail-web/studio/graph-3d.js')),
  readModule(path.join(root,'assets/mail-web/vendor/graph-engine/position-smoothing.js')),
]).then(modules=>Object.assign({},...modules));
const source=fs.readFileSync(path.join(root,'assets/mail-web/studio/learning-graph.js'),'utf8');
const {createForceLayout}=require(path.join(root,'assets/mail-web/force-layout.js'));
const translation=node=>{
  const [,x,y]=node.getAttribute('transform').match(/translate\(([-+\d.e]+),([-+\d.e]+)\)/);
  return{x:Number(x),y:Number(y)};
};
const close=(actual,expected,tolerance=.02)=>assert.ok(Math.abs(actual-expected)<=tolerance,`${actual} should be within ${tolerance} of ${expected}`);

async function fixture(count=3) {
  const math=await helpers,frames=new Map(),microtasks=[],cameras=[],layouts=[],workers=[],observers=[];
  let nextFrame=0,time=0,dispose;
  const create3DLayout=(items,links,options)=>{
    const nodes=items.map((node,index)=>({...node,z:node.z ?? index*30}));
    const index=new Map(nodes.map(node=>[node.id,node]));
    const worker={nodes,edges:links.map(edge=>({...edge,source:index.get(edge.from),target:index.get(edge.to)})),
      destroyed:0,step:()=>false,reheat(){},dragStart(){},dragEnd(){},
      dragMove(id,x,y,z){Object.assign(index.get(id),{x,y,z});},
      destroy(){this.destroyed++;},options};
    workers.push(worker);return worker;
  };
  const document={createElementNS:(_,tag)=>new Element(tag),createElement:tag=>{
    const node=new Element(tag);
    if(tag==='canvas')node.getContext=()=>({font:'',measureText:text=>({width:Array.from(text).reduce((sum,char)=>sum+(/[\u2e80-\uffff]/u.test(char)?13:7),0)})});
    return node;
  }};
  const context=vm.createContext({...math,create3DLayout,document,
    createCamera:()=>{const camera=math.createCamera();cameras.push(camera);return camera;},
    window:{matchMedia:()=>({matches:false}),createForceLayout:(...args)=>{const layout=createForceLayout(...args);layouts.push(layout);return layout;}},
    requestAnimationFrame:callback=>{const id=++nextFrame;frames.set(id,callback);return id;},
    cancelAnimationFrame:id=>frames.delete(id),queueMicrotask:callback=>microtasks.push(callback),
    performance:{now:()=>time},
    ResizeObserver:class{constructor(callback){this.callback=callback;observers.push(this);}observe(){}disconnect(){this.disconnected=true;}},
  });
  vm.runInContext(source.replace(/^import[^\n]*\r?\n/gm,'').replace(/export function /g,'function ')+'\nthis.render=drawLearningGraph;',context);
  const svg=new Element('svg'),stage=new Element('div'),tools=new Element('div');
  stage.classList.add('knowledge-stage');tools.classList.add('graph-tools');
  svg.clientWidth=900;svg.clientHeight=600;stage.append(svg,tools);
  tools.bounds={left:650,right:890,top:550,bottom:590,width:240,height:40};
  const controls=new Element('div'),reset=new Element('button');
  controls.classList.add('knowledge-controls');controls.bounds={left:8,right:430,top:8,bottom:65,width:422,height:57};
  reset.textContent='重置';controls.append(reset);stage.append(controls);
  const nodes=Array.from({length:count},(_,index)=>({id:'wiki/'+index,path:'wiki/'+index+'.md',type:'wiki',kind:'wiki',
    title:'真实知识条目 '+(index+1)+' 的 Markdown 标题与来源保持可读',uses:0}));
  const edges=nodes.slice(1).map((node,index)=>({from:nodes[index].id,to:node.id,type:'source'}));
  const selections=[],lassos=[];
  const options={insetTop:80,insetBottom:30,button:(label,action)=>{const node=new Element('button');node.textContent=label;node.onclick=action;return node;},
    nodeFill:()=> '#aabbcc',nodeRadius:()=>18,nodeDashed:()=>false,onLasso:rows=>lassos.push(Array.from(rows,node=>node.id))};
  const render=(extra={})=>{dispose=context.render(svg,nodes,edges,tools,node=>selections.push(node.id),{...options,...extra});return dispose;};
  const h={svg,stage,tools,reset,nodes,edges,selections,lassos,frames,microtasks,cameras,layouts,workers,observers,
    group:id=>svg.querySelectorAll('.studio-node').find(node=>node.dataset.id===id),
    point:id=>translation(h.group(id)),
    emit:(type,target,x,y,extra={})=>{time+=16;svg.dispatch(type,pointer(type,target,x,y,{timeStamp:time,...extra}));},
    dispose:()=>dispose(),
    redraw:extra=>{dispose();return render(extra);},
    step:()=>{const next=frames.entries().next().value;if(!next)return false;frames.delete(next[0]);time+=16;next[1](time);return true;},
    flush:limit=>{for(let i=0;i<(limit ?? 300)&&frames.size;i++)h.step();},
    micro:()=>{while(microtasks.length)microtasks.shift()();},
  };
  render();h.flush(3);return h;
}

test('every one of 21 visible nodes has its actual multiline caption',async()=>{
  const h=await fixture(21);
  try {
    assert.equal(h.svg.querySelectorAll('.studio-node').length,21);
    for(const node of h.nodes) {
      const group=h.group(node.id),point=h.point(node.id),caption=group.children[3];
      assert.ok(point.x>=0&&point.x<=900&&point.y>=0&&point.y<=600);
      assert.notEqual(caption.style.display,'none');
      assert.ok(caption.querySelectorAll('tspan').length>=2);
      assert.equal(group.children[4].textContent,node.title);
    }
  } finally {h.dispose();h.micro();}
});

test('switching a large graph to 3D and fitting it never loses all nodes at the near plane',async()=>{
  const h=await fixture(106);
  try {
    h.tools.querySelectorAll('button').find(button=>button.textContent==='3D').onclick();
    const worker=h.workers.at(-1);
    worker.nodes.forEach((node,i)=>Object.assign(node,{
      x:5000+Math.cos(i*2.4)*3000,y:-3500+Math.sin(i*2.4)*2400,z:(i/105-.5)*6000,
    }));
    worker.options.onTick('tick');h.flush();
    assert.ok(h.nodes.some(node=>h.group(node.id).style.display!=='none'));
    h.tools.querySelectorAll('button').find(button=>button.getAttribute('aria-label')==='适配画布').onclick();
    h.flush();
    for(const node of h.nodes) {
      assert.notEqual(h.group(node.id).style.display,'none');
      const point=h.point(node.id);
      assert.ok(point.x>=0&&point.x<=900&&point.y>=80&&point.y<=570);
    }
  } finally {h.dispose();h.micro();}
});

test('source captions compact only during another node drag and restore on release or cancellation without losing the full title',async()=>{
  const h=await fixture();
  try {
    const sourceNode=h.nodes[2];
    Object.assign(sourceNode,{kind:'raw',type:'raw',path:'raw/long-source.md',
      title:'来源材料中的完整长标题保留原文含义与出处，拖动时只临时收起显示行，结束后恢复阅读。'.repeat(3)});
    const originalData=JSON.stringify(sourceNode);
    h.redraw();h.micro();h.flush();
    const group=h.group(sourceNode.id),caption=group.querySelectorAll('text')[0],tooltip=group.querySelectorAll('title')[0];
    const visibleLines=()=>caption.querySelectorAll('tspan').filter(span=>span.style.display!=='none').map(span=>span.textContent);
    const originalLines=visibleLines();
    const verifyFullTitle=()=>{
      assert.equal(tooltip.textContent,sourceNode.title);
      assert.equal(group.getAttribute('aria-label'),sourceNode.title);
      assert.equal(JSON.stringify(sourceNode),originalData);
    };
    assert.equal(caption.querySelectorAll('tspan').length,2,'a long source title should use at most two lines at rest');
    assert.equal(originalLines.length,2);verifyFullTitle();
    for(const ending of ['pointerup','pointercancel']) {
      const id=h.nodes[0].id,target=h.group(id).children[1],start=h.point(id);
      h.emit('pointerdown',target,start.x,start.y);h.step();
      assert.deepEqual(visibleLines(),originalLines,'pressing alone must keep the source caption expanded');
      h.emit('pointermove',target,start.x+28,start.y+18);h.step();
      assert.equal(group.classList.contains('graph-active'),false);
      assert.notEqual(group.style.display,'none');assert.notEqual(caption.style.display,'none');
      assert.equal(visibleLines().length,1,'an unfocused source caption should temporarily use one line while dragging');
      assert.ok(visibleLines()[0].endsWith('…'));verifyFullTitle();
      h.emit(ending,target,start.x+28,start.y+18);h.step();
      assert.deepEqual(visibleLines(),originalLines,`${ending} should restore the complete two-line caption`);
      verifyFullTitle();h.flush();
    }
    assert.equal(h.selections.length,0);
  } finally {h.dispose();h.micro();}
});

test('wheel zoom keeps the node beneath the cursor at its screen anchor',async()=>{
  const h=await fixture();
  try {
    const id=h.nodes[0].id,point=h.point(id),scale=h.cameras[0].scale;
    h.emit('wheel',h.group(id).children[1],point.x,point.y,{deltaY:-200});
    for(let frame=0;frame<55;frame++) {
      h.step();const current=h.point(id);close(current.x,point.x);close(current.y,point.y);
    }
    assert.ok(h.cameras[0].scale>scale);
  } finally {h.dispose();h.micro();}
});

test('dragging a caption uses pointer delta without teleport or selection, and redraw keeps the point and camera',async()=>{
  const h=await fixture();
  try {
    h.emit('pointerdown',h.svg,100,100);h.emit('pointermove',h.svg,145,125);h.emit('pointerup',h.svg,145,125);
    h.flush();
    const id=h.nodes[1].id,group=h.group(id),start=h.point(id),caption=group.children[3];
    const offset=translation(caption),pointerStart={x:start.x+offset.x,y:start.y+offset.y-6};
    h.emit('pointerdown',caption.children[0],pointerStart.x,pointerStart.y);h.step();
    close(h.point(id).x,start.x);close(h.point(id).y,start.y);
    h.emit('pointermove',caption.children[0],pointerStart.x+64,pointerStart.y+38);h.step();
    close(h.point(id).x,start.x+64);close(h.point(id).y,start.y+38);
    h.emit('pointerup',caption.children[0],pointerStart.x+64,pointerStart.y+38);h.flush();
    assert.equal(h.selections.length,0);
    const moved=h.point(id),camera={...h.cameras[0]};
    h.redraw({entry:id});h.micro();h.flush();
    assert.equal(h.cameras.length,1);
    close(h.point(id).x,moved.x);close(h.point(id).y,moved.y);
    close(h.cameras[0].x,camera.x);close(h.cameras[0].y,camera.y);close(h.cameras[0].scale,camera.scale);
  } finally {h.dispose();h.micro();}
});

test('a linked neighbor visibly follows a held drag even after a long pause',async()=>{
  const h=await fixture(3);
  try {
    h.flush();
    const id=h.nodes[0].id,neighbor=h.nodes[1].id,target=h.group(id).children[1];
    const start=h.point(id),before=h.point(neighbor),length=Math.hypot(start.x-before.x,start.y-before.y);
    const direction={x:(start.x-before.x)/length,y:(start.y-before.y)/length};
    const move=distance=>h.emit('pointermove',target,start.x+direction.x*distance,start.y+direction.y*distance);
    const response=(a,b)=>(b.x-a.x)*direction.x+(b.y-a.y)*direction.y;
    h.emit('pointerdown',target,start.x,start.y);move(75);h.flush(45);
    assert.ok(response(before,h.point(neighbor))>8,'the directly linked node should visibly follow the drag');
    h.flush(480);
    const paused=h.point(neighbor);
    move(145);h.flush(45);
    assert.ok(response(paused,h.point(neighbor))>8,'dragging again while still held must keep the linked node responsive');
    const held=h.point(id);
    close(held.x,start.x+direction.x*145);close(held.y,start.y+direction.y*145);
    h.emit('pointerup',target,held.x,held.y);
    assert.equal(h.selections.length,0);
  } finally {h.dispose();h.micro();}
});

test('a drop releases smoothly and remains responsive to a later neighbor drag after redraw',async()=>{
  const h=await fixture(3);
  try {
    h.flush();
    const id=h.nodes[0].id,neighbor=h.nodes[1].id,target=h.group(id).children[1],start=h.point(id);
    h.emit('pointerdown',target,start.x,start.y);
    h.emit('pointermove',target,start.x+82,start.y+34);h.step();
    const drop=h.point(id);
    h.emit('pointerup',target,start.x+82,start.y+34);
    close(h.point(id).x,drop.x);close(h.point(id).y,drop.y);
    let previous=drop,maxStep=0,maxTravel=0;
    for(let frame=0;frame<120;frame++) {
      h.step();const current=h.point(id);
      maxStep=Math.max(maxStep,Math.hypot(current.x-previous.x,current.y-previous.y));
      maxTravel=Math.max(maxTravel,Math.hypot(current.x-drop.x,current.y-drop.y));previous=current;
    }
    assert.ok(maxStep<10,`release should settle smoothly rather than jump (${maxStep}px in one frame)`);
    assert.ok(maxTravel>3&&maxTravel<120,`the released node should recover within a bounded distance (${maxTravel}px)`);
    h.flush();h.redraw();h.micro();h.flush();
    const before=h.point(id),other=h.point(neighbor),otherTarget=h.group(neighbor).children[1];
    const length=Math.hypot(other.x-before.x,other.y-before.y),dx=(other.x-before.x)/length,dy=(other.y-before.y)/length;
    h.emit('pointerdown',otherTarget,other.x,other.y);
    h.emit('pointermove',otherTarget,other.x+dx*100,other.y+dy*100);h.flush(60);
    const followed=h.point(id),response=(followed.x-before.x)*dx+(followed.y-before.y)*dy;
    assert.ok(response>8,'a previously dropped node must follow its neighbor instead of remaining permanently pinned');
    h.emit('pointerup',otherTarget,other.x+dx*100,other.y+dy*100);
    assert.equal(h.selections.length,0);
  } finally {h.dispose();h.micro();}
});

test('hover and multi-selection give active nodes and direct neighbors distinct emphasis without hiding other titles',async()=>{
  const h=await fixture(5);
  try {
    const id=h.nodes[0].id,neighbor=h.nodes[1].id,other=h.nodes[3].id;
    const point=h.point(id),target=h.group(id).children[1];
    const verify=()=>{
      const active=h.group(id),related=h.group(neighbor),unrelated=h.group(other);
      assert.ok(active.classList.contains('graph-active'));
      assert.ok(related.classList.contains('graph-related'));
      assert.equal(related.classList.contains('graph-active'),false);
      assert.equal(unrelated.classList.contains('graph-active'),false);
      assert.equal(unrelated.classList.contains('graph-related'),false);
      const halo=active.querySelectorAll('.graph-node-halo')[0];
      assert.ok(halo,'an active node needs a visible outer outline');
      assert.ok(Number(halo.getAttribute('r'))>Number(active.children[1].getAttribute('r')));
      assert.ok(Number(halo.style.opacity ?? halo.getAttribute('opacity'))>=.5);
      for(const group of [active,related,unrelated]) {
        const caption=group.querySelectorAll('text')[0];
        assert.notEqual(caption.style.display,'none');
        assert.ok(caption.querySelectorAll('tspan').length>=2);
      }
      const backgroundCaption=unrelated.querySelectorAll('text')[0],backgroundOpacity=Number(backgroundCaption.style.opacity);
      assert.ok(backgroundOpacity>=.6&&backgroundOpacity<.9,'unrelated titles should dim moderately and remain readable');
      assert.ok(Number(active.querySelectorAll('text')[0].style.opacity)>backgroundOpacity);
      assert.ok(Number(related.querySelectorAll('text')[0].style.opacity)>backgroundOpacity);
      assert.ok(Number(unrelated.children[1].style.opacity)<Number(related.children[1].style.opacity));
    };
    h.emit('pointermove',target,point.x,point.y);h.flush(2);verify();
    h.emit('pointerdown',target,point.x,point.y,{ctrlKey:true});
    h.emit('pointerup',target,point.x,point.y,{ctrlKey:true});
    h.emit('pointerleave',h.svg,point.x,point.y);h.flush(2);verify();
    assert.deepEqual(h.lassos,[[id]]);
    assert.equal(h.selections.length,0);
  } finally {h.dispose();h.micro();}
});

test('Ctrl clicks toggle the original lasso callback without opening document details',async()=>{
  const h=await fixture();
  try {
    for(const id of [h.nodes[0].id,h.nodes[1].id,h.nodes[0].id]) {
      const point=h.point(id),target=h.group(id).children[1];
      h.emit('pointerdown',target,point.x,point.y,{ctrlKey:true});
      h.emit('pointerup',target,point.x,point.y,{ctrlKey:true});h.flush(2);
    }
    assert.equal(h.selections.length,0);
    assert.deepEqual(h.lassos,[[h.nodes[0].id],[h.nodes[0].id,h.nodes[1].id],[h.nodes[1].id]]);
    assert.equal(h.svg.dataset.highlighted,'1');
  } finally {h.dispose();h.micro();}
});

test('the existing reset button restores the layout after an intentional pan',async()=>{
  const h=await fixture();
  try {
    const initial={...h.cameras[0]};
    h.emit('pointerdown',h.svg,100,100);h.emit('pointermove',h.svg,200,160);h.emit('pointerup',h.svg,200,160);h.flush();
    assert.ok(Math.abs(h.cameras[0].x-initial.x)>1);
    h.stage.dispatch('click',{target:h.reset});h.redraw();h.micro();h.flush();
    close(h.cameras[0].x,initial.x);close(h.cameras[0].y,initial.y);close(h.cameras[0].scale,initial.scale);
  } finally {h.dispose();h.micro();}
});

test('a disposer from before a 3D mode switch cleans the current handlers and worker',async()=>{
  const h=await fixture();
  h.tools.children.find(node=>node.textContent==='3D').onclick();h.flush(2);
  assert.equal(h.workers.length,1);
  assert.equal(h.svg.listenerSets.get('pointerdown').size,1);
  h.dispose();
  assert.equal(h.svg.listeners.size,0);
  assert.equal(h.stage.listeners.size,0);
  assert.equal(h.frames.size,0);
  assert.equal(h.workers[0].destroyed,0);
  h.micro();
  assert.equal(h.workers[0].destroyed,1);
  assert.ok(h.observers.every(observer=>observer.disconnected));
});

test('synchronous repaint takes ownership before the previous queued worker teardown',async()=>{
  const h=await fixture();
  try {
    h.tools.children.find(node=>node.textContent==='3D').onclick();h.flush(2);
    h.redraw();h.micro();h.flush(2);
    assert.equal(h.workers.length,1);
    assert.equal(h.workers[0].destroyed,0);
    assert.equal(h.svg.listenerSets.get('pointerdown').size,1);
  } finally {h.dispose();h.micro();}
  assert.equal(h.workers[0].destroyed,1);
});
