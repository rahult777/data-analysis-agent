-- Build K: close the Data API to the publishable (anon) key (errors.md 2026-09-21).
-- The backend uses only the secret key (service_role, BYPASSRLS), which keeps its grants.
-- Zero policies = no rows for anon/authenticated; the revokes also remove TRUNCATE
-- (not governed by RLS) and hide both tables from the GraphQL schema.
ALTER TABLE public.analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.questions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.analyses, public.questions FROM anon, authenticated;
-- Tables/sequences created later in public by postgres (i.e. by migrations) are not auto-granted.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;

-- DOWN (manual rollback) — restores the state recorded 2026-09-28:
-- ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON SEQUENCES TO anon, authenticated;
-- ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated;
-- GRANT ALL ON TABLE public.analyses, public.questions TO anon, authenticated;
-- ALTER TABLE public.questions DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE public.analyses DISABLE ROW LEVEL SECURITY;
