# AGENT.md: Working Rules for Live Graph Agent Chat

These rules apply to every agent that works in this repository. The owner's instructions in chat override them for the current task only.

## 1. Source of truth

- `PLAN_OF_ACTION.md` is the specification. `TASKS.md` is the work breakdown. Read the sections a task names before starting it.
- If the plan and the code disagree, the plan wins. Stop and report before changing the plan.
- Every task changes exactly one file, as named in `TASKS.md`. If a task seems to need a second file, stop and report it.

## 2. Headless operation

- Agents run non-interactively. Nothing waits for a person in the middle of a task.
- Each task must be complete from its brief. The driver supplies the task row, the plan excerpts, the one file to change, the worktree, and the done check. The agent does not rely on chat history or on any earlier agent's memory.
- Workers write their full report to a run file under `.claude/state/runs/` and return only a short summary. The driver reads the run file only when it needs detail.
- The driver assigns tasks. Workers do not pick their own. The driver never assigns a task marked **[OWNER]**, a task blocked on O2 or O3, or a task whose dependencies are not done.
- The five worker agents are pinned to Haiku 5.5 in their definitions. The driver runs on Sonnet 5.5. Tasks are written so they do not depend on the model family.
- If a task cannot be completed headlessly, the agent records the reason in its report and stops. It does not guess.

## 3. Phase gate

- Do not write or change application code until the owner says "go" in chat.
- Before "go", only the planning documents and the agent configuration under `.claude/` may change, and only when the owner asks.
- When asked to remove something, delete it. Do not replace it with new code.

## 4. Forbidden actions

- **Never run `docker` or `docker compose`.** Write the compose files and list the commands for the owner to run. Verify compose files by parsing the YAML, not by running Docker.
- Never run a command that starts a service, binds a port, or pulls a container image.
- **Never read, write, or copy the dev `.env`.** Test runs use `.env.test` only.
- **Never run an integration test against dev data.** Integration tests run only on the test stack, and the guard in `backend/tests/conftest.py` must pass first.
- Never push. Commit only on your own task branch inside your worktree, as your definition describes. Only the driver merges to `main`.
- Never write a real secret, key, or token into any file. Only placeholders go into `.env.example` and `.env.test.example`.

## 5. Configuration and models

- No model name, endpoint URL, API key, numeric limit, or provider name may be hard-coded in source. All of them come from `.env` through `config.py`.
- Required settings have no code-level default. The app must fail at startup if one is missing.
- Every LLM and embedding call goes through an OpenAI-compatible endpoint, so changing a model never changes the code path.
- Zep is not part of this project. Do not add it.

## 6. Dependencies and security

- Use the packages named in the plan. Do not add a package without asking the owner.
- Do not use axios. The frontend uses `fetch`.
- Before pinning any package or container tag, check it against the OSV database (`https://api.osv.dev/v1/query`). If an advisory exists for the chosen version, pick another version. If none is safe, stop and report.
- Container tags must be pinned. Never use `latest`.
- The browser must never receive `API_TOKEN`. Do not place it in any file that the frontend build reads.
- Render model output and document text as plain text. Never use `dangerouslySetInnerHTML` or `eval`.
- Log lines must never contain tokens, keys, or document text.
- Run the secret scan config (`.gitleaks.toml`) before any push. A finding stops the push.

## 7. Backend rules

- Python 3.14, managed with uv. No `pip install` into a global environment.
- FastAPI runs with a single worker. The event bus and the rate limiter are in-process.
- Insertion runs as a background task in the same process. Do not add a job queue or batching.
- Each insertion writes its tracking row before the Graphiti call, so restart cleanup can find it.
- Database access goes through SQLAlchemy with bound parameters. No string-built SQL.

## 8. Frontend rules

- React, TypeScript, Vite, and Cytoscape.js.
- Live updates come from the SSE stream read with `fetch`. Do not use `EventSource`, because the token must be a header.
- The frontend reads only relative `/api` paths. No backend URL is hard-coded.

## 9. Reporting

- Scope is a portfolio project. Keep to sensible defaults and basic hygiene. Do not add production hardening that the plan does not ask for (section 1 of the plan states the scope).

- Report each task as done only after its "Done when" check has passed. If a check did not run, say so.
- Tests that skip because a service is not running are reported as "not verified", never as passed.
- The run file holds the full report: changed files with paths, commands run, owner commands still needed, vulnerability results, deviations from the plan, and open questions. The short summary holds only status, task ID, file, check result, needs, and run-file path.
- A worker that cannot finish within its brief stops and reports. It does not work around a missing input.
- Do not leave draft files, scratch files, or unused folders in the repository. Remove anything you created that the task did not need.

## 10. Git attribution

- Commit messages end with: `Co-Authored-By: Claude Haiku 5.5 <noreply@anthropic.com>`
- Pull request descriptions end with: `🤖 Generated with [Claude Code](https://claude.com/claude-code)`
