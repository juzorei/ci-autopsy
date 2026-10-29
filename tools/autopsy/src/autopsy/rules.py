"""Built-in failure signature registry and rule matching.

Rules are data, not code: a list of categories, each with regex signatures matched
against log lines. A custom registry can replace or extend the built-in one, so new
failure shapes are a text edit, not a release.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Higher priority = more specific explanation wins when several categories hit.
# A timed-out job ends with a cancellation line, so timeout outranks cancel;
# a cancelled job still outranks test failures visible in its log.
PRIORITY = [
    "config",
    "infra",
    "timeout",
    "oom",
    "cancel",
    "dependency",
    "flaky-suspect",
    "test-failure",
]

BUILTIN_RULES = """
[[category]]
name = "cancel"
description = "The run was cancelled (concurrency group or manual), not broken"
"cancel" = [
  "Cancelling since a (higher priority|deployment) waiting request exists",
  "The job running on runner .* has been cancelled",
  "Process completed with exit code 1.*cancell?ed",
  "has been cancelled through the API",
  "The operation was canceled",
]

[[category]]
name = "infra"
description = "Runner or hosted-CI infrastructure failed; rerun can be legitimate"
"infra" = [
  "The runner has received a shutdown signal",
  "runner.*(repossess|shutdown signal)",
  "No space left on device",
  "Lost communication with the runner",
  "The runner has unexpectedly exited",
  "System error.*runner|Runner.*unavailable",
  "We are currently experiencing.*incidents",
]
[[category]]
name = "config"
description = "Workflow YAML or setup is invalid; the code never ran"
"config" = [
  "Invalid workflow file",
  "(yaml|YAML) (parse|syntax) error",
  "Every job must define a runs-on",
  "Unexpected value '{{'",
  "Unrecognized named-value",
  "required workflow does not exist",
  "is not allowed to be used in this workflow",
  "No such (command|file or directory):.*actions/checkout",
]

[[category]]
name = "dependency"
description = "A registry or external service failed; usually not the code"
"dependency" = [
  "HTTP 429",
  "429 Too Many Requests",
  "Could not find a version that satisfies the requirement",
  "No matching distribution found",
  "(npm|yarn|pnpm) ERR!.*(network|ETIMEDOUT|ECONNRESET|404)",
  "error Your lock file needs to be updated",
  "ECONNRESET|ECONNREFUSED|ETIMEDOUT|EAI_AGAIN",
  "connect: connection refused",
  "Failed to fetch.*(registry|maven|nuget|pypi)",
  "(401|403) (Unauthorized|Forbidden).*(registry|npm|pypi)",
  "Certificate verification failed",
  "SSLError|CERTIFICATE_VERIFY_FAILED",
  "error: failed to select a version for",
]

[[category]]
name = "timeout"
description = "Exceeded a time limit (job, test, or network); find what got slow"
"timeout" = [
  "The job running on runner .* has exceeded the maximum execution time",
  "Timeout after [0-9]",
  "operation timed out",
  "timed? ?out after",
  "TimeoutError",
  "ReadTimeoutError",
  "SocketTimeoutException",
  "FAIL.*Timed out|Error: Timeout - Async callback was not invoked",
]

[[category]]
name = "oom"
description = "Killed for memory; usually a leak or an unbounded test"
"oom" = [
  "OOMKilled",
  "Killed.*signal terminated program",
  "out of memory|Out of memory",
  "Cannot allocate memory",
  "heap out of memory|JavaScript heap exhausted",
  "Fatal error: (heap|out of memory)",
]

[[category]]
name = "flaky-suspect"
description = "Patterns that often accompany flakes; confirm with a rerun loop"
"flaky-suspect" = [
  "(?i:address|port) already in use",
  "duplicate key value violates unique constraint",
  "database table is locked",
  "Attempted to (re-open|use) (a|an) (closed|already used)",
  "Timeout waiting for (port|server) to (start|become available)",
  "random(ly)? (fails|fails intermittently|seed)",
  "test order|order-dependent",
]

[[category]]
name = "test-failure"
description = "A test asserted; the rest of the triage is about which code"
"test-failure" = [
  "^FAILED ",
  "^FAIL: ",
  "^--- FAIL:",
  "^ERROR ",
  "short test summary info",
  "[0-9]+ (passed|failed)[,. ]+[0-9]+ (failed|error)",
  "AssertionError|AssertionError:",
  "Tests:.*failed|test[s]? failed",
]
"""


@dataclass(frozen=True)
class Rule:
    category: str
    regex: re.Pattern
    raw: str


@dataclass
class Hit:
    category: str
    line_no: int
    line: str
    rule: str


@dataclass
class Verdict:
    primary: str | None = None
    hits: list[Hit] = field(default_factory=list)
    lines_scanned: int = 0

    def categories(self) -> dict[str, list[Hit]]:
        by: dict[str, list[Hit]] = {}
        for hit in self.hits:
            by.setdefault(hit.category, []).append(hit)
        return by

    def evidence(self, category: str, limit: int = 3) -> list[Hit]:
        return self.categories().get(category, [])[:limit]


def parse_rules(text: str) -> list[Rule]:
    """Parse the registry TOML ([[category]] with a table of name -> regex text)."""
    import tomllib

    doc = tomllib.loads(text)
    rules = []
    for block in doc.get("category", []):
        name = block.get("name")
        if not name:
            raise ValueError("a [[category]] block has no name")
        for key, pattern in block.items():
            if key == "name" or key == "description":
                continue
            if isinstance(pattern, list):
                if not pattern or not all(isinstance(p, str) for p in pattern):
                    raise ValueError(f"[{name}] rule {key!r} must be a string or a list of strings")
                pattern = "|".join(f"(?:{p})" for p in pattern)
            elif not isinstance(pattern, str):
                raise ValueError(f"[{name}] rule {key!r} must be a string or a list of strings")
            try:
                rules.append(Rule(name, re.compile(pattern), key))
            except re.error as exc:
                raise ValueError(f"[{name}] rule {key!r} is not a valid regex: {exc}") from None
    if not rules:
        raise ValueError("registry has no rules")
    return rules


def load_rules(extra: str | None = None, replace: bool = False) -> list[Rule]:
    """Built-in registry, optionally extended or replaced by a registry *file path*."""
    def text_of(path: str) -> str:
        from pathlib import Path

        candidate = Path(path)
        if not candidate.exists():
            raise ValueError(f"registry file {path!r} not found")
        return candidate.read_text(encoding="utf-8")

    if replace:
        if not extra:
            raise ValueError("--rules with --replace needs a registry file")
        return parse_rules(text_of(extra))
    rules = parse_rules(BUILTIN_RULES)
    if extra:
        rules += parse_rules(text_of(extra))
    return rules


def classify_log(log: str, rules: list[Rule]) -> Verdict:
    """Match every rule against every line. First-match-per-line per rule keeps
    counts honest without rescanning one line for the same rule twice."""
    verdict = Verdict(lines_scanned=0)
    seen: set[tuple[int, int]] = set()
    for line_no, line in enumerate(log.splitlines(), 1):
        verdict.lines_scanned += 1
        for index, rule in enumerate(rules):
            if (line_no, index) in seen:
                continue
            if rule.regex.search(line):
                seen.add((line_no, index))
                verdict.hits.append(Hit(rule.category, line_no, line.strip()[:300], rule.raw))
    priorities = {name: i for i, name in enumerate(PRIORITY)}
    present = verdict.categories()
    verdict.primary = min(present, key=lambda c: priorities.get(c, len(priorities))) if present else None
    return verdict
