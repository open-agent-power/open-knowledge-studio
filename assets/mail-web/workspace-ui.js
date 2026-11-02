'use strict';
window.OksWorkspace = (() => {
  let connection = null;
  const key = 'oks.connection.v1';
  const make = (tag, text) => { const n = document.createElement(tag); n.textContent = text; return n; };
  function read(key) { try { return JSON.parse(sessionStorage.getItem(key)); } catch { return null; } }
  function save(key, value) { try { sessionStorage.setItem(key, JSON.stringify(value)); } catch { /* optional session hints */ } }
  function recovery() {
    const cached = connection || read(key);
    let panel = document.getElementById('connectionRecovery');
    if (!panel) {
      panel = make('aside', ''); panel.id = 'connectionRecovery'; panel.className = 'connection-recovery'; panel.setAttribute('role', 'alert');
      (document.querySelector('main') || document.body).prepend(panel);
    }
    panel.replaceChildren(make('h2', '无法连接本地服务'), make('p', '请在终端启动对应知识库，再重试。服务关闭后，网页不会自行启动它。'));
    if (cached?.knowledge_base) panel.append(make('p', cached.knowledge_base));
    const command = cached?.commands?.resume || `oks mail serve --path '<知识库路径>' --port ${location.port || '3182'}`;
    panel.append(make('code', command));
    const actions = make('div', ''), copy = make('button', '复制启动指令'), retry = make('button', '重试连接');
    copy.type = retry.type = 'button';
    copy.addEventListener('click', async () => { try { await navigator.clipboard.writeText(command); copy.textContent = '已复制'; } catch { copy.textContent = '请手动复制上方指令'; } });
    retry.addEventListener('click', async () => {
      retry.disabled = true;
      try {
        const data = await request('/api/workspace'), changedRoot = !!connection && connection.knowledge_base !== data.knowledge_base;
        connection = data; save(key, {knowledge_base:data.knowledge_base,commands:{resume:data.commands.resume}});
        panel.hidden = true;
        document.dispatchEvent(new CustomEvent('oks:reconnected', {detail:{changedRoot,context:data}}));
      } catch { /* recovery guidance stays visible */ }
      finally { retry.disabled = false; }
    });
    actions.append(copy, retry); panel.append(actions); panel.hidden = false;
  }
  function message(text) {
    const value = String(text || '操作失败，请检查当前状态。');
    if (/Task already exists/i.test(value)) return '任务标识已存在，请更换标识。';
    if (/Goal changed/i.test(value)) return '目标已变化，请重新查看后创建任务。';
    if (/Wiki source changed/i.test(value)) return '知识来源已变化，请重新加载选择。';
    if (/Local editing is disabled/i.test(value)) return '当前为只读模式，请按页面指引启用本地编辑。';
    if (/Bundled Skill changed/i.test(value)) return '内置 Skill 已变化，请重新比较后准备草稿。';
    return value;
  }
  async function request(url, options = {}) {
    let response;
    try { response = await fetch(url, {cache:'no-store', ...options}); }
    catch { recovery(); throw Error('本地服务连接已断开，请按上方指引恢复。'); }
    let data;
    try { data = await response.json(); } catch { throw Error('无法识别服务响应，请核对启动端口。'); }
    if (data.code === 'instance_changed') recovery();
    if (!response.ok) throw Error(message(data.error || '读取失败，请重试。'));
    return data;
  }
  const ready = request('/api/workspace').then(data => {
    connection = data;
    // Only the public instance path and restart command are cached, never private feedback.
    save(key, {knowledge_base:data.knowledge_base, commands:{resume:data.commands.resume}});
    return data;
  }).catch(() => null);
  return {request, ready, recovery, context:() => connection,
    rememberScope(scope) { if (connection) save('oks.review-labels.v1', {knowledge_base:connection.knowledge_base,subject:scope.subject, project:scope.project}); },
    scopeHint() { const value = read('oks.review-labels.v1'); return value?.knowledge_base === connection?.knowledge_base ? value : null; }
  };
})();
