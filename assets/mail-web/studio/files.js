import { callTimeline } from "./call-trace.js";
// Existing oks:// mounts, measured on the server; no fabricated flame spans.
export function createFilesView({ dom, actions, api }) {
  const { $, el, button } = dom;
  let ticket = 0, uri = 'oks://', operation = 'ls', limit = 20000, offset = 0;
  function destroy() { ticket++; }
  async function render() {
    const current = ++ticket;
    let serial = 0;
    const host = el('div', 'file-workspace'), browser = el('section', 'file-browser'), detail = el('aside', 'call-detail');
    const tools = el('div', 'file-tools'), address = el('input'), body = el('div');
    address.value = uri; address.setAttribute('aria-label', '虚拟路径');
    const budget = el('input'); budget.type = 'number'; budget.min = 1; budget.max = 200000; budget.value = limit;
    budget.setAttribute('aria-label', '读取字符上限'); budget.title = '字符上限';
    budget.onchange = () => { limit = Math.max(1, Math.min(200000, Number(budget.value) || 20000)); if (operation !== 'ls') void load('read'); };
    tools.append(button('↑', () => {
      const next = uri.replace(/\/$/, '').split('/'); next.pop();
      uri = next.length > 2 ? next.join('/') + '/' : 'oks://'; offset = 0; void load('ls');
    }), address, budget, button('打开', open));
    address.onkeydown = e => { if (e.key === 'Enter') void open(); };
    browser.append(tools, body); host.append(browser, detail); $('content').append(host);
    function trace(record) {
      detail.replaceChildren(el('strong', null, `${record.operation} · ${record.total_ms.toFixed(3)} ms`), el('div', 'detail-meta', record.uri));
      detail.append(el('small', 'detail-meta', `${record.status} · ${record.output_bytes ?? '—'} B`));
      detail.append(callTimeline(dom, record));
      const attrs = el('details'); attrs.append(el('summary', null, '输入 / 输出'), el('pre', null, JSON.stringify(record, null, 2))); detail.append(attrs);
      if (record.comparison) detail.append(el('div', 'detail-meta', record.comparison.equivalent ? `输出一致 · VFS ${record.comparison.vfs_ms.toFixed(3)} / 直接 ${record.comparison.direct_ms.toFixed(3)} ms · 单次顺序测量` : '输出不一致'));
    }
    async function open() {
      uri = address.value; offset = 0; const requested = uri;
      try {
        const data = await api.request('/api/studio/fs?' + new URLSearchParams({uri, operation:'stat'}));
        if (current === ticket && requested === uri) await load(data.result.type === 'directory' ? 'ls' : 'read');
      } catch(error) { actions.status(error.message); }
    }
    async function history(requestNo) {
      const data = await api.request('/api/studio/fs-history');
      if (current !== ticket || requestNo !== serial) return;
      const list = el('div', 'call-history'); list.append(el('strong', null, '历史'));
      for (const record of data.records.slice(-12).reverse())
        list.append(button(`${record.operation} · ${record.total_ms.toFixed(2)} ms · ${record.uri}`, () => trace(record), 'file-entry'));
      detail.append(list);
    }
    async function load(nextOperation) {
      const requestNo = ++serial;
      operation = nextOperation;
      const requested = uri;
      address.value = uri;
      try {
        const data = await api.request('/api/studio/fs?' + new URLSearchParams({ uri, operation, limit, offset }));
        if (current !== ticket || requested !== uri || requestNo !== serial) return;
        body.replaceChildren();
        const result = data.result;
        if (result.entries) {
          for (const item of result.entries) body.append(button((item.type === 'directory' ? '▸ ' : '') + item.name, () => {
            uri = item.uri; offset = 0; void load(item.type === 'directory' ? 'ls' : 'read');
          }, 'file-entry'));
        } else if (typeof result.content === 'string') {
          body.append(button('同文件对比', () => load('compare'), 'soft'), el('pre', null, result.content));
          if (result.truncated) body.append(el('small', 'detail-meta', `${result.offset}–${result.offset + result.returned_chars} / ${result.total_chars} 字符`), button('下一段', () => {offset = result.next_offset; void load('read');}, 'soft'));
        } else body.append(el('pre', null, JSON.stringify(result, null, 2)));
        trace(data.trace); await history(requestNo);
      } catch (error) { if (current === ticket && requestNo === serial) { actions.status(error.message); await history(requestNo); } }
    }
    await load(operation);
  }
  return { render, destroy };
}
