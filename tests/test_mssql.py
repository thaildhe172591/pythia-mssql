#!/usr/bin/env python3
"""Self-checks for pythia-mssql — no database, and no pymssql either: a
stand-in driver module records what the engine asks of it, and a stand-in
catalog answers by query file.

Needs pythia-core importable: installed, or a checkout next to this one
(../pythia-core), or PYTHIA_CORE_SRC pointing at its src/.

Run: python tests/test_mssql.py
"""
import contextlib
import io
import json
import os
import pathlib
import re
import sys
import tempfile
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
try:
    import pythia_core  # noqa: F401
except ModuleNotFoundError:
    for candidate in (os.environ.get("PYTHIA_CORE_SRC"),
                      ROOT.parent / "pythia-core" / "src"):
        if candidate and pathlib.Path(candidate).is_dir():
            sys.path.insert(1, str(candidate))
            break

from pythia_core.engine import engine_problems  # noqa: E402
from pythia_core.queries import contract_problems, query_binds  # noqa: E402

import pythia_mssql  # noqa: E402
from pythia_mssql import cli, read  # noqa: E402
from pythia_mssql.catalog import QUERY_BINDS, QUERY_DIR, fold, like_contains, sql_of  # noqa: E402
from pythia_mssql.engine import SqlServerEngine  # noqa: E402


def expect_exit(fn, *needles):
    try:
        fn()
    except SystemExit as e:
        msg = str(e).lower()
        for n in needles:
            assert n.lower() in msg, f"exit message missing {n!r}: {e}"
        return str(e)
    raise AssertionError("expected SystemExit, none raised")


# --- a stand-in for pymssql, and a catalog answered by query file -----------------

QUERY_TEXT = {sql_of(n): n for n in QUERY_BINDS}


class DriverError(Exception):
    pass


