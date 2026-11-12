// Read existing document text; these helpers never generate or change knowledge.
const sentenceSegmenter = new Intl.Segmenter('zh', {granularity:'sentence'});
const noSummary = '这份知识还没有可显示的摘要，打开详情查看原文。';

function documentParts(value) {
  const text=typeof value==='string' ? value.replace(/^\uFEFF/,'').replace(/\r\n/g,'\n') : '';
  const match=text.match(/^\s*---[ \t]*\n([\s\S]*?)\n---[ \t]*(?:\n|$)/);
  return match ? {front:match[1],body:text.slice(match[0].length)} : {front:'',body:text};
}

function plain(value) {
  return (typeof value==='string' ? value : '')
    .replace(/!?(?:\[([^\]]+)\]\([^)]*\))/g,'$1')
    .replace(/\[\[([^|\]]+)(?:\|([^\]]+))?\]\]/g,(_,target,label)=>label || target)
    .replace(/<[^>]+>/g,'')
    .replace(/^\s{0,3}#{1,6}\s+|\s+#+\s*$/g,'')
    .replace(/(`+|\*\*|__|~~)(.*?)\1/g,'$2')
    .replace(/\*([^*\n]+)\*/g,'$1')
    .replace(/(^|\s)_([^_\n]+)_(?=\s|$|[.,!?。，！？])/g,'$1$2')
    .replace(/\s+/g,' ').trim();
}

function frontTitle(front) {
  const lines=front.split('\n');
  for(let index=0;index<lines.length;index++) {
    const match=lines[index].match(/^(?:title|name):\s*(.*?)\s*$/);
    if(!match) continue;
    let value=match[1];
    if(/^[>|][+-]?$/.test(value)) {
      const block=[];
      for(let next=index+1;next<lines.length && /^\s+\S/.test(lines[next]);next++) block.push(lines[next].trim());
      value=block.join(' ');
    } else if(value.startsWith('"') && value.endsWith('"')) {
      try {value=JSON.parse(value);} catch {value=value.slice(1,-1);}
    } else if(value.startsWith("'") && value.endsWith("'")) value=value.slice(1,-1).replace(/''/g,"'");
    if(plain(value)) return plain(value);
  }
  return '';
}

function firstSentence(value) {
  const text=plain(value);
  const sentence=sentenceSegmenter.segment(text)[Symbol.iterator]().next().value?.segment.trim() || '';
  const chars=Array.from(sentence);
  return chars.length>180 ? chars.slice(0,179).join('').trimEnd()+'…' : sentence;
}

function markdownTitle(body) {
  let fence=false;
  for(const line of body.split('\n')) {
    if(/^\s*(```|~~~)/.test(line)) {fence=!fence;continue;}
    if(fence) continue;
    const heading=line.match(/^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$/);
    if(heading) return plain(heading[1]);
  }
  return '';
}

function pathStem(value) {
  let stem=String(value || '').split(/[\\/]/).pop().replace(/\.[^.]+$/,'');
  try {stem=decodeURIComponent(stem);} catch { /* A literal percent is valid in a file name. */ }
  return stem.replace(/[-_]+/g,' ').trim();
}

