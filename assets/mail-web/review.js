'use strict';
const $ = id => document.getElementById(id);
const el = (tag, text, className) => { const item = document.createElement(tag); item.textContent = text == null ? '' : String(text); if (className) item.className = className; return item; };
let localReview = false, currentScope = null, events = [], candidates = [], draft = null, draftSequence = 0, scopeSequence = 0;
const conditionEdits = new Map();
const reviewNotes = new Map();
const asText = value => typeof value === 'string' ? value : JSON.stringify(value, null, 2);
function friendlyError(message) {
  const text = String(message || '操作失败，请重新读取当前状态。');
  if (/Candidate changed|already reviewed/i.test(text)) return '这条建议已变化或已处理，请重新读取范围。';
  if (/Only current approved candidates|Source inactive or stale/i.test(text)) return '来源状态已变化，当前不能生成共享草稿。';
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
function statusLabel(status) { return ({pending:'待审核',pending_review:'待审核',candidate:'待审核',approved:'已批准',rejected:'已拒绝',withdrawn:'已撤回',invalidated:'来源变更',expired:'已过期',not_yet_valid:'尚未生效',invalid_time:'时间格式需核对',superseded:'已被替代'})[status] || '状态待核对'; }
function setStatus(id, text, state = '') { $(id).textContent = text; $(id).dataset.state = state; }
function scopeValue() { return {subject:$('subject').value.trim(),project:$('project').value.trim(),task:$('task').value.trim()}; }
let taskContextTicket = 0;
function describeScope(collapse = false) {
  const scope = scopeValue(), complete = Object.values(scope).every(Boolean);
  $('scopeSummary').textContent = complete ? `使用者：${scope.subject} · 项目：${scope.project}（可更换）` : '选择使用者、项目和任务';
  if (!complete || collapse) $('scopePicker').open = !complete;
}
async function describeTask() {
  const ticket = ++taskContextTicket, id = $('task').value.trim(), root = OksWorkspace.context()?.knowledge_base;
  $('taskContext').hidden = true; $('taskContext').replaceChildren();
  if (!root || !/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$/.test(id)) return;
  try {
    // Read task context only after the user explicitly requests these suggestions.
    const data = await request('/api/tasks/show?id=' + encodeURIComponent(id));
    if (ticket !== taskContextTicket || id !== $('task').value.trim() || root !== OksWorkspace.context()?.knowledge_base || data.knowledge_base !== root) return;
    const match = String(data.agreement?.goal?.text || '').match(/^title:\s*(.+)$/m);
    const name = match ? match[1].trim().replace(/^(['"])(.*)\1$/, '$2') : id;
    const link = el('a', name); link.href = '/tasks?id=' + encodeURIComponent(id);
    $('taskContext').append(document.createTextNode('来自任务：'), link); $('taskContext').hidden = false;
  } catch { /* Standalone feedback scopes need not have a durable task record. */ }
}
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
    setStatus('capabilityStatus', localReview ? '可以在此审核建议。' : '当前只能查看。启用本地审核后，才能批准或拒绝。', localReview ? 'ready' : 'disabled');
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
  const ticket = scopeSequence, root = OksWorkspace.context()?.knowledge_base;
  const unchanged = () => ticket === scopeSequence && root === OksWorkspace.context()?.knowledge_base
    && (!originalScope || ['subject','project','task'].every(key => originalScope[key] === scopeValue()[key]));
  try {
    const result = await jsonPost(url, body);
    if (!unchanged()) return null;
    setStatus('scopeStatus', message || '操作已完成。');
    if (url.endsWith('/export')) {
      if (result.path) {
        $('draftPath').value = result.path;
        await loadDraft(result.path);
        if (!unchanged()) return null;
        setStatus('draftStatus', '草稿已生成。请检查完整内容，再勾选确认加入知识库。');
      } else setStatus('draftStatus', '草稿已生成，但没有返回路径。请核对当前状态。', 'error');
    } else if (originalScope && ['subject','project','task'].every(key => originalScope[key] === scopeValue()[key])) await inspect(originalScope);
    return result;
  } catch (error) {
    if (unchanged()) setStatus('scopeStatus', error.message, 'error');
    return null;
  }
}
function button(label, action, disabled, handler) {
  const item = el('button', label); item.type = 'button'; item.dataset.action = action; item.disabled = disabled; item.addEventListener('click', handler); return item;
}
function renderCandidates() {
  const host = $('candidates'); host.replaceChildren();
  $('sharingPanel').hidden = !candidates.some(candidate => effectiveStatus(candidate) === 'approved');
  $('confirmShare').disabled = !localReview;
  if (!candidates.length) {
    host.append(el('p', currentScope ? '这里还没有改进建议。' : '点击“查看建议”后显示内容。', 'empty'));
    if (currentScope) {
      const link = el('a','去任务页提出建议'); link.href = '/tasks' + (/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$/.test(currentScope.task) ? '?id=' + encodeURIComponent(currentScope.task) : '');
      host.append(link);
    }
    return;
  }
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
    if (candidate.summary && candidate.title && candidate.summary !== candidate.title) card.append(el('p', candidate.summary));
    const policy = candidate.applicability || {};
    if (policy.valid_from || policy.valid_until) card.append(el('p', `生效：${policy.valid_from || '未设置'} · 截止：${policy.valid_until || '未设置'}`, 'meta'));
    else card.append(el('p', '仅用于所选使用者、项目和任务。', 'meta'));
    const editKey = id + '/' + rev;
    if (['pending','pending_review','candidate'].includes(status)) {
      const values = conditionEdits.get(editKey) || {valid_from:policy.valid_from || '',valid_until:policy.valid_until || '',replaces:''};
      const details = el('details', '', 'candidate-conditions'); details.append(el('summary','有效期与替代（可选）'));
      for (const [key,label] of [['valid_from','生效时间'],['valid_until','截止时间']]) {
        const name = label + '（本地）', wrapper = el('label', name), input = el('input'); input.type = 'datetime-local'; input.setAttribute('aria-label',name);
        const parsed = new Date(values[key]);
        if (values[key] && !Number.isNaN(parsed.valueOf())) input.value = new Date(parsed.valueOf()-parsed.getTimezoneOffset()*60000).toISOString().slice(0,16);
        input.disabled = !canReview; input.addEventListener('input', () => { values[key] = input.value ? new Date(input.value).toISOString() : ''; conditionEdits.set(editKey, values); });
        wrapper.append(input); details.append(wrapper);
      }
      const wrapper = el('label','替代已确认建议'), select = el('select'), none = el('option','不替代'); none.value = ''; select.append(none);
      select.setAttribute('aria-label','替代已确认建议');
      for (const other of candidates) if (effectiveStatus(other) === 'approved' && candidateId(other) !== id) {
        const option = el('option',other.title || candidateId(other)); option.value = candidateId(other); select.append(option);
      }
      select.value = values.replaces; select.disabled = !canReview;
      select.addEventListener('change', () => { values.replaces = select.value; conditionEdits.set(editKey, values); });
      wrapper.append(select); details.append(wrapper,el('p','批准时一并确认这些条件。撤回新版不会恢复旧版。','meta')); card.append(details);
    }
    if (rev === null) card.append(el('p', '来源版本信息不完整，不能审核。', 'file-warning'));
    const linked = (candidate.event_ids || []).map(key => map.get(String(key))).filter(Boolean);
    if (linked.length) {
      const evidence = el('details'), summary = el('summary', `关联事件证据 · ${linked.length}`), list = el('div');
      for (const event of linked) {
        const wrapper = el('section'); wrapper.append(el('p', `${event.event_id} · ${event.status || ''}`), el('pre', JSON.stringify(event.payload || {}, null, 2))); list.append(wrapper);
      }
      evidence.append(summary, list); card.append(evidence);
    } else if (candidate.event_ids?.length) card.append(el('p', `关联事件：${candidate.event_ids.join(', ')}（本次返回中未找到详情）`));
    const raw = el('details'), summary = el('summary', '技术详情'); raw.append(summary, el('pre', JSON.stringify(candidate, null, 2))); card.append(raw);
    const actions = el('div', '', 'candidate-actions');
    if (['pending','pending_review','candidate'].includes(status)) {
      const note = el('textarea'), label = el('label','决定的理由'), noteKey = id + '/' + rev;
      note.id = 'review-note-' + id; label.htmlFor = note.id; note.rows = 2; note.maxLength = 4000;
      note.placeholder = '为什么批准或拒绝这条建议'; note.value = reviewNotes.get(noteKey) || ''; note.disabled = !canReview;
      const approve = button('批准','approve',!(canReview && note.value.trim()),()=>reviewCandidate(candidate,'approve'));
      const reject = button('拒绝','reject',!(canReview && note.value.trim()),()=>reviewCandidate(candidate,'reject'));
      note.addEventListener('input',()=>{ reviewNotes.set(noteKey,note.value); approve.disabled = reject.disabled = !(canReview && note.value.trim()); });
      const form = el('div','','candidate-note'); form.append(label,note); card.append(form); actions.append(approve,reject);
    }
    if (status === 'approved') {
      actions.append(button('撤回', 'withdraw', !approved, () => withdrawCandidate(candidate)));
      actions.append(button('分享为草稿', 'export', !(approved && $('confirmShare').checked) || Object.keys(policy).length > 0, () => exportCandidate(candidate)));
      if (Object.keys(policy).length) card.append(el('p','临时要求保留在本任务；共享知识需另行整理和审核。','meta'));
    }
    if (['expired','not_yet_valid','invalid_time'].includes(status)) actions.append(button('撤回','withdraw',!canWrite(),()=>withdrawCandidate(candidate)));
    if (!localReview && actions.children.length) for (const action of actions.children) action.disabled = true;
    if (actions.children.length) card.append(actions);
    if (!id || !rev) card.append(el('p', '此建议记录不完整，暂不能操作。', 'file-warning'));
    host.append(card);
  }
}
async function inspect(scope) {
  conditionEdits.clear(); reviewNotes.clear();
  const ticket = ++scopeSequence;
  currentScope = {...scope}; events = []; candidates = []; renderCandidates(); renderEvents();
  void describeTask();
  setStatus('scopeStatus', '正在读取指定范围…');
  try {
    const data = await jsonPost('/api/feedback/inspect', {scope:{...scope}});
    if (ticket !== scopeSequence) return;
    OksWorkspace.rememberScope(scope);
    events = Array.isArray(data.events) ? data.events : [];
    candidates = Array.isArray(data.candidates) ? data.candidates : [];
    renderEvents(); renderCandidates();
    setStatus('scopeStatus', `找到 ${candidates.length} 条建议。相关记录可在下方展开。`);
  } catch (error) { if (ticket === scopeSequence) setStatus('scopeStatus', error.message, 'error'); }
}
async function reviewCandidate(candidate, decision) {
  const revision = revisionOf(candidate), id = candidateId(candidate), comment = (reviewNotes.get(id + '/' + revision) || '').trim();
  if (!comment) { setStatus('scopeStatus', '批准或拒绝前请填写这条建议的理由。', 'error'); document.getElementById('review-note-' + id)?.focus(); return; }
  if (!id || revision === null) { setStatus('scopeStatus', '无法确认这条建议的当前状态，请重新读取。', 'error'); return; }
  const values = conditionEdits.get(id + '/' + revision), extra = {};
  if (decision === 'approve' && values) {
    extra.applicability = Object.fromEntries(['valid_from','valid_until'].filter(key=>values[key]).map(key=>[key,values[key]]));
    extra.replaces_candidates = values.replaces ? [values.replaces] : [];
  }
  await mutate('/api/feedback/review', {scope:{...currentScope},candidate_id:id,expected_revision:revision,decision,comment,...extra}, decision === 'approve' ? '已提交批准决定。' : '已提交拒绝决定。');
}
async function withdrawCandidate(candidate) {
  const revision = revisionOf(candidate), id = candidateId(candidate);
  if (!id || revision === null) return;
  await mutate('/api/feedback/withdraw-candidate', {scope:{...currentScope},candidate_id:id,expected_revision:revision}, '已提交撤回操作。');
}
async function exportCandidate(candidate) {
  const revision = revisionOf(candidate), id = candidateId(candidate);
  if (!id || revision === null || !$('confirmShare').checked) return;
  await mutate('/api/feedback/export', {scope:{...currentScope},candidate_id:id,expected_revision:revision,confirm_share:true}, '已生成共享草稿。');
}
async function loadDraft(path) {
  $('draftPanel').open = true;
  const ticket = ++draftSequence; draft = null; $('confirmReview').checked = false; updateDraftControls();
  setStatus('draftStatus', '正在读取完整草稿…'); $('draftPreview').replaceChildren(); $('promoteStatus').textContent = '';
  if (!path) return;
  try {
    const data = await request('/api/learning/draft?path=' + encodeURIComponent(path));
    if (ticket !== draftSequence) return;
    if (typeof data.text !== 'string' || typeof data.sha256 !== 'string' || !data.path) throw Error('草稿无法完整读取，请核对路径后重试。');
    draft = {path:data.path,sha256:data.sha256,text:data.text};
    const raw = data.text.replace(/^\uFEFF/, ''), front = raw.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/);
    const title = front?.[1].match(/^title:\s*(.+)$/m)?.[1].trim().replace(/^(['"])(.*)\1$/, '$2');
    const header = el('header', ''), integrity = el('details', ''), pre = el('pre', front ? raw.slice(front[0].length).trim() : raw, 'draft-body');
    header.append(el('h2', title || '待审核草稿'));
    integrity.append(el('summary', '完整原文与来源校验'), el('p', data.path), el('code', data.sha256), el('pre',data.text));
    $('draftPreview').replaceChildren(header, pre, integrity);
    setStatus('draftStatus', '草稿已完整读取。请检查内容和来源，再勾选确认。');
    $('confirmReview').disabled = !canWrite();
  } catch (error) { if (ticket === draftSequence) setStatus('draftStatus', error.message, 'error'); }
  updateDraftControls();
}
$('scopeForm').addEventListener('submit', event => { event.preventDefault(); const scope = scopeValue(); if (Object.values(scope).some(value => !value)) { setStatus('scopeStatus', '请填写使用者、项目和任务。', 'error'); return; } inspect(scope); });
for (const id of ['subject','project','task']) $(id).addEventListener('input', () => {
  conditionEdits.clear();
  ++scopeSequence; currentScope = null; events = []; candidates = [];
  ++taskContextTicket; ++draftSequence; draft = null;
  $('taskContext').hidden = true; $('taskContext').replaceChildren();
  $('draftPath').value = ''; $('draftPreview').replaceChildren(); $('confirmReview').checked = false; $('draftPanel').open = false;
  $('promoteHandoff').replaceChildren(); $('promoteHandoff').hidden = true;
  $('draftStatus').textContent = $('promoteStatus').textContent = '';
  reviewNotes.clear(); $('confirmShare').checked = false;
  describeScope(); updateDraftControls();
  renderCandidates(); renderEvents(); setStatus('scopeStatus', '查看范围已变化，请再次点击“查看建议”。');
});
$('confirmShare').addEventListener('change', renderCandidates);
$('draftPath').addEventListener('input', updateDraftControls);
$('draftForm').addEventListener('submit', event => { event.preventDefault(); loadDraft($('draftPath').value.trim()); });
$('confirmReview').addEventListener('change', updateDraftControls);
$('promote').addEventListener('click', async () => {
  if (!canWrite() || !draft || !$('confirmReview').checked) return;
  $('promote').disabled = true; setStatus('promoteStatus', '正在加入知识库…');
  try {
    const result = await jsonPost('/api/learning/promote', {path:draft.path,expected_sha256:draft.sha256,confirm_review:true});
    setStatus('promoteStatus', `已加入知识库：${result.path || draft.path}`);
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
  if (draftParam) return;
  const hint = OksWorkspace.scopeHint(), task = new URLSearchParams(location.search).get('task');
  if (hint) { $('subject').value = hint.subject || ''; $('project').value = hint.project || ''; }
  if (task && /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$/.test(task)) $('task').value = task;
  describeScope(true);
  if (hint || task) setStatus('scopeStatus', '确认范围后点击“查看建议”；尚未读取私人内容。');
});
document.addEventListener('oks:reconnected', event => {
  ++scopeSequence; ++draftSequence; currentScope = null; events = []; candidates = []; draft = null;
  if (event.detail.changedRoot) {
    for (const id of ['subject','project','task','draftPath']) $(id).value = '';
    history.replaceState(null, '', '/review');
  }
  $('draftPreview').replaceChildren(); $('confirmReview').checked = false;
  reviewNotes.clear(); $('confirmShare').checked = false; $('draftPanel').open = false;
  $('promoteHandoff').replaceChildren(); $('promoteHandoff').hidden = true;
  ++taskContextTicket; $('taskContext').hidden = true; $('taskContext').replaceChildren();
  describeScope(true);
  renderCandidates(); renderEvents(); updateDraftControls(); loadCapability();
  setStatus('scopeStatus', '连接已恢复，请重新确认范围并读取。');
});
const draftParam = new URLSearchParams(location.search).get('draft');
if (draftParam) {
  document.title = '审核共享草稿 · OKS';
  document.querySelector('.intro .eyebrow').textContent = '学习 / 共享知识';
  document.querySelector('.intro h1').textContent = '审核共享草稿';
  document.querySelector('.intro>p:last-of-type').textContent = '阅读全文并核对来源，确认后加入知识库。这里不需要填写私人建议的范围。';
  for (const selector of ['.scope-section','.suggestions-section','.event-section']) document.querySelector(selector).hidden = true;
  document.querySelector('.page-footer p').textContent = '加入后可被当前知识库的后续查询使用，请核对内容与来源。';
  const back = document.querySelector('.page-footer a'); back.href = '/#wiki'; back.textContent = '返回知识库 ↗';
  $('draftPath').value = draftParam; loadDraft(draftParam);
}