class CatalogCursor:
    def __init__(self, conn):
        self.conn, self.description, self._rows = conn, None, []

    def execute(self, sql, params=None):
        assert params is not None, "always pass a dict"
        name = QUERY_TEXT[sql]                 # only files from queries/
        self.conn.asked.append((name, dict(params)))
        answer = self.conn.answers[name]       # unscripted query: KeyError
        cols, rows = answer(params) if callable(answer) else answer
        self.description = [(c,) for c in cols]
        self._rows = list(rows)

    def fetchall(self):
        return list(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class CatalogConn:
    def __init__(self, answers):
        self.answers, self.asked = answers, []
        self.closed, self.commits = False, 0

    def cursor(self):
        return CatalogCursor(self)

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True

    def names(self):
        return [n for n, _ in self.asked]


BASIC = {
    "server-version.sql": (("version", "edition", "database_name"),
                           [("16.0.4305.5", "Developer Edition (64-bit)", "app")]),
    "current-schema.sql": (("current_schema",), [("app_owner",)]),
}


@contextlib.contextmanager
def fake_pymssql(answers=None, fail=None):
    """Install a stand-in pymssql; yields the record of what was asked."""
    record = {"connect": [], "conns": []}
    mod = types.ModuleType("pymssql")

    def connect(**kw):
        record["connect"].append(kw)
        if fail:
            raise fail
        conn = CatalogConn(dict(answers or BASIC))
        record["conns"].append(conn)
        return conn

    mod.Error, mod.connect = DriverError, connect
    saved, had = sys.modules.get("pymssql"), "pymssql" in sys.modules
    sys.modules["pymssql"] = mod
    try:
        yield record
    finally:
        if had:
            sys.modules["pymssql"] = saved
        else:
            del sys.modules["pymssql"]


@contextlib.contextmanager
def project(cfg):
    keep_env = {k: os.environ.pop(k) for k in list(os.environ)
                if k.startswith("PYTHIA_MSSQL_")}
    keep_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        path = pathlib.Path(td) / ".pythia" / "mssql" / "connections.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(cfg), encoding="utf-8")
        if os.name == "posix":
            os.chmod(path, 0o600)
        os.chdir(td)
        try:
            yield pathlib.Path(td)
        finally:
            os.chdir(keep_cwd)
            os.environ.update(keep_env)


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


DEV = {"dev": {"host": "localhost", "port": 1433, "database": "app",
               "user": "app_agent", "password": "s3cret", "schema": "app_owner"}}


# --- packaging -----------------------------------------------------------------------

def pyproject():
    return (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_version_matches_pyproject():
    declared = re.search(r'^version\s*=\s*"([^"]+)"', pyproject(), re.M).group(1)
    assert pythia_mssql.__version__ == declared == SqlServerEngine.version


def test_dependencies_are_core_and_the_driver_only():
    deps = re.search(r"^dependencies\s*=\s*\[(.*?)\]", pyproject(), re.M | re.S).group(1)
    names = {re.match(r"[A-Za-z0-9_.-]+", d.strip().strip('"')).group(0)
             for d in deps.split(",") if d.strip()}
    assert names == {"pythia-core", "pymssql"}, names


def test_console_script_is_pythia_mssql():
    assert 'pythia-mssql = "pythia_mssql.cli:main"' in pyproject()
    assert not re.search(r"^pythia\s*=", pyproject(), re.M)


# --- contracts -------------------------------------------------------------------------

def test_engine_answers_the_connect_and_read_tiers():
    assert engine_problems(SqlServerEngine(), tiers=("connect", "read")) == []


def test_query_contract_holds():
    assert contract_problems(QUERY_DIR, QUERY_BINDS, "pyformat") == []


def test_pymssql_sees_no_placeholder_but_the_binds():
    """pymssql never turns %% into %, so sql_of does — and pymssql reads
    any '%(' as the start of a placeholder, even inside a literal. After
    the adapter, '%(' may only ever open a declared bind."""
    for name in QUERY_BINDS:
        sql = sql_of(name)
        assert "%%" not in sql, name
        stray = re.sub(r"%\(([a-z_][a-z0-9_]*)\)s", "", sql)
        assert "%(" not in stray, f"{name}: pymssql would read '%(' as a placeholder"
        assert query_binds(sql, "pyformat") == QUERY_BINDS[name], name


def test_example_config_resolves_and_holds_no_secret():
    cfg = json.loads((ROOT / "examples" / "connections.example.json").read_text(encoding="utf-8"))
    assert cfg["default"] in cfg
    for name, entry in cfg.items():
        if name == "default":
            continue
        assert entry["password"] == ""
        assert {"host", "port", "database", "user", "schema", "encrypt"} <= set(entry)


# --- the engine ------------------------------------------------------------------------

def test_names_keep_their_case_and_lose_their_quoting():
    assert fold("[t_order]") == "t_order" and fold('"T_Order"') == "T_Order"
    assert fold("[a]]b]") == "a]b" and fold("t_order") == "t_order"
    e = SqlServerEngine()
    assert e.schema_of({"schema": "[app_owner]"}) == "app_owner"
    assert e.schema_of({"user": "u"}) == "dbo"


def test_like_patterns_escape_like_itself():
    assert like_contains("50%_off[x]") == "%50\\%\\_off\\[x]%"


def test_target_never_shows_the_password():
    e = SqlServerEngine()
    assert e.target_of(DEV["dev"]) == "localhost:1433/app"
    assert "s3cret" not in e.target_of(DEV["dev"])
    assert e.target_of({"host": "db"}) == "db:1433" and e.target_of({}) == ""


def test_connect_passes_exactly_the_settings():
    e = SqlServerEngine()
    with fake_pymssql() as rec:
        e.connect(dict(DEV["dev"], encrypt="require"))
        e.connect({"host": "h", "database": "d", "user": "u"})
    first, second = rec["connect"]
    assert first == {"server": "localhost", "port": "1433", "database": "app",
                     "user": "app_agent", "password": "s3cret", "autocommit": False,
                     "login_timeout": 10, "appname": "pythia-mssql",
                     "encryption": "require"}
    assert second["encryption"] == "request" and second["autocommit"] is False


def test_connect_refuses_a_half_filled_or_unknown_setting_before_the_driver():
    e = SqlServerEngine()
    with fake_pymssql() as rec:
        expect_exit(lambda: e.connect({"host": "h", "user": "u"}),
                    "'database'", ".pythia/mssql/connections.json")
        expect_exit(lambda: e.connect(dict(DEV["dev"], encrypt="yes")),
                    "off, request, require")
    assert rec["connect"] == []


def test_missing_driver_names_the_package():
    saved, had = sys.modules.get("pymssql"), "pymssql" in sys.modules
    sys.modules["pymssql"] = None
    try:
        expect_exit(SqlServerEngine().driver_errors, "pip install pymssql")
    finally:
        if had:
            sys.modules["pymssql"] = saved
        else:
            del sys.modules["pymssql"]


def failure(number, message):
    exc = DriverError(number, message.encode() + b"DB-Lib error message 20018, severity 16")
    return SqlServerEngine().connect_failure(exc, "dev", DEV["dev"])


def test_connect_failure_names_the_next_step():
    assert "Login failed for app_agent" in failure(18456, "Login failed for user 'app_agent'.")
    assert "CREATE USER [app_agent]" in failure(4060, 'Cannot open database "app".')
    assert "Nothing answered at localhost:1433/app" in failure(
        20009, "Unable to connect: Adaptive Server is unavailable or does not exist")
    assert "TLS handshake" in failure(20002, "SSL routines: handshake failure")
    generic = failure(50000, "something else")
    assert "host/port/database" in generic and "s3cret" not in generic
    assert "DB-Lib" not in generic                  # the driver's noise is cut


def test_error_text_reads_the_number_and_the_first_line():
    assert read.error_text(DriverError(207, b"Invalid column name 'total'.DB-Lib error "
                                            b"message 20018, severity 16:\nGeneral")) == \
        (207, "Invalid column name 'total'.")
    assert read.error_text(DriverError("no number")) == (None, "no number")


# --- end to end, through pythia-core ------------------------------------------------------

def test_check_end_to_end_and_reads_never_commit():
    with fake_pymssql() as rec, project(DEV):
        code, out, err = run("check", "--json")
    doc = json.loads(out)
    assert code == 0 and doc["schema"] == "app_owner" and doc["schema_drift"] is False
    assert {"ITEM": "server", "VALUE": "SQL Server 16.0.4305.5 (Developer Edition "
            "(64-bit)) — database app"} in doc["rows"]
    conn = rec["conns"][0]
    assert conn.closed is True and conn.commits == 0   # closing rolls it back


def test_check_reports_the_default_schema_drift():
    answers = dict(BASIC)
    answers["current-schema.sql"] = (("current_schema",), [("dbo",)])
    with fake_pymssql(answers), project(DEV):
        code, out, _ = run("check")
    assert code == 0 and "current schema is 'dbo'" in out


def test_check_turns_a_refused_login_into_advice():
    with fake_pymssql(fail=DriverError(18456, b"Login failed for user 'app_agent'.")), \
            project(DEV):
        expect_exit(lambda: run("check"), "login failed for app_agent")


def test_another_tools_config_is_not_ours():
    keep = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        for other in (".pythia/connections.json", ".pythia/postgres/connections.json"):
            path = pathlib.Path(td) / other
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"dev": {"user": "x"}}), encoding="utf-8")
        os.chdir(td)
        try:
            with fake_pymssql() as rec:
                expect_exit(lambda: run("check"), "no sql server connection")
            assert rec["connect"] == []
        finally:
            os.chdir(keep)


