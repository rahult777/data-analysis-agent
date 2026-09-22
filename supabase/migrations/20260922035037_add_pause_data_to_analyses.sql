-- Persists the active pause question so GET /status can return it (decisions.md 2026-05-18).
-- Non-null only while status is domain_pause / missing_value_pause / outlier_pause.
ALTER TABLE public.analyses ADD COLUMN IF NOT EXISTS pause_data jsonb;

-- DOWN (manual rollback):
-- ALTER TABLE public.analyses DROP COLUMN IF EXISTS pause_data;
