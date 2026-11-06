import json

import pytest

from knowledge_studio.studio_workflow import workflow


def put(root, path, text):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return target


def test_declared_skill_steps_and_checked_tasks_do_not_manufacture_execution(tmp_path):
    put(tmp_path, 'goal/a.md', '---\nskills: [skills/a/SKILL.md]\n---\n# Goal\n- [x] Finished checkbox\n')
    put(tmp_path, 'skills/a/SKILL.md', '# Skill\n## Search\n## Write\n[[wiki/a]]\n')
    put(tmp_path, 'wiki/a.md', '# Knowledge\n')
    result = workflow(tmp_path, 'goal/a.md')
    assert result['runs'] == []
    assert result['references'] == [
        {'from': 'goal/a.md', 'to': 'skills/a/SKILL.md', 'kind': 'written_reference'},
        {'from': 'skills/a/SKILL.md', 'to': 'wiki/a.md', 'kind': 'written_reference'},
    ]
    assert any(row['checked'] for row in result['outline'])


def test_execution_identity_must_match_full_goal_not_basename(tmp_path):
    put(tmp_path, 'goal/a.md', '# Goal\n')
    for run_id, goal in [('right', 'goal/a.md'), ('wrong', 'profiles/goals/a.md')]:
        put(tmp_path, f'raw/executions/{run_id}/run.json', json.dumps({'run_id': run_id, 'goal_id': goal, 'status': 'running'}))
        put(tmp_path, f'raw/executions/{run_id}/events.jsonl', json.dumps({
            'run_id': run_id, 'event_id': run_id + ':1', 'event_type': 'ai_action',
            'actor': 'agent', 'payload': {'skill_path': 'skills/a/SKILL.md', 'step_id': 'search', 'unrelated': 'do not expose'},
        }))
    result = workflow(tmp_path, 'goal/a.md')
    assert [run['run_id'] for run in result['runs']] == ['right']
    assert result['runs'][0]['events'][0]['payload'] == {'skill_path': 'skills/a/SKILL.md', 'step_id': 'search'}


def test_workflow_rejects_escape_and_reports_corrupt_traces(tmp_path):
    put(tmp_path, 'goal/a.md', '# Goal\n')
    put(tmp_path, 'raw/executions/bad/run.json', '{broken')
    result = workflow(tmp_path, 'goal/a.md')
    assert not result['runs'] and result['warnings']
    with pytest.raises(ValueError):
        workflow(tmp_path, '../other/goal.md')
    outside = tmp_path.parent / (tmp_path.name + '-outside')
    outside.mkdir()
    (outside / 'run.json').write_text('{"goal_id":"goal/a.md"}')
    (tmp_path / 'raw/executions/escape').symlink_to(outside, target_is_directory=True)
    result = workflow(tmp_path, 'goal/a.md')
    assert any('escape' in warning for warning in result['warnings'])


def test_skill_execution_requires_explicit_full_skill_path(tmp_path):
    put(tmp_path, 'skills/a/SKILL.md', '# Skill\n## Search\n')
    put(tmp_path, 'raw/executions/run/run.json', json.dumps({'run_id': 'run', 'goal_id': 'goal/a.md'}))
    put(tmp_path, 'raw/executions/run/events.jsonl', '\n'.join(json.dumps({
        'run_id': 'run', 'event_id': str(i), 'event_type': 'ai_action', 'actor': 'agent',
        'payload': {'skill_path': skill_path, 'step_id': 'search'},
    }) for i, skill_path in enumerate(['skills/a/SKILL.md', 'skills/b/SKILL.md', 'a'])))
    result = workflow(tmp_path, 'skills/a/SKILL.md')
    assert len(result['runs']) == 1
    assert result['runs'][0]['skill_only']
    assert [event['event_id'] for event in result['runs'][0]['events']] == ['0']
