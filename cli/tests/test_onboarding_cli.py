import json
from typer.testing import CliRunner
from knowledge_studio.cli import app
from knowledge_studio import studio_history


def test_conversation_and_studio_share_progress_without_auto_approval(tmp_path):
    (tmp_path / 'wiki').mkdir()
    runner = CliRunner()
    suffix = ['--path', str(tmp_path)]
    result = runner.invoke(app, ['onboarding', 'status', *suffix])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)['status'] == 'not_started'
    assert not (tmp_path / 'records/studio/onboarding.json').exists()
    assert runner.invoke(app, ['onboarding', 'complete', 'discuss', *suffix]).exit_code == 0
    state = studio_history.onboarding(tmp_path)
    assert state['status'] == 'in_progress'
    assert state['steps'] == {'discuss': True, 'goals': False, 'learning': False}
    assert runner.invoke(app, ['onboarding', 'skip', *suffix]).exit_code == 0
    assert studio_history.onboarding(tmp_path)['steps']['learning'] is False
    assert runner.invoke(app, ['onboarding', 'reset', *suffix]).exit_code == 0
    assert not any(studio_history.onboarding(tmp_path)['steps'].values())
    for step in ('discuss', 'goals', 'learning'):
        assert runner.invoke(app, ['onboarding', 'complete', step, *suffix]).exit_code == 0
    assert studio_history.onboarding(tmp_path)['status'] == 'completed'
    assert not list((tmp_path / 'wiki').iterdir())
    before = (tmp_path / 'records/studio/onboarding.json').read_bytes()
    assert runner.invoke(app, ['onboarding', 'complete', 'invalid', *suffix]).exit_code != 0
    assert (tmp_path / 'records/studio/onboarding.json').read_bytes() == before


def test_onboarding_refuses_non_instance_without_writing(tmp_path):
    result = CliRunner().invoke(app, ['onboarding', 'skip', '--path', str(tmp_path)])
    assert result.exit_code != 0
    assert not list(tmp_path.iterdir())


def test_new_user_flow_links_team_without_copying_or_approving(tmp_path, monkeypatch):
    import subprocess
    from knowledge_studio import linked_sources
    runner = CliRunner()
    personal, team, host = (tmp_path / name for name in ('personal', 'team', 'codex-home'))
    monkeypatch.setenv('CODEX_HOME', str(host))
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ['skills-install', '--global', '--editor', 'codex']).exit_code == 0
    assert runner.invoke(app, ['init', str(personal), '--no-git', '--no-set-default']).exit_code == 0
    assert runner.invoke(app, ['team', 'init', str(team), '--no-git', '--no-set-default']).exit_code == 0
    subprocess.run(['git', 'init', str(team)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(team), 'add', '.'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(team), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'fixture'], check=True, capture_output=True)
    monkeypatch.setenv('OKS_ROOT', str(personal))
    result = runner.invoke(app, ['sources', 'link', str(team), '--name', 'team', '--repository', 'example/team'])
    assert result.exit_code == 0, result.output
    assert linked_sources.configuration(personal)[0]['path'] == str(team)
    assert not list((personal / 'wiki').rglob('*.md'))
    assert not (personal / 'profiles/team.md').exists()
    assert (host / 'skills/oh-my-oks/references/onboarding.md').is_file()
    for step in ('discuss', 'goals', 'learning'):
        assert runner.invoke(app, ['onboarding', 'complete', step]).exit_code == 0
    assert studio_history.onboarding(personal)['status'] == 'completed'
    assert not list((personal / 'wiki').rglob('*.md'))
    assert not list((personal / 'drafts').rglob('*.md'))
