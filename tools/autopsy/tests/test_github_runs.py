import json
import subprocess
from types import SimpleNamespace

import pytest

from autopsy import gh
from autopsy.cli import main
from autopsy.fixtures import FIXTURES


def metadata(**extra):
    return {"id": 123, "name": "CI", "run_number": 4, "run_attempt": 3,
            "html_url": "https://github.com/owner/repo/actions/runs/123",
            "event": "push", "status": "completed", "conclusion": "failure", **extra}


def test_jobs_gets_all_pages_for_the_selected_attempt(monkeypatch):
    requests = []
    def fake(*args):
        requests.append(args)
        assert '--method' in args and args[args.index('--method') + 1] == 'GET'
        assert '--paginate' in args and '--slurp' in args
        assert args[1] == 'repos/owner/repo/actions/runs/123/attempts/3/jobs?per_page=100'
        return json.dumps([{'jobs': [{'id': 1, 'conclusion': 'success'}]},
                           {'jobs': [{'id': 2, 'conclusion': 'failure'}]}])
    monkeypatch.setattr(gh, '_gh', fake)
    assert gh.Run(metadata(), 'owner', 'repo').failed_jobs() == [{'id': 2, 'conclusion': 'failure'}]
    assert len(requests) == 1


def test_explicit_attempt_url_fetches_attempt_metadata_and_logs(monkeypatch):
    requests = []
    def fake(*args):
        requests.append(args[1])
        if args[1].endswith('/logs'): return FIXTURES['runner-disk-full.txt']
        if '/jobs?' in args[1]: return json.dumps([{'jobs': [{'id': 55, 'name': 'Test', 'conclusion': 'failure'}]}])
        return json.dumps(metadata(run_attempt=2))
    monkeypatch.setattr(gh, '_gh', fake)
    run = gh.fetch_run('https://github.com/owner/repo/actions/runs/123/attempts/2?check_suite_focus=true#logs')
    assert run.attempt == 2
    assert len(gh.fetch_logs(run)) == 1
    assert requests == [
        'repos/owner/repo/actions/runs/123/attempts/2',
        'repos/owner/repo/actions/runs/123/attempts/2/jobs?per_page=100',
        'repos/owner/repo/actions/jobs/55/logs',
    ]


def test_bare_id_resolves_repo_and_current_attempt(monkeypatch):
    def fake(*args):
        return 'owner/repo\n' if args[0] == 'repo' else json.dumps(metadata())
    monkeypatch.setattr(gh, '_gh', fake)
    run = gh.fetch_run('123')
    assert run.repository == 'owner/repo' and run.attempt == 3


@pytest.mark.parametrize('target', [
    'https://github.com.evil/owner/repo/actions/runs/123',
    'https://evilgithub.com/owner/repo/actions/runs/123',
    'https://example.org/?next=github.com/owner/repo/actions/runs/123',
    'https://github.com/owner/repo/actions/runs/123garbage',
    'https://github.com/owner/repo/actions/runs/123/attempts/0',
])
def test_invalid_run_urls_never_call_github(monkeypatch, target):
    calls = []
    monkeypatch.setattr(gh, '_gh', lambda *args: calls.append(args) or '{}')
    with pytest.raises(gh.AutopsyError): gh.fetch_run(target)
    assert not calls


@pytest.mark.parametrize('response', ['not-json', '{}', '[{}]', '[{"jobs":null}]'])
def test_malformed_jobs_fail_instead_of_claiming_no_failures(monkeypatch, response):
    monkeypatch.setattr(gh, '_gh', lambda *args: response)
    with pytest.raises(gh.AutopsyError): gh.Run(metadata(), 'owner', 'repo').jobs()


def test_gh_timeout_is_actionable(monkeypatch, capsys):
    def fake(*args, **kwargs): raise subprocess.TimeoutExpired('gh', 180)
    monkeypatch.setattr(gh.subprocess, 'run', fake)
    assert main(['run', 'https://github.com/owner/repo/actions/runs/123']) == 2
    assert 'timed out' in capsys.readouterr().err


