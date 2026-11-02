'use strict';
const knowledgeModeNames={domains:'知识域',tags:'全部标签',skills:'可复用方法',materials:'来源资料'};
const skillTypeNames={concept:'概念',strategy:'策略','anti-pattern':'反策略',unclassified:'未分类'};
function goDomainGraph(id){state.knowledgeMode='domains';goTagGraph('domain:'+id);}
function goSkillGraph(type){state.knowledgeMode='skills';goTagGraph('skills:'+type);}
function knowledgeSourceNote(){
 const source=store.knowledge?.worker_source||{};const note=e('div','knowledge-source '+(source.state||'unconfigured'));
 const labels={live:source.origin==='fixture'?'隔离验收数据':'飞书采集 · 只读',stale:'飞书读取失败 · 保留历史快照',error:'飞书采集读取失败',unconfigured:'本地知识文件'};
 note.append(e('strong',null,labels[source.state]||'本地字段快照'));
 if(source.observed_at)note.append(e('span',null,'读取于 '+date(source.observed_at)));
 if(source.observed_at)note.append(e('span',null,`${source.records_count} 条采集记录 · ${source.linked_records} 条关联到当前知识`));
 const ordinary=wikiItems.filter(p=>!p.isSkill&&!p.isMaterial);if(ordinary.length&&ordinary.every(p=>p.classification?.source?.startsWith('本地 area')))note.append(e('span',null,'分类依据：本地 area'));
 if(source.partial)note.append(e('b',null,'只返回部分采集记录，未覆盖全部历史'));
 if(source.missing_fields?.length){const details=append(e('details'),e('summary',null,'缺少 '+source.missing_fields.length+' 个来源字段'));details.append(e('p',null,source.missing_fields.join('、')));note.append(details);}
 return note;
}
function workerFieldTable(record){
 const table=e('table','property-table worker-fields');table.setAttribute('aria-label','Worker 原始字段');
 const fields=store.knowledge?.worker_source?.field_names||['知识域','评级','总结','思考','重点问题（可选）','Wiki状态','质量状态','审核动作','审核时间','审核意见','运行状态','Raw Bundle','Wiki路径','运行ID'];
 fields.forEach(key=>table.append(append(e('tr'),e('td',null,key),e('td',null,record.fields?.[key]||'未记录'))));return table;
}
function workerIdentity(record){const source=record.source||{};return e('div','drawer-path',`Base ${source.base_token_hash||'未记录'} / ${source.table_id||'未记录'} / ${source.record_id||'未记录'} · ${record.observed_at?date(record.observed_at):'读取时间未记录'} · ${record.state||'snapshot'}`);}
function openWorkerRecord(record){const title=VM.short(record.fields?.['总结']||record.fields?.['思考']||record.fields?.['内容']||record.source?.record_id||'采集记录',80);const links=e('div','graph-node-actions');(record.linked_paths||[]).forEach(path=>{const item=wikiItems.find(p=>p.id===path);if(item)links.append(button('阅读关联知识 · '+item.title,'button',()=>{$('inspector').close();openWikiReader(item);}));});openDrawer('飞书采集记录 · 不等于已入库知识',title,[workerIdentity(record),workerFieldTable(record),links]);}
function itemWorkerFacts(item){
 const details=append(e('details','secondary-records worker-item-facts'),e('summary',null,item.isMaterial?'资料状态与采集来源':item.isSkill?'Skill 治理与来源':'知识状态与采集来源'));
 details.append(e('p',null,(item.isMaterial?'本地资料状态：':'本地知识状态：')+(item.status||'未记录')),e('p',null,item.isMaterial?'文字校对：'+(item.metadata?.ocr_review_status==='unreviewed'?'未经校对':'以原文记录为准'):'人工审核：'+(item.review?.label||'审核记录未知')));
 if(item.isSkill){const type=item.governance?.type;details.append(e('p',null,'方法类型：'+(skillTypeNames[type]||type||'未记录')),e('p',null,'身份来自文件中的明确 Skill 元数据，类型不用于普通知识分类。'));}
 else details.append(e('p',null,'分类依据：'+(item.classification?.source||'未记录')+' · '+(item.classification?.raw_values||[]).join('、')));
 if(item.classification?.source_disagrees)details.append(e('p','candidate-note','采集端分类与本次审核分类不同；当前采用审核分类，历史值保留为来源记录。'));
 if(!item.workerRecords?.length)details.append(e('p',null,'未关联飞书采集记录。'));
 (item.workerRecords||[]).forEach(record=>details.append(workerIdentity(record),workerFieldTable(record)));
 return details;
}
function renderIntakeRecords(host){
 const source=store.knowledge?.worker_source||{},records=source.records||[];if(!records.length)return;
 const details=append(e('details','worker-intake'),e('summary',null,`飞书采集记录 · ${records.length} 条（${records.length-(source.linked_records||0)} 条尚未关联当前知识）`));details.append(e('p','side-copy','采集记录与 Wiki 分开展示；只有明确的路径或完整来源标识才建立关联。'));
 const search=e('input');search.type='search';search.placeholder='搜索采集记录';search.setAttribute('aria-label','搜索采集记录');const list=e('div','intake-records'),selectors=e('div','knowledge-filters');const filters={};let count=20;const more=button('加载更多采集记录','button',()=>{count+=40;fill();});
 for(const key of ['评级','质量状态','Wiki状态']){const values=[...new Set(records.map(r=>r.fields[key]).filter(Boolean))].sort();if(!values.length)continue;const label=e('label',null,VM.fieldLabels[key]),select=e('select');select.setAttribute('aria-label','筛选'+VM.fieldLabels[key]);const empty=e('option',null,'全部');empty.value='';select.append(empty);for(const value of values){const option=e('option',null,value);option.value=value;select.append(option);}select.onchange=()=>{filters[key]=select.value;count=20;fill();};label.append(select);selectors.append(label);}
 function fill(){list.replaceChildren();const q=search.value.trim().toLocaleLowerCase();const matched=records.filter(r=>JSON.stringify(r.fields).toLocaleLowerCase().includes(q)&&Object.entries(filters).every(([k,v])=>!v||r.fields[k]===v));matched.slice(0,count).forEach(record=>{const row=button('','intake-record',()=>openWorkerRecord(record));row.append(e('strong',null,VM.short(record.fields['总结']||record.fields['思考']||record.fields['内容']||record.source.record_id,85)),e('span',null,`评级 ${record.fields['评级']||'未记录'} · 质量 ${record.fields['质量状态']||'未记录'} · Wiki ${record.fields['Wiki状态']||'未记录'}`));list.append(row);});more.hidden=matched.length<=count;if(!matched.length)list.append(e('p','side-copy','没有匹配的采集记录。'));}
 search.oninput=()=>{count=20;fill();};details.append(search,selectors,list,more);host.append(details);fill();
}
function sourceMaterialCollectionCover(collection){
 const cover=e('section','source-collection-cover');
 cover.append(e('span','source-collection-kicker','来源资料集合'),e('h3',null,collection.title));
 cover.append(e('p',null,'原图是依据，OCR 文字是未校对的辅助文本。这个集合不是普通知识，不进入知识域、图谱或自动召回。'));
 const stats=e('div','source-collection-stats');
 stats.append(append(e('span'),e('strong',null,String(collection.count)),e('small',null,'份资料')),append(e('span'),e('strong',null,String(collection.unreviewedCount)),e('small',null,'份未校对')));
 const other=Object.entries(collection.statusCounts).filter(([status])=>status!=='unreviewed').reduce((sum,[,count])=>sum+count,0);
 stats.append(append(e('span'),e('strong',null,String(other)),e('small',null,'份其他状态')));cover.append(stats);
 return cover;
}
function renderKnowledgeOverview(scroll){
 const mode=state.knowledgeMode||'domains';state.fieldFilters=state.fieldFilters||{};
 const box=e('div','tag-hub'),head=e('header','tag-hub-head');head.append(append(e('div'),e('h2',null,mode==='materials'?'来源资料':mode==='skills'?'可复用方法':mode==='tags'?'知识标签':'知识域')));
  const actions=e('div','tag-hub-actions');actions.append(button(mode==='skills'?'全部 Skills 图谱 ↗':'全部知识图谱 ↗','button',()=>mode==='skills'?goSkillGraph('all'):goTagGraph('全部知识')));if(mode!=='materials')head.append(actions);box.append(head,knowledgeSourceNote());if(mode==='materials')box.append(sourceMaterialCollectionCover(VM.sourceMaterialCollection(wikiItems)));
 const tabs=e('div','inline-tabs knowledge-tabs');Object.entries(knowledgeModeNames).forEach(([id,name])=>tabs.append(button(name,mode===id?'active':'',()=>{state.knowledgeMode=id;state.query='';state.fieldFilters={};history.replaceState(null,'','#wiki-overview&mode='+id);render();})));box.append(tabs);
 const tools=e('div','tag-hub-tools'),count=e('span'),cards=e('div','tag-cards');tools.append(makeSearch(mode==='materials'?'搜索来源资料':mode==='skills'?'搜索方法':'搜索知识域、标签或知识标题',fill),count);box.append(tools);
 const filters=e('div','knowledge-filters');if(!['skills','materials'].includes(mode))for(const key of ['评级','质量状态','Wiki状态']){const values=VM.fieldOptions(wikiItems.filter(p=>!p.isSkill&&!p.isMaterial),key,state.fieldFilters[key]);if(!values.length)continue;const label=e('label',null,VM.fieldLabels[key]),select=e('select');select.setAttribute('aria-label','筛选'+VM.fieldLabels[key]);const all=e('option',null,'全部');all.value='';select.append(all);for(const value of values){const option=e('option',null,value==='__missing'?'未记录':value);option.value=value;option.selected=state.fieldFilters[key]===value;select.append(option);}select.onchange=()=>{state.fieldFilters[key]=select.value;fill();};label.append(select);filters.append(label);}if(filters.childElementCount)box.append(filters);box.append(cards);scroll.append(box);
 function fill(){cards.replaceChildren();const base=wikiItems.filter(p=>mode==='materials'?p.isMaterial:!p.isMaterial&&p.isSkill===(mode==='skills')).filter(p=>VM.matchesFields(p,state.fieldFilters));let groups;
  if(mode==='materials'){const q=state.query.trim().toLocaleLowerCase();const matched=base.filter(p=>[p.title,p.summary,p.body,...p.tags].join(' ').toLocaleLowerCase().includes(q));count.textContent=matched.length+' 份来源资料';matched.forEach(item=>{const card=button('','tag-card material-card',()=>openWikiReader(item));card.append(e('strong',null,item.title),e('p',null,item.summary),e('small',null,'机器提取资料 · '+(item.metadata?.ocr_review_status==='unreviewed'?'文字未校对':'校对状态以原文为准')),e('span',null,'查看原图与提取文字 →'));cards.append(card);});if(!matched.length)cards.append(e('p','tag-empty','没有匹配的来源资料。'));return;}
  if(mode==='skills'){const types=[...Object.keys(skillTypeNames),...new Set(base.map(p=>p.governance?.type).filter(Boolean))];groups=[...new Set(types)].map(type=>({id:type,label:skillTypeNames[type]||type,items:base.filter(p=>(p.governance?.type||'unclassified')===type)})).filter(g=>g.items.length);}
  else if(mode==='tags')groups=collectTagGroups(base,getWikiTags);else groups=VM.domainGroups(base);
  const q=state.query.trim().toLocaleLowerCase();groups=groups.filter(g=>[g.label,...g.items.flatMap(p=>[p.title,...p.tags])].join(' ').toLocaleLowerCase().includes(q));
  count.textContent=base.length+(mode==='skills'?' 个 Skill 条目':' 篇知识')+' · '+groups.length+' 个分类';
  groups.forEach(group=>{const open=()=>mode==='skills'?goSkillGraph(group.id):mode==='domains'?goDomainGraph(group.id):goTagGraph(group.label);const card=button('','tag-card',open);card.setAttribute('aria-label','展开'+(mode==='domains'?'知识域 ':mode==='skills'?'Skill 类型 ':'标签 ')+group.label);card.style.setProperty('--tag-color',tagColor(group.id));card.append(append(e('span','tag-card-head'),e('strong',null,group.label),e('span','tag-card-count',group.items.length+' 篇')),tagMiniArt(group.items,tagColor(group.id)),e('span','tag-card-items',group.items.slice(0,3).map(p=>p.title).join(' · ')),append(e('span','tag-card-foot'),e('small',null,group.id==='_unmapped'?'保留历史领域，未自动映射':group.items.some(p=>p.kind==='candidate')?'包含待审核候选':mode==='skills'?'Skill 条目':'Wiki 条目'),e('span',null,'展开完整图谱 ↗')));cards.append(card);});
  if(!groups.length)cards.append(e('p','tag-empty','当前筛选下没有条目。缺失字段不会当成已完成或已通过。'));
 }
 fill();if(!['skills','materials'].includes(mode))renderIntakeRecords(box);box.append(e('p','tag-hub-note',mode==='materials'?'只展示明确标记的提取资料；旧文件和来源链接保留，未改变校对与审核状态。':mode==='skills'?'Skill 类型只用于插拔治理；浏览不安装、启用或改写包。':'分类不改写知识文件。同一知识可属于多个已声明知识域；标签不自动生成关系。'));
}