/** Full cleaned title, or an existing summary's first sentence. node is untouched. */
export function labelText(node) {
  const metadata=node.metadata || node.frontmatter || {};
  const parts=documentParts(node.text || node.body || '');
  const explicit=plain(metadata.title || metadata.name || '') || frontTitle(parts.front);
  if(explicit) return explicit;
  const heading=markdownTitle(parts.body);
  if(heading) return heading;
  const title=plain(node.title || node.name || '');
  const summary=plain(node.summary || metadata.summary || metadata.description || metadata.abstract || '');
  const usefulSummary=summary && summary!==noSummary ? summary : '';
  const stem=pathStem(node.path || node.id);
  const fallbackTitle=!title || title===stem || /^(?:未命名知识|未命名条目|raw|content|excerpt|index)$/i.test(title);
  if(title && (node.children || !fallbackTitle)) {
    const raw=node.kind==='raw' || node.type==='raw' || node.path?.startsWith('raw/');
    if(raw && Array.from(title).length>72 && (/[.…]$/.test(title) || usefulSummary.startsWith(title.slice(0,40))))
      return firstSentence(usefulSummary || title);
    return title;
  }
  if(usefulSummary) return firstSentence(usefulSummary);
  const paragraph=[];
  let fence=false;
  for(const line of parts.body.split('\n')) {
    if(/^\s*(```|~~~)/.test(line)) {fence=!fence;continue;}
    const clean=line.trim();
    if(fence || /^>|^#{1,6}\s|^---+$/.test(clean)) continue;
    if(!clean) {if(paragraph.length) break;continue;}
    paragraph.push(clean.replace(/^(?:[-*+]\s+|\d+[.)]\s+)/,''));
  }
  return firstSentence(paragraph.join(' ')) || stem || title || '未命名条目';
}

/** Bounded multiline captions; the caller keeps the complete title in its tooltip. */
export function wrapLabel(title, limit=22, maxLines=3) {
  const size=Math.max(1,Math.floor(limit)),rows=Math.max(1,Math.min(3,Math.floor(maxLines)));
  let rest=Array.from(plain(title));
  const lines=[];
  while(rest.length && lines.length<rows) {
    if(rest.length<=size) {lines.push(rest.join('').trim());break;}
    if(lines.length===rows-1) {lines.push(rest.slice(0,Math.max(0,size-1)).join('').trimEnd()+'…');break;}
    let take=size;
    for(let index=size;index>=Math.ceil(size*.6);index--) {
      if(/\s|[，、；：,;:]/u.test(rest[index-1])) {take=index;break;}
    }
    lines.push(rest.slice(0,take).join('').trim());
    rest=Array.from(rest.slice(take).join('').trimStart());
  }
  return lines.filter(Boolean);
}

/**
 * Expanded from the existing graph-labels collision search. x is the caption
 * center; y is its rectangle TOP, not a text baseline. previous stores {dx,dy}
 * relative to the node center using that same top-coordinate convention.
 * Obstacles use {left,right,top,bottom}; none of the inputs are mutated.
 */
export function placeCaptions(labels,width,height,obstacles=[],previous=new Map()) {
  const occupied=[...obstacles],positions=new Map(),padding=8,gap=14;
  if(width<=0 || height<=0) return positions;
  const overlaps=(a,b)=>a.left<b.right && a.right>b.left && a.top<b.bottom && a.bottom>b.top;
  const clamp=(value,min,max)=>min>max ? (min+max)/2 : Math.max(min,Math.min(max,value));
  for(const label of [...labels].sort((a,b)=>(b.priority || 0)-(a.priority || 0))) {
    if(!Number.isFinite(label.x) || !Number.isFinite(label.y) || label.x<0 || label.x>width || label.y<0 || label.y>height) continue;
    const half=label.width/2,h=label.height;
    const rectangle=(x,y)=>({left:x-half-3,right:x+half+3,top:y-3,bottom:y+h+3});
    const attempt=(x,y,insideOnly=false)=>{
      if(insideOnly&&(x<half+padding||x>width-half-padding||y<padding||y>height-h-padding))return false;
      x=clamp(x,half+padding,width-half-padding);y=clamp(y,padding,height-h-padding);
      const box=rectangle(x,y);
      if(box.left<0 || box.top<0 || box.right>width || box.bottom>height || occupied.some(other=>overlaps(box,other))) return false;
      positions.set(label.id,{x,y});occupied.push(box);return true;
    };
    const cached=previous.get(label.id);
    if(cached && attempt(label.x+cached.dx,label.y+cached.dy)) continue;
    if(attempt(label.x,label.y-h-gap) || attempt(label.x,label.y+gap) ||
      attempt(label.x+half+gap,label.y-h/2) || attempt(label.x-half-gap,label.y-h/2)) continue;
    let placed=false;
    const step=24,extent=Math.max(width,height);
    for(let radius=step;radius<=extent && !placed;radius+=step) {
      for(let offset=-radius;offset<=radius && !placed;offset+=step) {
        placed=attempt(label.x+offset,label.y-h/2-radius,true) || attempt(label.x+offset,label.y-h/2+radius,true) ||
          attempt(label.x-radius,label.y-h/2+offset,true) || attempt(label.x+radius,label.y-h/2+offset,true);
      }
    }
    if(!placed) {
      const x=clamp(label.x,half+padding,width-half-padding);
      const y=clamp(label.y-h-gap,padding,height-h-padding);
      positions.set(label.id,{x,y});occupied.push(rectangle(x,y));
    }
  }
  return positions;
}
