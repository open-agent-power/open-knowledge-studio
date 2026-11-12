import {nodeCategory, nodeHue} from './knowledge-model.js';
import {labelText, wrapLabel, placeCaptions} from './graph-text.js';
import {createCamera, fitCamera, setCamera, screenPoint, worldPoint, zoomAt, panBy, stopCamera, stepCamera} from './graph-camera.js';
import {createOrbit, rotateOrbit, fitOrbit, project3D, unproject3D, create3DLayout} from './graph-3d.js';
import {easePositions} from '../vendor/graph-engine/position-smoothing.js';

// State belongs to this SVG, so the existing detail/expand repaint retains it.
const views = new WeakMap();
let nextClip=0;
const ns = 'http://www.w3.org/2000/svg';
const make = (tag, attrs = {}) => {
  const el = document.createElementNS(ns, tag);
  Object.entries(attrs).forEach(([key,value])=>el.setAttribute(key,value));
  return el;
};
const sameTopology = (old, nodes, edges) => old && old.nodes.length===nodes.length &&
  old.nodes.every((n,i)=>n.id===nodes[i].id) && old.edges.length===edges.length &&
  old.edges.every((e,i)=>e.from===edges[i].from && e.to===edges[i].to && e.type===edges[i].type);

export function drawLearningGraph(svg, nodes, edges, tools, onSelect, options) {
  const {button, entry, nodeFill, nodeRadius, nodeDashed, onLasso, insetTop=0, insetBottom=0} = options;
  const stage = svg.parentElement;
  let state = views.get(svg);
  if (!state) {
    state = {camera:createCamera(), positions:new Map(), visual:new Map(), captions:new Map(), multi:new Set(), mode:'2d', orbit:createOrbit(), owner:0};
    views.set(svg,state);
  }
  if(state.resetRequested){state.positions.clear();state.visual.clear();state.captions.clear();state.multi.clear();state.multiMode=false;state.initialized=false;state.topology=null;state.worker?.destroy();state.worker=null;state.resetRequested=false;}
  const owner = ++state.owner, camera=state.camera;
  let width=svg.clientWidth, height=svg.clientHeight, raf=0, dead=false, lastTime=0, lastCaptionPack=0;
  const enlarged=state.width && width>state.width+1, shrunk=state.width&&width<state.width-1;
  let gesture=null, hover=null, lasso=false, pinch=null, orbitVelocity={x:0,y:0}, simulation=false, physicsTime=0, captionMoving=false;
  const captionTargets=new Map();
  const pointers=new Map(), reduced=window.matchMedia?.('(prefers-reduced-motion: reduce)').matches || false;
  const usableHeight=()=>Math.max(1,height-insetTop-insetBottom);
  if (state.width) {
    camera.x += (width-state.width)/2/camera.scale;
    camera.y += (usableHeight()-state.height)/2/camera.scale;
    camera.anchor=null; camera.flight=null;
  }
  state.width=width; state.height=usableHeight();
  svg.replaceChildren();
  tools.querySelectorAll('[data-zoom]').forEach(el=>el.remove());
  const layer=make('g'), selection=make('path',{fill:'#6386c51a',stroke:'#6386c5','stroke-dasharray':'5 4','pointer-events':'none'});
  const densityText=make('text',{'text-anchor':'end','font-size':11,fill:'#60738c','pointer-events':'none'});
  const defs=make('defs'),clip=make('clipPath',{id:`oks-graph-clip-${++nextClip}`}),clipRect=make('rect');
  clip.append(clipRect);defs.append(clip);layer.setAttribute('clip-path',`url(#${clip.getAttribute('id')})`);
  svg.append(layer,selection,densityText,defs);
  const measure=document.createElement('canvas').getContext('2d');
  measure.font='13px Segoe UI, Microsoft YaHei, sans-serif';
  let layout;

  function buildLayout() {
    const keep=state.positions;
    const items=nodes.map(n=>({...n,...keep.get(n.id)}));
    const unchanged=sameTopology(state.topology,nodes,edges);
    if (state.mode==='3d') {
      if (!state.worker || !unchanged) {
        state.worker?.destroy();
        if(!items.some(n=>Math.abs(n.z||0)>.01))items.forEach(n=>delete n.z);
        state.follow3D=true;
        state.worker=create3DLayout(items,edges,{distance:230,repel:6500,center:.003,
          onTick:type=>state.onTick?.(type),onError:message=>{state.error=message;state.onTick?.();}});
      }
      layout=state.worker;
    } else {
      layout=window.createForceLayout(items,edges,{distance:220,repel:7000,center:.006});
      for (const n of layout.nodes) {
        const saved=keep.get(n.id);
        if (saved) Object.assign(n,{x:saved.x,y:saved.y,z:saved.z||0});
        else {
          const parent=edges.find(e=>e.to===n.id && keep.has(e.from));
          if (parent) {const p=keep.get(parent.from),i=layout.nodes.indexOf(n);n.x=p.x+Math.cos(i*2.4)*180;n.y=p.y+Math.sin(i*2.4)*180;}
        }
      }
      if (!unchanged) layout.settle();
    }
    for (const n of layout.nodes) Object.assign(n,nodes.find(row=>row.id===n.id),{x:n.x,y:n.y,z:n.z||0});
    state.topology={nodes:nodes.map(n=>({id:n.id})),edges:edges.map(e=>({from:e.from,to:e.to,type:e.type}))};
    if (!state.initialized) fit(false);
    else if (state.fitRequested || (enlarged&&nodes.length>12)) fit(true);
    else if (!unchanged && items.some(n=>!keep.has(n.id))) fit(true);
    state.initialized=true;state.fitRequested=false;
  }

  function flat(node,visual=true) {
    const i=visual?indices.get(node.id):undefined;
    const row=i===undefined?node:{x:current[i*3],y:current[i*3+1],z:current[i*3+2]};
    if (state.mode!=='3d') return {x:row.x,y:row.y,depth:0,scale:1,visible:true};
    const p=project3D(row,state.orbit,1200,1200);
    return {...p,x:p.x-600,y:p.y-600};
  }
  function project(node) {
    const p=flat(node),screen=screenPoint(camera,p.x,p.y,width,usableHeight());
    return {...p,x:screen.x,y:screen.y+insetTop};
  }
  function fit(animate=true,overview=false) {
    if(state.mode==='3d')state.orbit=fitOrbit(state.orbit,layout?.nodes||[]);
    const points=(layout?.nodes || []).map(n=>({...flat(n,false),radius:14}));
    const next=fitCamera(points,width,usableHeight(),75);
    if (!next) return;
    next.scale=Math.min(1.25,next.scale);
    if(nodes.length>12&&!overview){
      let largest=0;
      const area=nodes.reduce((sum,n)=>{
        const lines=wrapLabel(labelText(n),width<650?16:22);
        const size=Math.max(60,...lines.map(line=>measure.measureText(line).width))*Math.max(18,lines.length*18);largest=Math.max(largest,size);return sum+size;
      },0)/nodes.length;
      const budget=Math.max(6,Math.floor(width*usableHeight()/Math.max(1,area*2.5,largest*(width<650?3:1.6))));
      let count=points.length;
      while(count>budget&&next.scale<3){next.scale*=1.16;count=points.filter(p=>Math.abs(p.x-next.x)*next.scale<width/2-15&&Math.abs(p.y-next.y)*next.scale<usableHeight()/2-15).length;}
      state.readingScale=next.scale;
      state.largeView=nodes.length>budget;
    }
    if (animate && !reduced) {camera.flight={x:next.x,y:next.y};camera.targetScale=next.scale;camera.anchor=null;}
    else setCamera(camera,next);
    schedule();
  }
  buildLayout();
  const indices=new Map(layout.nodes.map((n,i)=>[n.id,i]));
  const current=Float32Array.from(layout.nodes.flatMap(n=>{
    const parent=edges.find(e=>e.to===n.id && state.visual.has(e.from));
    const p=state.visual.get(n.id)||state.visual.get(parent?.from)||n;
    return[p.x,p.y,p.z||0];
  }));
  const targets=new Float32Array(current.length);
  if(shrunk&&entry){
    const selected=layout.nodes.find(n=>n.id===entry);
    if(selected){const p=flat(selected),s=screenPoint(camera,p.x,p.y,width,usableHeight());camera.x+=(s.x-Math.max(35,Math.min(width-35,s.x)))/camera.scale;camera.y+=(s.y-Math.max(35,Math.min(usableHeight()-35,s.y)))/camera.scale;}
  }

  const lineViews=layout.edges.map(edge=>{
    const el=make('line',{stroke:'#8fa4bf','stroke-width':1,'stroke-dasharray':edge.pending?'4 4':'','pointer-events':'none'});
    layer.append(el);return{edge,el};
  });
  const dots=layout.nodes.map(node=>{
    const title=labelText(node), lines=wrapLabel(title,width<650?16:22,nodeCategory(node)==='raw'?2:3);
    const g=make('g',{class:'studio-node',tabindex:0,role:'button','aria-label':title,'data-id':node.id});
    const leader=make('line',{x1:0,y1:0,stroke:'#c1ccdb','stroke-width':.65,'pointer-events':'none'});
    const hit=make('circle',{r:14,fill:'transparent','pointer-events':'all'});hit.style.stroke='none';
    const radius=node.children?Math.min(10,Math.max(7,(nodeRadius?.(node)||18)/2)):6;
    const color=nodeCategory(node)==='raw'?'#7d8a9d':`hsl(${nodeHue(node)} 48% 49%)`;
    const dot=make('circle',{r:radius,fill:node.children?'#f7f9fd':nodeFill?.(node)||color,stroke:color,
      'stroke-width':node.children?1.8:1,'stroke-dasharray':nodeDashed?.(node)?'3 3':''});
    const text=make('text',{'text-anchor':'middle'});
    Object.assign(text.style,{fontSize:'13px',fill:'#32465f',paintOrder:'stroke',stroke:'#f7f9fd',strokeWidth:'3px',cursor:'pointer'});
    lines.forEach((line,i)=>{const span=make('tspan',{x:0,dy:i?18:0});span.textContent=line;text.append(span);});
    const tooltip=make('title');tooltip.textContent=title;
    const halo=make('circle',{class:'graph-node-halo',fill:'none',stroke:'#356cc5','pointer-events':'none'});
    g.append(hit,dot,leader,text,tooltip,halo);layer.append(g);
    g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose(node,e);}};
    const captionWidth=Math.max(24,...lines.map(line=>measure.measureText(line).width))*1.08;
    return{node,g,hit,dot,text,leader,halo,radius,color,lines,sourceLeaf:nodeCategory(node)==='raw'&&!node.children,width:captionWidth,height:lines.length*18};
  });

  function activeNodes() {
    const active=new Set(state.multi);if(entry)active.add(entry);if(hover)active.add(hover);if(gesture?.node)active.add(gesture.node.id);
    const related=new Set(active);
    for(const edge of layout.edges)if(active.has(edge.from)||active.has(edge.to)){related.add(edge.from);related.add(edge.to);}
    return{active,related};
  }
  let obstacleKey='',obstacleCache=[];
  function obstacles() {
    const elements=[...stage.querySelectorAll('.knowledge-controls,.knowledge-filters,.graph-tools,.knowledge-key,.knowledge-selection')];
    const key=[width,height,...elements.map(el=>el.hidden)].join(':');
    if(key===obstacleKey)return[...obstacleCache];
    const origin=svg.getBoundingClientRect();
    obstacleCache=elements.filter(el=>!el.hidden).map(el=>{
      const r=el.getBoundingClientRect();return{left:r.left-origin.left-4,right:r.right-origin.left+4,top:r.top-origin.top-4,bottom:r.bottom-origin.top+4};
    });
    obstacleKey=key;return[...obstacleCache];
  }
  function draw(now=0,motion=false,elapsed=16) {
    clipRect.setAttribute('x',0);clipRect.setAttribute('y',insetTop);clipRect.setAttribute('width',width);clipRect.setAttribute('height',usableHeight());
    const {active,related}=activeNodes(),positions=new Map(layout.nodes.map(n=>{
      const p=project(n);p.inView=p.visible&&p.x>=-18&&p.x<=width+18&&p.y>=insetTop-18&&p.y<=height-insetBottom+18;
      return[n.id,p];
    }));
    const activeLeaves=new Set(layout.nodes.filter(n=>!n.children&&active.has(n.id)).map(n=>n.id));
    for(const row of lineViews) {
      const a=positions.get(row.edge.from),b=positions.get(row.edge.to);
      const hierarchy=row.edge.type==='contains',visible=a.visible&&b.visible&&(hierarchy?b.inView:a.inView||b.inView);
      if(row.visible!==visible){row.el.style.display=visible?'':'none';row.visible=visible;}
      if(!visible)continue;
      row.el.setAttribute('x1',a.x);row.el.setAttribute('y1',a.y);row.el.setAttribute('x2',b.x);row.el.setAttribute('y2',b.y);
      const emphasized=(active.has(row.edge.from)||active.has(row.edge.to))&&(!hierarchy||activeLeaves.has(row.edge.from)||activeLeaves.has(row.edge.to));
      const tone=emphasized?'active':active.size?'muted':'normal';
      if(row.tone!==tone){
        row.el.style.opacity=emphasized?'1':active.size?'.22':hierarchy?'.38':'.65';
        row.el.setAttribute('stroke',emphasized?'#356cc5':hierarchy?'#afbdce':'#8b9fb9');
        row.el.setAttribute('stroke-width',emphasized?'2.2':hierarchy?'.75':'1');row.tone=tone;
      }
    }
    const labels=[],factor=state.largeView?Math.max(.5,Math.min(1,camera.scale/(state.readingScale||camera.scale))):1;
    for(const row of dots) {
      const p=positions.get(row.node.id);
      if(row.visible!==p.inView){row.g.style.display=p.inView?'':'none';row.visible=p.inView;}
      if(p.inView)row.g.setAttribute('transform',`translate(${p.x},${p.y})`);
      const focused=active.has(row.node.id),neighbor=active.size&&related.has(row.node.id),muted=active.size&&!neighbor;
      const compact=Boolean(gesture?.moved)&&row.sourceLeaf&&!focused&&row.lines.length>1;
      if(row.compact!==compact){
        row.text.children[0].textContent=compact?row.lines[0].replace(/…$/,'')+'…':row.lines[0];
        for(let i=1;i<row.text.children.length;i++)row.text.children[i].style.display=compact?'none':'';
        row.compact=compact;row.captionTransform=null;lastCaptionPack=-Infinity;
      }
      row.displayHeight=compact?18:row.height;
      const tone=focused?'active':neighbor?'related':muted?'muted':'normal',chosen=state.multi.has(row.node.id);
      if(row.tone!==tone||row.chosen!==chosen){
        row.g.classList.toggle('graph-multi-selected',chosen);
        row.g.classList.toggle('graph-active',focused);row.g.classList.toggle('graph-related',Boolean(neighbor&&!focused));
        row.dot.style.strokeWidth=focused?'3px':neighbor?'2px':row.node.children?'1.8px':'1px';
        row.dot.setAttribute('stroke',focused?'#245db8':neighbor?'#5c80bd':row.color);
        row.dot.style.opacity=muted?'.55':'1';
        row.text.style.opacity=muted?'.76':'1';
        row.text.style.fill=focused?'#174a91':neighbor?'#284c78':'#32465f';
        row.text.style.fontWeight=focused?'700':neighbor?'600':'400';
        row.halo.style.display=focused||neighbor?'':'none';
        row.halo.setAttribute('stroke-width',focused?'2':'1.5');row.halo.style.opacity=focused?'1':'.7';
        row.tone=tone;row.chosen=chosen;
      }
      const radius=(state.mode==='3d'?row.radius*Math.max(.7,Math.min(1.5,Math.sqrt(p.scale))):row.radius)+(focused?1.5:neighbor?1:0);
      if(row.paintRadius!==radius&&p.inView){row.dot.setAttribute('r',radius);row.halo.setAttribute('r',radius+(focused?5:4));row.paintRadius=radius;}
      const captionFactor=neighbor?1:factor;
      labels.push({id:row.node.id,x:p.x,y:p.y-insetTop,width:(row.width+(compact?8:0))*captionFactor,height:row.displayHeight*captionFactor,priority:focused?100:neighbor?50:row.node.children?20:10});
      state.positions.set(row.node.id,{x:row.node.x,y:row.node.y,z:row.node.z||0});
      const i=indices.get(row.node.id);state.visual.set(row.node.id,{x:current[i*3],y:current[i*3+1],z:current[i*3+2]});
    }
    const blocks=obstacles();
    const visible=[...positions.values()].filter(p=>p.visible&&p.x>=0&&p.x<=width&&p.y>=insetTop&&p.y<=height-insetBottom).length;
    densityText.style.display=state.error||nodes.length>40||visible<nodes.length||factor<.9?'':'none';
    if(state.error||nodes.length>40||visible<nodes.length||factor<.9){
      densityText.textContent=state.error?`三维布局不可用：${state.error}`:`可见 ${visible} / ${nodes.length} · ${factor<.9?'全图概览，滚轮放大阅读标题':'拖动浏览，滚轮缩放'}`;
      densityText.setAttribute('fill',state.error?'#9b493f':'#60738c');
      densityText.setAttribute('x',width-14);densityText.setAttribute('y',insetTop+18);
      blocks.push({left:10,right:width-10,top:insetTop,bottom:insetTop+28});
    }
    for(const p of positions.values())blocks.push({left:p.x-10,right:p.x+10,top:p.y-10,bottom:p.y+10});
    const shifted=blocks.map(b=>({...b,top:b.top-insetTop,bottom:b.bottom-insetTop}));
    const repack=now===0||(motion&&now-lastCaptionPack>120)||(!motion&&!captionMoving);
    if(repack){
      captionTargets.clear();
      for(const[id,c]of placeCaptions(labels,width,usableHeight(),shifted,state.captions)){
        const p=positions.get(id);captionTargets.set(id,{dx:c.x-p.x,dy:c.y+insetTop-p.y});
      }
      lastCaptionPack=now;
    }
    const blend=now===0||reduced?1:1-Math.pow(.68,elapsed/16);
    captionMoving=false;
    for(const row of dots) {
      const p=positions.get(row.node.id),caption=captionTargets.get(row.node.id);
      if(row.captionVisible!==Boolean(caption)){row.text.style.display=caption?'':'none';row.leader.style.display=caption?'':'none';row.captionVisible=Boolean(caption);}
      if(!caption)continue;
      const previous=state.captions.get(row.node.id)||caption;
      const dx=previous.dx+(caption.dx-previous.dx)*blend,dy=previous.dy+(caption.dy-previous.dy)*blend;
      if(Math.abs(dx-caption.dx)+Math.abs(dy-caption.dy)>.2)captionMoving=true;
      const captionFactor=related.has(row.node.id)?1:factor;
      const transform=`translate(${dx},${dy+13*captionFactor}) scale(${captionFactor})`;
      if(row.captionTransform!==transform){
        row.text.setAttribute('transform',transform);row.leader.setAttribute('x2',dx);row.leader.setAttribute('y2',dy+row.displayHeight*captionFactor/2);row.captionTransform=transform;
      }
      state.captions.set(row.node.id,{dx,dy});
    }
    svg.dataset.graphMode=state.mode;svg.dataset.highlighted=String(active.size);
    if(state.mode==='3d')for(const row of [...dots].sort((a,b)=>positions.get(a.node.id).depth-positions.get(b.node.id).depth))layer.append(row.g);
    svg.setAttribute('aria-description',state.error||'拖动画布浏览；滚轮围绕鼠标缩放；Ctrl/Cmd 单击多选；三维模式拖动空白处旋转，Shift 拖动平移。');
  }
  function schedule() {if(!dead&&!raf)raf=requestAnimationFrame(tick);}
  function tick(now) {
    raf=0;const elapsed=Math.min(64,Math.max(1,lastTime?now-lastTime:16));lastTime=now;
    const moving=stepCamera(camera,elapsed,reduced,Boolean(gesture),width,usableHeight());
    let rotating=false;
    if(!gesture&&state.mode==='3d'&&(Math.abs(orbitVelocity.x)+Math.abs(orbitVelocity.y)>.015)){
      state.orbit=rotateOrbit(state.orbit,orbitVelocity.x,orbitVelocity.y);orbitVelocity.x*=.88;orbitVelocity.y*=.88;rotating=true;
    }
    if(simulation&&state.mode==='2d'){
      physicsTime+=elapsed;
      while(physicsTime>=16&&simulation){
        if(gesture?.node&&gesture.moved)layout.reheat();
        simulation=layout.step();physicsTime-=16;
      }
    }
    layout.nodes.forEach((n,i)=>{targets[i*3]=n.x;targets[i*3+1]=n.y;targets[i*3+2]=n.z||0;});
    const easing=easePositions(current,targets,reduced?1:1-Math.pow(.8,elapsed/16));
    draw(now,Boolean(gesture)||moving||rotating||simulation||easing,elapsed);if(moving||rotating||simulation||easing||captionMoving)schedule();
  }
  state.onTick=type=>{if(state.follow3D&&state.mode==='3d')fit(true);if(type==='end')state.follow3D=false;schedule();};
  function choose(node,event) {
    stopCamera(camera);
    if(state.multiMode||event.ctrlKey||event.metaKey){state.multi.has(node.id)?state.multi.delete(node.id):state.multi.add(node.id);onLasso?.(layout.nodes.filter(n=>state.multi.has(n.id)));schedule();}
    else {state.multi.clear();onSelect(node);}
  }
  function control(label,title,action) {
    const el=button(label,action);el.dataset.zoom='1';el.title=title;el.setAttribute('aria-label',title);tools.append(el);return el;
  }
  control('＋','放大图谱',()=>{state.follow3D=false;zoomAt(camera,1.2,null,width,usableHeight());schedule();});
  control('−','缩小图谱',()=>{state.follow3D=false;zoomAt(camera,1/1.2,null,width,usableHeight());schedule();});
  control('⌾','适配画布',()=>{state.follow3D=false;fit(true,true);});
  const multiButton=control('多选','多选高亮节点（也可 Ctrl/Cmd 单击）',()=>{state.multiMode=!state.multiMode;multiButton.setAttribute('aria-pressed',String(state.multiMode));if(!state.multiMode){state.multi.clear();onLasso?.([]);}schedule();});
  multiButton.setAttribute('aria-pressed',String(Boolean(state.multiMode)));
  const lassoButton=control('圈选','圈选节点',()=>{lasso=!lasso;lassoButton.setAttribute('aria-pressed',String(lasso));});
  const modeButton=control(state.mode==='3d'?'2D':'3D','切换二维／三维图谱',()=>{
    state.mode=state.mode==='3d'?'2d':'3d';state.error=null;state.fitRequested=true;state.topology=null;
    if(state.mode==='2d'){state.worker?.destroy();state.worker=null;state.follow3D=false;}
    save();cleanup(false);drawLearningGraph(svg,nodes,edges,tools,onSelect,options);
  });
  modeButton.setAttribute('aria-pressed',String(state.mode==='3d'));
  modeButton.title=state.mode==='3d'?'拖动空白处旋转；Shift+拖动平移；滚轮缩放':'切换三维：旋转查看真实空间关系';
  function placeTools(){
    tools.style.bottom=width<500?'48px':'';
    for(const el of stage.querySelectorAll('.knowledge-selection'))el.style.bottom=width<500?'90px':'';
  }
  placeTools();

  const point=e=>{const r=svg.getBoundingClientRect();return{x:e.clientX-r.left,y:e.clientY-r.top};};
  const release=id=>{if(svg.hasPointerCapture(id))svg.releasePointerCapture(id);};
  function releaseNode(node,moved){
    node.fx=null;node.fy=null;
    if(state.mode==='3d')layout.dragEnd();
    else if(moved){layout.config.link=.018;layout.reheat();simulation=true;}
  }
  function down(e) {
    if(e.button!==0)return;
    const p=point(e);pointers.set(e.pointerId,p);state.follow3D=false;stopCamera(camera);orbitVelocity={x:0,y:0};
    if(pointers.size===2){if(gesture?.node)releaseNode(gesture.node,gesture.moved);const [a,b]=[...pointers.values()];pinch={distance:Math.hypot(a.x-b.x,a.y-b.y),scale:camera.scale};gesture=null;return;}
    const node=layout.nodes.find(n=>n.id===e.target.closest('.studio-node')?.dataset.id);
    if(node){const i=indices.get(node.id);Object.assign(node,{x:current[i*3],y:current[i*3+1],z:current[i*3+2]});}
    gesture={id:e.pointerId,start:p,last:p,node,x:node?.x,y:node?.y,z:node?.z||0,moved:false,time:e.timeStamp||performance.now(),shift:e.shiftKey};
    if(lasso)gesture.points=[p];
    if(node){node.fx=node.x;node.fy=node.y;if(state.mode==='3d')layout.dragStart(node.id);}
    svg.setPointerCapture(e.pointerId);e.preventDefault();schedule();
  }
  function move(e) {
    const p=point(e);
    if(pointers.has(e.pointerId))pointers.set(e.pointerId,p);
    if(pinch&&pointers.size===2){const[a,b]=[...pointers.values()];const scale=pinch.scale*Math.hypot(a.x-b.x,a.y-b.y)/Math.max(1,pinch.distance);zoomAt(camera,scale/camera.targetScale,{x:(a.x+b.x)/2,y:(a.y+b.y)/2-insetTop},width,usableHeight());e.preventDefault();schedule();return;}
    if(!gesture){const id=e.target.closest('.studio-node')?.dataset.id||null;if(id!==hover){hover=id;schedule();}return;}
    if(gesture.id!==e.pointerId)return;
    const dx=p.x-gesture.start.x,dy=p.y-gesture.start.y;
    if(Math.hypot(dx,dy)>5){gesture.moved=true;if(gesture.node&&!gesture.dragStarted&&state.mode==='2d'){gesture.dragStarted=true;layout.config.link=.055;layout.reheat();simulation=true;physicsTime=0;}}
    if(gesture.points){gesture.points.push(p);selection.setAttribute('d',gesture.points.map((q,i)=>`${i?'L':'M'}${q.x},${q.y}`).join(' ')+' Z');return;}
    if(!gesture.moved)return;
    const sx=p.x-gesture.last.x,sy=p.y-gesture.last.y;
    if(gesture.node){
      let target={x:gesture.x+dx/camera.scale,y:gesture.y+dy/camera.scale,z:gesture.z};
      if(state.mode==='3d'){
        const base=project3D({x:gesture.x,y:gesture.y,z:gesture.z},state.orbit,1200,1200);
        target=unproject3D({x:base.x+dx/camera.scale,y:base.y+dy/camera.scale},state.orbit,1200,1200,base.depth);
        layout.dragMove(gesture.node.id,target.x,target.y,target.z);
      }
      Object.assign(gesture.node,target,{fx:target.x,fy:target.y});
      const i=indices.get(gesture.node.id);current[i*3]=target.x;current[i*3+1]=target.y;current[i*3+2]=target.z||0;
    } else if(state.mode==='3d'&&!gesture.shift){state.orbit=rotateOrbit(state.orbit,sx,sy);orbitVelocity={x:sx*.4,y:sy*.4};}
    else panBy(camera,sx,sy,Math.max(1,(e.timeStamp||performance.now())-gesture.time));
    gesture.last=p;gesture.time=e.timeStamp||performance.now();e.preventDefault();schedule();
  }
  function up(e) {
    pointers.delete(e.pointerId);if(pinch){pinch=null;gesture=null;release(e.pointerId);return;}
    if(!gesture||gesture.id!==e.pointerId)return;
    const current=gesture;gesture=null;release(e.pointerId);
    if(current.points){
      state.multi=new Set(dots.filter(row=>insidePolygon(project(row.node),current.points)).map(row=>row.node.id));
      lasso=false;lassoButton.setAttribute('aria-pressed','false');selection.setAttribute('d','');onLasso?.(layout.nodes.filter(n=>state.multi.has(n.id)));
    }else if(current.node){
      releaseNode(current.node,current.moved);
      if(!current.moved&&e.type==='pointerup')choose(current.node,e);
    }else if(!current.moved&&e.type==='pointerup'){state.multi.clear();onLasso?.([]);}
    schedule();
  }
  function wheel(e){e.preventDefault();state.follow3D=false;const p=point(e);zoomAt(camera,Math.exp(-e.deltaY*.0015),{x:p.x,y:p.y-insetTop},width,usableHeight());schedule();}
  function leave(){if(!gesture){hover=null;schedule();}}
  function reset(e){const name=e.target.closest('button')?.textContent;if(e.target.closest('.knowledge-controls')&&name==='重置')state.resetRequested=true;else if(['仅看选中','仅看本区'].includes(name))state.fitRequested=true;}
  const observer=new ResizeObserver(()=>{
    const next=svg.clientWidth,h=svg.clientHeight;
    if(next===width&&h===height)return;
    camera.x+=(next-width)/2/camera.scale;camera.y+=(h-height)/2/camera.scale;
    width=next;height=h;state.width=width;state.height=usableHeight();placeTools();schedule();
  });
  observer.observe(svg);
  for(const[type,fn]of Object.entries({pointerdown:down,pointermove:move,pointerup:up,pointercancel:up,pointerleave:leave}))svg.addEventListener(type,fn);
  svg.addEventListener('wheel',wheel,{passive:false});stage.addEventListener('click',reset,true);
  svg.style.touchAction='none';svg.style.cursor='grab';
  function save(){state.width=width;state.height=usableHeight();for(const n of layout.nodes)state.positions.set(n.id,{x:n.x,y:n.y,z:n.z||0});}
  function cleanup(defer=true){
    if(dead)return;save();dead=true;cancelAnimationFrame(raf);observer.disconnect();
    for(const[type,fn]of Object.entries({pointerdown:down,pointermove:move,pointerup:up,pointercancel:up,pointerleave:leave}))svg.removeEventListener(type,fn);
    svg.removeEventListener('wheel',wheel);stage.removeEventListener('click',reset,true);
    if(defer)queueMicrotask(()=>{if(state.owner===owner){state.worker?.destroy();state.worker=null;state.onTick=null;}});
  }
  state.currentCleanup=()=>cleanup();
  draw();schedule();return()=>state.currentCleanup?.();
}

function insidePolygon(point, polygon) {
  let inside=false;
  for(let i=0,j=polygon.length-1;i<polygon.length;j=i++){
    const a=polygon[i],b=polygon[j];
    if((a.y>point.y)!==(b.y>point.y)&&point.x<(b.x-a.x)*(point.y-a.y)/(b.y-a.y)+a.x)inside=!inside;
  }
  return inside;
}
