"""Exercise the local receiver through real section comments and canonical Mail."""
import base64
import json
from pathlib import Path
import struct
import subprocess
import sys
from types import SimpleNamespace
import zlib

import pytest

from knowledge_studio import discussion_agent as receiver
from knowledge_studio import discussion_comments as comments
from knowledge_studio import mail, studio

PATH = 'profiles/discuss/2026/11/08/agent.md'
TEXT = ('---\r\ntitle: 讨论样例\r\nowner: human\r\n---\r\n# 讨论\r\n\r\n'
        '## 判断\r\n原句。\r\n\r\n## 下一节\r\n保持原文。\r\n')


def png_chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)


PNG = (b'\x89PNG\r\n\x1a\n'
       + png_chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
       + png_chunk(b'IDAT', zlib.compress(b'\x00\xff\xff\xff')) + png_chunk(b'IEND', b''))


@pytest.fixture
def kb(tmp_path, monkeypatch):
    monkeypatch.setenv('OKS_MACHINE_ID', 'machine_discussion_agent_test')
    # Host discovery is isolated; high-level tests only replace the model answer.
    monkeypatch.setattr(receiver.shutil, 'which', lambda name: sys.executable)
    root = tmp_path / 'knowledge'
    (root / PATH).parent.mkdir(parents=True)
    (root / PATH).write_bytes(TEXT.encode())
    return root


def agent(root, host='codex', **kwargs):
    result = receiver.DiscussionAgent(root, host, **kwargs)
    mail.register_session(root, result.session_id, result.agent_id, machine_id=result.machine_id)
    return result


def send(root, worker, **overrides):
    document = comments.document(root, PATH)
    section = next(section for section in document['sections'] if section['title'] == '判断')
    payload = {'path': PATH, 'anchor_id': section['id'], 'expected_sha256': document['sha256'],
               'agent': worker.agent_id, 'text': '请结合原文处理这一段。', **overrides}
    return comments.send(root, payload)['comments'][-1]


def raw_comment(root, record):
    row = mail.parse_message(mail.canonical_path(root, record['message_id']))
    return row, comments.comment(root, row)


def model_answer(monkeypatch, worker, *, replacement=None, needs_info=False, side_effect=None):
    calls = []
    def answer(body, document, directory):
        calls.append((body, document, directory))
        if side_effect:
            side_effect()
        return {'reply': '已处理这条意见。', 'replacement': replacement, 'needs_info': needs_info}
    monkeypatch.setattr(worker, '_answer', answer)
    return calls


def results(root, record):
    return [row for row in mail.thread_messages(root, record['thread_id'], 'human')
            if row['meta']['record_kind'] == 'result']


def projected_reply(root):
    return comments.read(root, PATH)['comments'][-1]['replies'][-1]


def test_reply_only_scan_uses_real_receipt_and_readable_canonical_result_without_editing(kb, monkeypatch):
    worker = agent(kb)
    record = send(kb, worker)
    original = (kb / PATH).read_bytes()
    calls = model_answer(monkeypatch, worker)
    worker.scan()
    assert len(calls) == 1 and (kb / PATH).read_bytes() == original
    receipt = mail._load_receipt_snapshot(kb, worker.session_id, record['message_id'])
    assert receipt['status'] == 'acknowledged'
    assert receipt['agent_id'] == worker.agent_id and receipt['machine_id'] == worker.machine_id
    actual = results(kb, record)
    assert len(actual) == 1
    meta = actual[0]['meta']
    assert meta['thread_id'] == record['thread_id'] and meta['reply_to'] == record['message_id']
    assert meta['sender_kind'] == 'agent' and meta['origin_session_id'] == worker.session_id
    assert meta['origin_machine_id'] == worker.machine_id and meta['to'] == ['@human']
    answer = projected_reply(kb)
    assert answer['body'] == '已处理这条意见。'
    assert answer['result']['status'] == 'answered' and answer['result']['changed'] is False
    assert answer['result']['source_sha256'] == answer['result']['result_sha256'] == record['source_sha256']
    state = json.loads((worker._job(record['message_id']) / 'state.json').read_text())
    assert state['status'] == 'answered' and worker.current_message_id is None


def test_authorized_edit_replaces_only_original_section_and_preserves_frontmatter_and_crlf(kb, monkeypatch):
    worker = agent(kb)
    record = send(kb, worker, allow_edit=True)
    model_answer(monkeypatch, worker, replacement='## 判断\n修订后的句子。\n')
    row, body = raw_comment(kb, record)
    result = worker.process_comment(row, body)
    expected = TEXT.replace('## 判断\r\n原句。\r\n\r\n', '## 判断\r\n修订后的句子。\r\n\r\n')
    assert (kb / PATH).read_bytes() == expected.encode()
    assert result['status'] == 'updated' and result['changed'] is True
    assert result['source_sha256'] == record['source_sha256']
    assert result['result_sha256'] == comments.document(kb, PATH)['sha256'] != record['source_sha256']
    assert projected_reply(kb)['result'] == result
    revisions = list((kb / 'records/timeline').rglob('*.json'))
    assert revisions  # The ordinary Studio versioned writer, not a separate write path.


