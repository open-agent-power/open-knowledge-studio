/* Shared collision-aware labels, extracted from the existing knowledge graph. */
(function(root){
function graphLabelPositions(labels,width,height,obstacles=[]){
 const overlaps=(a,b)=>a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top;
 const boxes=[...obstacles],positions=new Map();
 for(const label of [...labels].sort((a,b)=>b.priority-a.priority)){
  const half=Math.min(label.width,width-24)/2;
  const x=Math.max(half+12,Math.min(width-half-12,label.x));
  if(label.x<0||label.x>width||label.y<0||label.y>height)continue;
  for(const [dx,dy] of [[0,24],[0,-20],[-24,24],[24,24],[-24,-20],[24,-20],[0,40],[0,-36]]){
   const cx=Math.max(half+12,Math.min(width-half-12,x+dx)),y=label.y+dy,box={left:cx-half-4,right:cx+half+4,top:y-14,bottom:y+5};
   if(box.top<8||box.bottom>height-8||boxes.some(b=>overlaps(box,b)))continue;
   positions.set(label.id,{x:cx,y});boxes.push(box);break;
  }
 }
 return positions;
}
const api={graphLabelPositions};root.OksGraphLabels=api;
if(typeof module!=="undefined"&&module.exports)module.exports=api;
})(typeof globalThis!=="undefined"?globalThis:this);
