'use strict';
const $ = id => document.getElementById(id);
const el = (tag, text, className) => { const item = document.createElement(tag); item.textContent = text == null ? '' : String(text); if (className) item.className = className; return item; };
let localReview = false, currentScope = null, events = [], candidates = [], draft = null, draftSequence = 0, scopeSequence = 0;
const asText = value => typeof value === 'string' ? value : JSON.stringify(value, null, 2);
function friendlyError(message) {
  const text = String(message || '操作失败，请重新读取当前状态。');
  if (/Candidate changed|already reviewed/i.test(text)) return '这条建议已变化或已处理，请重新读取范围。';
  if (/Only current approved candidates|Source inactive or stale/i.test(text)) return '来源状态已变化，当前不能分享草稿。';
  if (/Draft changed/i.test(text)) return '草稿内容已变化，请重新查看后再保存。';
  if (/Local review is disabled/i.test(text)) return '本地审核未启用，写操作已拒绝。';
  if (/Cannot read this exact private scope/i.test(text)) return '无法读取此范围，请核对填写内容；原记录未更改。';
  return text;
}
async function request(url, options) {
  try { return await OksWorkspace.request(url, options); }
  catch (error) { throw Error(friendlyError(error.message)); }
}
function jsonPost(url, body) { return request(url, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); }
function revisionOf(candidate) { const value = candidate.expected_revision ?? candidate.revision; return typeof value === 'string' && /^[0-9a-f]{64}$/.test(value) ? value : null; }
function candidateId(candidate) { return candidate.candidate_id ?? candidate.id ?? candidate.slug ?? ''; }
function effectiveStatus(candidate) { return String(candidate.effective_status || candidate.status || '').toLowerCase(); }
function statusLabel(status) { return ({pending:'待审核',pending_review:'待审核',candidate:'待审核',approved:'已确认',rejected:'已拒绝',withdrawn:'已撤回',invalidated:'来源变更'})[status] || '状态待核对'; }
function setStatus(id, text, state = '') { $(id).textContent = text; $(id).dataset.state = state; }
function scopeValue() { return {subject:$('subject').value.trim(),project:$('project').value.trim(),task:$('task').value.trim()}; }
function canWrite() { return localReview; }
function updateDraftControls() {
  $('promote').disabled = !(canWrite() && draft && $('confirmReview').checked);
  $('confirmReview').disabled = !(localReview && draft);
  $('readDraft').disabled = !$('draftPath').value.trim();
}
function startupCommand(root = '') { return `oks mail serve --path "${root || '<知识库路径>'}" --local-review`; }
async function loadCapability() {
  try {
    const data = await request('/api/mail/capabilities');
    localReview = data.local_review === true;
    setStatus('capabilityStatus', localReview ? '本地审核已启用。写操作仍需逐项触发。' : '本地审核未启用；可读取显式范围数据，写操作保持禁用。', localReview ? 'ready' : 'disabled');
    $('localGate').hidden = localReview;
    const workspace = await request('/api/workspace');
    $('serveCommand').textContent = workspace.commands.review;
  } catch (error) {
    localReview = false;
    $('localGate').hidden = false;
    $('serveCommand').textContent = startupCommand();
    setStatus('capabilityStatus', '无法确认本地审核能力，所有写操作保持禁用：' + error.message, 'error');
  }
  updateDraftControls();
  renderCandidates();
}
function eventMap() { return new Map(events.map(event => [String(event.event_id), event])); }
function renderEvents() {
  const host = $('events'); host.replaceChildren();
  if (!events.length) { host.append(el('p', '此范围暂无事件。', 'empty')); return; }
  for (const event of events) {
    const card = el('article', '', 'event-card');
    card.append(el('h3', event.status === 'withdrawn' ? '已撤回' : '反馈记录'));
    const payload = event.payload || {};
    if (payload.action) card.append(el('p', '操作：' + ({observed:'已查看',adopted:'已采用',revised:'已修改',rejected:'已拒绝'}[payload.action] || '已记录')));
    if (payload.reason) card.append(el('p', '原因：' + payload.reason));
    if (payload.asset?.path) card.append(el('p', '来源：' + payload.asset.path));
    const details = el('details'), summary = el('summary', '完整事件记录');
    const agreement = payload.agreement || {};
    details.append(summary, el('pre', JSON.stringify(event, null, 2))); card.append(details); host.append(card);
  }
}
async function mutate(url, body, message) {
  const originalScope = body.scope ? {...body.scope} : null;
  try {
    const result = await jsonPost(url, body);
    setStatus('scopeStatus', message || '操作已完成。');
    if (url.endsWith('/export')) {
      if (result.path) {
        $('draftPath').value = result.path;
        await loadDraft(result.path);
        setStatus('draftStatus', '草稿已生成。请检查完整内容，再勾选确认保存到 Wiki。');
      } else setStatus('draftStatus', '草稿已生成，但没有返回路径。请核对当前状态。', 'error');
    } else if (originalScope && ['subject','project','task'].every(key => originalScope[key] === scopeValue()[key])) await inspect(originalScope);
    return result;
  } catch (error) {
    setStatus('scopeStatus', error.message, 'error');
    return null;
  }
}
function button(label, action, disabled, handler) {
  const item = el('button', label); item.type = 'button'; item.dataset.action = action; item.disabled = disabled; item.addEventListener('click', handler); return item;
}
function renderCandidates() {
  const host = $('candidates'); host.replaceChildren();
  if (!candidates.length) { host.append(el('p', currentScope ? '此范围没有返回候选。' : '先填写范围并读取。', 'empty')); return; }
  const map = eventMap();
  for (const candidate of candidates) {
    const id = candidateId(candidate), rev = revisionOf(candidate), status = effectiveStatus(candidate);
    const canReview = canWrite() && !!id && rev !== null && ['pending','pending_review','candidate'].includes(status);
    const approved = canWrite() && !!id && rev !== null && status === 'approved';
    const card = el('article', '', 'candidate-card'), head = el('div', '', 'candidate-head');
    const label = statusLabel(status);
    head.append(el('h3', candidate.title || candidate.summary || '学习建议'), el('span', label, 'candidate-state'));
    card.append(head);
    card.querySelector('.candidate-state').dataset.state = status;
    if (candidate.summary && candidate.title) card.append(el('p', candidate.summary));
    if (rev === null) card.append(el('p', '来源版本信息不完整，不能审核。', 'file-warning'));
    const linked = (candidate.event_ids || []).map(key => map.get(String(key))).filter(Boolean);
    if (linked.length) {
      const evidence = el('details'), summary = el('summary', `关联事件证据 · ${linked.length}`), list = el('div');
      for (const event of linked) {
        const wrapper = el('section'); wrapper.append(el('p', `${event.event_id} · ${event.status || ''}`), el('pre', JSON.stringify(event.payload || {}, null, 2))); list.append(wrapper);
      }
      evidence.append(summary, list); card.append(evidence);
    } else if (candidate.event_ids?.length) card.append(el('p', `关联事件：${candidate.event_ids.join(', ')}（本次返回中未找到详情）`));
    const raw = el('details'), summary = el('summary', '候选原始记录'); raw.append(summary, el('pre', JSON.stringify(candidate, null, 2))); card.append(raw);
    const actions = el('div', '', 'candidate-actions');
    if (['pending','pending_review','candidate'].includes(status)) {
      actions.append(button('批准', 'approve', !(canReview && $('comment').value.trim()), () => reviewCandidate(candidate, 'approve')));
      actions.append(button('拒绝', 'reject', !(canReview && $('comment').value.trim()), () => reviewCandidate(candidate, 'reject')));
    }
    if (status === 'approved') {
      actions.append(button('撤回', 'withdraw', !approved, () => withdrawCandidate(candidate)));
      actions.append(button('分享为草稿', 'export', !(approved && $('confirmShare').checked), () => exportCandidate(candidate)));
    }
    if (!localReview && actions.children.length) for (const action of actions.children) action.disabled = true;
    if (actions.children.length) card.append(actions);
    if (!id || !rev) card.append(el('p', '此建议记录不完整，暂不能操作。', 'file-warning'));
    host.append(card);
  }
}
async function inspect(scope) {
  const ticket = ++scopeSequence;
  currentScope = {...scope}; events = []; candidates = []; renderCandidates(); renderEvents();
  setStatus('scopeStatus', '正在读取指定范围…');
  try {
    const data = await jsonPost('/api/feedback/inspect', {scope:{...scope}});
    if (ticket !== scopeSequence) return;
    OksWorkspace.rememberScope(scope);
    events = Array.isArray(data.events) ? data.events : [];
    candidates = Array.isArray(data.candidates) ? data.candidates : [];
    renderEvents(); renderCandidates();
    setStatus('scopeStatus', `读取完成：${events.length} 个事件，${candidates.length} 个候选。`);
  } catch (error) { if (ticket === scopeSequence) setStatus('scopeStatus', error.message, 'error'); }
}
async function reviewCandidate(candidate, decision) {
  const comment = $('comment').value.trim(), revision = revisionOf(candidate), id = candidateId(candidate);
  if (!comment) { setStatus('scopeStatus', '批准或拒绝前请填写审核说明。', 'error'); $('comment').focus(); return; }
  if (!id || revision === null) { setStatus('scopeStatus', '无法确认这条建议的当前状态，请重新读取。', 'error'); return; }
  await mutate('/api/feedback/review', {scope:{...currentScope},candidate_id:id,expected_revision:revision,decision,comment}, decision === 'approve' ? '已提交批准决定。' : '已提交拒绝决定。');
}
async function withdrawCandidate(candidate) {
  const revision = revisionOf(candidate), id = candidateId(candidate);
  if (!id || revision === null) return;
  await mutate('/api/feedback/withdraw-candidate', {scope:{...currentScope},candidate_id:id,expected_revision:revision}, '已提交撤回操作。');
}
async function exportCandidate(candidate) {
  const revision = revisionOf(candidate), id = candidateId(candidate);
  if (!id || revision === null || !$('confirmShare').checked) return;
  await mutate('/api/feedback/export', {scope:{...currentScope},candidate_id:id,expected_revision:revision,confirm_share:true}, '已导出共享Draft。');
}
async function loadDraft(path) {
  const ticket = ++draftSequence; draft = null; $('confirmReview').checked = false; updateDraftControls();
  setStatus('draftStatus', '正在读取完整 Draft…'); $('draftPreview').replaceChildren(); $('promoteStatus').textContent = '';
  if (!path) return;
  try {
    const data = await request('/api/learning/draft?path=' + encodeURIComponent(path));
    if (ticket !== draftSequence) return;
    if (typeof data.text !== 'string' || typeof data.sha256 !== 'string' || !data.path) throw Error('草稿无法完整读取，请核对路径后重试。');
    draft = {path:data.path,sha256:data.sha256,text:data.text};
    const header = el('header', ''), integrity = el('details', ''), pre = el('pre', data.text);
    header.append(el('p', data.path)); integrity.append(el('summary', '来源版本'), el('code', data.sha256));
    $('draftPreview').replaceChildren(header, integrity, pre);
    setStatus('draftStatus', '草稿已完整读取。请检查内容和来源，再勾选确认。');
    $('confirmReview').disabled = !canWrite();
  } catch (error) { if (ticket === draftSequence) setStatus('draftStatus', error.message, 'error'); }
  updateDraftControls();
}
$('scopeForm').addEventListener('submit', event => { event.preventDefault(); const scope = scopeValue(); if (Object.values(scope).some(value => !value)) { setStatus('scopeStatus', '请填写使用者、项目和任务。', 'error'); return; } inspect(scope); });
for (const id of ['subject','project','task']) $(id).addEventListener('input', () => {
  ++scopeSequence; currentScope = null; events = []; candidates = [];
  renderCandidates(); renderEvents(); setStatus('scopeStatus', '范围已变化，请重新读取。');
});
$('confirmShare').addEventListener('change', renderCandidates);
$('comment').addEventListener('input', renderCandidates);
$('draftPath').addEventListener('input', updateDraftControls);
$('draftForm').addEventListener('submit', event => { event.preventDefault(); loadDraft($('draftPath').value.trim()); });
$('confirmReview').addEventListener('change', updateDraftControls);
$('promote').addEventListener('click', async () => {
  if (!canWrite() || !draft || !$('confirmReview').checked) return;
  $('promote').disabled = true; setStatus('promoteStatus', '正在提交晋升…');
  try {
    const result = await jsonPost('/api/learning/promote', {path:draft.path,expected_sha256:draft.sha256,confirm_review:true});
    setStatus('promoteStatus', `已保存到 Wiki：${result.path || draft.path}`);
    $('promoteHandoff').replaceChildren();
    if (result.path) {
      const command = `oks task start <new-task-id> --goal profiles/goals/<goal>.md --wiki ${result.path}`;
      const link = el('a', result.path); link.href = '/#wiki-reader&path=' + encodeURIComponent(result.path); link.className = 'source-link';
      const code = el('code', command), copy = el('button', '复制来源参数'); copy.type = 'button';
      copy.addEventListener('click', async () => { try { await navigator.clipboard.writeText('--wiki ' + result.path); copy.textContent = '已复制'; } catch { copy.textContent = '--wiki ' + result.path; } });
      $('promoteHandoff').append(el('p', '新任务需要时，可显式加入这条 Wiki 来源：'), link, code, copy);
      $('promoteHandoff').hidden = false;
    }
    $('confirmReview').checked = false; draft = null; updateDraftControls();
  } catch (error) { setStatus('promoteStatus', error.message, 'error'); updateDraftControls(); }
});
loadCapability();
OksWorkspace.ready.then(() => {
  const hint = OksWorkspace.scopeHint(), task = new URLSearchParams(location.search).get('task');
  if (hint) { $('subject').value = hint.subject || ''; $('project').value = hint.project || ''; }
  if (task && /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$/.test(task)) $('task').value = task;
  if (hint || task) setStatus('scopeStatus', '请确认上方范围，再点击“读取”。尚未读取私人内容。');
});
document.addEventListener('oks:reconnected', event => {
  ++scopeSequence; ++draftSequence; currentScope = null; events = []; candidates = []; draft = null;
  if (event.detail.changedRoot) {
    for (const id of ['subject','project','task','draftPath']) $(id).value = '';
    history.replaceState(null, '', '/review');
  }
  $('draftPreview').replaceChildren(); $('confirmReview').checked = false;
  $('promoteHandoff').replaceChildren(); $('promoteHandoff').hidden = true;
  renderCandidates(); renderEvents(); updateDraftControls(); loadCapability();
  setStatus('scopeStatus', '连接已恢复，请重新确认范围并读取。');
});
const draftParam = new URLSearchParams(location.search).get('draft');
if (draftParam) { $('draftPath').value = draftParam; loadDraft(draftParam); }
