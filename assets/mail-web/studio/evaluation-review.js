export function createEvaluationReview({ dom, actions, api }) {
  const { el, button } = dom;
  let ticket = 0;
  function destroy() { ticket++; }
  async function render(host) {
    const current = ++ticket;
    try {
      const data = await api.request('/api/evaluation/candidates');
      if (current !== ticket) return;
      const bar = el('div', 'file-tools'), enabled = el('input'), retain = el('input');
      enabled.type = retain.type = 'checkbox'; enabled.checked = data.preferences.capture_enabled; retain.checked = data.preferences.retain_query;
      for (const [input, title] of [[enabled, '扩展查询记录'], [retain, '保留查询原文']]) { const label = el('label'); label.append(input, document.createTextNode(title)); bar.append(label); }
      bar.append(button('保存', async () => {
        try { await api.post('/api/evaluation/preferences', { values: { capture_enabled: enabled.checked, retain_query: retain.checked } }); }
        catch (error) { actions.status(error.message); }
      }, 'soft'));
      const exportName = el('input'); exportName.placeholder = '数据集名称'; exportName.setAttribute('aria-label', '导出数据集名称'); bar.append(exportName);
      for (const [kind, title] of [['recall', '导出评测集'], ['preference', '导出偏好对']]) bar.append(button(title, async () => {
        try { const value = await api.post('/api/evaluation/export', { name: exportName.value, kind }); actions.status(value.path || `${value.case_count} 条`); }
        catch (error) { actions.status(error.message); }
      }, 'soft'));
      host.append(bar, el('small', 'detail-meta', '采纳是信号；未确认不等于拒绝。仅审核标签进入导出。'));
      const layout = el('div', 'file-workspace'), list = el('div', 'file-browser'), detail = el('div', 'call-detail'); layout.append(list, detail); host.append(layout);
      for (const item of data.items) list.append(button(`${item.status === 'reviewed' ? '✓ ' : '○ '}${item.query || item.id}`, () => select(item), 'file-entry'));
      if (!data.items.length) list.append(el('small', 'detail-meta', '0 条候选'));
      function select(item) {
        detail.replaceChildren();
        const query = el('textarea'); query.value = item.query || ''; query.placeholder = '审核查询'; query.setAttribute('aria-label', '审核查询'); query.style.width = '100%'; detail.append(query);
        const labels = new Map();
        const add = (slug) => {
          if (!slug || labels.has(slug)) return;
          const row = el('div', 'file-tools'), select = el('select');
          for (const [value, text] of [['', '未确认'], ['accepted', '接受'], ['rejected', '拒绝']]) { const option = el('option', null, text); option.value = value; select.append(option); }
          select.value = item.review?.decisions?.[slug]?.decision || '';
          row.append(el('span', null, slug), select); detail.append(row); labels.set(slug, select);
        };
        for (const hit of item.hits) add(hit.slug);
        for (const slug of Object.keys(item.review?.decisions || {})) add(slug);
        const extra = el('input'); extra.placeholder = '补充 Wiki slug'; extra.setAttribute('aria-label', '补充 Wiki slug'); detail.append(extra, button('+', () => add(extra.value.trim()), 'soft'));
        const reason = el('textarea'); reason.placeholder = '拒绝原因'; reason.setAttribute('aria-label', '拒绝原因'); reason.style.width = '100%'; detail.append(reason);
        const derived = el('input'), confirm = el('input'); derived.type = confirm.type = 'checkbox';
        for (const [input, text] of [[derived, '确认补充或改写了原查询'], [confirm, '确认审核结果']]) { const label = el('label'); label.style.display = 'block'; label.append(input, document.createTextNode(text)); detail.append(label); }
        detail.append(button('保存审核', async () => {
          const values = { accept: [], reject: [], clear: [] };
          for (const [slug, input] of labels) values[input.value === 'accepted' ? 'accept' : input.value === 'rejected' ? 'reject' : 'clear'].push(slug);
          try {
            const updated = await api.post('/api/evaluation/review', { id: item.id, query: query.value, ...values, reason: reason.value,
              confirm: confirm.checked, derived_query: derived.checked, expected_sha256: item.review_sha256 });
            if (current === ticket) { item.review = updated.review; item.review_sha256 = updated.review_sha256; actions.status('已保存'); }
          } catch (error) { actions.status(error.message); }
        }, 'soft'));
        const signals = el('details'); signals.append(el('summary', null, '来源与信号'), el('pre', null, JSON.stringify({ source: item.source, adoption: item.adoption, signals: item.signals, hits: item.hits }, null, 2))); detail.append(signals);
      }
    } catch (error) { if (current === ticket) actions.status(error.message); }
  }
  return { render, destroy };
}
