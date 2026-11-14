const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../..');
const baseline = require('./fixtures/graph-non-learning.json');
const demoSource = fs.readFileSync(path.join(root,'assets/mail-web/studio/graph.js'),'utf8');
const {createForceLayout} = require(path.join(root,'assets/mail-web/force-layout.js'));
const labels = require(path.join(root,'assets/mail-web/graph-labels.js'));
const model = import('data:text/javascript;base64,' + Buffer.from(fs.readFileSync(
  path.join(root,'assets/mail-web/studio/knowledge-model.js'),'utf8',
)).toString('base64'));

class Element {
  constructor(tag) {
    this.tagName=tag; this.attributes={}; this.dataset={}; this.style={};
    this.children=[]; this._text=''; this.listeners=new Map(); this.listenerSets=new Map(); this.captured=new Set();
    this.classes=new Set();
    this.classList={contains:name=>this.classes.has(name),
      add:(...names)=>names.forEach(name=>this.classes.add(name)),
      remove:(...names)=>names.forEach(name=>this.classes.delete(name)),
      toggle:(name,value)=>{const show=value===undefined ? !this.classes.has(name) : value;
        show ? this.classes.add(name) : this.classes.delete(name);return show;}};
  }
  get textContent() {return this._text+this.children.map(node=>node.textContent).join('');}
  set textContent(value) {this._text=String(value);this.children=[];}
  setAttribute(name,value) {
    this.attributes[name]=String(value);
    if(name==='class') this.classes=new Set(String(value).split(/\s+/));
    if(name.startsWith('data-')) this.dataset[name.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=String(value);
  }
  getAttribute(name) {return this.attributes[name] ?? null;}
  append(...nodes) {for(const node of nodes){node.remove?.();node.parentElement=this;this.children.push(node);}}
  replaceChildren(...nodes) {this.children=[];this.append(...nodes);}
  remove() {if(this.parentElement?.children)this.parentElement.children=this.parentElement.children.filter(node=>node!==this);}
  closest(selector) {
    if(selector===this.tagName) return this;
    if(selector.startsWith('.') && this.classList.contains(selector.slice(1))) return this;
    return this.parentElement?.closest?.(selector) || null;
  }
  querySelectorAll(selector) {
    const selectors=selector.split(',').map(value=>value.trim());
    return this.children.flatMap(node=>[
      ...(selectors.some(selector=>selector==='[data-zoom]' ? !!node.dataset.zoom : selector.startsWith('.')
        ? node.classList.contains(selector.slice(1)) : node.tagName===selector) ? [node] : []),
      ...node.querySelectorAll(selector),
    ]);
  }
  getComputedTextLength() {return Array.from(this.textContent).length*(parseFloat(this.style.fontSize)||10)*.55;}
  addEventListener(name,handler) {
    if(!this.listenerSets.has(name))this.listenerSets.set(name,new Set());
    this.listenerSets.get(name).add(handler);this.listeners.set(name,handler);
  }
  removeEventListener(name,handler) {
    const handlers=this.listenerSets.get(name);if(!handlers)return;handlers.delete(handler);
    if(handlers.size)this.listeners.set(name,[...handlers].at(-1));
    else {this.listeners.delete(name);this.listenerSets.delete(name);}
  }
  dispatch(name,event) {for(const handler of [...(this.listenerSets.get(name)||[])])handler(event);}
  getBoundingClientRect() {return this.bounds || {left:0,top:0,width:this.clientWidth||0,height:this.clientHeight||0,right:this.clientWidth||0,bottom:this.clientHeight||0};}
  setPointerCapture(id) {this.captured.add(id);}
  hasPointerCapture(id) {return this.captured.has(id);}
  releasePointerCapture(id) {this.captured.delete(id);}
}

async function fixture({source=demoSource,learning=false,screenSize=true}={}) {
  const helpers=await model, frames=new Map(); let nextFrame=0, observer;
  const dispatched=[];
  const context=vm.createContext({
    ...helpers,
    drawLearningGraph:(...args)=>{dispatched.push(args);return()=>{};},
    document:{createElementNS:(_,tag)=>new Element(tag)},
    window:{createForceLayout,OksGraphLabels:labels},
    requestAnimationFrame:callback=>{const id=++nextFrame;frames.set(id,callback);return id;},
    cancelAnimationFrame:id=>frames.delete(id),
    ResizeObserver:class {constructor(callback){this.callback=callback;observer=this;}observe(){}disconnect(){this.disconnected=true;}},
  });
  vm.runInContext(source.replace(/^import[^\n]*\r?\n/gm,'').replace(/export function /g,'function ')+
    '\nthis.render=drawGraph;',context);
  const stage=new Element('div'); if(learning)stage.classList.add('knowledge-stage');
  const svg=new Element('svg'),tools=new Element('div');
  svg.clientWidth=900;svg.clientHeight=600;stage.append(svg);
  const nodes=[{id:'group',title:'知识',type:'group',family:'wiki',uses:0,children:[{id:'leaf'}]},
    {id:'leaf',title:'当前真实条目',type:'wiki',uses:0,pending:true}];
  const before=JSON.stringify(nodes), selections=[], lassos=[];
  const dispose=context.render(svg,nodes,[{from:'group',to:'leaf',type:'contains',pending:true}],tools,
    node=>selections.push(node.id),{
      entry:'leaf',screenSize,button:(label,action)=>{const node=new Element('button');node.textContent=label;node.onclick=action;return node;},
      nodeFill:node=>node.id==='group' ? '#ccddee' : '#aabbcc',nodeRadius:()=>48,
      nodeDashed:node=>node.pending,nodeRegion:()=> 'wiki',regionColor:()=> '#dae4f3',
      onLasso:nodes=>lassos.push(nodes.map(node=>node.id)),
    });
  const groups=svg.querySelectorAll('.studio-node');
  const layer=svg.children[0];
  const zoom=()=>Number(layer.getAttribute('transform').match(/scale\(([^)]+)\)/)[1]);
  return {svg,tools,nodes,before,groups,selections,lassos,frames,observer,zoom,dispose,dispatched};
}

