"""HuntReady ingestion pipeline.

Upstream and offline — writes structured records to Supabase Postgres.
The TypeScript serving stack never imports from this package.

See ADR-003 (ingestion upstream and offline) and ADR-005 (Python for ingestion).
"""
