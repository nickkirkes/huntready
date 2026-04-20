# M0: Repo Scaffold

**Status:** In Progress
**Dependencies:** None (M0 is the first milestone)
**Validated:** 2026-04-20

---

## Objective

M0 delivers a private GitHub repository that a cold visitor can clone and understand in fifteen minutes, containing all thinking-layer documents, a working code scaffold in four directories, and a provisioned Supabase project with PostGIS. No business logic, no migrations, no regulation data. This is the foundation that M1 (Montana ingestion) builds on — every subsequent milestone assumes M0's scaffolds are installable and its documentation is accurate. See [`docs/roadmap.md`](../../roadmap.md) for milestone dependencies and [`docs/context.md`](../../context.md) for V1 done criteria.

---

## Stories

### S0.1: Verify `.gitignore` coverage

**As a** developer cloning the repo
**I want** the `.gitignore` to cover all generated/secret file patterns for our stack
**So that** no accidental commits of secrets, build artifacts, or OS files occur during M0-M5 development

**Context:**
The `.gitignore` already exists at repo root. This story verifies its completeness — it does not modify the file. If gaps are found, they are documented and handed to an implementation agent as a follow-up.

The repo uses: Node.js (npm, possibly pnpm), Python 3.11+ (venv, pip, eggs), Next.js (.next/, out/), Supabase CLI (.supabase/), Mapbox, and standard OS/IDE artifacts. Environment variables live in `.env` files that must never be committed.

**Acceptance Criteria:**
- [x] `.gitignore` covers `node_modules/`, `.next/`, `out/`, `dist/`, `build/`, `*.tsbuildinfo`
- [x] `.gitignore` covers `__pycache__/`, `*.pyc`, `.venv/`, `venv/`, `*.egg-info/`, `.eggs/`
- [x] `.gitignore` covers `.env`, `.env.local`, `.env.*.local`
- [x] `.gitignore` covers `.supabase/`
- [x] `.gitignore` covers `.DS_Store`, `Thumbs.db`
- [x] `.gitignore` covers debug logs (`npm-debug.log*`, `yarn-debug.log*`, `yarn-error.log*`)
- [x] Gaps identified and documented (if any):
  - `.pnpm-store/` (pnpm cache directory)
  - `pnpm-debug.log*` (pnpm debug logs)
  - `coverage/` (test coverage output)
  - `.env.*` with `!.env.example` (blocks `.env.production`, `.env.staging` etc. while allowing `.env.example` — currently only `.env.*.local` is blocked)
- [x] If gaps exist, a list of recommended additions is produced for an implementation agent

---

### S0.2: Create `docs/planning/` structure

**As a** PM agent
**I want** a `docs/planning/` directory with an index and an epics subdirectory
**So that** planning artifacts have a home and future PM sessions know where to look

**Context:**
This is a PM-owned story. Creates the directory structure and initial files. The M0 epic file (this document) lives at `docs/planning/epics/M0-scaffold.md`. The planning README is the index for all milestones.

Directory structure:
```
docs/planning/
├── README.md              # Planning index — milestone table, story status
└── epics/
    └── M0-scaffold.md     # This file
```

**Acceptance Criteria:**
- [ ] `docs/planning/README.md` exists with milestone status table (M0-M5)
- [ ] `docs/planning/epics/M0-scaffold.md` exists (this file)
- [ ] Both files have valid internal markdown links that resolve

---

### S0.3: Create `.env.example`

**As a** developer cloning the repo
**I want** a `.env.example` file documenting all required environment variables
**So that** I know what credentials to obtain without seeing anyone's real values

**Context:**
Per project security constraints, credentials never appear in committed files. `.env.example` documents variable names and their purpose with empty/placeholder values. The actual `.env` is in `.gitignore`.

Variables to document (drawn from [`docs/architecture.md`](../../architecture.md) and CLAUDE.md):
- `SUPABASE_URL` — Supabase project URL (used by MCP server and web app)
- `SUPABASE_SERVICE_ROLE_KEY` — service-role key (MCP server + ingestion pipeline)
- `SUPABASE_ANON_KEY` — anon key (web app, scoped by RLS)
- `DATABASE_URL` — direct Postgres connection string (ingestion pipeline + migrations only; not used by serving stack per [ADR-003](../../adrs/ADR-003-ingestion-upstream-offline.md))
- `MAPBOX_ACCESS_TOKEN` — Mapbox GL JS token (web map, needed at M4)

