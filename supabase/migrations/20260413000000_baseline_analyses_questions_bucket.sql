-- Baseline: the schema that existed before the first tracked migration, reconstructed
-- read-only from the live catalog on 2026-10-05. The live project already has all of it.
-- NEVER apply this file to the live project. Live migration history is intentionally untouched:
-- its two recorded versions (20260922035107, 20260927184255) differ from the local filenames.
CREATE TABLE IF NOT EXISTS public.analyses (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at          timestamptz DEFAULT now(),
  updated_at          timestamptz DEFAULT now(),
  original_filename   text NOT NULL,
  stored_filename     text NOT NULL,
  file_size           integer,
  status              text NOT NULL DEFAULT 'profiling',
  error_message       text,
  profile_report      jsonb,
  cleaning_report     jsonb,
  cleaning_decisions  jsonb,
  analysis_report     jsonb,
  insight_report      jsonb,
  executive_summary   jsonb,
  chart_paths         text[],
  row_count           integer,
  column_count        integer,
  data_quality_score  numeric,
  session_id          uuid DEFAULT gen_random_uuid(),
  user_pause_response jsonb
);
CREATE TABLE IF NOT EXISTS public.questions (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  analysis_id uuid REFERENCES public.analyses (id),
  created_at  timestamptz DEFAULT now(),
  question    text NOT NULL,
  answer      text,
  pandas_code text,
  status      text DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS idx_analyses_status ON public.analyses USING btree (status);
CREATE INDEX IF NOT EXISTS idx_analyses_created_at ON public.analyses USING btree (created_at);
CREATE INDEX IF NOT EXISTS idx_questions_analysis_id ON public.questions USING btree (analysis_id);
ALTER TABLE public.analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.questions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.analyses, public.questions FROM anon, authenticated;
INSERT INTO storage.buckets (id, name, public)
VALUES ('cleaned-datasets', 'cleaned-datasets', false)
ON CONFLICT (id) DO NOTHING;

-- DOWN (manual rollback) — NEVER RUN ON LIVE: it destroys every analysis and question.
-- DROP TABLE IF EXISTS public.questions;
-- DROP TABLE IF EXISTS public.analyses;
-- Bucket: empty it and delete it through the Storage API or dashboard (SQL deletes on storage tables are blocked).