def test_gh_decodes_logs_as_utf8(monkeypatch):
    def fake(*args, **kwargs):
        assert kwargs.get('encoding') == 'utf-8'
        return SimpleNamespace(returncode=0, stdout='log', stderr='')
    monkeypatch.setattr(gh.subprocess, 'run', fake)
    assert gh._gh('api', 'endpoint') == 'log'


@pytest.mark.parametrize('fixture,should_rerun', [('runner-disk-full.txt', True), ('pytest-real-assert.txt', False)])
def test_cli_rerun_guidance_is_scoped_to_the_failure(monkeypatch, capsys, fixture, should_rerun):
    import autopsy.cli as cli
    monkeypatch.setattr(cli, 'fetch_run', lambda _: gh.Run(metadata(), 'owner', 'repo'))
    monkeypatch.setattr(cli, 'fetch_logs', lambda _: [gh.JobLog({'name': 'test', 'conclusion': 'failure'}, FIXTURES[fixture])])
    assert main(['run', '123']) == 0
    output = capsys.readouterr().out
    assert 'attempt 3' in output
    command = 'gh run rerun 123 --repo owner/repo --failed'
    assert (command in output) == should_rerun
    assert 'gh run rerun owner/repo #123' not in output


@pytest.mark.parametrize('conclusion,status', [('success', 'completed'), ('failure', 'completed'), (None, 'in_progress')])
def test_empty_job_list_has_no_blind_rerun(monkeypatch, capsys, conclusion, status):
    import autopsy.cli as cli
    monkeypatch.setattr(cli, 'fetch_run', lambda _: gh.Run(metadata(conclusion=conclusion, status=status), 'owner', 'repo'))
    monkeypatch.setattr(cli, 'fetch_logs', lambda _: [])
    assert main(['run', '123']) == 0
    output = capsys.readouterr().out
    assert 'No failed-job logs' in output and status in output
    assert 'gh run rerun' not in output and 'No signature matched' not in output


def test_attempt_annotations_default_to_selected_attempt(monkeypatch):
    calls = []
    monkeypatch.setattr(gh, '_gh', lambda *args: calls.append(args[1]) or '{}')
    run = gh.Run(metadata(run_attempt=2), 'owner', 'repo')
    assert gh.fetch_attempt_annotations(run) == []
    assert calls == ['repos/owner/repo/actions/runs/123/attempts/2']


def test_job_log_ansi_controls_are_removed_before_reporting(monkeypatch):
    raw = '\x1b[31mNo space left on device\x1b[0m\n\x1b]52;c;clipboard-payload\x07'
    raw += '\x1b]8;;https://example.com\x1b\\visible\x1b]8;;\x1b\\\x07'
    calls = []
    def fake(*args):
        calls.append(args)
        return raw
    monkeypatch.setattr(gh, '_gh', fake)
    run = gh.Run(metadata(), 'owner', 'repo')
    monkeypatch.setattr(run, 'failed_jobs', lambda: [{'id': 55, 'conclusion': 'failure'}])
    logs = gh.fetch_logs(run)
    assert logs[0].log == 'No space left on device\nvisible'
    assert '--allow-escape-sequences' in calls[0]


def test_explicit_attempt_does_not_recommend_rerunning_current_run(monkeypatch, capsys):
    import autopsy.cli as cli
    monkeypatch.setattr(cli, 'fetch_run', lambda _: gh.Run(metadata(), 'owner', 'repo', explicit_attempt=True))
    monkeypatch.setattr(cli, 'fetch_logs', lambda _: [gh.JobLog({'name': 'test'}, FIXTURES['runner-disk-full.txt'])])
    assert main(['run', '123']) == 0
    output = capsys.readouterr().out
    assert 'Check the latest attempt' in output
    assert 'gh run rerun 123 --repo' not in output
