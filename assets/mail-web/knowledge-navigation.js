'use strict';
const KnowledgeNavigation=(()=>{
 const filterParams={'评级':'f_rating','质量状态':'f_quality','Wiki状态':'f_wiki'};
 function normalize(value={}){return{graphTag:String(value.graphTag||''),knowledgeMode:['domains','tags','skills','materials'].includes(value.knowledgeMode)?value.knowledgeMode:'domains',fieldFilters:{...(value.fieldFilters||{})},graphContext:!!value.graphContext,query:String(value.query||'')};}
 function paramsFor(value){const o=normalize(value),p=new URLSearchParams();p.set('mode',o.knowledgeMode);for(const[k,v]of Object.entries(filterParams))if(o.fieldFilters[k])p.set(v,o.fieldFilters[k]);if(o.graphContext)p.set('context','1');if(o.query)p.set('q',o.query);return p;}
 function parse(params,tag=''){const scope=params.get('scope')||tag;return normalize({graphTag:scope,knowledgeMode:scope.startsWith('skills:')?'skills':scope.startsWith('domain:')?'domains':params.get('mode')||'tags',fieldFilters:Object.fromEntries(Object.entries(filterParams).map(([k,v])=>[k,params.get(v)||''])),graphContext:params.get('context')==='1',query:params.get('q')||''});}
 function graphHash(value,selected=''){const o=normalize(value),p=paramsFor(o);if(selected)p.set('node',selected);const prefix=o.graphTag.startsWith('domain:')?'wiki-domain='+encodeURIComponent(o.graphTag.slice(7)):o.graphTag.startsWith('skills:')?'wiki-skill='+encodeURIComponent(o.graphTag.slice(7)):'wiki-tag='+encodeURIComponent(o.graphTag);return '#'+prefix+'&'+p;}
 function readerHash(item,value){const o=normalize(value),p=paramsFor(o);p.set('path',item.id);p.set('scope',o.graphTag);return '#wiki-reader&'+p;}
 function defaultOrigin(item){return normalize({graphTag:item.isMaterial?'materials:all':item.isSkill?'skills:'+(item.governance?.type||'unclassified'):'domain:'+(item.knowledgeDomains?.[0]?.id||'_unmapped'),knowledgeMode:item.isMaterial?'materials':item.isSkill?'skills':'domains'});}
 function scopeItems(items,origin,matchTag,matchFields){const tag=origin.graphTag;return items.filter(p=>matchFields(p,origin.fieldFilters)).filter(p=>{
  if(tag==='materials:all')return p.isMaterial===true;if(p.isMaterial)return false;
  if(tag==='全部知识')return !p.isSkill;if(tag==='全部Skills'||tag==='skills:all')return p.isSkill;
  if(tag.startsWith('domain:'))return !p.isSkill&&(p.knowledgeDomains||[]).some(d=>d.id===tag.slice(7));
  if(tag.startsWith('skills:'))return p.isSkill&&(p.governance?.type||'unclassified')===tag.slice(7);
  return !p.isSkill&&matchTag(p,tag);
 });}
 return{normalize,parse,graphHash,readerHash,defaultOrigin,scopeItems};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=KnowledgeNavigation;

function knowledgeOrigin(item){
 if(state.page==='wiki'&&!state.global&&state.wikiOrigin)return KnowledgeNavigation.normalize(state.wikiOrigin);
 if(state.page==='wiki'&&state.graphTag)return KnowledgeNavigation.normalize({...state,graphTag:state.graphTag});
 return KnowledgeNavigation.normalize({...KnowledgeNavigation.defaultOrigin(item),fieldFilters:state.page==='wiki'?state.fieldFilters:{}});
}
function knowledgeScopeLabel(origin){const tag=origin.graphTag;if(tag==='materials:all')return '来源资料';if(tag.startsWith('domain:')){const id=tag.slice(7);return store.knowledge?.worker_source?.domain_options?.[id]||(id==='_unmapped'?'待对齐知识域':id);}if(tag.startsWith('skills:'))return tag==='skills:all'?'全部 Skills':'Skills · '+(skillTypeNames[tag.slice(7)]||tag.slice(7));return tag==='全部知识'||tag==='全部Skills'?tag:'# '+tag;}
function knowledgeScopeItems(origin){return KnowledgeNavigation.scopeItems(wikiItems,origin,matchesTag,VM.matchesFields);}
function knowledgeReadingGroups(item){const origin=state.wikiOrigin||KnowledgeNavigation.defaultOrigin(item),items=knowledgeScopeItems(origin);return[{label:knowledgeScopeLabel(origin),items},...(!items.some(p=>p.id===item.id)?[{label:'关联知识',items:[item]}]:[])];}
function selectKnowledge(item){state.wiki=item.id;document.querySelectorAll('.force-node').forEach(node=>node.classList.toggle('selected',node.dataset.path===item.id));if(state.page==='wiki'&&state.global&&state.graphTag)history.replaceState(null,'',KnowledgeNavigation.graphHash(knowledgeOrigin(item),item.id));}
function syncKnowledgeGraphRoute(){if(state.page==='wiki'&&state.global&&state.graphTag)history.replaceState(null,'',KnowledgeNavigation.graphHash(knowledgeOrigin(wikiItems.find(p=>p.id===state.wiki)||{}),state.wiki));}
function returnKnowledgeGraph(){if(state.wikiOrigin?.knowledgeMode==='materials'){state.knowledgeMode='materials';goTagOverview();return;}const item=wikiItems.find(p=>p.id===state.wiki),origin=state.wikiOrigin||(state.global&&state.graphTag?knowledgeOrigin(item||{}):KnowledgeNavigation.defaultOrigin(item||{}));state.page='wiki';state.global=true;state.graphTag=origin.graphTag;state.knowledgeMode=origin.knowledgeMode;state.fieldFilters={...origin.fieldFilters};state.graphContext=origin.graphContext;state.query=origin.query;state.wikiOrigin=null;history.pushState(null,'',KnowledgeNavigation.graphHash(origin,state.wiki));render({resetScroll:true});}
function restoreKnowledgeNavigation(parts){if(!state.global){state.wikiOrigin=parts.has('scope')?KnowledgeNavigation.parse(parts):null;if(state.wikiOrigin){state.fieldFilters={...state.wikiOrigin.fieldFilters};state.graphContext=state.wikiOrigin.graphContext;state.knowledgeMode=state.wikiOrigin.knowledgeMode;}}else if(state.graphTag){const origin=KnowledgeNavigation.parse(parts,state.graphTag);state.fieldFilters=origin.fieldFilters;state.graphContext=origin.graphContext;state.knowledgeMode=origin.knowledgeMode;state.query=origin.query;state.wikiOrigin=null;state.wiki=parts.get('node')||'';}else{state.wikiOrigin=null;state.fieldFilters={};state.graphContext=false;}}
function renderKnowledgeWorkspaceBar(){
 const bar=e('header','knowledge-workspace-bar'),crumbs=e('nav','knowledge-location');crumbs.setAttribute('aria-label','知识位置');
 const item=wikiItems.find(p=>p.id===state.wiki)||(!state.wiki&&!state.global?wikiItems[0]:null);if(item&&!state.global){state.wiki=item.id;if(!state.wikiOrigin)state.wikiOrigin=KnowledgeNavigation.defaultOrigin(item);state.knowledgeMode=state.wikiOrigin.knowledgeMode;}let origin=state.global?(state.graphTag?knowledgeOrigin(item||{}):null):(state.wikiOrigin||KnowledgeNavigation.defaultOrigin(item||{}));
 crumbs.append(button(state.knowledgeMode==='materials'?'来源资料':state.knowledgeMode==='skills'?'可复用方法':'全部知识','text-button',()=>{if(!state.global||state.graphTag)goTagOverview();}));
 if(origin){if(origin.knowledgeMode!=='materials')crumbs.append(e('span','location-sep','/'),button(knowledgeScopeLabel(origin),'text-button',()=>{if(!state.global)returnKnowledgeGraph();}));if(!state.global&&item){const title=e('span','location-title',item.title);title.title=item.title;title.setAttribute('aria-current','page');crumbs.append(e('span','location-sep','/'),title);}}
 bar.append(crumbs);
 const filters=origin?Object.entries(origin.fieldFilters).filter(([,value])=>value).map(([key,value])=>(VM.fieldLabels[key]||key)+' '+(value==='__missing'?'未记录':value)):[];if(filters.length)bar.append(e('span','workspace-filter-note','筛选：'+filters.join(' · ')));
 if(origin?.knowledgeMode==='materials'){document.title=(item?.title||'来源资料')+' · 知识工作区';bar.append(button('返回资料列表','button',()=>{state.knowledgeMode='materials';goTagOverview();}));return bar;}
 if(origin){document.title=(item&&!state.global?item.title:knowledgeScopeLabel(origin))+' · 知识工作区';const modes=e('div','knowledge-view-switch');modes.setAttribute('role','group');modes.setAttribute('aria-label','知识视图');const graph=button('图谱',state.global?'active':'',()=>{if(!state.global)returnKnowledgeGraph();});graph.setAttribute('aria-pressed',String(state.global));const candidates=knowledgeScopeItems(origin),selected=candidates.find(p=>p.id===state.wiki)||candidates[0];const read=button('阅读',!state.global?'active':'',()=>{if(state.global&&selected)openWikiReader(selected);});read.disabled=!selected;read.setAttribute('aria-pressed',String(!state.global));modes.append(graph,read);bar.append(modes);}else bar.append(e('span','workspace-hint',state.knowledgeMode==='materials'?'查看原图与提取记录':'选择知识域，开始浏览'));
 return bar;
}
