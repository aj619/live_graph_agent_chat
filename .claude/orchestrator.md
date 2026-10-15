# Orchestrator Playbook

This is the instruction set for the **driver session**: the main Claude Code session that runs `/loop`. It is not a subagent. Subagents cannot launch other subagents, so the driver does all the assigning, merging, and status keeping.

Read `AGENT.md` first. Its rules apply to the driver too.

**Driver model: Sonnet 5.5.** Set it with `/model` before starting the loop. Workers are pinned to Haiku in their own files, so the driver's model does not change theirs.

## Design principles (why the rules below look the way they do)

These follow Anthropic's published guidance on multi-agent systems and context engineering.

1. **Start simple, scale on evidence.** Run a pilot before going parallel. Add concurrency only when a cycle shows it helps.
2. **Coding is interdependent.** Parallelism pays off across independent modules, not within one module's task chain. Keep a single writer per file.
3. **Brief each worker fully.** A worker should not reconstruct its job from documents. The brief names the objective, the exact task, the files it may change, the boundaries, and the done check.
4. **Keep context small.** Give each worker only the plan excerpts its task names, not the whole plan.
5. **Results go to files, summaries go to the driver.** A worker writes its full report to a run file. It returns a short summary. The driver reads the run file only when it needs detail. Relayed detail loses information.
6. **Effort matches the task.** Review-type agents run at phase boundaries, not after every task.
7. **Cost is bounded up front.** Multi-agent runs use far more tokens than a single session, so caps are set before the loop starts.

## Team

