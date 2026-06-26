# Claude Code Permission Configuration

**Status:** Proposed (staged, not committed) · **Date:** 2026-06-26 · **Owner:** Nick Kirkes

This document explains HuntReady's Claude Code permission configuration: what it
allows, asks, and denies; where each setting lives and why; how it reconciles with
the **roughly** plugin; and how it reconciles with the operator's existing
`~/.claude/settings.json`. It is the companion to the change staged in
`.claude/settings.json` (diff at the end) and to the draft ADR
`docs/adrs/ADR-DRAFT-claude-code-permission-config-ownership.md`.

The goal is to collapse per-step approval noise in this repo (auto-accept edits,
run the dev loop without prompts) while keeping hard guardrails (no secret reads,
no force-push, no home-directory deletion, gated DB/push) — **without breaking the
operator's heavily-customized global setup and without being clobbered by, or
blocking, roughly.**

> **Verification basis.** Semantics verified against the official Claude Code docs
> on 2026-06-26: [Configure permissions](https://code.claude.com/docs/en/permissions),
> [Configure the sandboxed Bash tool](https://code.claude.com/docs/en/sandboxing),
> [Orchestrate teams of Claude Code sessions](https://code.claude.com/docs/en/agent-teams).
> Roughly's behavior verified by reading its source at
> `/Users/nickkirkes/rowdycloud/code/roughly` (`skills/setup/SKILL.md`,
> `skills/upgrade/SKILL.md`, `skills/build/SKILL.md`, the settings template).

---

## 1. Design choice for this operator: keep the policy project-scoped

The operator's `~/.claude/settings.json` is large and deliberate: a ~600-entry
`permissions.allow` list, broad `Read(//Users/nickkirkes/**)`, heavy native/mobile
tooling (Expo, Xcode, CocoaPods, `psql` to local Supabase, `supabase`, `gh`,
`brew`), and no `deny`, `sandbox`, or `defaultMode`. That changes the right
strategy: **almost everything lands in the HuntReady project file, scoped to this
repo. The user file gets one line.** Global denies or a global sandbox would break
the operator's other projects (see §3).

### 1a. Project settings — `.claude/settings.json` (committed, shared) — the working policy

Merged **non-destructively**: the existing `hooks` block (roughly's Stop hook +
plan-mode-gate) is preserved byte-for-byte; `env` and `permissions` are added as
new sibling keys.

| Block | Setting | Why |
| :-- | :-- | :-- |
| `env.CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS = "1"` | Enable agent teams in this repo | Experimental, inert until you ask for teammates. See §6. |
| `permissions.defaultMode` = `acceptEdits` | Auto-accept edits + safe in-tree fs commands | Edits flow; state-changing/networked Bash still gates. Not plan mode, so it doesn't trip roughly's plan-mode-gate. |
| `permissions.allow` | ruff, mypy, pytest, `.venv/bin/python`, `pre-commit run`, `npm run`, `npx tsc`, read-only `supabase` | The repo's actual dev loop (Stop hook + `.pre-commit-config.yaml` + `package.json`). Mostly redundant with your global allow-list, but explicit here so the policy is self-contained and shareable. |
| `permissions.ask` | `git push`, `supabase db push`, `supabase db reset`, `supabase migration repair` | Networked / DB-mutating / history-rewriting. `ask` prompts even though your global settings allow `git push` — a deliberate re-gate for this repo (see §3). |
| `permissions.deny` | `sudo`; `rm -rf ~`, `rm -rf /Users`; `git push --force`/`-f`; reads of `.env*`, `*.pem`, `*.key` | Hard guardrails that **do not collide** with your global allow-list (see §3 for what was deliberately dropped). Deny wins over any allow, in any scope. |

### 1b. User settings — `~/.claude/settings.json` (one line, manual)

Provided as `user-settings.recommended.json`. **Merge** this single key into your
existing file (don't replace it):

```json
{ "teammateMode": "auto" }
```

It sets the agent-teams display mode to split panes when you're in tmux/iTerm2,
in-process otherwise. That is the *only* user-level change recommended — the floor
and the sandbox were deliberately kept out of your global file (§3).

---

## 2. Where each setting lives, and why

Precedence (high → low): **managed → CLI args → `.claude/settings.local.json` →
`.claude/settings.json` → `~/.claude/settings.json`**. Within that, rules evaluate
**deny → ask → allow**, and a deny at any scope beats an allow at any scope.

| Setting | Home | Reason |
| :-- | :-- | :-- |
| `permissions` (allow/ask/deny + `defaultMode`), `env` (agent teams) | Project `.claude/settings.json` | Applies to roughly's subagents (they inherit the session — §5), committed/shared, and scoped so it can't disturb your other projects. |
| `teammateMode` | User `~/.claude/settings.json` | Display preference; harmless globally. |
| Sandbox | **Not enabled** (optional — §4) | A global sandbox would break your native/DB tooling; even project-scoped it fights local `psql`/`supabase`. Left off by default. |
| Hooks (Stop, plan-mode-gate) | Untouched, project file | Roughly-managed. Merged around. |

Why **not** a user-level deny "floor" (my earlier draft proposed one): your global
config intentionally allows things a blanket floor would block — `Bash(curl:*)`,
`rm -rf /tmp/...`, and `grep`-ing `.env` in other repos. A user-scope deny wins
everywhere and would silently break those. Scoping the guardrails to HuntReady
keeps your other projects exactly as they are. The cost is that the guardrails
don't survive a *full overwrite* of the project file — but the only path that does
that is under your control (§5).

---

## 3. Reconciliation with your existing `~/.claude/settings.json`

Four concrete interactions, and how each was resolved:

1. **`curl`/`wget` — dropped from deny.** Your global allow-list contains
   `Bash(curl:*)` and many curl-based workflows. A project deny would block curl
   inside HuntReady and surprise you. Dropped. (HuntReady's pipeline fetches via
   Python `requests`, not curl, so nothing here needs it; network egress is simply
   not hard-restricted without the sandbox.)
2. **`rm -rf` — narrowed, not blanket.** You allowlist `rm -rf /tmp/...` cleanups
   (including `rm -rf /tmp/huntready-verify`). A blanket `Bash(rm -rf:*)` deny would
   block those. Replaced with `Bash(rm -rf ~:*)` and `Bash(rm -rf /Users:*)` —
   catches "nuke home" without touching `/tmp`. (`rm -rf /` and `rm -rf ~` are also
   circuit-broken by Claude Code itself.)
3. **Secret reads — kept (a net security win).** You have broad
   `Read(//Users/nickkirkes/**)` and no deny, so an agent can currently read
   `~/.aws/credentials`, `~/.ssh/`, and any `.env`. The project denies on
   `.env*`/`*.pem`/`*.key` close that **inside HuntReady**, where `.env` holds the
   Supabase secret + `DATABASE_URL`. Scoped to the project so it doesn't break your
   `.env`-grep workflows in other repos.
4. **`git push` — re-gated to a prompt here.** You globally allow `git push`; the
   project `ask` rule makes it prompt in HuntReady (ask beats allow). This matches
   HuntReady's "operator pushes deliberately" discipline. If you'd rather keep
   silent auto-push here, delete the `ask` entry for `git push`.

**Also flagged (not changed by this task):** your `enabledPlugins` has **both
`ruckus@nickkirkes` and `roughly@nickkirkes` set to `true`** from the same
marketplace. That's the old and new name of the same plugin; running both risks
double-registered commands/hooks. Consider setting `ruckus@nickkirkes` to `false`.
(Similarly `feature-dev` and `pr-review-toolkit` are enabled from two marketplaces
each.)

---

## 4. Sandbox — optional, off by default for this operator

The macOS sandbox (Seatbelt, zero-install) would let a broad Bash allow-list run
safely. But your workflow runs a lot of things the sandbox prompts on or breaks:
`psql` to `127.0.0.1` local Supabase, the `supabase` CLI, and (in other repos)
Expo/Xcode/CocoaPods, which write outside the working tree and use Apple Events.
Enabling it globally would degrade those; even project-scoped it fights HuntReady's
heavy local-DB verification. So it is **left off**.

If you later want OS-level Bash containment for HuntReady specifically, enable it in
the project file and smooth the rough edges:

```json
{
  "sandbox": {
    "enabled": true,
    "network": { "allowedDomains": ["services.arcgis.com", "*.arcgis.com", "www2.census.gov", "fwp.mt.gov", "spl.cde.state.co.us", "*.supabase.co"] },
    "excludedCommands": ["psql", "supabase"],
    "credentials": {
      "files": [{ "path": "./.env", "mode": "deny" }, { "path": "~/.ssh", "mode": "deny" }, { "path": "~/.aws", "mode": "deny" }],
      "envVars": [{ "name": "SUPABASE_SECRET_KEY", "mode": "deny" }, { "name": "DATABASE_URL", "mode": "deny" }]
    }
  }
}
```

`sandbox.credentials` is the one feature worth calling out: it OS-level-denies the
secret files and unsets the secret env vars for sandboxed subprocesses — closing
the gap that `Read(...)` deny rules leave open (a Python script that opens `.env`
itself is not stopped by a Read deny). It only takes effect when the sandbox is on.

**Note on the limit of `Read` denies:** they block the built-in Read tool and
file-reading Bash commands Claude recognizes (`cat`, `head`, `tail`, `sed`), but
not an arbitrary `python`/`node` script that opens a file. Without the sandbox,
secret protection in HuntReady rests on the Read denies plus not committing `.env`.

---

## 5. Reconciliation with roughly (confirmed from source)

Roughly (installed earlier as *ruckus*; source at
`/Users/nickkirkes/rowdycloud/code/roughly`) drives planning/build. Its in-repo
state is `.roughly/` (plans, `known-pitfalls.md`, `workflow-upgrades`) and the
hooks it installed into `.claude/`. There is **no** roughly file that sets Claude
Code permissions.

### Does roughly write/overwrite `.claude/settings.json`? — Yes; one path is destructive

From `skills/setup/SKILL.md` (Step 5d) and `skills/upgrade/SKILL.md`:

- **`settings.json.template` is hooks-only** — a `PostToolUse` formatter and the
  `UserPromptSubmit` plan-mode-gate. No `permissions`, no `sandbox`.
- **`/roughly:setup` Branch 1 — formatter provided → full overwrite** of
  `.claude/settings.json` with that template. This is the **one path that would
  wipe the `permissions` block** (and the Stop hook). The skill warns about it:
  "Users with both a formatter and customizations… should run setup once without a
  formatter, then add their formatter manually."
- **`/roughly:setup` Branch 3 (no formatter, file exists)** and the **Stop-hook
  install** both **`jq`-merge** only their target hook key, snapshot the file first
  (`settings.json.pre-stop-hook`), and preserve every other field.
- **`/roughly:upgrade`** does a **structural merge that preserves user
  customizations** and writes `[file].backup-[date]`.

**Implication:** the `permissions` block is safe under `upgrade` and under
no-formatter `setup`. HuntReady currently has **no** `PostToolUse` formatter hook,
so it was set up via the safe (merge) path and stays there as long as you don't run
`/roughly:setup` **with a formatter argument**. That single overwrite path is the
residual risk, and it is entirely operator-controlled. Mitigations: don't pass a
formatter to `setup` on this repo; roughly's own backup-before-write habit; and
this doc as the source to re-merge from.

### Runtime permission overrides — confirmed: none

The build pipeline (`skills/build/SKILL.md`) dispatches **subagents via the Task
tool** ("subagents implement"; review-plan is "a blocking subagent call"). It does
**not** shell out to headless `claude -p`, and sets **no** `--allowedTools` /
`--disallowedTools` / `--permission-mode`. (The only `claude --bare`/`-p`
references in the repo are CI dogfood fixtures, not the runtime skills.) So:

- Subagents **inherit this session's permissions** — the allow/ask/deny rules apply
  to them unchanged.
- `ask` rules **cannot block** a roughly build: it runs interactively in your
  session, and nothing in its build loop (ruff/mypy/pytest/tsc/pre-commit/`--dry-run`
  loaders/`git add`/`git commit`) is in `ask` or `deny`.
- Deny **cannot be loosened** by roughly at runtime.

### Deny/ask cross-check — no conflicts

Roughly's build commands hit none of the `deny` or `ask` rules. `detect-secrets`
scans tracked files only (`.env*` is gitignored). The Stop hook and plan-mode-gate
run as **hooks**, which aren't gated by the permission allow-list at all.

### Overlap summary

| Surface | Roughly | This config | Resolution |
| :-- | :-- | :-- | :-- |
| `.claude/settings.json` → `hooks` | Owns it; merges additively (or overwrites under formatter-setup) | Untouched | Preserved; we add only sibling keys. Don't run `setup` with a formatter. |
| `.claude/settings.json` → `permissions`/`env` | Doesn't write | Adds | Survives upgrade + no-formatter setup; formatter-setup overwrite is the one risk (operator-controlled). |
| Runtime (subagents) | Task tool, inherits session | — | `ask` never blocks builds; deny applies to subagents. |
| Build commands | Runs them | none in ask/deny | No block, no conflict. |

---

## 6. Agent teams (experimental — `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`)

Enabled in the project file via `env`. Inert until you ask for teammates; nothing
spawns on its own. Display mode is set by `teammateMode` in your user file (§1b).

- **Teammates inherit the lead's permissions** — this config's allow/ask/deny apply
  to teammates unchanged. The docs recommend pre-approving common ops before
  spawning teammates to cut prompt friction; the allow-list does that.
- **Your global hooks multiply across teammates.** Each teammate is a full session,
  so your `PreToolUse`/`PostToolUse` `git-ai checkpoint` runs on every teammate
  tool call, and your `SessionStart` "run cubic review" injection fires per
  teammate. Roughly's `Stop` hook (ruff+mypy+pytest, ~14 s) may also fire per
  teammate session. Expect materially higher token + checkpoint volume with teams.
- **Best fit:** parallel research/review or independent modules — not roughly's
  sequential single-story builds (the docs steer that toward subagents, which
  roughly already uses). Good first use here: parallel code review or auditing
  several adapters at once.

Verified against [the agent-teams doc](https://code.claude.com/docs/en/agent-teams)
(v2.1.178+); the feature is experimental with known limits around session
resumption, task-status lag, and shutdown.

---

## 7. How to apply (no commit performed by this task)

1. **Project file:** apply the staged diff to `.claude/settings.json` (the merged
   file is `settings.json.merged`; unified diff in the hand-back). `.claude/` is a
   protected path this session can't write directly, so this is a copy-in step.
2. **User file:** merge `{ "teammateMode": "auto" }` into `~/.claude/settings.json`.
3. Open Claude Code in the repo and run `/permissions` to confirm the rules loaded.
4. Don't run `/roughly:setup` with a formatter on this repo (§5).
5. Consider disabling `ruckus@nickkirkes` in `~/.claude/settings.json` (§3).
6. Review the draft ADR; if accepted, number and commit it per repo convention.

Nothing in this task was committed, and no branch was created.
