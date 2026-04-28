# E01 Migration Verification Runbook

Verifies that E01 schema migrations (S01.2 entity tables + S01.3 RLS) apply cleanly and produce the expected database state. See [ADR-004](../adrs/ADR-004-supabase-postgres-postgis.md) (Supabase + PostGIS) and [ADR-002](../adrs/ADR-002-mcp-canonical-interface.md) (PostgREST disabled via RLS).

## Prerequisites

- **Supabase CLI** v2.84+ (`brew install supabase/tap/supabase`)
- **Docker** running (`docker info`)
- No other local Supabase project using the same ports (check `supabase/config.toml` port settings; adjust if needed)

## 1. Apply Migrations (local)

```bash
# From repo root
supabase start        # Boots local Postgres + PostGIS via Docker
supabase db reset     # Drops/recreates DB, applies all migrations from scratch
```

Both migrations should apply in order:
1. `20260425000000_initial_schema.sql` — 10 tables, 4 indexes, PostGIS extension
2. `20260425000001_rls_deny_all.sql` — RLS + deny-all policies + REVOKE

## 2. Apply Migrations (cloud)

```bash
# Link to your Supabase project (one-time)
supabase link --project-ref <project-id>

# Push migrations to cloud
supabase db push
```

Requires `SUPABASE_URL` and credentials in `.env` (see `.env.example`). The project ref is the subdomain from your Supabase URL.

## 3. Verify Tables and PostGIS

Connect via psql (local URL printed by `supabase start`, or your cloud DATABASE_URL):

```sql
-- All 10 tables exist and are empty
SELECT 'regulation_record' AS tbl, COUNT(*) FROM regulation_record
UNION ALL SELECT 'season_definition', COUNT(*) FROM season_definition
UNION ALL SELECT 'license_tag', COUNT(*) FROM license_tag
UNION ALL SELECT 'draw_spec', COUNT(*) FROM draw_spec
UNION ALL SELECT 'reporting_obligation', COUNT(*) FROM reporting_obligation
UNION ALL SELECT 'geometry', COUNT(*) FROM geometry
UNION ALL SELECT 'jurisdiction_binding', COUNT(*) FROM jurisdiction_binding
UNION ALL SELECT 'regulation_season', COUNT(*) FROM regulation_season
UNION ALL SELECT 'regulation_license', COUNT(*) FROM regulation_license
UNION ALL SELECT 'regulation_reporting', COUNT(*) FROM regulation_reporting;
-- Expected: 10 rows, all count = 0

-- PostGIS functional
SELECT postgis_version();
-- Expected: version string (e.g. "3.3 USE_GEOS=1 USE_PROJ=1 USE_STATS=1")

SELECT ST_AsText(ST_GeomFromText('MULTIPOLYGON(((0 0, 1 0, 1 1, 0 1, 0 0)))', 4326));
-- Expected: MULTIPOLYGON(((0 0,1 0,1 1,0 1,0 0)))
```

## 4. Verify RLS

### Anon role denied

```bash
curl -s http://127.0.0.1:<API_PORT>/rest/v1/regulation_record \
  -H "apikey: <ANON_KEY>" \
  -H "Authorization: Bearer <ANON_KEY>"
```

Expected: `{"code":"42501","details":null,"hint":null,"message":"permission denied for table regulation_record"}`

### Authenticated role denied

```bash
curl -s http://127.0.0.1:<API_PORT>/rest/v1/regulation_record \
  -H "apikey: <ANON_KEY>" \
  -H "Authorization: Bearer <AUTHENTICATED_JWT>"
```

To generate an authenticated JWT for local testing, get the JWT secret from `supabase status` (shown as `JWT secret`), then mint a token with Node.js builtins:

```bash
node -e "
  const c = require('crypto');
  const h = Buffer.from(JSON.stringify({alg:'HS256',typ:'JWT'})).toString('base64url');
  const p = Buffer.from(JSON.stringify({role:'authenticated',iss:'supabase',exp:Math.floor(Date.now()/1000)+3600})).toString('base64url');
  const s = c.createHmac('sha256','<JWT_SECRET>').update(h+'.'+p).digest('base64url');
  console.log(h+'.'+p+'.'+s);
"
```

Replace `<JWT_SECRET>` with the value from `supabase status`.

Expected: `{"code":"42501","details":null,"hint":null,"message":"permission denied for table regulation_record"}`

### Service role succeeds

```bash
curl -s http://127.0.0.1:<API_PORT>/rest/v1/regulation_record \
  -H "apikey: <SERVICE_ROLE_KEY>" \
  -H "Authorization: Bearer <SERVICE_ROLE_KEY>"
```

Expected: `[]` (empty array, no error)

### Policy and grant verification (SQL)

```sql
-- 20 deny-all policies (2 per table x 10 tables)
SELECT tablename, policyname, roles, cmd, qual, with_check
FROM pg_policies WHERE schemaname = 'public'
ORDER BY tablename, policyname;
-- Expected: 20 rows, all qual='false', with_check='false' (expression strings, not booleans)

-- Grants revoked from anon and authenticated
SELECT grantee, privilege_type FROM information_schema.table_privileges
WHERE table_schema = 'public' AND table_name = 'regulation_record'
  AND grantee IN ('anon', 'authenticated');
-- Expected: 0 rows
```

## 5. Verify Cross-Language Type Checks

All commands run from the repo root:

```bash
# TypeScript
(cd mcp-server && npm run lint)

# Python lint
(cd ingestion && source .venv/bin/activate && ruff check .)

# Python type check
(cd ingestion && source .venv/bin/activate && python -m mypy ingestion/lib/schema.py --ignore-missing-imports)
```

All three must exit 0. Subshells `()` keep the working directory unchanged between commands.

## 6. Reproducibility

Run `supabase db reset` a second time to confirm migrations are reproducible on a fresh database:

```bash
supabase db reset
# Re-run the table count and service_role curl checks from sections 3 and 4
```

## Cleanup

```bash
supabase stop    # Stops local Docker containers
```
