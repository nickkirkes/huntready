# HuntReady

HuntReady is a regulatory data platform for licensed hunting in the United States. Given a coordinate, species, and date, it returns applicable regulations with source citations, license/tag requirements, season windows, reporting obligations, and agency contacts. It routes hunters to authoritative state agency sources — it does not interpret or paraphrase regulations.

## Repo structure

```
huntready/
├── mcp-server/        TypeScript — MCP server, canonical interface (ADR-002)
├── ingestion/         Python 3.11+ — offline ingestion pipeline (ADR-003)
├── web/               Next.js — map-first web companion
├── plugin/            Claude Code plugin — developer-facing skills (ADR-009)
├── supabase/          Supabase config and migrations
├── docs/
│   ├── context.md          Product frame
│   ├── architecture.md     System design, schema types, response shapes
│   ├── roadmap.md          Milestones M0–M5
│   ├── open-questions.md   Unresolved decisions
│   ├── adrs/               13 architecture decision records
│   ├── research/           Source-structure research and schema proposals
│   └── planning/           Epics and milestone tracking
├── .env.example       Required environment variables (no secrets)
├── CLAUDE.md          Claude Code project context
└── CHANGELOG.md       What has been built
```

## Prerequisites

- **Node.js** 20+
- **Python** 3.11+
- **Supabase account** — free tier ([supabase.com](https://supabase.com))
- **PostgreSQL client tools** (`psql`) — for Supabase provisioning verification only

## Local development setup

### 1. Clone and configure environment

```bash
git clone git@github.com:YOUR_ORG/huntready.git
cd huntready
cp .env.example .env
# Fill in .env with your Supabase credentials and Mapbox token
```

### 2. MCP server (TypeScript)

```bash
cd mcp-server
npm install
npx tsx src/index.ts          # Should print: "HuntReady MCP Server — scaffold"
```

### 3. Ingestion pipeline (Python)

```bash
cd ingestion
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -c "import ingestion"  # Should succeed silently
```

### 4. Web companion (Next.js)

```bash
cd web
npm install
npm run dev                   # Starts dev server at http://localhost:3000
```

### 5. Supabase (first-time only)

If you are provisioning a new Supabase project:

1. Create a free-tier project at [supabase.com](https://supabase.com)
2. Enable PostGIS: Dashboard > Database > Extensions > "postgis" > Enable
3. Copy credentials into your `.env` (see `.env.example` for variable names)
4. Verify: `psql "$DATABASE_URL" -c "SELECT postgis_version();"`

### 6. Pre-commit hooks

This repo uses [pre-commit](https://pre-commit.com) to enforce code quality on every commit.

```bash
# Install pre-commit (one-time)
uv tool install pre-commit   # or: pip install pre-commit

# Install the git hooks
pre-commit install

# Run all hooks manually (optional)
pre-commit run --all-files
```

**What runs on commit:**

| Hook | Scope | What it checks |
|------|-------|----------------|
| `tsc: mcp-server` | `mcp-server/**/*.ts` | TypeScript type errors |
| `tsc: web` | `web/**/*.ts(x)` | TypeScript type errors |
| `ruff` | `ingestion/` | Python lint (auto-fixes when possible) |
| `detect-secrets` | All files | Prevents secrets from being committed |

If a hook fails, fix the issue and re-stage your files. Ruff may auto-fix some issues — check `git diff` after a failure.

## Documentation

- [Product context](docs/context.md) — what HuntReady is and is not
- [Architecture](docs/architecture.md) — system design, data model, response shapes
- [Roadmap](docs/roadmap.md) — milestones M0–M5
- [Open questions](docs/open-questions.md) — unresolved decisions
- [ADRs](docs/adrs/) — 13 architecture decision records
- [Planning](docs/planning/) — milestone tracking and epic files

## Current status

**M0 (Scaffold) complete.** Working code scaffolds, Supabase provisioned with PostGIS, thinking-layer documents committed. No business logic, no regulation data. M1 begins Montana ingestion.

## V1 scope

- **States:** Montana, Colorado
- **Species:** elk, mule deer, whitetail, pronghorn, black bear
- **Surfaces:** MCP server, web companion, Claude Code plugin
