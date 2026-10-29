---
name: ci-triage
description: Diagnose a failed GitHub Actions run and decide the right fix instead of reflexively rerunning or rewriting code. Use whenever CI is red, a workflow fails on a schedule or nightly run, "the pipeline is broken again", a PR shows failed checks, a deployment job failed, the user pastes a CI error or run link, or asks "why did CI fail", "is this flaky", "rerun or fix", "fix the build", or wants to spend attention on real failures and auto-munge infra noise. Covers fetching failed-job logs with gh, classifying the failure (infra, config, dependency, timeout, OOM, cancel, flaky-suspect, real test failure), extracting pytest/Jest-style summaries, deciding rerun vs code fix vs workflow fix, and reproducing locally.
---

# CI triage

Red CI has exactly three honest outcomes: infrastructure noise (rerun), a broken workflow (fix YAML), or a real failure (fix code). Most wasted effort comes from guessing wrong — "rerun a broken workflow five times", or "debug a flaky registry timeout as if it were your code." This skill forces the classification step before any fixing.

Install the CLI:

```bash
pip install ci-autopsy
```

## 1. Pull the failure, not the whole log

Never read a 40 MB log in one scroll. Get only the failed jobs:

```bash
gh run view 123456789 --log-failed        # human view; big runs can be slow
autopsy run https://github.com/owner/repo/actions/runs/123456789   # classified summary
```

`autopsy run` fetches every failed job's log through the authenticated `gh` (no tokens of its own), classifies each, prints the verdict with evidence lines, extracted pytest summaries (failing tests, counts, first assertion) and the next action.

If the run failed at the *workflow* level (no job ever started — invalid YAML), there are no job logs. Read the annotations instead:

```bash
gh api repos/{owner}/{repo}/actions/runs/{id}/attempts/1 --jq '.workflow_annotations'
```

For saved logs or logs from other CI systems, `autopsy classify file.log [file2.log ...]` does the same classification offline. `--json` for machine-readable output.

## 2. Read the verdict

```text
== Test (ubuntu-latest, 3.13) (failure)
   pytest    2 failed, 431 passed, 1 skipped
   failed    tests/test_pricing.py::test_discount_applied
   first     AssertionError: assert 90.0 == 85.0
   verdict   test-failure
   evidence  L3: FAILED tests/test_pricing.py::test_discount_applied - ...
   action    Deterministic-looking test failures. This is the code; reproduce locally, not more triage.
```

The categories, in the order that wins when several hit one log:

| Verdict | Meaning | Action |
|---|---|---|
| `config` | Workflow YAML invalid; the code never ran | Fix the workflow file on the error line. Rerunning cannot help. |
| `infra` | Runner/hosted infra failed (shutdown signal, disk full, lost communication) | `gh run rerun <id> --failed` is legitimate. If "No space left" repeats, prune caches/artifacts in the workflow. |
| `timeout` | Job/test step exceeded a time limit | Find the step that ate the time (the timestamps are in the log). Don't reflexively raise limits: a test waiting on a port that never opens looks identical to "CI is slow". |
| `oom` | Killed for memory (OOMKilled, heap exhausted) | Profile locally before raising runner size. |
| `cancel` | Cancelled by a newer run (concurrency) or manually | Not a failure. If slow test jobs die to cancellation storms, revisit the `concurrency` group key. |
| `dependency` | Registry/network failed (429, ECONNRESET, lock conflicts, service down) | Rerun may pass transiently. For reliability: pin versions, cache deps, retry the install step. Check the registry status page before assuming your fault. |
| `flaky-suspect` | Port in use, locked DB, late server start — the classic flake fingerprints | **Confirm before fixing.** See step 4. |
| `test-failure` | Test assertions with counts | This is the code. Reproduce locally and fix — or, if you must ship today, skip-and-file honestly. |
| `unknown` | No signature matched | Read the raw log yourself (head, tail, and lines around `##[error]`). A *repeating* unknown pattern belongs in a custom rule file — see step 5 — so next time it's classified. |

Priority is deliberate: a timed-out job ends with a "cancelled" line, so `timeout` outranks `cancel` — but a plain concurrency cancel still outranks test failures visible in its log, because those tests never finished.

## 3. Match the action to the verdict

- `config` — fix YAML. `actionlint` on the file catches most of this class before push.
- `infra`, `dependency` — rerun failed jobs only: `gh run rerun <id> --failed`. Never rerun the whole run when one matrix leg failed; the other legs already told you they're fine.
- `cancel` — nothing is broken. Don't "fix" anything.
- `timeout`, `oom` — measure locally, then either fix the slowness/leak or raise the specific limit with a comment saying why.
- `test-failure` — reproduce locally before editing. If it doesn't reproduce locally, it was `flaky-suspect` all along: proceed to step 4.
- `flaky-suspect` — proceed to step 4. Do not "fix" code before confirming the flake.

## 4. Confirm a flake before fixing it

A flake fixits worth nothing unless you can show the flake. Minimal loop, pytest:

```bash
# order dependence: fixed seed first, then single test repeatedly
pytest tests/test_flaky.py -p no:randomly
for i in $(seq 1 20); do pytest tests/test_flaky.py -q --randomly-seed=$i | tail -1; done

# resource/timing: hammer it
pytest tests/test_flaky.py --count=20 -x    # needs pytest-repeat
```

If it fails under some seeds but passes alone, you have order dependence; if it fails standalone but passes in the full suite, you have isolation leakage (a fixture or global state another test "helpfully" sets). The full methodology (fixtures, sockets, time, seeds, quarantine with a TODO and an expiry date): [references/flaky-tests.md](references/flaky-tests.md).

For the narrow port/server-start class, check: does the test bind a fixed port instead of port 0 / an ephemeral one? Is there a `sleep` waiting for a server instead of polling readiness? Those two are most of the genre.

## 5. Teach autopsy your project's noise

Every project has its own recurring failures (a cancel-during-mergequeue, a known-flaky vendor health check). Instead of re-triaging them from scratch, keep a rule file in the repo:

```bash
autopsy rules > .github/autopsy-rules.toml   # start from the built-in registry
# add a [[category]] block:
#   name = "corp-proxy"
#   "corp-proxy" = ["our proxy is down again"]
autopsy classify log.txt --rules .github/autopsy-rules.toml            # extend
autopsy classify log.txt --rules .github/autopsy-rules.toml --replace # replace entirely
```

Rules are data (regexes in TOML), not code — commit them to the repo, review them in PRs. Keep the built-ins unless a category is provably wrong for your project.

## 6. Report

End every triage with the three-line summary a human needs:

```text
verdict:  dependency (registry 429), not a code failure
evidence: L41 "HTTP 429 Too Many Requests for URL https://pypi.org/simple/..."
done:     rerun failed jobs (gh run rerun 123456789 --failed); caching added in #123 to prevent repeats
```

If the verdict was `unknown` or ambiguous, say so honestly — an honest "I don't know, read lines 200-260" beats a confidently wrong verdict.

## Scope

This skill is for triaging failures in *your own* repositories and CI. Don't run it against systems you don't have authorization to inspect, and don't use triage tooling to hide failures you know are real (quarantining a test requires a linked issue and an expiry date, never a silent skip).