# --- the read tier ---------------------------------------------------------------------------

RESOLVE = ("objid", "type", "label", "bare_name")
T_ORDER = (10, "TABLE", "t_order", "t_order")
F_TOTAL = (20, "FUNCTION", "f_order_total", "f_order_total")
P_BROKEN = (30, "PROCEDURE", "p_broken", "p_broken")


def resolving(*objs):
    return lambda b: (RESOLVE, [o for o in objs if o[3] == b["n"]])


def test_source_numbers_lines_as_sql_server_keeps_them():
    conn = CatalogConn({"source.sql": (("unit", "definition"), [
        ("f_order_total", "create function f()\r\nreturns int as\r\nbegin return 1 end\r\n")])})
    rows = read.source(conn, "app_owner", "[f_order_total]")
    assert rows == [("f_order_total", 1, "create function f()"),
                    ("f_order_total", 2, "returns int as"),
                    ("f_order_total", 3, "begin return 1 end")]
    assert conn.asked == [("source.sql", {"s": "app_owner", "n": "f_order_total"})]
    unreadable = CatalogConn({"source.sql": (("unit", "definition"), [("p_secret", None)])})
    assert read.source(unreadable, "app_owner", "p_secret") == []


def test_grep_escapes_like_and_numbers_matching_lines():
    conn = CatalogConn({"grep.sql": (("unit", "type", "definition"), [
        ("f_a", "FUNCTION", "line one\nselect 50% off\nselect 50% OFF again"),
        ("f_b", "FUNCTION", "no match here")])})
    cols, rows = read.grep(conn, "app_owner", "50% off", 10)
    assert rows == [("f_a", "FUNCTION", 2, "select 50% off"),
                    ("f_a", "FUNCTION", 3, "select 50% OFF again")]
    assert conn.asked[0][1]["p"] == "%50\\% off%"
    assert len(read.grep(conn, "app_owner", "50% off", 1)[1]) == 1


