"""autopsy: classify failed GitHub Actions runs and point at the right fix."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .fixtures import INTENDED, write_fixtures
from .gh import AutopsyError, JobLog, fetch_logs, fetch_run
from .pytest_summary import parse_pytest
from .rules import Verdict, classify_log, load_rules

ADVICE = {
    "cancel": "Cancelled by a newer run or manually -- not a failure. If cancellation storms are killing slow test jobs, add a concurrency group key that doesn't cancel in-progress runs.",
    "infra": "Runner/infrastructure fault, not your code. `gh run rerun <id> --failed` is legitimate; if disk or 'no space left' repeats, prune caches and artifacts in the workflow.",
    "config": "The workflow file itself is invalid, the code never ran. Fix the YAML/composite action on the error line; check the annotations via `gh api .../attempts/N` too.",
    "dependency": "External registry or network failed mid-install. Rerun may pass transiently; for reliability, pin versions, use a cache/setup action, and check the registry status page. If it's ECONNRESET on a proxy in a corporate network, that's the culprit, not the registry.",
    "timeout": "Something got slow or genuinely hangs. Don't raise the limit reflexively: find the step that ate the time, check for a test waiting on a port that never opens, and time-cap the suite.",
    "oom": "Killed for memory: a leak, an unbounded collection, or a genuinely bigger build. Profile locally before raising runner size; the log above shows the step that died.",
    "flaky-suspect": "Classic flake fingerprints (ports in use, locked db, late server start). Confirm with reruns before 'fixing': `autopsy rerun` guidance is in the skill. Quarantine only if you must ship today.",
    "test-failure": "Deterministic-looking test failures with failure counts. This is the code; the failing test list and first assertion are in the summary. Next step: reproduce locally, not more triage.",
}
UNKNOWN = ("No signature matched. Read the raw log yourself -- head, tail and the lines "
           "around ##[error] markers. If you find a repeating pattern, add it to a rules "
           "file (see `autopsy classify --rules`) so next time it's classified.")


def autopsy_log(log: str, rules) -> tuple[Verdict, object]:
    verdict = classify_log(log, rules)
    return verdict, parse_pytest(log)


def print_report(job_label: str, verdict: Verdict, pytest, extra_rules: str | None = None) -> None:
    print(f"== {job_label}")
    if pytest is not None and pytest.is_pytest:
        counts = pytest.counts_text()
        if counts:
            print(f"   pytest    {counts}")
        for test in pytest.failed_tests[:5]:
            print(f"   failed    {test}")
        if len(pytest.failed_tests) > 5:
            print(f"   ... {len(pytest.failed_tests) - 5} more failing tests")
        if pytest.first_error:
            print(f"   first     {pytest.first_error}")
    if verdict.primary:
        cat = verdict.primary
        print(f"   verdict   {cat}")
        for hit in verdict.evidence(cat, 3):
            print(f"   evidence  L{hit.line_no}: {hit.line[:160]}")
        print(f"   action    {ADVICE.get(cat, UNKNOWN)}")
    else:
        print("   verdict   unknown")
        print(f"   action    {UNKNOWN}")
    if extra_rules:
        print("   (custom rules also active)")


def cmd_classify(args) -> int:
    rules = load_rules(args.rules, args.replace)
    logs = [Path(f).read_text(encoding="utf-8", errors="replace") for f in args.logs]
    if args.json:
        rows = []
        for path, log in zip(args.logs, logs):
            verdict, pytest = autopsy_log(log, rules)
            rows.append({
                "file": str(path), "primary": verdict.primary,
                "categories": {c: len(v) for c, v in verdict.categories().items()},
                "failed_tests": pytest.failed_tests[:20], "counts": pytest.counts,
            })
        print(json.dumps(rows, indent=2))
    else:
        for path, log in zip(args.logs, logs):
            verdict, pytest = autopsy_log(log, rules)
            print_report(Path(path).name, verdict, pytest, extra_rules=args.rules)
    return 0


def cmd_run(args) -> int:
    rules = load_rules(args.rules, args.replace)
    run = fetch_run(args.target)
    print(f"run       {run.name} [{run.event}] {run.url}")
    logs = fetch_logs(run)
    any_hits = False
    primaries = []
    for entry in logs:
        verdict, pytest = autopsy_log(entry.log, rules)
        print_report(entry.label, verdict, pytest)
        if verdict.primary:
            any_hits = True
            primaries.append(verdict.primary)
    if not any_hits:
        print(f"action    {UNKNOWN}")
    print("\nnext      rerun failed jobs with: gh run rerun"
          + (f" {run.repository} #{run.id}" if run.repository != "?" else "")
          + f" --failed   (http failed-only view: {run.url[:-1] + '?check_suite_id=1 focus=failed' if False else run.url})")
    return 0


def cmd_demo(args) -> int:
    directory = write_fixtures(args.directory)
    print(f"wrote {len(INTENDED)} synthetic log fixtures to {directory}\n")
    intended_text = "\n".join(f"  {name:<28} -> {cat}" for name, cat in INTENDED.items())
    print(f"expected verdicts:\n{intended_text}\n")
    print("try:")
    print(f"  autopsy classify {directory}/runner-disk-full.txt")
    print(f"  autopsy classify {directory}/*.txt --json")
    print(f"  autopsy classify {directory}/pytest-real-assert.txt   # pytest summary extraction")
    return 0


def cmd_rules(args) -> int:
    from .rules import BUILTIN_RULES
    print(BUILTIN_RULES)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autopsy", description=__doc__)
    parser.add_argument("--version", action="version", version=f"autopsy {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="fetch a failed run's logs via gh and classify them")
    p.add_argument("target", help="full run URL or numeric run id (from the repo directory)")
    p.add_argument("--rules", help="extra registry .toml with [[category]] blocks")
    p.add_argument("--replace", action="store_true", help="use only the custom registry")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("classify", help="classify saved log files offline")
    p.add_argument("logs", nargs="+")
    p.add_argument("--rules")
    p.add_argument("--replace", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_classify)

    p = sub.add_parser("demo", help="write synthetic CI log fixtures and explain them")
    p.add_argument("directory", nargs="?", default="autopsy-demo")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("rules", help="print the built-in signature registry (to extend or replace)")
    p.set_defaults(func=cmd_rules)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except AutopsyError as exc:
        print(f"autopsy: error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"autopsy: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
