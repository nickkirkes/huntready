# M0: Repo Scaffold Checklist

**Purpose:** Get from "thinking layer done" to "repo exists and is shaped correctly" without touching business logic.

**Time estimate:** 3-5 hours of concentrated work. One long sitting or two shorter ones.

**Done when:**
- The private GitHub repo exists with all thinking-layer docs committed
- Four code directories (`mcp-server/`, `ingestion/`, `web/`, `plugin/`) have minimal scaffolding that lints and runs
- Supabase project provisioned; connection string recorded
- Tag `m0` is pushed
- A clean clone into a new directory resolves every internal link in the docs

---

## Step 1: Create the repo

```bash
# Using gh CLI (install from https://cli.github.com/ if needed)
gh repo create huntready --private --description "Regulatory companion for licensed hunting in the US"
gh repo clone huntready
cd huntready
```

If you prefer the web UI: create a new private repo named `huntready` at github.com/new, then `git clone` it locally.

## Step 2: Top-level file layout

At repo root, create this structure. Directories with no files yet get a `.gitkeep` so git tracks them.

```
huntready/
├── README.md
├── context.md
├── architecture.md
├── roadmap.md
├── open-questions.md
├── .gitignore
├── .env.example
├── adrs/
│   ├── README.md
│   ├── TEMPLATE.md
│   ├── ADR-001-authority-preserved.md
│   ├── ADR-002-mcp-canonical-interface.md
│   ├── ... (all 13 ADRs)
├── research/
│   ├── schema-v2-proposal.md
│   ├── montana-source-structure-findings.md
│   ├── montana-gis-endpoints-verified.md
│   ├── gmu-source-evaluation.md
│   ├── colorado-draw-schema-proposal.md
│   ├── mcp-tool-response-shape-recommendation.md
│   ├── mcp-response-shape-analysis.md
│   └── frontend-response-shape-analysis.md
├── mcp-server/
│   ├── package.json
│   ├── tsconfig.json
│   ├── src/
│   │   └── index.ts
│   └── .gitkeep
├── ingestion/
│   ├── pyproject.toml
│   ├── ingestion/
│   │   └── __init__.py
│   └── states/
│       ├── montana/
│       │   └── .gitkeep
│       └── colorado/
│           └── .gitkeep
├── web/
│   ├── package.json
│   ├── tsconfig.json
│   ├── next.config.js
│   └── app/
│       └── page.tsx
├── plugin/
│   ├── .claude-plugin/
│   │   └── plugin.json
│   └── plugins/
│       └── huntready/
│           └── skills/
│               ├── regulation-lookup/
│               │   └── SKILL.md
│               └── ingest-state/
│                   └── SKILL.md
└── supabase/
    ├── config.toml
    └── migrations/
        └── .gitkeep
```

## Step 3: Copy the thinking-layer docs

From `/mnt/user-data/outputs/` (or wherever you have them staged), copy:

```bash
# From your outputs directory to repo root
cp /path/to/outputs/context.md .
cp /path/to/outputs/architecture.md .
cp /path/to/outputs/roadmap.md .
cp /path/to/outputs/open-questions.md .

# ADRs folder
mkdir -p adrs
cp /path/to/outputs/adrs/*.md adrs/

# Research folder
mkdir -p research
cp /path/to/outputs/research/*.md research/
```

**Before committing, verify internal links resolve.** The ADRs link to `../research/` paths; the research docs link to relative paths; `open-questions.md` links to `adrs/ADR-XXX-...`. Run this check:

```bash
# Find all markdown links to local files and verify each target exists
python3 <<'PYEOF'
import os, re
for root, dirs, files in os.walk('.'):
    if '.git' in root: continue
    for f in files:
        if not f.endswith('.md'): continue
        fp = os.path.join(root, f)
        with open(fp) as fh:
            content = fh.read()
        # Find markdown links that look like relative paths
        for m in re.finditer(r'\[([^\]]+)\]\(([^)]+)\)', content):
            target = m.group(2)
            if target.startswith(('http://', 'https://', '#', 'mailto:')):
                continue
            # Resolve relative to the file's directory
            target_path = os.path.normpath(os.path.join(os.path.dirname(fp), target.split('#')[0]))
            if target_path and not os.path.exists(target_path):
                print(f"BROKEN: {fp}  ->  {target}  (resolved to {target_path})")
PYEOF
```

If this prints anything, fix the paths before continuing. Typical fixes: the ADRs use `../research/` which resolves correctly only when the research folder is at the repo root; if you nested things differently, either fix the structure or update the links.

## Step 4: .gitignore

Create at repo root:

```gitignore
# Environment
.env
.env.local
.env.*.local

# Dependencies
node_modules/
__pycache__/
*.pyc
.venv/
venv/
.pnpm-store/

# Build artifacts
dist/
build/
.next/
*.tsbuildinfo

# IDE
.vscode/
.idea/
*.swp
.DS_Store

# Supabase local dev (if you use it)
supabase/.branches
supabase/.temp

# Test/coverage artifacts
coverage/
.pytest_cache/
.mypy_cache/
.ruff_cache/

# Logs
*.log
npm-debug.log*
```