def test_dependents_join_the_catalog_and_whole_word_text():
    tree = ("schema_name", "name", "type", "objid")
    conn = CatalogConn({
        "resolve.sql": resolving(T_ORDER),
        "dependents-catalog.sql": lambda b: (tree, [("app_owner", "f_order_total", "FUNCTION", 20)]
                                             if b["objid"] == 10 else []),
        "dependents-text.sql": lambda b: (tree + ("definition",), [
            ("app_owner", "p_dyn", "PROCEDURE", 40, "exec('select * from [t_order]')"),
            ("app_owner", "p_other", "PROCEDURE", 41, "select * from t_order_line"),
            ("app_owner", "f_order_total", "FUNCTION", 20, "from t_order")]
            if b["objid"] == 10 else [])})
    rows, blind = read.dependents(conn, "app_owner", "t_order", 2)
    assert rows == [(1, "app_owner", "f_order_total", "FUNCTION", "catalog"),
                    (1, "app_owner", "p_dyn", "PROCEDURE", "text")], rows
    assert any("dynamic SQL" in b for b in blind) and any("linked servers" in b for b in blind)
    assert conn.asked[2][1]["p"] == "%t\\_order%"
    assert read.dependents(CatalogConn({"resolve.sql": resolving()}), "app_owner", "nope", 2) is None


def test_errors_bind_each_module_and_name_what_is_missing():
    def check(b):
        if b["q"] == "[app_owner].[p_broken]":
            raise DriverError(2020, b"The dependencies reported ... might not include")
        if b["q"] == "[app_owner].[v_bad]":
            raise DriverError(207, b"Invalid column name 'total'.DB-Lib error message")
        return ("references_found",), [(1,)]
    mods = ("name", "type", "qualified_name", "has_dynamic_sql")
    conn = CatalogConn({
        "resolve.sql": resolving(T_ORDER, F_TOTAL, P_BROKEN),
        "modules.sql": lambda b: (mods, [
            ("f_order_total", "FUNCTION", "[app_owner].[f_order_total]", 0),
            ("p_broken", "PROCEDURE", "[app_owner].[p_broken]", 0),
            ("p_dyn", "PROCEDURE", "[app_owner].[p_dyn]", 1),
            ("v_bad", "VIEW", "[app_owner].[v_bad]", 0)] if b["n"] is None else
            [m for m in [("f_order_total", "FUNCTION", "[app_owner].[f_order_total]", 0)]
             if m[0] == b["n"]]),
        "referenced-check.sql": check,
        "unresolved.sql": (("missing",), [("app_owner.t_missing",)])})
    rows, blind = read.compile_errors(conn, "app_owner", None, DriverError)
    assert rows == [("p_broken", "PROCEDURE", None, None, "error",
                     "2020: references what does not exist: app_owner.t_missing"),
                    ("v_bad", "VIEW", None, None, "error",
                     "207: Invalid column name 'total'.")], rows
    assert "p_dyn" in blind and "dynamic SQL" in blind
    assert read.compile_errors(conn, "app_owner", "f_order_total", DriverError) == ([], None)
    rows, blind = read.compile_errors(conn, "app_owner", "t_order", DriverError)
    assert rows == [] and "not a view, procedure" in blind
    assert read.compile_errors(conn, "app_owner", "nope", DriverError) is None