@pytest.mark.parametrize('allow_edit,needs_info', [(False, False), (True, True)])
def test_model_replacement_is_rejected_without_edit_permission_or_with_missing_information(
        kb, monkeypatch, allow_edit, needs_info):
    worker = agent(kb)
    record = send(kb, worker, allow_edit=allow_edit)
    model_answer(monkeypatch, worker, replacement='## 判断\n不可应用。', needs_info=needs_info)
    worker.scan()
    assert (kb / PATH).read_bytes() == TEXT.encode()
    answer = projected_reply(kb)['result']
    assert answer['status'] == 'failed' and answer['changed'] is False
    assert '没有授权' in answer['reply'] or '补充信息' in answer['reply']


def test_source_changed_before_scan_requests_new_version_without_calling_model(kb, monkeypatch):
    worker = agent(kb)
    record = send(kb, worker, allow_edit=True)
    calls = model_answer(monkeypatch, worker, replacement='## 判断\n不可应用。')
    current = TEXT.replace('原句。', '用户先修改了。')
    (kb / PATH).write_bytes(current.encode())
    worker.scan()
    assert not calls and (kb / PATH).read_bytes() == current.encode()
    result = projected_reply(kb)['result']
    assert result['status'] == 'needs_info' and result['changed'] is False
    assert result['source_sha256'] == record['source_sha256']
    assert result['result_sha256'] == comments.document(kb, PATH)['sha256']


def test_source_changed_while_model_runs_is_never_overwritten(kb, monkeypatch):
    worker = agent(kb)
    send(kb, worker, allow_edit=True)
    current = TEXT.replace('原句。', '用户在处理中修改了。')
    model_answer(monkeypatch, worker, replacement='## 判断\n不可覆盖。',
                 side_effect=lambda: (kb / PATH).write_bytes(current.encode()))
    worker.scan()
    assert (kb / PATH).read_bytes() == current.encode()
    answer = projected_reply(kb)['result']
    assert answer['status'] == 'failed' and answer['changed'] is False
    assert '处理期间原文发生修改' in answer['reply']
    assert answer['result_sha256'] == comments.document(kb, PATH)['sha256']


@pytest.mark.parametrize('action', ['switch_root', 'stop'])
def test_root_switch_or_stop_during_answer_prevents_applying_replacement(kb, monkeypatch, action):
    selected = [kb]
    worker = agent(kb, current_root=lambda: selected[0])
    send(kb, worker, allow_edit=True)
    def interrupt():
        if action == 'switch_root':
            selected[0] = kb.parent / 'another-knowledge-base'
        else:
            worker.stop()
    model_answer(monkeypatch, worker, replacement='## 判断\n不能应用。', side_effect=interrupt)
    worker.scan()
    assert (kb / PATH).read_bytes() == TEXT.encode()
    answer = projected_reply(kb)['result']
    assert answer['status'] == 'failed' and answer['changed'] is False
    assert '连接已变更或接收端停止' in answer['reply']


@pytest.mark.parametrize('action', ['switch_root', 'stop'])
def test_inactive_scan_does_not_claim_receive_or_invoke_model(kb, monkeypatch, action):
    selected = [kb]
    worker = agent(kb, current_root=lambda: selected[0])
    record = send(kb, worker)
    calls = model_answer(monkeypatch, worker)
    if action == 'switch_root':
        selected[0] = kb.parent / 'another-knowledge-base'
    else:
        worker.stop()
    worker.scan()
    assert not calls and not results(kb, record)
    assert mail._load_receipt_snapshot(kb, worker.session_id, record['message_id']) is None
    assert comments.read(kb, PATH)['comments'][0]['received'] is False


def test_restart_after_success_does_not_repeat_model_or_edit_same_message(kb, monkeypatch):
    first = agent(kb)
    record = send(kb, first, allow_edit=True)
    first_calls = model_answer(monkeypatch, first, replacement='## 判断\n仅修改一次。')
    first.scan()
    after = (kb / PATH).read_bytes()
    second = agent(kb)
    second_calls = model_answer(monkeypatch, second, replacement='## 判断\n不得再次修改。')
    second.scan()
    assert len(first_calls) == 1 and not second_calls
    assert (kb / PATH).read_bytes() == after and len(results(kb, record)) == 1


