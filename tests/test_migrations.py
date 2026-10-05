"""Tests for supabase/migrations/ and the backend's Supabase key wiring (Build K).

These read files only: no network, no Supabase, no Anthropic calls. They pin what can
be checked without a database — that every table the backend uses has RLS enabled and
anon/authenticated privileges revoked by some migration, that the backend connects with
the secret key, and the migration conventions. The live state is verified separately
(decisions.md 2026-09-28, Build K).

All tests run from the project root, like the rest of the suite.
"""

import ast
import pathlib
import re

from backend import config

ROOT = pathlib.Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = ROOT / "supabase" / "migrations"
BACKEND_DIR = ROOT / "backend"


def migration_files() -> list[pathlib.Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def strip_sql_comments(sql: str) -> str:
    """Drop `--` comments, so the commented DOWN block never counts as applied SQL."""
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def sql_statements(sql: str) -> list[str]:
    """Split comment-free SQL into whitespace-normalized statements."""
    return [
        " ".join(statement.split())
        for statement in strip_sql_comments(sql).split(";")
        if statement.strip()
    ]


def table_name(identifier: str) -> str:
    """`public.analyses` / `"analyses"` / `analyses` -> `analyses`."""
    return identifier.strip().strip('"').split(".")[-1].strip('"').lower()


def backend_tables() -> set[str]:
    """Every table the backend reads or writes through `.table("...")`."""
    tables: set[str] = set()
    for path in BACKEND_DIR.rglob("*.py"):
        tables.update(re.findall(r"\.table\(\s*[\"']([A-Za-z_]+)[\"']\s*\)", path.read_text()))
    return tables


def rls_enabled_tables(statements: list[str]) -> set[str]:
    enabled: set[str] = set()
    for statement in statements:
        match = re.fullmatch(
            r"ALTER TABLE (?:IF EXISTS )?(?:ONLY )?(\S+) ENABLE ROW LEVEL SECURITY",
            statement,
            re.IGNORECASE,
        )
        if match:
            enabled.add(table_name(match.group(1)))
    return enabled


CLIENT_ROLES = {"anon", "authenticated"}


def target_tables(target: str, known: set[str]) -> set[str]:
    """The tables a GRANT/REVOKE target names; `ALL TABLES IN SCHEMA public` means all known."""
    if re.fullmatch(r"ALL TABLES IN SCHEMA public", target.strip(), re.IGNORECASE):
        return set(known)
    return {table_name(t) for t in re.sub(r"^TABLE ", "", target.strip(), flags=re.I).split(",")}


def final_table_states(known: set[str]) -> dict[str, dict[str, bool]]:
    """Each known table's state after every migration, applied in filename order.

    `rls` flips on ENABLE/DISABLE ROW LEVEL SECURITY. `locked` becomes true on a
    `REVOKE ALL` from both client roles and false again on any later GRANT of anything
    to anon, authenticated or PUBLIC (which includes both).
    """
    states = {table: {"rls": False, "locked": False} for table in known}
    for path in migration_files():
        for statement in sql_statements(path.read_text()):
            rls = re.fullmatch(
                r"ALTER TABLE (?:IF EXISTS )?(?:ONLY )?(\S+) (ENABLE|DISABLE) ROW LEVEL SECURITY",
                statement,
                re.IGNORECASE,
            )
            revoke = re.fullmatch(
                r"REVOKE ALL(?: PRIVILEGES)? ON (.+) FROM (.+)", statement, re.IGNORECASE
            )
            grant = re.fullmatch(r"GRANT .+? ON (.+) TO (.+)", statement, re.IGNORECASE)
            if rls and table_name(rls.group(1)) in states:
                states[table_name(rls.group(1))]["rls"] = rls.group(2).upper() == "ENABLE"
            elif revoke:
                grantees = {role.strip().lower() for role in revoke.group(2).split(",")}
                if CLIENT_ROLES <= grantees:
                    for table in target_tables(revoke.group(1), known) & states.keys():
                        states[table]["locked"] = True
            elif grant:
                grantees = {role.strip().lower() for role in grant.group(2).split(",")}
                if grantees & (CLIENT_ROLES | {"public"}):
                    for table in target_tables(grant.group(1), known) & states.keys():
                        states[table]["locked"] = False
    return states


def test_backend_table_scan_finds_the_known_tables() -> None:
    """Guards the scan itself: if it found nothing, the next test would pass vacuously."""
    assert {"analyses", "questions"} <= backend_tables()


def test_every_backend_table_ends_with_rls_enabled_and_client_roles_revoked() -> None:
    """Checks the state after the last migration, so a later GRANT or DISABLE fails it."""
    states = final_table_states(backend_tables())
    for table, state in sorted(states.items()):
        assert state["rls"], f"After all migrations, RLS is not enabled on public.{table}."
        assert state["locked"], (
            f"After all migrations, anon/authenticated are not fully revoked on public.{table}."
        )


def test_every_created_table_enables_rls_in_the_same_migration() -> None:
    for path in migration_files():
        statements = sql_statements(path.read_text())
        enabled = rls_enabled_tables(statements)
        for statement in statements:
            match = re.match(
                r"CREATE TABLE (?:IF NOT EXISTS )?(\S+?)\s*\(", statement, re.IGNORECASE
            )
            if match:
                assert table_name(match.group(1)) in enabled, (
                    f"{path.name} creates {match.group(1)} without enabling RLS on it."
                )


def test_every_migration_has_a_down_block() -> None:
    files = migration_files()
    assert files, "supabase/migrations/ holds no .sql files."
    for path in files:
        assert re.search(r"^-- DOWN\b", path.read_text(), re.MULTILINE), (
            f"{path.name} has no commented '-- DOWN' rollback block."
        )


def test_supabase_client_connects_with_the_secret_key() -> None:
    """RLS with zero policies only works for a key that bypasses it (service_role)."""
    source = (BACKEND_DIR / "utils" / "supabase_client.py").read_text()
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "create_client"
    ]
    assert len(calls) == 1
    key_arg = calls[0].args[1]
    assert isinstance(key_arg, ast.Name) and key_arg.id == "SUPABASE_SECRET_KEY"
    assert "PUBLISHABLE" not in source


def test_publishable_key_is_not_required_by_the_backend() -> None:
    assert "SUPABASE_PUBLISHABLE_KEY" not in config._REQUIRED_VARS
    assert not hasattr(config, "SUPABASE_PUBLISHABLE_KEY")


def test_openai_key_is_not_required_by_the_backend() -> None:
    assert "OPENAI_API_KEY" not in config._REQUIRED_VARS
    assert not hasattr(config, "OPENAI_API_KEY")
