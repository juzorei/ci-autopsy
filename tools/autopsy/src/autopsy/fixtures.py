"""Realistic synthetic CI logs so `autopsy demo` and the tests never need a repo.

Fixtures mirror real GitHub Actions log shapes: timestamp/level prefixes, gh CLI
job headers, pytest tails. Each has exactly one intended verdict.
"""

from __future__ import annotations

from pathlib import Path

TS = "2026-10-29T12:00:00.0000000Z"

FIXTURES: dict[str, str] = {
    "runner-disk-full.txt": f"""\
##[group]Run actions/setup-python@v7
{TS} ##[endgroup]
{TS} ##[error]The runner has received a shutdown signal. This can happen when the Runner service is stopped, or the runner is cooling off
{TS} ##[warning]No space left on device
{TS} Cleaning up orphan processes
""",
    "cancel-concurrency.txt": f"""\
{TS} ##[warning]canceling since a higher priority waiting request exists
{TS} ##[error]The job running on runner Hosted Agent has been cancelled
{TS} Post Run actions/checkout@v7
{TS} Cleaning up orphan processes
""",
    "workflow-syntax.txt": f"""\
##[error]Invalid workflow file
##[error].github/workflows/ci.yml (Line: 14, Col: 3): Every job must define a runs-on
""",
    "registry-429.txt": f"""\
{TS} ##[group]Run pip install -r requirements.txt
{TS} Collecting numpy==2.1.0
{TS} ##[error]HTTP 429 Too Many Requests for URL https://pypi.org/simple/numpy/
{TS} Retrying (1/6)...
{TS} ##[error]Process completed with exit code 1.
""",
    "npm-econnreset.txt": f"""\
{TS} npm ERR! network request to https://registry.npmjs.org/express failed, reason: read ECONNRESET
{TS} npm ERR! code ETIMEDOUT
{TS} ##[error]Process completed with exit code 1.
""",
    "pytest-flaky-port.txt": f"""\
{TS} ============================= test session starts ==============================
{TS} platform win32 -- Python 3.12.4, pytest-8.3.5
{TS} test_bind_addr.py .                                                          [ 50%]
{TS} test_bind_addr.py F                                                          [100%]
{TS} =================================== FAILURES ===================================
{TS} ___________________________ test_server_binds_second_time __________________________
{TS} OSError: [Errno 100] Address already in use: ('127.0.0.1', 8765)
{TS} ============================ short test summary info ===========================
{TS} FAILED tests/test_bind_addr.py::test_server_binds_second_time - OSError: [Errno 100] Address already in use: ('127.0.0.1', 8765)
{TS} ================= 1 failed, 1 passed, 2 warnings in 3.11 seconds ================
""",
    "pytest-real-assert.txt": f"""\
{TS} ##[section]Run pytest -q
{TS} ============================ short test summary info ===========================
{TS} FAILED tests/test_pricing.py::test_discount_applied - AssertionError: assert 90.0 == 85.0
{TS} FAILED tests/test_pricing.py::test_discount_stacks - AssertionError: assert 180.0 == 170.0
{TS} ================= 2 failed, 431 passed, 1 skipped in 52.30 seconds ================
{TS} ##[error]Process completed with exit code 1.
""",
    "job-timeout.txt": f"""\
{TS} ##[error]The job running on runner GitHub Actions 100 has exceeded the maximum execution time of 360 minutes.
{TS} ##[warning]Timeout after 180000 ms
{TS} ##[error]The operation was canceled
""",
    "node-oom.txt": f"""\
{TS} <--- Last few GCs --->
{TS} [4324:0x103a00000]    120034 ms: Mark-Compact 4035.6 (4124.7) -> 4035.5 (4124.9) MB, 412.6 / 0.0 ms  (average mu = 0.123, current mu = 0.088) allocation failure; scavenge might not succeed
{TS} FATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory
{TS} ##[error]Process completed with exit code 134.
""",
    "docker-connrefused.txt": f"""\
{TS} docker: Error response from daemon: dial tcp 127.0.0.1:5432: connect: connection refused.
{TS} ##[error]Process completed with exit code 1.
""",
}

INTENDED = {
    "runner-disk-full.txt": "infra",
    "cancel-concurrency.txt": "cancel",
    "workflow-syntax.txt": "config",
    "registry-429.txt": "dependency",
    "npm-econnreset.txt": "dependency",
    "pytest-flaky-port.txt": "flaky-suspect",
    "pytest-real-assert.txt": "test-failure",
    "job-timeout.txt": "timeout",
    "node-oom.txt": "oom",
    "docker-connrefused.txt": "dependency",
}


def write_fixtures(directory: str | Path) -> Path:
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    for name, text in FIXTURES.items():
        (out / name).write_text(text, encoding="utf-8")
    return out
