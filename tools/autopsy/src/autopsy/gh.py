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

RUN_URL = re.compile(r"github\.com/([^/]+)/([^/]+)/actions/runs/(\d+)(?:/attempts?/(\d+))?")
FAILED_CONCLUSIONS = ("failure", "cancelled", "timed_out")


class AutopsyError(RuntimeError):
    pass


def _gh(*args: str) -> str:
    try:
        proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=180)
    except FileNotFoundError:
        raise AutopsyError("gh is not installed; get it from https://cli.github.com/") from None
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise AutopsyError(f"gh {' '.join(args[:3])} failed: {detail[-1] if detail else 'unknown error'}")
    return proc.stdout


class Run:
    def __init__(self, data: dict, owner: str | None = None, repo: str | None = None):
        self.data = data
        self.owner = owner or data.get("repository", {}).get("owner", {}).get("login")
        self.repo = repo or data.get("repository", {}).get("name")

    @property
    def id(self) -> int:
        return self.data["id"]

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
        page = json.loads(_gh("api", f"repos/{self.repository}/actions/runs/{self.id}/jobs", "--field", "per_page=-1"))
        return page.get("jobs", [])

    def failed_jobs(self) -> list[dict]:
        return [j for j in self.jobs() if j.get("conclusion") in FAILED_CONCLUSIONS]


def fetch_run(target: str) -> Run:
    parsed = RUN_URL.search(target)
    if parsed:
        owner, repo, run_id = parsed.group(1), parsed.group(2), parsed.group(3)
        run = json.loads(_gh("api", f"repos/{owner}/{repo}/actions/runs/{run_id}"))
        return Run(run, owner, repo)
    if target.isdigit():
        # A bare run id: resolve the repository from the current directory's git remote.
        slug = _gh("repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner").strip()
        if not slug:
            raise AutopsyError("a bare run id needs the repo: run autopsy from the repository, or pass the full URL")
        owner, repo = slug.split("/")
        run = json.loads(_gh("api", f"repos/{owner}/{repo}/actions/runs/{target}"))
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
        log = _gh("api", endpoint, "--header", "Accept: application/vnd.github+json")
        logs.append(JobLog(job, log))
    return logs


def fetch_attempt_annotations(run: Run, attempt: int | None = None) -> list[dict]:
    attempt = attempt or run.data.get("run_attempt", 1)
    return json.loads(_gh("api", f"repos/{run.repository}/actions/runs/{run.id}/attempts/{attempt}")).get(
        "workflow_annotations", [])
