// A document outline is a definition, never evidence that its steps ran.
export async function showWorkflow(container, node, {el, api, active}) {
  container.replaceChildren(el('span','detail-meta','读取中…'));
  try {
    const data = await api.request('/api/studio/workflow?' + new URLSearchParams({path:node.path}));
    if (!active()) return;
    container.replaceChildren();
    const references = el('section','workflow-references');
    references.append(el('h3',null,'文档引用'));
    if (!data.references.length) references.append(el('small','detail-meta','未声明关联'));
    for (const edge of data.references) {
      const row = el('div','workflow-reference');
      row.append(el('code',null,edge.from),el('span',null,'引用 ↓'),el('code',null,edge.to));
      references.append(row);
    }
    container.append(references);
    const definition = el('section','workflow-definition');
    definition.append(el('h3',null,'文档结构'),el('small','detail-meta','定义 · 不代表已执行'));
    for (const row of data.outline) {
      const step = el('div','workflow-step',row.text);
      step.style.setProperty('--step-indent',Math.min(5, row.level - 1));
      step.title = `${data.path}:${row.line+1}`;
      definition.append(step);
    }
    container.append(definition);
    const recorded = el('section','workflow-recorded');
    recorded.append(el('h3',null,'执行记录'));
    if (!data.runs.length) recorded.append(el('small','detail-meta','未找到执行记录'));
    for (const run of data.runs) {
      recorded.append(el('code','detail-path',`${run.run_id} · ${run.status}`));
      if (run.skill_only) recorded.append(el('small','detail-meta','仅显示明确关联此技能的事件'));
      for (const event of run.events) {
        const step = el('div','workflow-step recorded');
        step.append(el('span',null,event.payload.title || event.event_type),
          el('small',null,`${event.actor} · ${event.timestamp || ''}`));
        if (event.payload.step_id || event.payload.skill_path)
          step.append(el('code',null,[event.payload.skill_path,event.payload.step_id].filter(Boolean).join(' · ')));
        if (event.payload.summary) step.append(el('small',null,event.payload.summary));
        step.title = event.event_id; recorded.append(step);
      }
      if (run.truncated) recorded.append(el('small','detail-meta','仅展示前 500 条记录'));
    }
    container.append(recorded);
    for (const warning of data.warnings) container.append(el('small','detail-meta',warning));
  } catch (error) {
    if (active()) container.replaceChildren(el('small','detail-meta',error.message));
  }
}
