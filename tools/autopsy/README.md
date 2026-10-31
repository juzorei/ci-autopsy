# ci-autopsy

An agent skill companion CLI for investigating failed GitHub Actions runs and saved CI logs. Python 3.11+, standard library only; live `run` requires an authenticated, current GitHub CLI (`gh`).

```bash
pip install ci-autopsy
autopsy run https://github.com/owner/repo/actions/runs/123456789
autopsy run https://github.com/owner/repo/actions/runs/123456789/attempts/2
autopsy classify saved-job.log
autopsy demo
```

`run` reads metadata, retrieves all job pages for the selected attempt, and analyses only failed, cancelled or timed-out jobs. Without `/attempts/N`, it pins the latest attempt reported by the metadata snapshot. It never triggers a rerun or modifies the repository.

Reports include matched categories, evidence lines and pytest failure summaries. A classification is a log-pattern hypothesis, not proof of a root cause. `unknown` means no signature matched. Empty job lists report the run state: an unfinished run or a workflow-level failure is not a passing build.

`classify --json` provides machine-readable offline output. `--rules path.toml` adds custom signatures; `--replace` uses only that registry. `autopsy rules` prints the built-in registry.

## 0.1.1 fixes

- GitHub jobs are fetched with GET and real pagination, including failures beyond the first page.
- Attempt URLs select that attempt's metadata and jobs rather than silently analysing the latest run.
- Timeouts return a readable error and exit 2. GitHub text is decoded as UTF-8 on Windows too.
- Downloaded log ANSI formatting and terminal control sequences are removed before reporting. Use a current `gh` supporting `--paginate`, `--slurp` and `--allow-escape-sequences`.
- Concrete rerun guidance uses `gh run rerun <id> --repo owner/repo --failed`, and is shown only when every analysed job has an infrastructure/dependency verdict. Explicit-attempt reports ask the reader to inspect the latest attempt before rerunning.

The CLI is read-only. Successful analysis returns 0 even when it reports a failed job; it is not a CI success/failure gate. Retrieval and usage errors return 2.

Agent skill: `npx skills add juzorei/ci-autopsy`. Source and documentation: https://github.com/juzorei/ci-autopsy
