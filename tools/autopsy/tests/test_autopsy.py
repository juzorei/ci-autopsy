import json
from pathlib import Path

import pytest

from autopsy.cli import main
from autopsy.fixtures import FIXTURES, INTENDED, write_fixtures
from autopsy.gh import RUN_URL, AutopsyError, fetch_run
from autopsy.pytest_summary import parse_pytest
from autopsy.rules import PRIORITY, classify_log, load_rules, parse_rules


@pytest.fixture(scope="module")
def rules():
    return load_rules()


@pytest.mark.parametrize("name,expected", sorted(INTENDED.items()))
def test_fixture_verdicts(name, expected, rules):
    verdict, pytest_ctx = classify_log(FIXTURES[name], rules), None
    assert verdict.primary == expected, f"{name}: categories hit: {verdict.categories()}"


def test_cancel_beats_test_failure(rules):
    """A cancelled job that also shows a failed test must classify as cancel."""
    log = FIXTURES["pytest-real-assert.txt"] + "##[error]The job running on runner X has been cancelled\n"
    assert classify_log(log, rules).primary == "cancel"


def test_infra_beats_dependency_and_failure(rules):
    log = (
        FIXTURES["runner-disk-full.txt"]
        + "FAILED tests/x.py::test_y - AssertionError\n"
        + "ECONNRESET\n"
    )
    assert classify_log(log, rules).primary == "infra"


def test_unknown_log_is_not_forced(rules):
    verdict = classify_log("all quiet on the western front\n", rules)
    assert verdict.primary is None


def test_builtin_registry_parses_and_every_rule_compiles(rules):
    assert {r.category for r in rules} >= set(PRIORITY)
    for rule in rules:
        assert rule.regex.pattern


def test_custom_registry_extends_and_replaces(tmp_path):
    custom = tmp_path / "r.toml"
    custom.write_text(
        '[[category]]\nname = "corp-proxy"\n"corp-proxy" = ["our proxy is down again"]\n'
    )
    extended = load_rules(str(custom))
    assert {r.category for r in extended} >= set(PRIORITY) | {"corp-proxy"}
    only = load_rules(str(custom), replace=True)
    assert {r.category for r in only} == {"corp-proxy"}
    log = "error: our proxy is down again\n"
    assert classify_log(log, only).primary == "corp-proxy"


def test_bad_registry_rules_fail_loudly(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text('[[category]]\nname = "x"\n"x" = "["\n')
    with pytest.raises(ValueError, match="valid regex"):
        parse_rules(bad.read_text())
    with pytest.raises(ValueError, match="needs a registry"):
        load_rules(replace=True)


def test_pytest_summary_extraction():
    s = parse_pytest(FIXTURES["pytest-real-assert.txt"])
    assert s.counts["failed"] == 2 and s.counts["passed"] == 431
    assert len(s.failed_tests) == 2
    assert "test_discount_applied" in s.failed_tests[0]
    assert "assert 90.0 == 85.0" in s.first_error


def test_pytest_duplicate_summary_not_duplicated():
    s = parse_pytest(FIXTURES["pytest-real-assert.txt"] + FIXTURES["pytest-real-assert.txt"])
    assert len(s.failed_tests) == 2


def test_non_pytest_log_has_no_summary():
    assert not parse_pytest(FIXTURES["node-oom.txt"]).is_pytest


def test_run_url_parsing():
    url = "https://github.com/foo/bar/actions/runs/1234567"
    assert RUN_URL.search(url).groups() == ("foo", "bar", "1234567", None)

    class Run: pass

    with pytest.raises(AutopsyError, match="URL"):
        fetch_run("not a url")


def test_cli_demo_and_classify(tmp_path, capsys):
    d = tmp_path / "fx"
    assert main(["demo", str(d)]) == 0
    out = capsys.readouterr().out
    assert "expected verdicts" in out

    files = [str(p) for p in sorted(d.glob("*.txt"))]
    assert main(["classify", *files, "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert {r["file"].split("\\")[-1]: r["primary"] for r in rows} == dict(INTENDED)

    assert main(["classify", files[0]]) == 0
    text = capsys.readouterr().out
    assert "verdict" in text and "action" in text


def test_cli_classify_unknown_and_custom(tmp_path, capsys):
    quiet = tmp_path / "quiet.txt"
    quiet.write_text("nothing to see\n")
    assert main(["classify", str(quiet)]) == 0
    assert "unknown" in capsys.readouterr().out

    custom = tmp_path / "r.toml"
    custom.write_text('[[category]]\nname = "corp"\n"x" = ["special breaker"]\n')
    flagged = tmp_path / "flag.txt"
    flagged.write_text("special breaker!\n")
    assert main(["classify", str(flagged), "--rules", str(custom), "--replace"]) == 0
    assert "corp" in capsys.readouterr().out


def test_cli_rules(capsys):
    assert main(["rules"]) == 0
    out = capsys.readouterr().out
    for cat in ("cancel", "infra", "config", "dependency", "timeout", "oom", "flaky-suspect", "test-failure"):
        assert f'name = "{cat}"' in out