## Step 5: .env.example

This documents what secrets/config are needed without committing them. Create at repo root:

```bash
# Supabase — populate these from your Supabase project dashboard
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_SECRET_KEY=        # MCP server and ingestion pipeline use this
SUPABASE_PUBLISHABLE_KEY=   # Web app uses this (scoped by RLS)

# Database — direct connection for migrations and ingestion
DATABASE_URL=postgresql://postgres:[password]@db.[ref].supabase.co:5432/postgres

# Mapbox — web companion
MAPBOX_ACCESS_TOKEN=

# MCP server
MCP_SERVER_PORT=3001
```

## Step 6: Code scaffolds

### 6a. `mcp-server/package.json`

```json
{
  "name": "@huntready/mcp-server",
  "version": "0.0.1",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "tsx watch src/index.ts",
    "build": "tsc",
    "start": "node dist/index.js",
    "lint": "tsc --noEmit"
  },
  "dependencies": {
    "@modelcontextprotocol/sdk": "^1.0.0",
    "@supabase/supabase-js": "^2.45.0"
  },
  "devDependencies": {
    "@types/node": "^22.0.0",
    "tsx": "^4.19.0",
    "typescript": "^5.6.0"
  }
}
```

### 6b. `mcp-server/tsconfig.json`

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "outDir": "dist",
    "rootDir": "src",
    "resolveJsonModule": true
  },
  "include": ["src/**/*"]
}
```

### 6c. `mcp-server/src/index.ts`

```typescript
// HuntReady MCP Server — entry point
// ADRs 002, 005: canonical interface, TypeScript for serving

console.log("HuntReady MCP server — scaffold. Tools not yet implemented.");
```

### 6d. `ingestion/pyproject.toml`

```toml
[project]
name = "huntready-ingestion"
version = "0.0.1"
description = "HuntReady regulation ingestion pipeline"
requires-python = ">=3.11"
dependencies = [
    "pdfplumber>=0.11",
    "geopandas>=1.0",
    "shapely>=2.0",
    "requests>=2.32",
    "psycopg[binary]>=3.2",
    "pydantic>=2.8",
]

[project.optional-dependencies]
dev = ["ruff>=0.6", "mypy>=1.11", "pytest>=8.0"]

[tool.ruff]
line-length = 100
target-version = "py311"
```

### 6e. `ingestion/ingestion/__init__.py`

```python
"""HuntReady regulation ingestion pipeline.

See ADR-003 (ingestion upstream and offline) and ADR-005 (Python for ingestion).
"""
```

### 6f. `web/package.json`

```json
{
  "name": "@huntready/web",
  "version": "0.0.1",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "next lint"
  },
  "dependencies": {
    "next": "^15.0.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "mapbox-gl": "^3.7.0"
  },
  "devDependencies": {
    "@types/node": "^22.0.0",
    "@types/react": "^19.0.0",
    "typescript": "^5.6.0"
  }
}
```

### 6g. `web/tsconfig.json`

Let Next.js generate it on first run. Just leave it empty for now or use the Next.js starter:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "paths": { "@/*": ["./*"] }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx"],
  "exclude": ["node_modules"]
}
```

### 6h. `web/next.config.js`

```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
};
module.exports = nextConfig;
```

### 6i. `web/app/page.tsx`

```tsx
export default function Home() {
  return (
    <main style={{ padding: "2rem", fontFamily: "system-ui" }}>
      <h1>HuntReady</h1>
      <p>Scaffold. Map and regulation panel not yet implemented.</p>
    </main>
  );
}
```

### 6j. `plugin/.claude-plugin/plugin.json`

```json
{
  "name": "huntready",
  "version": "0.0.1",
  "description": "HuntReady developer-facing skills — see ADR-009"
}
```

### 6k. `plugin/plugins/huntready/skills/regulation-lookup/SKILL.md`

```markdown
# regulation-lookup

Query HuntReady's MCP tools during development to verify adapter output.

**Status:** Scaffold. Implementation deferred to M5.
```

### 6l. `plugin/plugins/huntready/skills/ingest-state/SKILL.md`

```markdown
# ingest-state

Walk a developer through onboarding a new state adapter: fetch sources,
run the extractor, normalize against the schema, and scaffold the adapter
directory.

**Status:** Scaffold. Implementation deferred to M5.
```

### 6m. `supabase/config.toml`

Let the Supabase CLI generate this on `supabase init` if you end up using it. For now, a placeholder:

```toml
# Supabase local development configuration
# See https://supabase.com/docs/guides/cli/config
project_id = "huntready"
```

## Step 7: Initial README

Create `README.md` at the root. This is the minimum; it will grow as code lands.

