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
    entries: list[dict[str, Any]] = (
        raw.get("pdfs", []) if isinstance(raw, dict) else []
    )
    if not entries:
        msg = (
            f"sources.yaml at {args.sources} contains no entries under top-level "
            "'pdfs' key — refusing to silently no-op."
        )
        raise PdfFetchError(msg)

    failures: list[tuple[str, Exception]] = []
    succeeded: list[str] = []
    for entry in entries:
        entry_id = str(entry.get("id", "<unknown>"))
        missing = _REQUIRED_FIELDS - set(entry.keys())
        if missing:
            failures.append((
                entry_id,
                PdfFetchError(f"missing required fields: {sorted(missing)}"),
            ))
            continue
        if not entry.get("url"):
            failures.append((
                entry_id,
                PdfFetchError(
                    f"url for {entry_id} is empty or missing — populate "
                    f"sources.yaml before re-running."
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

    logger.info("succeeded: %d, failed: %d", len(succeeded), len(failures))
    if failures:
        msg_lines = [
            f"{len(failures)} of {len(entries)} PDF fetches failed:",
            *(f"  - {cid}: {exc}" for cid, exc in failures),
        ]
        raise PdfFetchError("\n".join(msg_lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
