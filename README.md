# ci-autopsy

[English](README.md) | [Русский](README.ru.md)

[![CI](https://github.com/juzorei/ci-autopsy/actions/workflows/ci.yml/badge.svg)](https://github.com/juzorei/ci-autopsy/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/github/license/juzorei/ci-autopsy)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/ci-autopsy)](https://pypi.org/project/ci-autopsy/)

An agent skill and a CLI that diagnose failed GitHub Actions runs before anyone starts guessing.

Red CI has three honest outcomes — infrastructure noise, a broken workflow, or a real code failure. Most wasted effort comes from mixing them up: rerunning a broken workflow five times, or debugging a registry timeout as if it were your code. `autopsy` forces the classification step first.

```text
$ autopsy run https://github.com/owner/repo/actions/runs/123456789
== Test (ubuntu-latest, 3.13) (failure)
   pytest    2 failed, 431 passed, 1 skipped
   failed    tests/test_pricing.py::test_discount_applied
   first     AssertionError: assert 90.0 == 85.0
   verdict   test-failure
   evidence  L3: FAILED tests/test_pricing.py::test_discount_applied - AssertionError: ...
   action    Deterministic-looking test failures. This is the code; reproduce locally, not more triage.
```

## How it works

**0.1.1:** live GitHub reads now use GET with complete job pagination, honour `/attempts/N`, and strip terminal control sequences from downloaded logs. Reports identify the selected attempt and do not blindly recommend rerunning code failures or empty/in-progress runs. See the [CLI reference](tools/autopsy/README.md).

- `autopsy run <url-or-id>` — fetches every failed job's log through the authenticated `gh` (no tokens, no API keys), classifies each job, prints verdict + evidence + extracted pytest summary + the appropriate action.
- `autopsy classify <logs...>` — the same classification on saved logs, offline; `--json` for scripts.
- `autopsy rules` — prints the built-in signature registry (plain TOML). Extend it with `--rules your.toml` or fully replace with `--replace`: every project has its own recurring noise, and rules are data, not code — commit them, review them in PRs.
- `autopsy demo` — ten realistic synthetic logs (disk-full runners, registry 429s, concurrency cancels, port-in-use flakes) to try everything without a repo.

The eight verdicts are prioritized, not mutual: a timed-out job ends with a "cancelled" line, so `timeout` outranks `cancel` — but a plain concurrency cancel still outranks test failures visible in its log. The priority list encodes lessons from real runs.

Python 3.11+, no dependencies beyond `gh` being installed for `run`.

## The skill

[skills/ci-triage](skills/ci-triage) turns the CLI into a workflow a coding agent can follow on its own: fetch only failed jobs, classify before touching anything, match the action to the verdict (rerun / fix YAML / fix code), confirm flakes before fixing them with seed loops and rerun hammers, teach autopsy the project's noise via a committed rule file, and end with a three-line report a human can act on.

## Install

```bash
pip install ci-autopsy          # CLI
npx skills add juzorei/ci-autopsy   # the skill, for any supported agent
```

As a Claude Code plugin: `/plugin marketplace add juzorei/ci-autopsy`.

## More from this portfolio

Part of a series of focused skill+CLI tools by the same author:

- [loglens](https://github.com/juzorei/loglens) — triage huge logs the same way autopsy triages failed CI
- [flakehunt](https://github.com/juzorei/flakehunt) — prove a test is flaky before rerunning it green
- [bumpmap](https://github.com/juzorei/bumpmap) — the other half of a broken PR: dependency upgrades

Browse the rest at the [juzorei profile](https://github.com/juzorei?tab=repositories).

## Scope

For triaging failures in your own repositories and CI. Quarantining a flaky test honestly (linked issue + expiry date) instead of silencing it is part of the skill's contract.

MIT licensed.