def test_interrupted_previous_session_fails_without_replaying_uncertain_edit(kb, monkeypatch):
    previous = agent(kb)
    record = send(kb, previous, allow_edit=True)
    row, _ = raw_comment(kb, record)
    previous._save_state(previous._job(record['message_id']), 'running')
    mail.record_delivery(kb, previous.session_id, row, agent_id=previous.agent_id,
                         machine_id=previous.machine_id)
    # A crash may happen after saving and before its result; do not repeat either case.
    current = TEXT.replace('原句。', '中断前可能已应用。')
    (kb / PATH).write_bytes(current.encode())
    restarted = agent(kb)
    calls = model_answer(monkeypatch, restarted, replacement='## 判断\n不能重放。')
    restarted.scan()
    assert not calls and (kb / PATH).read_bytes() == current.encode()
    answer = projected_reply(kb)['result']
    assert answer['status'] == 'failed' and answer['changed'] is False
    assert '中断' in answer['reply'] and '未自动重放' in answer['reply']
    assert answer['result_sha256'] == comments.document(kb, PATH)['sha256']
    receipt = mail._load_receipt_snapshot(kb, restarted.session_id, record['message_id'])
    assert receipt['status'] == 'acknowledged'
    state = json.loads((restarted._job(record['message_id']) / 'state.json').read_text())
    assert state['status'] == 'failed'
    restarted.scan()
    assert not calls and len(results(kb, record)) == 1


def test_same_session_running_job_is_skipped_without_competing_result(kb, monkeypatch):
    worker = agent(kb)
    record = send(kb, worker)
    worker._save_state(worker._job(record['message_id']), 'running')
    calls = model_answer(monkeypatch, worker)
    worker.scan()
    assert not calls and not results(kb, record)


def test_host_command_uses_executable_or_node_entry_with_direct_argv(tmp_path, monkeypatch):
    monkeypatch.setattr(receiver, 'os', SimpleNamespace(name='nt'))
    executable = tmp_path / 'claude.exe'
    monkeypatch.setattr(receiver.shutil, 'which', lambda name: str(executable))
    assert receiver.host_command('claude') == [str(executable)]
    wrapper = tmp_path / 'claude.cmd'
    wrapper.write_text('@node cli.js\n')
    entry = tmp_path / 'node_modules/@anthropic-ai/claude-code/cli.js'
    entry.parent.mkdir(parents=True)
    entry.write_text('// installed entry point')
    node = tmp_path / 'node.exe'
    monkeypatch.setattr(receiver.shutil, 'which', lambda name: str(node if name == 'node' else wrapper))
    assert receiver.host_command('claude') == [str(node), str(entry)]
    with pytest.raises(ValueError, match='Choose claude or codex'):
        receiver.host_command('cmd /c anything')


def test_volta_wrapper_keeps_its_installed_runtime_without_shell(tmp_path, monkeypatch):
    monkeypatch.setattr(receiver, 'os', SimpleNamespace(name='nt'))
    wrapper = tmp_path / 'codex.cmd'
    wrapper.write_text('@volta run codex %*\n')
    installed = tmp_path / 'installed'
    entry = installed / 'node_modules/@openai/codex/bin/codex.js'
    entry.parent.mkdir(parents=True)
    entry.write_text('// installed entry point')
    found = {'codex': str(wrapper), 'volta': 'volta.exe', 'node': 'node.exe'}
    monkeypatch.setattr(receiver.shutil, 'which', found.get)
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout=str(installed / 'codex.cmd'))
    monkeypatch.setattr(receiver.subprocess, 'run', run)
    assert receiver.host_command('codex') == ['volta.exe', 'run', 'codex']
    assert calls == []


class HostProcess:
    def __init__(self, stdout='', *, timeout=False):
        self.stdout = stdout
        self.returncode = None if timeout else 0
        self.timeout = timeout
        self.calls = []
        self.killed = False

    def communicate(self, text=None, **kwargs):
        self.calls.append((text, kwargs))
        if self.timeout and not self.killed:
            raise subprocess.TimeoutExpired(['host'], kwargs['timeout'])
        return self.stdout, ''

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


