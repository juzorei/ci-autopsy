"""Talk to GitHub Actions through the authenticated gh CLI. No tokens of our own.

Targets can be a full run URL
(`https://github.com/owner/repo/actions/runs/123`, optionally `/attempts/2`),
or a bare run id when the current directory belongs to the repository.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass

RUN_URL = re.compile(
    r"^(?:https://)?github\.com/([\w.-]+)/([\w.-]+)/actions/runs/([1-9]\d*)"
    r"(?:/attempts/([1-9]\d*))?/?(?:[?#].*)?$"
)
FAILED_CONCLUSIONS = ("failure", "cancelled", "timed_out")
TERMINAL_SEQUENCES = re.compile(
    r"(?:\x1b\]|\x9d)[^\x07\x1b\x9c]*(?:\x07|\x1b\\|\x9c|$)"
    r"|(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]|\x1b[@-_]", re.MULTILINE
)


def _plain_log(log: str) -> str:
    log = TERMINAL_SEQUENCES.sub("", log)
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "", log)


class AutopsyError(RuntimeError):
    pass


def _gh(*args: str) -> str:
    try:
        proc = subprocess.run(["gh", *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=180)
    except FileNotFoundError:
        raise AutopsyError("gh is not installed; get it from https://cli.github.com/") from None
    except subprocess.TimeoutExpired:
        raise AutopsyError("gh timed out after 180 seconds; check connectivity and try the read again") from None
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise AutopsyError(f"gh {' '.join(args[:3])} failed: {detail[-1] if detail else 'unknown error'}")
    return proc.stdout


def _gh_json(*args: str):
    try:
        return json.loads(_gh(*args))
    except json.JSONDecodeError:
        raise AutopsyError("GitHub returned invalid JSON; no complete report is available") from None


class Run:
    def __init__(self, data: dict, owner: str | None = None, repo: str | None = None,
                 *, explicit_attempt: bool = False):
        self.data = data
        self.explicit_attempt = explicit_attempt
        self.owner = owner or data.get("repository", {}).get("owner", {}).get("login")
        self.repo = repo or data.get("repository", {}).get("name")

    @property
    def id(self) -> int:
        return self.data["id"]

    @property
    def attempt(self) -> int:
        return self.data.get("run_attempt", 1)

    @property
    def name(self) -> str:
        return f"{self.data.get('name')} #{self.data.get('run_number')}"

    @property
    def repository(self) -> str:
        return f"{self.owner}/{self.repo}" if self.owner and self.repo else "?"

    @property
    def url(self) -> str:
        return self.data.get("html_url", "")

    @property
    def event(self) -> str:
        return self.data.get("event", "?")

    @property
    def clone_url(self) -> str:
        return self.data.get("repository", {}).get("clone_url", "")

    def jobs(self) -> list[dict]:
        # Pin jobs to the metadata snapshot even if a new attempt starts meanwhile.
        pages = _gh_json("api", f"repos/{self.repository}/actions/runs/{self.id}"
                         f"/attempts/{self.attempt}/jobs?per_page=100",
                         "--method", "GET", "--paginate", "--slurp")
        if not isinstance(pages, list) or not pages:
            raise AutopsyError("GitHub returned an invalid jobs page list")
        jobs = []
        for page in pages:
            if not isinstance(page, dict) or not isinstance(page.get("jobs"), list):
                raise AutopsyError("GitHub returned an invalid jobs page")
            if not all(isinstance(job, dict) for job in page["jobs"]):
                raise AutopsyError("GitHub returned an invalid job record")
            jobs.extend(page["jobs"])
        return jobs

    def failed_jobs(self) -> list[dict]:
        return [j for j in self.jobs() if j.get("conclusion") in FAILED_CONCLUSIONS]


def fetch_run(target: str) -> Run:
    parsed = RUN_URL.search(target)
    if parsed:
        owner, repo, run_id = parsed.group(1), parsed.group(2), parsed.group(3)
        attempt = parsed.group(4)
        endpoint = f"repos/{owner}/{repo}/actions/runs/{run_id}"
        if attempt:
            endpoint += f"/attempts/{attempt}"
        run = _gh_json("api", endpoint)
        return Run(run, owner, repo, explicit_attempt=attempt is not None)
    if target.isdigit():
        # A bare run id: resolve the repository from the current directory's git remote.
        slug = _gh("repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner").strip()
        if not slug:
            raise AutopsyError("a bare run id needs the repo: run autopsy from the repository, or pass the full URL")
        owner, repo = slug.split("/")
        run = _gh_json("api", f"repos/{owner}/{repo}/actions/runs/{target}")
        return Run(run, owner, repo)
    raise AutopsyError(f"can't parse {target!r}; expected a full run URL or a numeric run id")


@dataclass
class JobLog:
    job: dict
    log: str

    @property
    def label(self) -> str:
        return f"{self.job.get('name')} ({self.job.get('conclusion')})"


def fetch_logs(run: Run) -> list[JobLog]:
    logs = []
    for job in run.failed_jobs():
        endpoint = f"repos/{run.repository}/actions/jobs/{job['id']}/logs"
        # gh protects terminal output by default. Capture raw text in memory and
        # remove formatting/control sequences before any evidence is printed.
        log = _plain_log(_gh("api", endpoint, "--header", "Accept: application/vnd.github+json",
                            "--allow-escape-sequences"))
        logs.append(JobLog(job, log))
    return logs


def fetch_attempt_annotations(run: Run, attempt: int | None = None) -> list[dict]:
    attempt = attempt or run.attempt
    return _gh_json("api", f"repos/{run.repository}/actions/runs/{run.id}/attempts/{attempt}").get(
        "workflow_annotations", [])
