# Finding and fixing flaky tests

"Flaky" means the same code passes and fails across runs. Each cause has a specific probe, so stop rerunning blindly and start narrowing.

## The four causes and their probes

### 1. Order dependence (fails alone, passes in the suite, or vice versa)

Something a *previous or later* test did changes behavior: leaked global state, an un-reset mock, a mutated module-level constant, an unclosed DB transaction.

```bash
pytest tests/ -q                                    # suite: green
pytest tests/test_flaky.py -q                       # alone: red? order dependence
pytest tests/ -p no:randomly                        # fixed file order
for seed in 1 2 3 4 5; do pytest tests/ -q --randomly-seed=$seed | tail -1; done
```

(pytest-randomly shuffles by default; a test suite that's *never* run shuffled has hidden order assumptions it hasn't met yet.)

Once a seed reproduces it, bisect the pair. If `pytest A B` is red but each alone is green, A leaks into B. The usual suspects: `time.sleep` monkeypatched at module level, a DB row inserted without teardown, `sys.path` or `cwd` mutated.

Fix: make the test hermetic — reset state in a fixture, don't trust other tests' setup. Never fix by reordering the file.

### 2. Isolation leakage (fails in the suite, passes alone)

The inverse direction of the same coin, plus resource leftovers: a server from an earlier test still holds the port.

```bash
pytest tests/test_flaky.py --count=20 -q            # needs pytest-repeat: same test, N times
```

If run 7 of 20 fails: state accumulates across the test's own instances — an appending file, a counter, a growing list.

### 3. Time and timing

Real sleeps, race windows, "wait 2 seconds for the server".

- Failure signatures: `TimeoutError`, "server didn't start within", pass on a fast dev machine, fail on a loaded CI runner.
- Probe: artificially load the machine or slow the clock (`freezegun` for clock-driven code). If the test's success depends on machine speed, it's this.
- Fix: poll readiness instead of sleeping (`for _ in range(50): try connect: break; time.sleep(0.1)`), freeze time in clock tests, and never assert on wall-clock durations.

### 4. Concurrency and resources

Fixed ports, parallel workers racing one file, `tmp_path` shared across xdist workers by mistake.

- Signatures in autopsy's `flaky-suspect`: "Address already in use", "database table is locked", "duplicate key value".
- Fix: `port=0` (ephemeral) everywhere, unique per-worker paths (pytest-xdist's `tmp_path` already does this), file locking or per-worker DB schemas.

## Confirm-first discipline

Before "fixing" a flake, you must have seen it fail at least twice and pass at least once under controlled conditions. Otherwise, you're rerunning a deterministic failure you didn't reproduce, or editing code for a bug that exists only under conditions you haven't identified.

- If it fails the same way every standalone run: it's not flaky, treat it as a normal deterministic failure and fix the code.
- If it only fails under reruns: it's flaky, keep the failing seed in a comment for reproduction.

## Quarantine, honestly

If you must ship today with a real flake:

1. Mark it (pytest: `@pytest.mark.flaky(reason="...", link="issue #123")`).
2. Track it in a linked issue -- flaky tests are tech debt.
3. Set an expiry. After the expiry date, quarantine is gone and the test blocks CI like any other failure. If nobody fixed it in a month, the test isn't worth keeping — the team has decided by inaction, explicitly.
4. A count of quarantined tests that only grows is a red flag. Spend focused time on stability batch-work: fix the worst offenders instead of growing the pile.

## Residual risk

CI rerun buttons and pytest-rerunfailures mask flakes by design: they re-run failures automatically and mark a run green if the reruns pass. If you use them, keep the rerun reporting on (pytest-rerunfailures reports reruns in its summary) — silenced counting makes the suite *look* healthy while it rots invisibly.

## Tools reference

| Tool | What it gives you |
|---|---|
| pytest-randomly | Order dependence via seed shuffling (default-on) |
| pytest-repeat | `--count=N` hammering for isolation leakage |
| pytest-forked / xdist `-p xdist` | True isolation testing (process-level cleanup erases leaks) |
| pytest-rerunfailures | Auto-reruns — a masking tool; keep its rerun reporting enabled |
| freezegun / pytest-freezer | Clock determinism for time-dependent tests |
| responses/respx | Network determinism (turns "sometimes ECONNRESET" into "always exact fixture") |