Security constraints:
- Values must be empty or clearly placeholder (e.g., `SUPABASE_URL=` or `# paste your project URL here`)
- Do NOT include structural URL templates that reveal Supabase hostname format
- Include comments explaining which layer uses each variable and where to find the value
- File must be committed; the corresponding `.env` must NOT be committed

**Acceptance Criteria:**
- [ ] `.env.example` exists at repo root
- [ ] Contains all five variables listed above with empty values and descriptive comments
- [ ] `DATABASE_URL` comment explicitly states it is for ingestion/migrations only, not serving
- [ ] No real credentials, tokens, URLs, or project references in the file
- [ ] File is tracked by git (not in `.gitignore`)

---

### S0.4: Scaffold `mcp-server/` and verify installs

**As a** developer cloning the repo
**I want** the `mcp-server/` directory to contain a working TypeScript project scaffold
**So that** I can begin implementing MCP tools without setting up boilerplate

**Context:**
Per [ADR-002](../../adrs/ADR-002-mcp-canonical-interface.md), the MCP server is the canonical interface. Per [ADR-005](../../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md), serving is TypeScript.

Directory structure:
```
mcp-server/
├── package.json
├── tsconfig.json
└── src/
    └── index.ts
```

**`package.json` requirements:**
- `"name": "@huntready/mcp-server"`
- `"type": "module"` (required — `@modelcontextprotocol/sdk` uses ESM)
- `"version": "0.0.1"`
- Dependencies: `@modelcontextprotocol/sdk` (^1.9.0+), `@supabase/supabase-js` (^2.x)
- DevDependencies: `typescript` (^5.x), `tsx` (^4.x), `@types/node` (^22.x)
- Scripts:
  - `"dev": "tsx src/index.ts"`
  - `"build": "tsc"`
  - `"start": "node dist/index.js"`
  - `"lint": "tsc --noEmit"`

**`tsconfig.json` requirements:**
- `"target": "ES2022"`
- `"module": "ESNext"`
- `"moduleResolution": "Bundler"`
- `"strict": true`
- `"outDir": "./dist"`
- `"rootDir": "./src"`
- `"skipLibCheck": true`
- `"esModuleInterop": true`
- `"resolveJsonModule": true`

**`src/index.ts`:**
A hello-world that prints `"HuntReady MCP Server — scaffold"` and exits cleanly. No MCP tool registration, no database connection, no environment variable reads.

**Important:** No `.env` or database connection at M0. The scaffold proves the project compiles and runs. `package-lock.json` should be committed for reproducible installs.

**Acceptance Criteria:**
- [ ] `mcp-server/package.json` exists with `"type": "module"` and all dependencies listed above
- [ ] `mcp-server/tsconfig.json` exists with strict mode, ESNext module, Bundler resolution
- [ ] `mcp-server/src/index.ts` exists, compiles without error, and prints the expected message
- [ ] `cd mcp-server && npm install` completes without error
- [ ] `cd mcp-server && npx tsx src/index.ts` prints "HuntReady MCP Server — scaffold" and exits 0
- [ ] `cd mcp-server && npm run lint` reports no type errors
- [ ] `package-lock.json` is committed
- [ ] No imports from `ingestion/` or any Python code

---

### S0.5: Scaffold `ingestion/` and verify installs

**As a** developer cloning the repo
**I want** the `ingestion/` directory to contain a working Python project scaffold
**So that** I can begin implementing state adapters without setting up boilerplate

**Context:**
Per [ADR-003](../../adrs/ADR-003-ingestion-upstream-offline.md), ingestion is upstream and offline. Per [ADR-005](../../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md), ingestion is Python 3.11+.

Directory structure:
```
ingestion/
├── pyproject.toml
├── ingestion/
│   └── __init__.py
└── states/
    ├── montana/
    │   └── .gitkeep
    └── colorado/
        └── .gitkeep
```

Note the doubled path: the project root is `ingestion/` and the Python package directory within it is also `ingestion/` (i.e., `ingestion/ingestion/__init__.py`). This is standard Python project layout.