```markdown
# HuntReady

Regulatory companion for licensed hunting in the United States. Answers the
question: *"I'm planning to hunt [species] at [coordinate] on [date]. What do
I need to know, what do I need to buy, and who do I need to tell?"*

Currently scaffold (M0). See [`roadmap.md`](roadmap.md) for the build plan.

## Repository shape

- [`context.md`](context.md) — what HuntReady is and is not, the user, authority boundaries, V1 done criteria
- [`architecture.md`](architecture.md) — system design, data model, deployment
- [`roadmap.md`](roadmap.md) — milestones M0 through M5
- [`open-questions.md`](open-questions.md) — decisions not yet made
- [`adrs/`](adrs/) — architecture decision records (13 accepted as of M0)
- [`research/`](research/) — extended reasoning documents that informed the ADRs
- [`mcp-server/`](mcp-server/) — MCP server (TypeScript); canonical query interface
- [`ingestion/`](ingestion/) — regulation ingestion pipeline (Python)
- [`web/`](web/) — web companion (Next.js)
- [`plugin/`](plugin/) — Claude Code plugin (skills: `regulation-lookup`, `ingest-state`)
- [`supabase/`](supabase/) — Postgres migrations and Supabase config

## Local development

Prerequisites:
- Node 20+
- Python 3.11+
- A Supabase project (free tier is sufficient for V1)

Setup:

\```bash
git clone git@github.com:YOUR_ORG/huntready.git
cd huntready
cp .env.example .env
# Fill in .env with your Supabase credentials
\```

Currently scaffold only — no services run yet. M1 will add the first working
ingestion and query path.

## License

Proprietary. This is a private portfolio artifact; see [ADR open question Q13](open-questions.md)
for the post-V1 licensing decision.
```

Note: the backticks around the bash block need to be triple-backticks in the actual file; I've escaped them here so this checklist itself renders cleanly.

## Step 8: Install dependencies and verify each subdir builds

```bash
# Web and MCP server
cd mcp-server && npm install && npm run lint && cd ..
cd web && npm install && cd ..

# Ingestion
cd ingestion && python3.11 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]" && cd ..
```

"Lints and runs" is a low bar at M0 — the TypeScript code is one `console.log`, the Python code is just a module docstring. But verifying it all builds catches any scaffold problems before they compound.

## Step 9: Provision Supabase

1. Sign in at https://supabase.com/dashboard and create a new project.
   - Name: `huntready`
   - Region: whichever is closest to you (Nashville → us-east-1 or us-east-2)
   - Database password: generate a strong one and save it immediately
2. Wait for the project to provision (~2 minutes).
3. Settings → API: copy the URL, the `anon` key, and the `service_role` key into your local `.env` (not `.env.example`).
4. Settings → Database: copy the connection string into `.env` as `DATABASE_URL`.
5. Database → Extensions: enable `postgis`. (It may already be enabled by default; confirm it shows as enabled.)
6. Verify the connection from your machine:

```bash
psql "$DATABASE_URL" -c "SELECT postgis_version();"
# Should output something like: "3.3 USE_GEOS=1 USE_PROJ=1 USE_STATS=1"
```

If that succeeds, Supabase is ready for M1a migrations.

## Step 10: Initial commit and tag

```bash
git add .
git status  # verify nothing sensitive (like .env) is staged
git commit -m "M0: scaffold

- Thinking-layer docs (context, architecture, roadmap, open-questions, 13 ADRs, research)
- Code scaffold for mcp-server, ingestion, web, plugin
- Supabase project provisioned (PostGIS enabled)
- README with repo-shape overview and local-dev setup"

git tag m0
git push --tags origin main
```

## Step 11: Verify M0 is actually done

Do a clean-clone sanity check:

```bash
cd /tmp
git clone git@github.com:YOUR_ORG/huntready.git huntready-verify
cd huntready-verify
# Run the internal-link check from Step 3 again
# All links should resolve
# README should render cleanly on GitHub
```

If the clean clone works and the README reads well in the GitHub UI, **M0 is done**. Delete the `/tmp` copy.

---

## What you've committed to with this M0

- The repo is private, owned by you. Collaborators (OnX panel, future reviewers) get invited as needed.
- The thinking-layer is the source of truth for future agents and humans. Every subsequent commit operates within it.
- The four code subdirectories are claimed. M1 onwards will fill them.
- Supabase is the database. No migration to another vendor without a new ADR.

## What M0 does not yet do

- No regulation data exists yet.
- No MCP tools are implemented.
- No web UI beyond the scaffold page.
- No plugin skills beyond placeholders.
- No tests, no CI, no deploy configuration.

Each of these is an M1+ concern. Don't pre-build them.

## The first thing to do after M0

Open `roadmap.md` and read the M1 section. Then come back to `architecture.md` and read the "Data model" section. Those two together set you up for M1a. The schema you're about to write migrations for is already fully specified — your job is translation, not design.
