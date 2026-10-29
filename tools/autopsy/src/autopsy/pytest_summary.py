"""Extract structured facts from pytest log tails: failing tests and counts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# FAILED tests/test_api.py::test_timeout - AssertionError: expected 200
# searched, not matched: CI log lines carry timestamp/level prefixes
FAILED_LINE = re.compile(r"(?:FAILED|ERROR)\s+(\S+?::\S+|\S+\.py\S*|\S+)(?:\s+-\s+(.*))?$")
# 3 failed, 17 passed, 2 warnings in 4.51s   |   = 20 failed, 0 passed =
COUNTS_LINE = re.compile(r"^(?:=+|=+ )*(= .*)?")  # marker, real counts parsed below
SUMMARY = re.compile(r"=+\s*(.*)\s*=*$")
ENTRY = re.compile(r"(\d+)\s+(failed|passed|skipped|xfailed|xpassed|error|warnings)", re.I)
JUNIT_STYLE = re.compile(r"^\s*(?:Failures:|Errors:)\s*$")


@dataclass
class PytestSummary:
    counts: dict[str, int] = field(default_factory=dict)
    failed_tests: list[str] = field(default_factory=list)
    first_error: str | None = None

    @property
    def is_pytest(self) -> bool:
        return bool(self.counts) or bool(self.failed_tests)

    def counts_text(self) -> str:
        return ", ".join(f"{self.counts[k]} {k}" for k in
                         ("failed", "error", "passed", "skipped", "xfailed", "xpassed", "warnings")
                         if self.counts.get(k))


def parse_pytest(log: str) -> PytestSummary:
    """Read the tail facts: the ``short test summary info`` block and the final
    ``= N failed, M passed =`` counts line. CI log lines carry timestamp/level
    prefixes, so everything matches by search, not from the line start."""
    summary = PytestSummary()
    in_block = False
    for line in log.splitlines():
        stripped = line.strip()
        if "short test summary info" in stripped and not FAILED_LINE.search(stripped):
            in_block = True
            continue
        if in_block:
            m = FAILED_LINE.search(stripped)
            if m:
                test_id = m.group(1)
                if test_id not in summary.failed_tests:
                    summary.failed_tests.append(test_id)
                if summary.first_error is None and m.group(2):
                    summary.first_error = m.group(2)[:200]
                continue
            if stripped.startswith("="):
                in_block = False
        if not summary.counts and "=" in stripped and ENTRY.search(stripped):
            if stripped.count("=") >= 2:
                for count, kind in ENTRY.findall(stripped):
                    summary.counts[kind.lower()] = int(count)
    # pytest-rerunfailures / xdist sometimes only print FAILED lines without the block
    for line in log.splitlines():
        m = FAILED_LINE.search(line)
        if m and m.group(1) not in summary.failed_tests:
            summary.failed_tests.append(m.group(1))
    return summary


FILENAME = re.compile(r"\.(py|cpp|rs|go|ts|js)\b")