function snapshot(node) {
  return {tag:node.tagName,attrs:node.attributes,data:node.dataset,style:node.style,text:node.textContent,
    children:node.children.map(snapshot)};
}
const pointer=(type,target,x,y,extra={})=>({type,target,button:0,pointerId:1,clientX:x,clientY:y,preventDefault(){},...extra});

module.exports={Element,snapshot,pointer,fixture};

if(require.main===module) {
test('the learning stage delegates its original data and actions to the dedicated renderer',async()=>{
  const h=await fixture({learning:true});
  try {
    assert.equal(h.dispatched.length,1);
    assert.equal(h.dispatched[0][0],h.svg);
    assert.equal(h.dispatched[0][1],h.nodes);
    assert.equal(h.dispatched[0][3],h.tools);
    assert.equal(h.dispatched[0][5].entry,'leaf');
    assert.equal(JSON.stringify(h.nodes),h.before);
  } finally {h.dispose();}
});

test('non-learning stages retain the complete original SVG appearance',async()=>{
  for(const screenSize of [false,true]) {
    const demo=await fixture({learning:false,screenSize});
    try {
      assert.ok(demo.svg.querySelectorAll('ellipse').length>0);
      assert.deepEqual(snapshot(demo.svg),baseline[String(screenSize)].svg);
      assert.deepEqual(snapshot(demo.tools),baseline[String(screenSize)].tools);
    } finally {demo.dispose();}
  }
});

test('real original event handlers still select on click and keyboard, drag without selecting, and lasso',async()=>{
  const h=await fixture();
  try {
    const leaf=h.groups.find(node=>node.dataset.id==='leaf');
    h.svg.listeners.get('pointerdown')(pointer('pointerdown',leaf.children[0],100,100));
    h.svg.listeners.get('pointerup')(pointer('pointerup',leaf.children[0],100,100));
    leaf.onkeydown({key:'Enter',preventDefault(){}});
    assert.deepEqual(h.selections,['leaf','leaf']);
    h.svg.listeners.get('pointerdown')(pointer('pointerdown',leaf.children[0],100,100));
    h.svg.listeners.get('pointermove')(pointer('pointermove',leaf.children[0],125,112));
    h.svg.listeners.get('pointerup')(pointer('pointerup',leaf.children[0],125,112));
    assert.deepEqual(h.selections,['leaf','leaf']);
    const previous=h.zoom();
    h.svg.listeners.get('wheel')({deltaY:-50,preventDefault(){}});
    assert.ok(h.zoom()>previous);
    h.tools.children.find(node=>node.textContent==='圈选').onclick();
    h.svg.listeners.get('pointerdown')(pointer('pointerdown',h.svg,0,0));
    for(const [x,y] of [[900,0],[900,600],[0,600]])h.svg.listeners.get('pointermove')(pointer('pointermove',h.svg,x,y));
    h.svg.listeners.get('pointerup')(pointer('pointerup',h.svg,0,600));
    assert.equal(h.lassos.length,1);
    assert.ok(h.lassos[0].length>0);
  } finally {h.dispose();}
  assert.equal(h.svg.listeners.size,0);
  assert.equal(h.observer.disconnected,true);
});
}
