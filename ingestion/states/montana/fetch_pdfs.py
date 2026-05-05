"""Montana PDF fetch orchestrator.

Reads ingestion/states/montana/sources.yaml and invokes
ingestion.lib.pdf_fetch.fetch_pdf for each entry. Per the read-only-scripts
fail-loud pitfall, partial failures across entries are collected and re-raised
as a single PdfFetchError after all entries have been attempted — this lets
the operator see all four results in one run rather than one-at-a-time.

Run from the repo root:
    ingestion/.venv/bin/python ingestion/states/montana/fetch_pdfs.py

Optional env: HUNTREADY_INGESTION_CONTACT (appended to User-Agent).
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

import yaml

from ingestion.lib.pdf_fetch import PdfFetchError, fetch_pdf

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SOURCES_YAML = _REPO_ROOT / "ingestion" / "states" / "montana" / "sources.yaml"
_FIXTURE_DIR = _REPO_ROOT / "ingestion" / "states" / "montana" / "fixtures"

# Required fields per entry. If any of these is missing or empty (other than
# expected_sha256, which can be the literal "unknown"), the orchestrator raises
# rather than silently skipping the entry.
_REQUIRED_FIELDS: frozenset[str] = frozenset({
    "id", "agency", "title", "url",
    "expected_page_count", "document_type", "publication_date",
})

# String fields validated for non-empty content (excludes url, which has its
# own pending-flag-aware guard further down the loop).
_STRING_FIELDS: tuple[str, ...] = (
    "id", "agency", "title", "document_type", "publication_date",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch all Montana FWP regulation PDFs listed in sources.yaml.",
    )
    parser.add_argument(
        "--sources",
        type=Path,
        default=_SOURCES_YAML,
        help="Path to sources.yaml (default: ingestion/states/montana/sources.yaml)",
    )
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        default=_FIXTURE_DIR,
        help="Output directory for PDFs and manifests "
             "(default: ingestion/states/montana/fixtures/)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger = logging.getLogger(__name__)

    raw: Any = yaml.safe_load(args.sources.read_text(encoding="utf-8"))
    raw_entries: list[Any] = (
        list(raw.get("pdfs", [])) if isinstance(raw, dict) else []
    )
    if not raw_entries:
        msg = (
            f"sources.yaml at {args.sources} contains no entries under top-level "
            "'pdfs' key — refusing to silently no-op."
        )
        raise PdfFetchError(msg)

    failures: list[tuple[str, Exception]] = []
    succeeded: list[str] = []
    # `pending` is tracked separately from `failures` because its remediation is
    # different (operator must locate the URL, not debug a fetch error). It is
    # NOT a success bucket: any pending entries still block the run from exiting
    # 0 — exiting 0 with a known-unfetched canonical source would let downstream
    # extraction stories run against an incomplete fixture set. The distinction
    # is visibility, not severity.
    pending: list[str] = []
    for index, entry in enumerate(raw_entries):
        # Per-entry shape guard: a non-mapping element (scalar, list, None)
        # would crash `.keys()` / `.get()` below with a bare AttributeError
        # that escapes our `except PdfFetchError` clauses. Surface it as a
        # PdfFetchError so the aggregation loop continues and other entries
        # still get attempted.
        if not isinstance(entry, dict):
            failures.append((
                f"<entry-{index}>",
                PdfFetchError(
                    f"entry at index {index} is not a YAML mapping "
                    f"(got {type(entry).__name__}: {entry!r})"
                ),
            ))
            continue
        entry_id = str(entry.get("id", f"<entry-{index}>"))
        missing = _REQUIRED_FIELDS - set(entry.keys())
        if missing:
            failures.append((
                entry_id,
                PdfFetchError(f"missing required fields: {sorted(missing)}"),
            ))
            continue
        # Empty-value / wrong-type guard: keys present but values that are
        # empty, null, or the wrong type will cause confusing downstream errors
        # (wrong manifests for agency/title; failed fetch_pdf calls for
        # document_type/publication_date). Catch them here with a message that
        # names the YAML entry and each offending field. url is intentionally
        # excluded — empty urls are handled by the pending-flag branch and the
        # existing empty-url guard immediately below.
        invalid_fields: list[str] = []
        for field in _STRING_FIELDS:
            val = entry.get(field)
            if not isinstance(val, str) or not val.strip():
                invalid_fields.append(f"  {field}: {val!r}")
        page_count_val = entry.get("expected_page_count")
        if (
            isinstance(page_count_val, bool)
            or not isinstance(page_count_val, int)
            or page_count_val <= 0
        ):
            invalid_fields.append(f"  expected_page_count: {page_count_val!r}")
        if invalid_fields:
            failures.append((
                entry_id,
                PdfFetchError(
                    f"empty or invalid field values in entry {entry_id!r}:\n"
                    + "\n".join(invalid_fields)
                ),
            ))
            continue
        # An entry can declare itself intentionally not-yet-fetchable via
        # `pending: true` — used for sources whose URL is known to exist but
        # hasn't been located yet (e.g. the MT FWP black bear correction PDF
        # whose errata-page location is TBD as of S03.1). Pending entries are
        # tracked separately from `failures` for clearer operator messaging
        # (remediation is "locate the URL", not "debug the fetch error"), but
        # they still block the run from exiting 0 — see the `pending` list
        # declaration above for why.
        if entry.get("pending") is True:
            if entry.get("url"):
                failures.append((
                    entry_id,
                    PdfFetchError(
                        f"entry {entry_id} has pending: true AND a non-empty "
                        f"url — the two are mutually exclusive; clear url or "
                        f"remove pending: true"
                    ),
                ))
                continue
            logger.info(
                "entry %s pending (operator marked url as not yet populated)",
                entry_id,
            )
            pending.append(entry_id)
            continue
        if not entry.get("url"):
            failures.append((
                entry_id,
                PdfFetchError(
                    f"url for {entry_id} is empty or missing — populate "
                    f"sources.yaml (or set pending: true) before re-running."
                ),
            ))
            continue
        try:
            metadata = fetch_pdf(
                citation_id=entry["id"],
                url=entry["url"],
                publication_date=entry["publication_date"],
                document_type=entry["document_type"],
                fixture_dir=args.fixture_dir,
            )
        except PdfFetchError as exc:
            logger.error("fetch failed for %s: %s", entry_id, exc)
            failures.append((entry_id, exc))
            continue

        # Verify the page count matches the entry's expectation. Mismatch is a
        # hard failure (not a warning) — extraction stories key off page numbers
        # and a different page count means the source has changed. Write a
        # *-pending-reextraction.flag marker so downstream stories block on the
        # fixture in the same way they block on a SHA-256 drift, and so a
        # subsequent fetch_pdfs run also blocks until the operator acknowledges.
        expected_pages = entry["expected_page_count"]
        if metadata.page_count != expected_pages:
            marker_path = (
                args.fixture_dir
                / f"{entry_id}-{entry['publication_date']}-pending-reextraction.flag"
            )
            marker_text = (
                f"Page count mismatch on fetch.\n"
                f"  citation_id:    {entry_id}\n"
                f"  url:            {entry['url']}\n"
                f"  expected_pages: {expected_pages}\n"
                f"  observed_pages: {metadata.page_count}\n"
                f"\n"
                f"Operator: the source structure has changed. Investigate, "
                f"update sources.yaml expected_page_count if the new count is "
                f"correct, then DELETE this file to unblock downstream stories.\n"
            )
            # Track marker write outcome separately so the appended failure
            # message accurately reflects whether the marker landed. We log
            # but do not re-raise an OSError here: the page-count failure is
            # already recorded in `failures` and surfaces in the final
            # aggregated PdfFetchError, so the operator sees the entry either
            # way. The asymmetry with pdf_fetch.py's SHA-drift path (which
            # raises immediately on marker write failure) is intentional —
            # the orchestrator's job is to attempt every entry.
            marker_status: str
            try:
                marker_path.write_text(marker_text, encoding="utf-8")
            except OSError as marker_exc:
                logger.error(
                    "page-count mismatch for %s AND failed to write marker at %s: %s",
                    entry_id, marker_path, marker_exc,
                )
                marker_status = (
                    f"MARKER WRITE FAILED at {marker_path}: {marker_exc}. "
                    f"Operator MUST manually block downstream stories until resolved."
                )
            else:
                marker_status = f"Marker written at {marker_path}."
            failures.append((
                entry_id,
                PdfFetchError(
                    f"page count mismatch for {entry_id}: "
                    f"expected {expected_pages}, observed {metadata.page_count}. "
                    f"{marker_status}"
                ),
            ))
            continue
        succeeded.append(entry_id)
        logger.info(
            "fetched %s: %d pages, sha256=%s…",
            entry_id, metadata.page_count, metadata.pdf_sha256[:12],
        )

    logger.info(
        "succeeded: %d, pending: %d, failed: %d",
        len(succeeded), len(pending), len(failures),
    )
    # Pending and failed both block the run from exiting 0 — a "success" exit
    # against an incomplete canonical source set would mislead downstream
    # stories (S03.3+) into running against a partial fixture set. The
    # remediation paths differ (failures need debugging; pending entries need
    # URL discovery) so we surface the two categories separately in the
    # raised message rather than collapsing them.
    blocked_total = len(failures) + len(pending)
    if blocked_total:
        msg_lines = [
            f"{blocked_total} of {len(raw_entries)} PDF entries are not yet fetched:",
        ]
        if failures:
            msg_lines.append(f"  {len(failures)} failed:")
            msg_lines.extend(f"    - {cid}: {exc}" for cid, exc in failures)
        if pending:
            msg_lines.append(
                f"  {len(pending)} pending "
                f"(operator-marked intentionally incomplete; locate URL "
                f"and remove `pending: true` from sources.yaml):"
            )
            msg_lines.extend(f"    - {cid}" for cid in pending)
        raise PdfFetchError("\n".join(msg_lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
