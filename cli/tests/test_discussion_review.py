"""Agent discussion review is reconstructed from canonical requests, replies and Session receipts."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json

import pytest

from knowledge_studio import discussion_review, mail, studio

MACHINE = 'machine_review_test'
SESSION = 'review-session'


@pytest.fixture
def kb(tmp_path):
    root = tmp_path / 'knowledge'
    root.mkdir()
    mail.register_session(root, SESSION, 'reviewer', machine_id=MACHINE)
    return root


def document(root, text='## 人的判断\n- First statement.\n\n## 待确认\nQuestion?\n',
             path='discuss/2026/11/07/review.md'):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode('utf-8'))
    return path


def ask(root, source, reviewer='reviewer', previous_request_id=None, **kwargs):
    return discussion_review.request_review(root, {
        'path': source['path'], 'expected_sha256': source['sha256'], 'reviewer': reviewer,
        'previous_request_id': previous_request_id,
    }, **kwargs)


def request_message(root, review):
    return mail.parse_message(mail.canonical_path(root, review['request']['message_id']))


def presented(root, review, session=SESSION, agent='reviewer', machine=MACHINE, delivered=True):
    return mail.record_delivery(root, session, request_message(root, review),
                                agent_id=agent, machine_id=machine, delivered=delivered)


def reply(root, review, *, results=None, sender='reviewer', sender_kind='agent', session=SESSION,
          machine=MACHINE, thread=None, payload=None, record_kind='result', reply_to=None,
          recipients=None):
    body = {
        'schema': discussion_review.RESULT_SCHEMA,
        'request_message_id': review['request']['message_id'],
        'source_sha256': review['sha256'],
        'results': results if results is not None else [
            {'item_id': item['id'], 'verdict': 'accepted', 'reason': 'Checked exact statement.',
             'evidence': []} for item in review['items']
        ],
        **(payload or {}),
    }
    return mail.write_message(
        root, body=json.dumps(body, ensure_ascii=False), sender=sender,
        sender_kind=sender_kind, recipients=recipients or ['@human'],
        origin_session_id=session, origin_machine_id=machine,
        thread_id=thread or review['request']['thread_id'],
        reply_to=reply_to or review['request']['message_id'], record_kind=record_kind,
        title='Discussion review result',
    )


def test_read_empty_and_plain_paragraphs_is_read_only(kb):
    path = document(kb, '')
    before = {p.relative_to(kb): p.read_bytes() for p in kb.rglob('*') if p.is_file()}
    result = discussion_review.read(kb, path)
    assert result['sha256'] == hashlib.sha256(b'').hexdigest()
    assert result['items'] == [] and result['total'] == 0 and result['request'] is None
    assert result['summary'] == dict(accepted=0, disputed=0, needs_info=0, pending=0, unrequested=0)
    assert result['reviewers'] == [{'id': '@reviewer', 'label': 'reviewer'}]
    assert {p.relative_to(kb): p.read_bytes() for p in kb.rglob('*') if p.is_file()} == before
    path = document(kb, '## 人的判断\nOne paragraph.\nContinuation.\n\nSecond paragraph.\n')
    result = discussion_review.read(kb, path)
    assert [item['text'] for item in result['items']] == ['One paragraph.\nContinuation.', 'Second paragraph.']
    assert result['summary']['unrequested'] == 2


def test_items_preserve_inline_code_checkboxes_multiline_and_child_lists(kb):
    path = document(kb, '# Discussion\n\n## 人的判断\n'
                    '- [x] Keep `source_id`.\n  Continued line.\n  - Child statement.\n\n'
                    '  More detail.\n- [ ] Second statement.\n\n## AI 理解\nAI stays read-only.\n'
                    '## 待确认\n1. Is `source_id` stable?\n2. Another question.\n')
    items = discussion_review.read(kb, path)['items']
    assert [item['id'] for item in items] == [
        'human_judgment:1', 'human_judgment:2', 'open_question:1', 'open_question:2',
    ]
    assert items[0]['text'] == '- [x] Keep `source_id`.\n  Continued line.\n  - Child statement.\n\n  More detail.'
    assert items[0]['status'] == 'unrequested'
    assert items[2]['kind'] == 'open_question'
    assert all('AI stays' not in item['text'] for item in items)


def test_fences_comments_and_example_headings_do_not_create_items(kb):
    path = document(kb, '# Discussion\n\n```md\n## 人的判断\n- Fake\n```\n'
                    '<!--\n## 待确认\nHidden question.\n-->\n'
                    '## 人的判断\nActual statement.\n### 示例\n- Example statement.\n'
                    '#### Example child\nAnother example.\n### 正式结论\n- Written conclusion.\n'
                    '```python\n## 待确认\n- Fake inside code\n```\n'
                    '## 待确认\nActual question.\n')
    assert [item['text'] for item in discussion_review.read(kb, path)['items']] == [
        'Actual statement.', '- Written conclusion.', 'Actual question.',
    ]


def test_nested_fences_preserve_the_parent_without_swallowing_the_next_item(kb):
    text = ('## 人的判断\n- Parent statement.\n\n    ```md\n'
            '    ## 待确认\n    - Example question.\n    ```\n\n- Next statement.\n')
    path = document(kb, text)
    items = discussion_review.read(kb, path)['items']
    assert len(items) == 2
    assert items[0]['text'] == text.split('\n', 1)[1].split('\n\n- Next statement.')[0]
    assert items[1]['text'] == '- Next statement.'


def test_legacy_confirmation_metadata_is_ignored_and_source_is_never_rewritten(kb):
    text = ('\ufeff---\r\ntitle: Discussion\r\ndiscussion_confirmations: arbitrary legacy value\r\n'
            '---\r\n## 人的判断\r\n- [x] Already checked list item.  \r\n')
    path = document(kb, text)
    before = (kb / path).read_bytes()
    source = discussion_review.read(kb, path)
    assert source['summary']['unrequested'] == 1
    queued = ask(kb, source)
    assert queued['summary']['pending'] == 1
    assert not hasattr(discussion_review, 'save')
    assert (kb / path).read_bytes() == before


def test_request_uses_canonical_mail_exact_snapshots_and_queued_notifications(kb):
    path = document(kb)
    before = discussion_review.read(kb, path)
    result = ask(kb, before)
    assert result['summary']['pending'] == 2
    assert result['request']['status'] == 'pending'
    row = request_message(kb, result)
    payload = json.loads(row['body'])
    assert row['meta']['record_kind'] == 'review_request'
    assert row['meta']['sender_kind'] == 'human'
    assert row['meta']['to'] == ['@reviewer', '@human']
    assert payload['source_sha256'] == before['sha256']
    assert payload['items'] == [{key: item[key] for key in discussion_review.ITEM_FIELDS}
                                for item in before['items']]
    assert '现有授权' in payload['instructions']
    notification = json.loads((mail.notifications_dir(kb, 'reviewer') /
                               (result['request']['message_id'] + '.json')).read_text('utf-8'))
    assert notification['status'] == 'pending' and not notification['wake_supported']


def test_retry_and_concurrent_requests_reuse_one_active_message(kb):
    source = discussion_review.read(kb, document(kb))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: ask(kb, source), range(2)))
    assert results[0]['request']['message_id'] == results[1]['request']['message_id']
    assert len(list(mail._iter_canonical(kb))) == 1
    presented(kb, results[0])
    assert ask(kb, source)['request']['status'] == 'received'
    assert len(list(mail._iter_canonical(kb))) == 1


def test_retry_after_send_failure_reuses_the_already_saved_request(kb, monkeypatch):
    source = discussion_review.read(kb, document(kb))
    original = mail.write_message
    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError('Reply transport interrupted after local persistence')
    monkeypatch.setattr(mail, 'write_message', interrupted)
    with pytest.raises(OSError):
        ask(kb, source)
    monkeypatch.setattr(mail, 'write_message', original)
    result = ask(kb, source)
    assert result['request']['status'] == 'pending'
    assert len(list(mail._iter_canonical(kb))) == 1


def test_receipt_is_only_received_until_an_assigned_agent_reports(kb):
    path = document(kb)
    current = ask(kb, discussion_review.read(kb, path))
    presented(kb, current, delivered=False)
    assert discussion_review.read(kb, path)['request']['status'] == 'pending'
    presented(kb, current)
    mail.acknowledge_delivery(kb, SESSION, current['request']['message_id'],
                              agent_id='reviewer', machine_id=MACHINE)
    after = discussion_review.read(kb, path)
    assert after['request']['status'] == 'received'
    assert after['summary']['pending'] == 2 and after['summary']['accepted'] == 0


def test_assigned_agent_results_record_reason_evidence_session_and_disagreement(kb):
    path = document(kb, '## 人的判断\n- One\n- Two\n- Three\n')
    current = ask(kb, discussion_review.read(kb, path))
    presented(kb, current)
    outcomes = [
        {'item_id': item['id'], 'verdict': verdict, 'reason': reason, 'evidence': evidence}
        for item, verdict, reason, evidence in zip(current['items'],
            ['accepted', 'disputed', 'needs_info'],
            ['Verified source.', 'Conflicts with source.', 'Need supporting data.'],
            [['records/source.md'], ['records/conflict.md'], []])
    ]
    sent = reply(kb, current, results=outcomes)
    after = discussion_review.read(kb, path)
    assert after['request']['status'] == 'reviewed'
    assert after['summary'] == dict(accepted=1, disputed=1, needs_info=1, pending=0, unrequested=0)
    review = after['items'][1]['review']
    assert review == dict(reviewer='@reviewer', session_id=SESSION, reason='Conflicts with source.',
                          evidence=['records/conflict.md'], message_id=sent['message_id'],
                          at=sent['meta']['timestamp'])


def test_partial_results_leave_missing_items_pending_and_can_be_completed(kb):
    path = document(kb)
    current = ask(kb, discussion_review.read(kb, path))
    presented(kb, current)
    reply(kb, current, results=[
        {'item_id': current['items'][0]['id'], 'verdict': 'accepted', 'reason': 'Checked.', 'evidence': []},
    ])
    after = discussion_review.read(kb, path)
    assert [item['status'] for item in after['items']] == ['accepted', 'pending']
    assert after['request']['status'] == 'received'
    reply(kb, current, results=[
        {'item_id': current['items'][1]['id'], 'verdict': 'disputed', 'reason': 'Still differs.', 'evidence': []},
    ])
    assert discussion_review.read(kb, path)['request']['status'] == 'reviewed'


@pytest.mark.parametrize('change', [
    {'sender': 'other'}, {'sender': 'human', 'sender_kind': 'human'},
    {'sender_kind': 'unknown'}, {'session': ''}, {'session': 'unpresented-session'},
    {'machine': 'other_machine'}, {'record_kind': 'acknowledgement'}, {'thread': 'other-thread'},
    {'payload': {'request_message_id': 'another-request'}},
    {'payload': {'source_sha256': '0' * 64}},
])
def test_unassigned_or_unbound_results_cannot_approve_items(kb, change):
    path = document(kb)
    current = ask(kb, discussion_review.read(kb, path))
    presented(kb, current)
    reply(kb, current, **change)
    after = discussion_review.read(kb, path)
    assert after['summary']['pending'] == 2 and after['summary']['accepted'] == 0


def test_wrong_recipient_receipt_or_no_receipt_does_not_validate_a_result(kb):
    path = document(kb)
    current = ask(kb, discussion_review.read(kb, path))
    reply(kb, current)
    assert discussion_review.read(kb, path)['summary']['accepted'] == 0
    presented(kb, current, agent='other')
    assert discussion_review.read(kb, path)['summary']['accepted'] == 0


def test_plain_result_and_acknowledgement_do_not_produce_verdicts(kb):
    path = document(kb)
    current = ask(kb, discussion_review.read(kb, path))
    presented(kb, current)
    mail.write_message(kb, body='Reviewed and acknowledged.', sender='reviewer',
                       sender_kind='agent', recipients=['@human'], origin_session_id=SESSION,
                       origin_machine_id=MACHINE, thread_id=current['request']['thread_id'],
                       record_kind='result')
    assert discussion_review.read(kb, path)['summary']['accepted'] == 0


def test_private_agent_reply_is_not_exposed_in_the_human_discussion_projection(kb):
    path = document(kb)
    current = ask(kb, discussion_review.read(kb, path))
    presented(kb, current)
    sent = reply(kb, current, recipients=['@other'], results=[
        {'item_id': current['items'][0]['id'], 'verdict': 'disputed',
         'reason': 'PRIVATE_REVIEW_REASON', 'evidence': ['private/evidence.md']},
    ])
    assert sent['message_id'] not in {
        row['meta']['message_id'] for row in mail.iter_messages(kb, 'human')
    }
    shown = discussion_review.read(kb, path)
    assert shown['summary']['pending'] == 2
    assert 'PRIVATE_REVIEW_REASON' not in json.dumps(shown)
    assert 'private/evidence.md' not in json.dumps(shown)


def test_agent_requester_observes_its_own_mail_visibility(kb):
    path = document(kb)
    source = discussion_review.read(kb, path, requester='proposer')
    current = ask(kb, source, requester='proposer', session_id='proposer-session')
    presented(kb, current)
    reply(kb, current, recipients=['@proposer'])
    assert discussion_review.read(kb, path, requester='proposer')['summary']['accepted'] == 2
    assert discussion_review.read(kb, path)['summary']['pending'] == 2


def test_reply_can_follow_an_intervening_message_in_the_same_thread(kb):
    path = document(kb)
    current = ask(kb, discussion_review.read(kb, path))
    presented(kb, current)
    between = mail.write_message(kb, body='Additional thread note.', sender='human',
                                 recipients=['@reviewer'], thread_id=current['request']['thread_id'])
    reply(kb, current, reply_to=between['message_id'])
    assert discussion_review.read(kb, path)['summary']['accepted'] == 2


@pytest.mark.parametrize('results', [
    [{'item_id': 'human_judgment:1', 'verdict': 'accepted', 'reason': '', 'evidence': []}],
    [{'item_id': 'human_judgment:1', 'verdict': 'accepted', 'reason': 'Checked.', 'evidence': 'none'}],
    [{'item_id': 'human_judgment:1', 'verdict': 'accepted', 'reason': 'One.', 'evidence': []},
     {'item_id': 'human_judgment:1', 'verdict': 'disputed', 'reason': 'Two.', 'evidence': []}],
])
def test_ambiguous_or_incomplete_verdicts_do_not_default_to_accepted(kb, results):
    path = document(kb)
    current = ask(kb, discussion_review.read(kb, path))
    presented(kb, current)
    reply(kb, current, results=results)
    assert discussion_review.read(kb, path)['summary']['accepted'] == 0


def test_source_edits_keep_the_old_request_stale_and_allow_a_new_cycle(kb):
    path = document(kb)
    original = ask(kb, discussion_review.read(kb, path))
    presented(kb, original)
    reply(kb, original)
    changed = document(kb, '## 人的判断\n- Revised statement.\n')
    after = discussion_review.read(kb, changed)
    assert after['request']['status'] == 'stale'
    assert after['summary']['unrequested'] == 1
    current = ask(kb, after)
    assert current['request']['message_id'] != original['request']['message_id']
    reply(kb, original)
    assert discussion_review.read(kb, path)['summary']['pending'] == 1


def test_latest_assigned_reviewer_supersedes_earlier_results(kb):
    path = document(kb)
    first = ask(kb, discussion_review.read(kb, path))
    presented(kb, first)
    mail.register_session(kb, 'other-session', 'other', machine_id=MACHINE)
    latest = ask(kb, discussion_review.read(kb, path), reviewer='other')
    reply(kb, first)
    after = discussion_review.read(kb, path)
    assert after['request']['message_id'] == latest['request']['message_id']
    assert after['summary']['pending'] == 2


def test_completed_review_can_be_requested_again_without_inheriting_old_results(kb):
    path = document(kb)
    first = ask(kb, discussion_review.read(kb, path))
    presented(kb, first)
    reply(kb, first)
    latest = ask(kb, discussion_review.read(kb, path), previous_request_id=first['request']['message_id'])
    assert latest['request']['message_id'] != first['request']['message_id']
    reply(kb, first)
    assert discussion_review.read(kb, path)['summary']['pending'] == 2


def test_completed_request_retry_after_lost_response_does_not_create_another_cycle(kb):
    path = document(kb)
    source = discussion_review.read(kb, path)
    first = ask(kb, source)
    presented(kb, first)
    reply(kb, first)
    retried = ask(kb, source)
    assert retried['request']['message_id'] == first['request']['message_id']
    assert retried['request']['status'] == 'reviewed'
    second = ask(kb, source, previous_request_id=first['request']['message_id'])
    presented(kb, second)
    reply(kb, second)
    retried_second = ask(kb, source, previous_request_id=first['request']['message_id'])
    assert retried_second['request']['message_id'] == second['request']['message_id']
    assert len([row for row in mail._iter_canonical(kb)
                if row['meta']['record_kind'] == 'review_request']) == 2


def test_request_snapshot_must_match_all_current_items(kb):
    path = document(kb)
    source = discussion_review.read(kb, path)
    sent = ask(kb, source)
    row = request_message(kb, sent)
    data = json.loads(row['body'])
    data['items'] = data['items'][:1]
    target = row['path']
    raw = target.read_text('utf-8')
    target.write_text(raw[:raw.index('{')] + json.dumps(data, ensure_ascii=False) + '\n', encoding='utf-8')
    presented(kb, sent)
    reply(kb, sent)
    after = discussion_review.read(kb, path)
    assert after['request']['status'] == 'stale'
    assert after['summary']['unrequested'] == 2


def test_registered_reviewers_are_distinct_and_do_not_imply_online_status(kb):
    for agent in ['human', 'all', 'unknown', 'reviewer']:
        mail.register_session(kb, 'extra-' + agent, agent, machine_id=MACHINE)
    path = document(kb)
    assert discussion_review.read(kb, path)['reviewers'] == [{'id': '@reviewer', 'label': 'reviewer'}]
    assert discussion_review.read(kb, path, requester='reviewer')['reviewers'] == []


@pytest.mark.parametrize('reviewer', ['human', 'all', 'unknown', 'missing'])
def test_request_rejects_unregistered_or_reserved_reviewers(kb, reviewer):
    source = discussion_review.read(kb, document(kb))
    with pytest.raises(ValueError):
        ask(kb, source, reviewer=reviewer)
    assert list(mail._iter_canonical(kb)) == []


def test_request_rejects_self_stale_source_and_empty_discussion(kb):
    source = discussion_review.read(kb, document(kb))
    with pytest.raises(ValueError):
        ask(kb, source, requester='reviewer')
    source['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='changed'):
        ask(kb, source)
    empty = discussion_review.read(kb, document(kb, ''))
    with pytest.raises(ValueError, match='no reviewable'):
        ask(kb, empty)


@pytest.mark.parametrize('path', ['wiki/a.md', 'drafts/a.md', 'profiles/other.md', 'discuss/../wiki/a.md'])
def test_read_and_request_reject_paths_outside_discussions(kb, path):
    with pytest.raises(ValueError):
        discussion_review.read(kb, path)
    with pytest.raises(ValueError):
        discussion_review.request_review(kb, {'path': path, 'reviewer': 'reviewer'})


def test_message_text_projects_request_and_bound_results_without_mutating_json(kb):
    path = document(kb)
    current = ask(kb, discussion_review.read(kb, path))
    request_row = request_message(kb, current)
    original_body = request_row['body']
    shown = discussion_review.message_text(request_row, [request_row])
    assert '指定复核者 @reviewer' in shown and '- First statement.' in shown
    assert '被审原文版本 ' + current['sha256'][:12] in shown
    assert request_row['body'] == original_body
    presented(kb, current)
    sent = reply(kb, current, results=[
        {'item_id': current['items'][0]['id'], 'verdict': 'disputed', 'reason': 'Source differs.',
         'evidence': ['records/source.md']},
    ])
    result_row = mail.parse_message(sent['path'])
    shown = discussion_review.message_text(result_row, [request_row, result_row])
    assert '有分歧' in shown and 'Source differs.' in shown and 'records/source.md' in shown
    assert '被审原文版本 ' + current['sha256'][:12] in shown
    assert discussion_review.message_text(result_row, [result_row]) is None
    assert json.loads(result_row['body'])['schema'] == discussion_review.RESULT_SCHEMA


def test_profiles_discuss_remains_classified_and_available_for_agent_review(kb):
    goal = document(kb, '# Goal\n', 'goal/a.md')
    path = document(kb, '---\ntitle: Discussion\n---\n\n[[goal/a.md]]\n\n## 人的判断\nStatement.\n',
                    'profiles/discuss/2026/11/07/a.md')
    assert studio.read_file(kb, path)['kind'] == 'discuss'
    assert studio.document_date(path) == '2026-11-07'
    assert path in studio.view(kb, goal)['files']
    assert ask(kb, discussion_review.read(kb, path))['summary']['pending'] == 1