**`pyproject.toml` requirements:**
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "huntready-ingestion"
version = "0.0.1"
requires-python = ">=3.11"
dependencies = [
    "pdfplumber>=0.11",
    "pypdf>=4.0",
    "geopandas>=1.0",
    "shapely>=2.0",
    "psycopg[binary]>=3.1",
    "pydantic>=2.0",
    "requests>=2.32",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "ruff>=0.4",
    "mypy>=1.11",
]
```

Note: `unstructured` is deferred to M1 (heavy dependency with system-level requirements). The M0 scaffold installs the core toolchain only.

**`ingestion/__init__.py`:**
```python
"""HuntReady ingestion pipeline.

Upstream and offline — writes structured records to Supabase Postgres.
The TypeScript serving stack never imports from this package.

See ADR-003 (ingestion upstream and offline) and ADR-005 (Python for ingestion).
"""
```

**State directories:** `states/montana/.gitkeep` and `states/colorado/.gitkeep` per [ADR-007](../../adrs/ADR-007-montana-and-colorado-seed-states.md).

**Platform note:** `psycopg[binary]` requires pre-compiled wheels. If install fails on the developer's platform (rare on macOS ARM with modern pip), fall back to `psycopg` without `[binary]` and ensure `libpq-dev` is available.

**Acceptance Criteria:**
- [ ] `ingestion/pyproject.toml` exists with `[build-system]`, project name, requires-python >= 3.11, and all dependencies listed above
- [ ] `ingestion/ingestion/__init__.py` exists with a docstring referencing ADR-003 and ADR-005
- [ ] `ingestion/states/montana/.gitkeep` and `ingestion/states/colorado/.gitkeep` exist
- [ ] From `ingestion/`: `python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"` completes without error
- [ ] Within the activated virtualenv: `python -c "import ingestion"` succeeds
- [ ] No imports from `mcp-server/` or any TypeScript code exist in the Python project
- [ ] `.venv/` directory is NOT committed (covered by `.gitignore`)

---

### S0.6: Scaffold `web/` and verify installs

**As a** developer cloning the repo
**I want** the `web/` directory to contain a working Next.js project scaffold
**So that** I can begin building the web companion without setting up boilerplate

**Context:**
Per [ADR-002](../../adrs/ADR-002-mcp-canonical-interface.md), the web companion is a client of the MCP server — it does not query the database directly.

Directory structure:
```
web/
├── package.json
├── tsconfig.json
├── next.config.js
└── app/
    ├── layout.tsx
    └── page.tsx
```

**`package.json` requirements:**
- `"name": "@huntready/web"`
- Dependencies: `next` (^15.x), `react` (^19.x), `react-dom` (^19.x)
- DevDependencies: `typescript` (^5.x), `@types/react` (^19.x), `@types/react-dom` (^19.x), `@types/node` (^22.x)
- Scripts: `"dev": "next dev"`, `"build": "next build"`, `"start": "next start"`, `"lint": "next lint"`

**Note:** Tailwind CSS and Mapbox GL are deferred to M4 (web companion implementation). M0 scaffold needs only the bare Next.js App Router working.

**`tsconfig.json` requirements:**
- `"strict": true`
- `"jsx": "preserve"`
- `"module": "esnext"`
- `"moduleResolution": "bundler"`
- `"isolatedModules": true`
- `"incremental": true`
- `"paths": { "@/*": ["./*"] }`
- `"include": ["next-env.d.ts", "**/*.ts", "**/*.tsx"]`

**`next.config.js`:**
```js
/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
};

module.exports = nextConfig;
```

**`app/layout.tsx`** — must export a default component that renders `<html lang="en">` and `<body>` tags with `{children}`, and export a `metadata` const with `title: "HuntReady"`. Next.js App Router requires the root layout to include these HTML wrapper tags or `next build` will fail.

**`app/page.tsx`** — renders an `<h1>HuntReady</h1>` and `<p>Scaffold — web companion</p>`. No `any` types.

**Acceptance Criteria:**
- [ ] `web/package.json` exists with next, react, react-dom dependencies and correct devDependencies
- [ ] `web/tsconfig.json` exists with strict mode, jsx preserve, bundler resolution, isolatedModules
- [ ] `web/next.config.js` exists with `reactStrictMode: true`
- [ ] `web/app/layout.tsx` exists, exports default component with `<html>` and `<body>` tags, exports metadata
- [ ] `web/app/page.tsx` exists and renders "HuntReady" heading with "Scaffold — web companion"
- [ ] `cd web && npm install` completes without error
- [ ] `cd web && npx next build` completes without error (production build succeeds)
- [ ] No `any` types in any `.tsx` files
- [ ] `package-lock.json` is committed
- [ ] No imports from `ingestion/`, no direct database access, no MCP client code