| Agent (`.claude/agents/`) | Owns (file paths) | Kind |
|---|---|---|
| `backend-builder` | `backend/app/**`, `backend/Dockerfile` | writes |
| `frontend-builder` | `frontend/src/**`, `frontend/index.html`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/eslint.config.js`, `frontend/nginx.conf.template` | writes |
| `infra-docs` | `compose/**`, `docker-compose.yml`, `frontend/Dockerfile`, `.env.example`, `.env.test.example`, `.gitignore`, `.gitleaks.toml`, `SECURITY_CHECK.md`, `scripts/**`, `README.md` | writes |
| `test-author` | `backend/tests/**`, `frontend/tests/**` | writes tests, runs them |
| `security-reviewer` | none (read-only) | reviews |
| driver (this file) | `TASKS.md`, `STATUS.md`, `FINAL_REPORT.md`, `backend/pyproject.toml`, `backend/uv.lock`, `frontend/package.json`, `frontend/package-lock.json`, `.env.example`, `.env.test.example`, and the run files for the security reviewer | coordinates |

Shared files are changed only by the driver. Workers report what they need from them.

## Gates (never bypass)

- Do nothing until the owner has said "go" in chat. Until then, report that the loop is idle.
- Tasks marked **[OWNER]** are never assigned. Tasks blocked on O2 or O3 are never assigned.
- Never run `docker` or `docker compose`. Never read or write the dev `.env`. Never push.
- Never edit `PLAN_OF_ACTION.md`. Plan changes go to the owner.

## Concurrency and cost

- **Repository first.** Task T1.0 is done by the driver before any worker runs: `git init` on `main`, with the planning documents and `.claude/` as the first commit. No worktree can be created before this.
- **Pilot first.** The first cycle runs **one** worker on **Phase 1, task T1.1**. The driver reviews its output and cost before any further cycle.
- After the pilot, at most **2** workers run at once (backend and frontend are the usual pair). Raise this only after the owner agrees, in chat, and record the decision in `STATUS.md`.
- At most **4** agent runs per cycle, including retries.
- **Daily cap: 48 agent runs per day** (about one full day of 30-minute cycles at 1 run each). The owner can change this in this file. The driver never raises it on its own. When the cap is reached, stop the loop and report it.

## One cycle

### 1. Lock
- Create `.claude/state/cycle.lock` exclusively. If it exists and is younger than 2 hours, another cycle is running: stop and report. If it is older, treat it as stale, replace it, and note that in `STATUS.md`.
- Remove the lock at the end of the cycle, including after a failure.

### 2. Read the board
- Read `TASKS.md`. A task is **ready** when:
  - its status is not done,
  - it is not owner-only and not blocked on O2 or O3,
  - every task in its "Depends on" column is done (merged to `main`),
  - no active claim exists: no branch `task/<ID>` exists with a commit newer than 24 hours.
- Stale claims (branch exists, no commit for 24 hours): remove the worktree and branch, record it in `STATUS.md`, and make the task ready again.

### 3. Assign
- **Route** each ready task by its file path to the agent that owns it. A task that touches a file owned by no agent goes to the driver as a shared-file change.
- **One writer per file.** If two ready tasks name the same file, run them in order. The file lock lives in `STATUS.md`.
- **Worktree per task:** `git worktree add /home/beast/Projects/Softwares/Portfolio/lgac-worktrees/<ID> -b task/<ID> main`. This folder sits outside the repository, and `.claude/settings.json` allows writes there.
- **Run files:** `/home/beast/Projects/Softwares/Portfolio/live_graph_agent_chat/.claude/state/runs/<ID>-<attempt>.md`. Create the folder if it does not exist.
- **Brief every spawn** with the template below. Do not pass only an ID and a path.
- Run agents in parallel only when they touch different files and the concurrency cap allows it.

#### Brief template
```
Task: <ID>. Row from TASKS.md, verbatim: <row>
Worktree: <absolute path>. Work only inside it. Use absolute paths. Never change directory out of it.
Change only: <one file, absolute path inside the worktree>
Depends on (already merged to main): <IDs, or none>
Plan sections (verbatim excerpts, or the section numbers if they are long): <excerpts>
Must not: <items from AGENT.md §4 that apply, plus any task-specific limit>
Done when: <check, verbatim from the row>
Run file (write your full report here): <absolute path under .claude/state/runs/>
Return: the short summary defined in your agent definition.
```

### 4. Collect
- Each worker returns a **short summary** (format in its definition) and writes a **run file**. The security reviewer cannot write files, so the driver writes its run file from the `REPORT` section of its final message.
- Workers that finished a task have committed it on `task/<ID>`. The driver checks that the branch has the commit before merging.
- Accept a **done** result only if the worker reports its "Done when" check as passed.
- For **failed** or **blocked**, read the run file, record the reason in `STATUS.md`, and increment the task's attempt count. After **2** failed attempts, mark the task blocked and report it to the owner. Do not retry a third time.

### 5. Merge
- Rebase `task/<ID>` onto `main` in its worktree. A conflict means the task fails: do not resolve conflicts by guessing. Record it and retry next cycle, after the conflicting task has merged.
- Re-run the task's own checks on the rebased branch.
- If they pass, merge to `main` with `git merge --no-ff task/<ID>`, then remove the worktree and branch.
- Tick the task's box in `TASKS.md` on `main`. Only the driver ticks boxes.
- If a merge breaks a check on `main`, revert it with `git revert` at once, mark the task failed, and stop assigning tasks that depend on it.

### 6. Shared files
- If a merged change touched `backend/pyproject.toml` or `frontend/package.json`, regenerate the matching lock file (`uv lock`, `npm install --package-lock-only`) on `main` and commit it.
- A change to `.env.example` or `.env.test.example` is applied by the driver, not by the worker that asked for it.

### 7. Phase-boundary checks
- When a phase has all its buildable tasks merged, assign the phase checks listed in `TASKS.md` ("Phase checks" section): C2.1 and C2.2 after Phase 2, C7.1 and C7.2 after Phase 7, C8.1 after Phase 8.
- Findings from the reviewer become new tasks in `STATUS.md` for the owning worker. The driver does not fix them itself.
- Do not run the reviewer after individual tasks. That is wasted cost.

### 8. Report
Overwrite `STATUS.md` at the repository root each cycle with:
- time of the cycle,
- the pilot status and any concurrency decision,
- tasks merged this cycle, with commit IDs,
- tasks running, with branch names,
- tasks failed (attempt count and reason, from the run file), and tasks blocked,
- owner-only tasks waiting for the owner, with the exact command or check needed,
- file locks in use,
- agent runs this cycle and today's total against the daily cap.

Add `STATUS.md`, `.claude/state/`, and `.claude/state/runs/` to `.gitignore`. Do not commit `STATUS.md`.

### 9. Stop condition
- If no task is ready, nothing is running, and every remaining task is owner-only or blocked, stop the loop (ScheduleWakeup with `stop: true`) and report it.
- If the daily cap is reached, stop the loop and report it.
- If nothing changed this cycle, use `noop: true`.

## Owner-only items, always listed
- T0.1, T0.2 and any task marked **[OWNER]** in `TASKS.md`.
- The Phase 3 integration run (T3.9), the dev-data check (T3.10), the restart proof (Phase 4), and every acceptance check in Phase 11.

## Open items the owner should confirm
- The shell behaviour of parallel subagents has not been verified. Until it is, every brief says to use absolute paths inside the worktree.
- Permission rules for the worktree location are in `settings.json`. Check them during the pilot, because a permission prompt stalls a headless worker.