def test_a_table_is_rebuilt_column_by_column_in_batches():
    conn = CatalogConn({
        "table-head.sql": (("q",), [("[app_owner].[t_order]",)]),
        "table-columns.sql": (("c",) * 11, [
            ("[id]", "bigint", False, "df_id", "(NEXT VALUE FOR [app_owner].[seq])",
             False, None, None, None, None, None),
            ("[line]", "int", False, None, None, True, "1", "1", None, None, None),
            ("[note]", "varchar(10)", True, None, None, False, None, None, None, None,
             "Latin1_General_BIN2"),
            ("[twice]", None, True, None, None, False, None, None, "([line]*(2))", True, None)]),
        "table-keys.sql": (("c",) * 6, [("[pk_t_order]", "PK", "CLUSTERED", "[id]", 1, False)]),
        "table-foreign-keys.sql": (("c",) * 6, [
            ("[fk_o]", "[id]", "[app_owner].[t_parent]", "[id]", "CASCADE", "NO_ACTION")]),
        "table-checks.sql": (("c",) * 2, [("[ck_line]", "([line]>(0))")]),
        "table-indexes.sql": (("c",) * 7, [
            ("[ix_note]", False, "NONCLUSTERED", "([note] IS NOT NULL)", "[note]", False, True),
            ("[ix_note]", False, "NONCLUSTERED", "([note] IS NOT NULL)", "[line]", True, False)]),
        "table-comments.sql": (("c",) * 4, [("app_owner", "t_order", None, "Orders, 'all'")]),
        "table-triggers.sql": (("d",), [("create trigger trg on t_order after update as select 1",)]),
    })
    ddl = read.table_ddl(conn, 10)
    assert ddl.split("\nGO\n")[0] == (
        "CREATE TABLE [app_owner].[t_order] (\n"
        "    [id] bigint NOT NULL CONSTRAINT [df_id] DEFAULT (NEXT VALUE FOR [app_owner].[seq]),\n"
        "    [line] int IDENTITY(1,1) NOT NULL,\n"
        "    [note] varchar(10) COLLATE Latin1_General_BIN2 NULL,\n"
        "    [twice] AS ([line]*(2)) PERSISTED,\n"
        "    CONSTRAINT [pk_t_order] PRIMARY KEY CLUSTERED ([id]),\n"
        "    CONSTRAINT [fk_o] FOREIGN KEY ([id]) REFERENCES [app_owner].[t_parent] ([id]) "
        "ON DELETE CASCADE,\n"
        "    CONSTRAINT [ck_line] CHECK ([line]>(0))\n);")
    assert "CREATE NONCLUSTERED INDEX [ix_note] ON [app_owner].[t_order] ([note] DESC) " \
           "INCLUDE ([line]) WHERE ([note] IS NOT NULL);" in ddl
    assert "@value = N'Orders, ''all'''" in ddl and ddl.endswith("select 1\nGO")


def main():
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except (Exception, SystemExit) as e:  # noqa: BLE001 — keep going
                failed += 1
                print(f"FAIL {name}: {e!r}")
    if failed:
        sys.exit(f"{failed} test(s) failed")
    print("OK")


if __name__ == "__main__":
    main()