---

### S0.7: Scaffold `plugin/`

**As a** developer cloning the repo
**I want** the `plugin/` directory to contain a Claude Code plugin scaffold following ADR-009 conventions
**So that** the project's agentic-development identity is visible from M0

**Context:**
Per [ADR-009](../../adrs/ADR-009-agentic-development-first-class.md), agentic development is a first-class project feature. The plugin uses the `.claude-plugin/` + `plugins/<name>/skills/<skill>/SKILL.md` convention.

Directory structure:
```
plugin/
├── .claude-plugin/
│   └── plugin.json
└── plugins/
    └── huntready/
        └── skills/
            ├── regulation-lookup/
            │   └── SKILL.md
            └── ingest-state/
                └── SKILL.md
```

**`plugin.json`:**
```json
{
  "name": "huntready",
  "version": "0.0.1",
  "description": "HuntReady Claude Code plugin — developer-facing skills for regulation lookup and state onboarding. See ADR-009."
}
```

**`regulation-lookup/SKILL.md`:**
- Title: "Regulation Lookup"
- Body: "Scaffold — implementation deferred to M5. This skill will wrap HuntReady's MCP tools for querying regulation data during development sessions. See [`docs/roadmap.md`](../../../../docs/roadmap.md) milestone M5."

**`ingest-state/SKILL.md`:**
- Title: "Ingest State"
- Body: "Scaffold — implementation deferred to M5. This skill will walk a developer through onboarding a new state adapter: fetching sources, running the extractor, normalizing against the schema, and scaffolding a new adapter directory. See [`docs/roadmap.md`](../../../../docs/roadmap.md) milestone M5."

No TypeScript, no npm install, no runtime dependencies. Pure documentation scaffold.

**Acceptance Criteria:**
- [ ] `plugin/.claude-plugin/plugin.json` exists with valid JSON containing name, version, and description
- [ ] `plugin/plugins/huntready/skills/regulation-lookup/SKILL.md` exists with placeholder content referencing M5
- [ ] `plugin/plugins/huntready/skills/ingest-state/SKILL.md` exists with placeholder content referencing M5
- [ ] No implementation code in `plugin/` — only JSON and Markdown
- [ ] Internal markdown links in SKILL.md files resolve to existing docs

---

### S0.8: `supabase/` directory and project provisioning

**As a** developer setting up the project locally
**I want** the `supabase/` directory to exist and the Supabase project to be provisioned
**So that** M1's first migration has somewhere to land and PostGIS is confirmed working

**Context:**
Per [ADR-004](../../adrs/ADR-004-supabase-postgres-postgis.md), Supabase Postgres + PostGIS is the storage layer. PostGIS must be enabled before M1 begins.

Directory structure:
```
supabase/
├── config.toml
└── migrations/
    └── .gitkeep
```

**`config.toml`** — minimal Supabase CLI config with a placeholder project ID. Does NOT contain credentials.
```toml
[project]
id = "your-project-id-here"
```

**`migrations/.gitkeep`** — holds the directory in git. No migrations at M0; migrations are M1 scope.

**Human-executed provisioning steps** (not automatable by an agent):
1. Create Supabase project named "huntready" on free tier via dashboard.supabase.com
2. Enable PostGIS extension: Dashboard > Database > Extensions > search "postgis" > Enable
3. Copy project URL, service-role key, anon key, and database connection string into local `.env` (per the variables documented in `.env.example` from S0.3)
4. Verify: `psql "$DATABASE_URL" -c "SELECT postgis_version();"` returns a version string

**Security:** Credentials go into `.env` only — never into committed files. `DATABASE_URL` is a credentialed connection string containing a password; it follows the same "local `.env` only" rule as the service-role key.

**RLS note:** At M0 there are no tables, so PostgREST exposes nothing. However, M1's first action must include a deny-all RLS policy on any tables it creates, per ADR-004's commitment that "PostgREST must be affirmatively disabled via RLS." This is documented here as context for the M1 PM; it is not an M0 deliverable.

**Roadmap alignment (resolved 2026-04-20):** `docs/roadmap.md` has been updated by the human so M0 reads as scaffold-only. M1 now owns the initial migrations and deny-all RLS policies. No expansion of S0.8 is needed.

