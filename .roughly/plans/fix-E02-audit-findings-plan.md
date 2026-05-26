# Fix Plan: E02 audit findings (F1, F2, F3)

## Root Cause

The E02 audit at [`docs/planning/epics/E02-audit.md`](../planning/epics/E02-audit.md) surfaced three P3 cosmetic findings. All three are narrow, deterministic edits:

- **F1:** `MT_FWP_HOST = "fwp-gis.mt.gov"` constant in [`ingestion/ingestion/lib/arcgis.py:49`](../../ingestion/ingestion/lib/arcgis.py#L49) was added during early scaffolding and never wired up. It's the only Montana-specific identifier in a shared library; the constant and its leading comment (line 48) are pure dead code.
- **F2:** `_write_features_fixture` ([`arcgis.py:870-888`](../../ingestion/ingestion/lib/arcgis.py#L870-L888)) writes via direct `write_text`, while its sibling `_write_manifest_fixture` ([`arcgis.py:891-905`](../../ingestion/ingestion/lib/arcgis.py#L891-L905)) uses an atomic tmp+rename pattern with a trailing newline. The asymmetry was introduced when S02.7 added the manifest writer without back-applying the pattern to the older features writer.
- **F3:** Epic AC at [`E02-geometry-ingestion.md:451`](../planning/epics/E02-geometry-ingestion.md#L451) cites Kalispell CWD Management Zone as "OBJECTID 970"; the live load and discovery doc both record OBJECTID 968. Pure stale-prediction documentation drift.

## File Table
| File | Action | Task(s) |
|------|--------|---------|
| `ingestion/ingestion/lib/arcgis.py` | Modify | T1, T2 |
| `docs/planning/epics/E02-geometry-ingestion.md` | Modify | T3 |

## Tasks

### T1: Delete dead `MT_FWP_HOST` constant (~1 min)
**Files:** `ingestion/ingestion/lib/arcgis.py`
**Action:** Delete the unused module-level constant and its leading comment.
**Details:**
- Remove lines 48-49 (the comment `# fwp-gis.mt.gov constants — used as defaults; functions accept overrides` and the constant `MT_FWP_HOST = "fwp-gis.mt.gov"`).
- Preserve surrounding blank-line structure: the import block above ends at line 46 (`from ingestion.lib.schema import SourceCitation`) followed by a blank line at 47; the next constant block begins at line 51 with `# Base User-Agent value (...)`. After deletion, the module should have one blank line between `from ingestion.lib.schema import SourceCitation` and the `# Base User-Agent value` comment block.
- No other code touches this constant — `grep -rn "MT_FWP_HOST"` confirms zero references outside line 49 itself.

**Verify:** (run from repo root)
```bash
cd ingestion && \
  grep -n "MT_FWP_HOST" ingestion/lib/arcgis.py || echo "removed cleanly" && \
  .venv/bin/ruff check ingestion/lib/arcgis.py && \
  .venv/bin/mypy ingestion/lib/arcgis.py
```
**UI:** no

### T2: Make `_write_features_fixture` atomic (~3 min)
**Files:** `ingestion/ingestion/lib/arcgis.py`
**Action:** Refactor `_write_features_fixture` to use the tmp+rename pattern + trailing newline, mirroring `_write_manifest_fixture`.
**Details:**
- Current implementation at lines 870-888 calls `fixture_path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")` directly.
- Replace the body of the function (after `payload` construction) so it follows the exact pattern from `_write_manifest_fixture` at lines 898-905:
  ```python
  fixture_path = fixture_dir / f"{layer_slug}-{layer_id}-features-{timestamp}.geojson"
  tmp = fixture_path.with_suffix(fixture_path.suffix + ".tmp")
  tmp.write_text(
      json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
      encoding="utf-8",
  )
  tmp.replace(fixture_path)
  ```
- Note the additions: `+ "\n"` for trailing newline (POSIX convention, matches manifest writer); `tmp.with_suffix(... + ".tmp")` and `tmp.replace(...)` for atomic write.
- Behavior contract: a partially-written features fixture should never appear at the final path. If the process is killed mid-write, only `*.tmp` orphans (already covered by the existing `*.tmp` rule in [`fixtures/.gitignore`](../../ingestion/states/montana/fixtures/.gitignore)) remain.
- No other function or test calls `_write_features_fixture` directly (`grep -n "_write_features_fixture" tests/test_arcgis.py` returned empty). Indirect coverage exists via `fetch_features` integration tests; existing tests should continue to pass since the written content is unchanged except for the appended `\n`.

**Verify:** (run from repo root)
```bash
cd ingestion && \
  .venv/bin/ruff check ingestion/lib/arcgis.py && \
  .venv/bin/mypy ingestion/lib/arcgis.py && \
  .venv/bin/pytest tests/test_arcgis.py
```
**UI:** no

### T3: Fix stale OBJECTID 970 → 968 in epic (~1 min)
**Files:** `docs/planning/epics/E02-geometry-ingestion.md`
**Action:** Replace the stale OBJECTID literal in the S02.5 acceptance criterion.
**Details:**
- Edit line 451. Current text: `Libby CWD Management Zone (OBJECTID 967) and Kalispell CWD Management Zone (OBJECTID 970)`.
- Replace `(OBJECTID 970)` with `(OBJECTID 968)`. The Libby OBJECTID 967 stays unchanged (matches both discovery doc and the audit's evidence).
- This is a single literal swap. No other content on the line or surrounding paragraphs needs to change.
- Cross-references: `cwd-source-discovery.md` records OBJECTID 968 for Kalispell, and the audit report at `docs/planning/epics/E02-audit.md` already cites 968 as the correct value.

**Verify:** (run from repo root)
```bash
grep -n "OBJECTID 970" docs/planning/epics/E02-geometry-ingestion.md || echo "stale value removed" && \
  grep -n "OBJECTID 968" docs/planning/epics/E02-geometry-ingestion.md
```
**UI:** no

## Blast Radius

- **Do NOT modify:**
  - The audit report itself (`docs/planning/epics/E02-audit.md`) — it already cites correct values.
  - `cwd-source-discovery.md` — already authoritative.
  - Any S02.X test files unrelated to T1/T2/T3.
  - The `_write_manifest_fixture` function — it's already correct and is the model for T2.
  - Other ADRs, runbooks, or planning docs.
- **Watch for:**
  - T2 trailing-newline change: any test that asserts byte-equality of a features fixture against a hard-coded string. None found via grep, but a snapshot/golden-file test could fail; if so, update the golden file (it's gitignored anyway).
  - T2 atomic write: ensure `tmp.replace(fixture_path)` (not `tmp.rename(...)`) is used, since `replace` is the cross-platform overwrite-safe method (matches `_write_manifest_fixture`).
  - T1 must not also delete the surrounding `# Base User-Agent value` comment block at line 51+ — that comment governs a real, used constant block.

## Verification at end (run from repo root)

```bash
cd ingestion && \
  .venv/bin/ruff check ingestion/ tests/ && \
  .venv/bin/mypy ingestion/lib/ && \
  .venv/bin/pytest tests/
```

Pytest should pass with the same green count as before; ruff and mypy clean. Mirrors the project convention in `CLAUDE.md` § "Verification commands".