@pytest.mark.parametrize('host', ['claude', 'codex'])
def test_native_host_receives_original_image_and_direct_process_arguments(kb, monkeypatch, host):
    worker = agent(kb, host)
    record = send(kb, worker, images=[{'name': '原图.png', 'data_base64': base64.b64encode(PNG).decode()}])
    row, body = raw_comment(kb, record)
    answer = {'reply': '已收到图像输入。', 'replacement': None, 'needs_info': False}
    process = HostProcess(json.dumps({'structured_output': answer}))
    launches = []
    def popen(command, **kwargs):
        launches.append((command, kwargs))
        if host == 'codex':
            Path(command[command.index('-o') + 1]).write_text(json.dumps(answer), encoding='utf-8')
        return process
    monkeypatch.setattr(receiver.subprocess, 'Popen', popen)
    result = worker.process_comment(row, body)
    assert result['status'] == 'answered' and worker.process is None
    command, kwargs = launches[0]
    assert isinstance(command, list) and kwargs.get('shell', False) is False
    assert kwargs['cwd'] == kb and kwargs['encoding'] == 'utf-8'
    assert process.calls[0][1]['timeout'] == 240
    input_text = process.calls[0][0]
    if host == 'claude':
        content = json.loads(input_text)['message']['content']
        source = next(item['source'] for item in content if item['type'] == 'image')
        assert source['type'] == 'base64' and source['media_type'] == 'image/png'
        assert base64.b64decode(source['data']) == PNG
        assert '--tools=' in command and '--setting-sources=' in command
    else:
        attachment = Path(command[command.index('-i') + 1])
        assert attachment == kb / body['images'][0]['path'] and attachment.read_bytes() == PNG
        assert command[-1] == '-' and command[command.index('--sandbox') + 1] == 'read-only'
        assert '--ignore-user-config' in command
    assert projected_reply(kb)['result'] == result


def test_native_host_timeout_kills_drains_and_clears_process_then_reports_failed(kb, monkeypatch):
    worker = agent(kb, 'claude')
    record = send(kb, worker)
    process = HostProcess(timeout=True)
    monkeypatch.setattr(receiver.subprocess, 'Popen', lambda *args, **kwargs: process)
    monkeypatch.setattr(receiver, '_terminate_host', lambda target: target.kill())
    row, body = raw_comment(kb, record)
    result = worker.process_comment(row, body)
    assert process.killed and worker.process is None
    assert len(process.calls) == 2 and process.calls[-1] == (None, {'timeout': 10})
    assert result['status'] == 'failed' and result['changed'] is False
    assert (kb / PATH).read_bytes() == TEXT.encode()
    assert projected_reply(kb)['result'] == result


def test_windows_host_cleanup_targets_only_the_owned_launcher_tree(monkeypatch):
    monkeypatch.setattr(receiver, 'os', SimpleNamespace(name='nt'))
    calls = []
    monkeypatch.setattr(receiver.subprocess, 'run', lambda argv, **kwargs: calls.append((argv, kwargs)))
    receiver._terminate_host(SimpleNamespace(pid=12345))
    assert calls[0][0] == ['taskkill', '/PID', '12345', '/T', '/F']
    assert calls[0][1].get('shell', False) is False


def test_posix_host_cleanup_stops_the_owned_process_session(monkeypatch):
    calls = []
    monkeypatch.setattr(receiver, 'os', SimpleNamespace(name='posix', killpg=lambda pid, sig: calls.append((pid, sig))))
    monkeypatch.setattr(receiver, 'signal', SimpleNamespace(SIGKILL=9))
    receiver._terminate_host(SimpleNamespace(pid=12345))
    assert calls == [(12345, receiver.signal.SIGKILL)]


def test_posix_cleanup_accepts_cli_exit_race(monkeypatch):
    def exited(*args):
        raise ProcessLookupError('Already exited')
    monkeypatch.setattr(receiver, 'os', SimpleNamespace(name='posix', killpg=exited))
    monkeypatch.setattr(receiver, 'signal', SimpleNamespace(SIGKILL=9))
    receiver._terminate_host(SimpleNamespace(pid=12345))


def test_cleanup_failure_clears_handle_and_does_not_interrupt_server_close(kb, monkeypatch):
    worker = agent(kb, 'claude')
    record = send(kb, worker)
    process = HostProcess(timeout=True)
    monkeypatch.setattr(receiver.subprocess, 'Popen', lambda *args, **kwargs: process)
    def unavailable(target):
        raise subprocess.TimeoutExpired(['taskkill'], 10)
    monkeypatch.setattr(receiver, '_terminate_host', unavailable)
    row, body = raw_comment(kb, record)
    result = worker.process_comment(row, body)
    assert result['status'] == 'failed' and worker.process is None
    worker.process = process
    worker.stop()
    assert worker.stopping.is_set() and worker.error


def test_server_startup_failure_stops_the_started_discussion_receiver(kb, monkeypatch):
    from knowledge_studio import mail_web, studio_history

    (kb / 'wiki').mkdir(exist_ok=True)
    (kb / 'mail').mkdir(exist_ok=True)
    stopped = []
    worker = SimpleNamespace(start=lambda: worker, stop=lambda: stopped.append(True))
    monkeypatch.setattr(receiver, 'DiscussionAgent', lambda *args, **kwargs: worker)

    def fail_history(*args, **kwargs):
        raise OSError('History directory is not writable')

    monkeypatch.setattr(studio_history, 'Watcher', fail_history)
    with pytest.raises(OSError, match='not writable'):
        mail_web.create_server(kb, 0, local_edit=True, discussion_agent='claude')
    assert stopped == [True]
