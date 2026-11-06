/* Small, dependency-free force layout. Graph data and document content stay separate. */
(function(root){
 'use strict';
 function createForceLayout(items,links,options={}){
  const config={center:.006,repel:2600,link:.018,distance:180,...options};
  const nodes=items.map((item,i)=>{const angle=items.length>6?i*2.399963:i*2*Math.PI/Math.max(1,items.length)-Math.PI/2;const radius=items.length>6?55*Math.sqrt(i):150;return {...item,x:items.length===1?0:Math.cos(angle)*radius,y:items.length===1?0:Math.sin(angle)*radius,vx:0,vy:0,fx:null,fy:null};});
  const byId=new Map(nodes.map(n=>[n.id,n]));
  const edges=links.filter(l=>byId.has(l.from)&&byId.has(l.to)).map(l=>({...l,source:byId.get(l.from),target:byId.get(l.to)}));
  // Tag similarity is weaker than a written link. Normalise dense tag groups so
  // a popular tag cannot pull the whole library into one overlapping bundle.
  const tagDegrees=new Map();edges.filter(e=>e.type==='shared_tag').forEach(e=>{for(const id of [e.from,e.to])tagDegrees.set(id,(tagDegrees.get(id)||0)+1);});
  const strength=edge=>edge.type==='shared_tag'?.3/Math.sqrt(Math.max(tagDegrees.get(edge.from),tagDegrees.get(edge.to))):1;
  let alpha=1,steps=0,quiet=0;
  function step(){
   nodes.forEach(n=>{const target=config.anchor?.(n)||{x:0,y:0};n.vx-=(n.x-target.x)*config.center*alpha;n.vy-=(n.y-target.y)*config.center*alpha;});
   for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){
    const a=nodes[i],b=nodes[j];let dx=b.x-a.x,dy=b.y-a.y;
    if(Math.abs(dx)+Math.abs(dy)<.01){dx=.2*(j+1);dy=.13*(i+1);}
    const distance=Math.max(1,Math.hypot(dx,dy));
    const force=Math.min(10,config.repel/(distance*distance))*alpha;
    const collision=Math.max(0,105-distance)*.055*alpha;
    const x=dx/distance*(force+collision),y=dy/distance*(force+collision);
    a.vx-=x;a.vy-=y;b.vx+=x;b.vy+=y;
   }
   edges.forEach(edge=>{const {source:a,target:b}=edge;const dx=b.x-a.x,dy=b.y-a.y,d=Math.max(.1,Math.hypot(dx,dy));const f=(d-config.distance)*config.link*strength(edge)*alpha;const x=dx/d*f,y=dy/d*f;a.vx+=x;a.vy+=y;b.vx-=x;b.vy-=y;});
   let speed=0;
   nodes.forEach(n=>{if(n.fx!==null){n.x=n.fx;n.y=n.fy;n.vx=0;n.vy=0;}else{n.vx*=.78;n.vy*=.78;n.x+=n.vx;n.y+=n.vy;speed=Math.max(speed,Math.hypot(n.vx,n.vy));}});
   alpha*=.978;steps++;quiet=speed<.025?quiet+1:0;
   if(steps>35&&quiet>=18)alpha=0;
   return alpha>.012||speed>.025;
  }
  return {nodes,edges,config,step,reheat(){alpha=.9;steps=0;quiet=0;},get alpha(){return alpha;},get steps(){return steps;},settle(){for(let i=0;i<650;i++)if(!step())break;}};
 }
 root.createForceLayout=createForceLayout;
 if(typeof module!=='undefined'&&module.exports)module.exports={createForceLayout};
})(typeof globalThis!=='undefined'?globalThis:this);