**Acceptance Criteria:**
- [ ] `supabase/config.toml` exists with placeholder project ID (not a real project ID)
- [ ] `supabase/migrations/.gitkeep` exists
- [ ] Supabase project "huntready" is provisioned on free tier (human-verified)
- [ ] PostGIS extension is enabled (human-verified via Dashboard)
- [ ] `SELECT postgis_version()` returns a valid version string when run against the provisioned database (human-verified)
- [ ] Credentials exist in local `.env` only — no secrets in any committed file
- [ ] No migrations created at M0 (M1 scope)
- [ ] No RLS policies created at M0 (M1's first task, documented in M1 epic as a prerequisite)

---

### S0.9: Draft M0 documentation artifacts

**As a** PM agent
**I want** the three M0 documentation deliverables produced
**So that** a cold visitor can understand the repo and future sessions have accurate context

**Context:**
This is a PM-owned story. The PM agent writes these files directly after all implementation stories (S0.1-S0.8) are complete.

**README.md** (repo root):
- What HuntReady is (one paragraph, drawn from `docs/context.md`)
- Repo structure diagram showing all top-level directories and their purpose
- Prerequisites: Node.js 20+, Python 3.11+, Supabase account, PostgreSQL client tools (`psql` — for provisioning verification only)
- Local development setup: step-by-step for each subdirectory (mcp-server, ingestion, web)
- Where to find docs: links to context, architecture, roadmap, open-questions, ADRs
- Not a marketing document. Factual, brief, gets a cold visitor oriented.
- Clone URL uses a placeholder: `git@github.com:YOUR_ORG/huntready.git`

**CLAUDE.md** updates (not a rewrite — preserve existing tone and structure):
- Confirm all 13 ADR entries have correct filenames matching actual files in `docs/adrs/`
- Add `DATABASE_URL` to environment variables section with note: "ingestion pipeline + migrations only (not used by serving stack per ADR-003)"
- Rename `MAPBOX_TOKEN` to `MAPBOX_ACCESS_TOKEN` (matches Mapbox's own convention and `.env.example`)
- Update "Project status" section to reflect M0 completion
- Note: if any links in CLAUDE.md reference `research/schema-v2-proposal.md`, correct to `research/schema-proposal-v2.md` (actual filename)
- The `docs/architecture.md` broken link to this file has been fixed by the human (resolved 2026-04-20)

**CHANGELOG.md** (new file, repo root):
- Format: `## [Unreleased]` at top, then `## M0 — Scaffold — [Date]` block
- One entry per completed story: brief factual description of what was delivered
- Use milestone language, not internal story IDs (a cold visitor should understand the log without access to this epic file)
- No marketing language

**Acceptance Criteria:**
- [ ] `README.md` exists at repo root with: what HuntReady is, repo structure, prerequisites, setup instructions, doc links
- [ ] README setup instructions are sequential, each step is a single command or action, no step requires knowledge not in the README
- [ ] `CLAUDE.md` is updated (not rewritten) to reflect M0's final state
- [ ] All internal markdown links in `CLAUDE.md` resolve to existing files
- [ ] Any `CLAUDE.md` links to `research/schema-v2-proposal.md` are corrected to `research/schema-proposal-v2.md`
- [ ] `MAPBOX_TOKEN` in CLAUDE.md is renamed to `MAPBOX_ACCESS_TOKEN`
- [ ] `CHANGELOG.md` exists at repo root with `## [Unreleased]` and `## M0 — Scaffold` sections
- [ ] No marketing language in any of the three files

---

### S0.10: Clean-clone verification and tag `m0`

**As a** reviewer evaluating this project
**I want** confidence that a fresh clone of the repo works end-to-end
**So that** M0's quality claim is backed by evidence, not assumption

**Context:**
This story runs after all preceding stories (S0.1-S0.9) have merged to main. It produces no new commits — it verifies the existing state and creates a git tag.

**Verification steps:**
1. Clone the repo to a fresh directory: `git clone <url> /tmp/huntready-verify`
2. Verify all internal markdown links resolve (every `[text](path)` in every `.md` file points to an existing file)
3. Verify `mcp-server/` scaffold:
   - `cd /tmp/huntready-verify/mcp-server && npm install && npx tsx src/index.ts` prints expected message
   - `npm run lint` passes
4. Verify `ingestion/` scaffold:
   - `cd /tmp/huntready-verify/ingestion && python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]" && python -c "import ingestion"`
5. Verify `web/` scaffold:
   - `cd /tmp/huntready-verify/web && npm install && npx next build` succeeds
6. Verify `plugin/` scaffold:
   - All JSON and Markdown files exist at expected paths
7. Verify `.env.example` exists and contains expected variable names
8. If any verification step fails: stop, document the failure, hand back to an implementation agent. Do NOT tag.
9. Once all verifications pass: `git tag -a m0 -m "M0: Repo scaffold complete. Working code scaffolds in four directories (mcp-server, ingestion, web, plugin), Supabase provisioned with PostGIS, thinking-layer documents committed, cold-clone verified."`
10. Push the tag: `git push origin m0`
11. Confirm on GitHub that the `m0` tag is visible

**Acceptance Criteria:**
- [ ] Clean clone to `/tmp/huntready-verify` succeeds
- [ ] All internal markdown links resolve (zero broken links)
- [ ] `mcp-server/` installs and hello-world runs without error
- [ ] `ingestion/` installs in a virtualenv and package imports successfully
- [ ] `web/` installs and `next build` completes without error
- [ ] `plugin/` files exist at expected paths
- [ ] `.env.example` is present with all documented variables
- [ ] Tag `m0` exists on the commit at `main` HEAD
- [ ] Tag is pushed to the remote and visible on GitHub
- [ ] No new commits are produced by this story — it creates a tag on an existing commit

---

## Exit Criteria

- [ ] All 10 stories complete (S0.1 through S0.10)
- [ ] `CLAUDE.md` updated to reflect final M0 state
- [ ] `README.md` reads cleanly on GitHub and gets a cold visitor to local install in under ten minutes
- [ ] Clean `git clone` to a fresh directory succeeds; all internal links resolve; all scaffolds install and run
- [ ] Tag `m0` pushed and visible on GitHub
- [ ] `CHANGELOG.md` reflects M0 completion
- [ ] No secrets in any committed file

---

## Parallelization Notes

**Within M0: stories run sequentially.** The developer creates a feature branch for each story, executes it, opens a PR, reviews and merges, then starts the next story.

Recommended merge order:

S0.1 → S0.2 → S0.3 → S0.4 → S0.5 → S0.6 → S0.7 → S0.8 → S0.9 → S0.10

**Rationale:** S0.1-S0.3 are prerequisite housekeeping. S0.4-S0.7 are the four directory scaffolds (independent but sequential to avoid merge conflicts on root-level files). S0.8 has a human-blocking component (Supabase provisioning) that can be initiated during an earlier story's implementation. S0.9 references all prior stories' artifacts. S0.10 must be last.

**Potential parallel pair:** S0.4 and S0.5 could theoretically run in parallel (different directories, no shared files) but the coordination overhead exceeds the time saved for a solo developer.

---

## Known Issues to Escalate

1. ~~**Roadmap/PM-prompt discrepancy on M0 scope:**~~ Resolved 2026-04-20. Roadmap updated to match PM-prompt definition (scaffold-only, migrations and RLS deferred to M1).

2. ~~**Broken link in `docs/architecture.md`:**~~ Resolved 2026-04-20. Human fixed both references to `research/schema-proposal-v2.md`.

3. **`.gitignore` gap:** The `.env.*` pattern is not covered broadly — only `.env.*.local` is blocked. A `.env.production` or `.env.staging` file could be accidentally committed. S0.1 documents this; the fix requires human approval to modify `.gitignore`.

---

## References

- [`docs/context.md`](../../context.md) — product frame, V1 done criteria
- [`docs/architecture.md`](../../architecture.md) — system design, six-entity schema, response shape
- [`docs/roadmap.md`](../../roadmap.md) — milestones M0-M5
- [`docs/open-questions.md`](../../open-questions.md) — unresolved decisions
- [ADR-002](../../adrs/ADR-002-mcp-canonical-interface.md) — canonical interface; `mcp-server/` scaffold
- [ADR-003](../../adrs/ADR-003-ingestion-upstream-offline.md) — ingestion upstream and offline; Python/TS boundary
- [ADR-004](../../adrs/ADR-004-supabase-postgres-postgis.md) — Supabase + PostGIS; RLS commitment
- [ADR-005](../../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md) — language split
- [ADR-007](../../adrs/ADR-007-montana-and-colorado-seed-states.md) — seed states
- [ADR-009](../../adrs/ADR-009-agentic-development-first-class.md) — agentic development; plugin scaffold
