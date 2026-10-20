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



# --- the write tier: reading T-SQL, without a database -----------------------------

from pythia_mssql import write  # noqa: E402


def test_the_reader_knows_t_sql_quoting():
    text = ("create procedure p as\n"
            "begin\n  select 'a;b', N'it''s; ok', [semi;colon], \"q;uoted\" -- not a cut ;\n"
            "end; /* outer /* nested ; */ still comment ; */\n"
            "select 2;")
    lexed = write.lex(text)
    assert not lexed.unterminated
    masked = lexed.masked
    assert len(masked) == len(text)
    for hidden in ("a;b", "it", "semi", "uoted", "not a cut", "nested", "still"):
        assert hidden not in masked, hidden
    assert write.lex("select 'open").unterminated
    assert write.lex("select [open").unterminated
    assert write.lex("/* open /* nested */").unterminated
    assert write.lex("select N'x' + n'y'").masked.count("'") == 4    # quotes stay, contents go


def test_a_script_splits_at_go_and_a_module_takes_its_whole_batch():
    script = ("-- release 7\n"
              "create or alter procedure app_owner.p_one as\n"
              "begin\n  update t set x = 1; -- inside the body\n  select 1;\nend\n"
              "GO\n"
              "alter table t add note nvarchar(40);\n"
              "update t set note = N'go; here' where id = 1;\n"
              "go 1\n"
              "  GO  \n"
              "exec sys.sp_addextendedproperty @name = N'MS_Description', @value = N'GO',\n"
              "  @level0type = N'SCHEMA', @level0name = N'app_owner', @level1type = N'TABLE', @level1name = N't'\n"
              "GO\n")
    got = write.split_script(script)
    assert [line for line, _ in got] == [2, 8, 9, 12], got
    assert got[0][1].startswith("-- release 7\ncreate or alter procedure") and got[0][1].endswith("end")
    assert got[2][1] == "update t set note = N'go; here' where id = 1"
    assert [write.classify(t)[0] for _, t in got] == ["source", "structural", "data_dml", "comments"]
    assert write.split_script("-- only a comment\nGO\n") == []
    assert write.split_script("select 'GO\nGO'") == [(1, "select 'GO\nGO'")]   # GO in a string


def classified(text):
    return write.classify(text)[0]


def refusal(text):
    group, why = write.classify(text)
    assert group is None, (text, group)
    return why


def test_classify_sorts_every_statement_or_says_why_not():
    assert classified("CREATE PROCEDURE app_owner.p AS SELECT 1") == "source"
    assert classified("create or alter function dbo.f() returns int as begin return 1 end") == "source"
    assert classified("-- header\nALTER VIEW v AS SELECT 1 AS x") == "source"
    assert classified("create trigger trg on t after insert as select 1") == "source"
    assert classified("create proc p as select 1") == "source"
    assert classified("exec sys.sp_addextendedproperty @name = N'MS_Description', @value = N'x', "
                      "@level0type = N'SCHEMA', @level0name = N'dbo', @level1type = N'TABLE', "
                      "@level1name = N't'") == "comments"
    assert classified("EXECUTE sp_updateextendedproperty @name = N'MS_Description', @value = N'y', "
                      "@level0type = N'SCHEMA', @level0name = N'dbo', @level1type = N'TABLE', "
                      "@level1name = N't'") == "comments"
    assert classified("exec sp_rename 'dbo.t.old', 'new', 'COLUMN'") == "structural"
    assert classified("UPDATE t_order SET status = 'PAID' WHERE id = 1") == "data_dml"
    assert classified("insert into t_order (id) values (1)") == "data_dml"
    assert classified("alter table t_order add note nvarchar(40)") == "structural"
    assert classified("create table t (id int)") == "structural"
    assert classified("drop procedure p") == "structural"
    assert classified("truncate table t_order") == "structural"
    assert classified("create index ix on t (id)") == "structural"
    assert classified("grant select on t_order to app_ro") == "grants"
    assert classified("deny delete on t_order to app_ro") == "grants"
    assert classified("alter role db_datareader add member app_ro") == "grants"
    assert classified("create user app_ro for login app_ro") == "grants"
    assert classified("set ansi_warnings on") == "session"
    assert "owns the transaction" in refusal("begin tran")
    assert "owns the transaction" in refusal("commit transaction")
    assert "owns the transaction" in refusal("set transaction isolation level serializable")
    assert "control flow" in refusal("if 1 = 1 delete from t")
    assert "control flow" in refusal("declare @x int = 1")
    assert "control flow" in refusal("begin delete from t; end")
    assert "procedure's body" in refusal("exec dbo.p_settle")
    assert "MS_Description" in refusal(
        "exec sp_addextendedproperty @name = N'Owner', @value = N'x', @level0type = N'SCHEMA', "
        "@level0name = N'dbo', @level1type = N'TABLE', @level1name = N't'")
    assert "named" in refusal("exec sp_addextendedproperty N'MS_Description', N'x', N'SCHEMA', N'dbo'")
    assert "database" in refusal("use other_db")
    assert "reads" in refusal("select * from t")
    assert "WITH" in refusal("with x as (select 1 as a) delete from t")
    assert "inside a transaction" in refusal("alter database app set recovery simple")
    assert "inside a transaction" in refusal("backup database app to disk = 'x'")
    assert "inside a transaction" in refusal("create fulltext index on t (c) key index pk")
    assert "server" in refusal("create login l with password = 'x'")
    assert "temporary" in refusal("create table #t (x int)")
    assert "one statement per file" in refusal("insert into t values (1); insert into t values (2);")
    assert "one statement per file" in refusal("insert into t values (1)\ndelete from t where id = 2")
    assert "one statement per file" in refusal("alter table t add c int\ndrop table u")
    assert classified("alter table t add c int,\n  d int") == "structural"
    assert classified("alter table t\n  drop column c") == "structural"
    assert classified("alter table t\n  alter column c bigint") == "structural"
    assert classified("update t\nset x = 1\nwhere id in (select id from u)") == "data_dml"
    assert classified("insert into t (id)\nselect id from u") == "data_dml"
    assert "GO" in refusal("create procedure p as select 1\nGO\nselect 2")
    assert "ends inside" in refusal("create procedure p as select 'open")
    assert "no statement" in refusal("-- only a comment\n")
    assert "Cannot classify" in refusal("dbcc checkdb")


def test_parse_object_reads_the_name_as_sql_server_would():
    p = write.parse_object
    assert p("CREATE OR ALTER PROCEDURE [App_Owner].[P_Total] @x int AS SELECT 1", "source") == \
        {"type": "PROCEDURE", "name": "P_Total", "schema": "App_Owner"}
    assert p("create proc p_a as select 1", "source") == \
        {"type": "PROCEDURE", "name": "p_a", "schema": None}
    assert p('alter view "v x" as select 1', "source")["name"] == "v x"
    assert p("create trigger app_owner.trg on app_owner.t after update as select 1",
             "source") == {"type": "TRIGGER", "name": "trg", "schema": "app_owner"}
    assert p("create function dbo.f() returns int as begin return 1 end", "source")["type"] == "FUNCTION"
    col = p("exec sys.sp_updateextendedproperty @name = N'MS_Description', @value = N'it''s', "
            "@level0type = N'SCHEMA', @level0name = N'app_owner', @level1type = N'TABLE', "
            "@level1name = N't_order', @level2type = N'COLUMN', @level2name = N'status'", "comments")
    assert col == {"type": "COMMENT", "name": "t_order.status", "schema": "app_owner",
                   "table": "t_order", "column": "status", "kind": "TABLE",
                   "value": "it's", "verb": "update"}
    tab = p("exec sp_addextendedproperty @name = N'MS_Description', @value = N'x', "
            "@level0type = N'SCHEMA', @level0name = N'dbo', @level1type = N'VIEW', "
            "@level1name = N'v_x'", "comments")
    assert (tab["name"], tab["kind"], tab["column"], tab["verb"]) == ("v_x", "VIEW", None, "add")
    assert p("delete from t_order where id = 1", "data_dml") is None


def test_dml_probe_finds_the_rows_or_refuses_to_guess():
    probe = write.dml_probe
    assert probe("update [app_owner].[t_order] set status = 'PAID' where id < 3") == \
        ("[app_owner].[t_order]", "id < 3")
    assert probe("delete from app_owner.t_order where status = 'x;y'") == \
        ("app_owner.t_order", "status = 'x;y'")
    assert probe("delete t_order") == ("t_order", None)
    assert probe("delete from t_order -- all?\n where id = 1 -- one") == ("t_order", "id = 1")
    assert probe("insert into t_order (id) values (1)") is None
    for stmt, why in (
            ("merge t using s on t.id = s.id when matched then delete;", "MERGE"),
            ("update t set x = s.x from s where t.id = s.id", "FROM"),
            ("delete t from t join s on s.id = t.id", "FROM"),
            ("update top (10) t set x = 1", "TOP"),
            ("delete from t output deleted.id where id = 1", "OUTPUT"),
            ("delete from t where id in (select id from s)", "subquery"),
            ("update t set x = 1 where current of c", "CURRENT OF"),
            # the probe runs `where (<predicate>)` before approval: a predicate
            # that closes the parenthesis would add a statement of its own
            ("delete from t where id = 1) update x set v = 1 where (1 = 1", "parentheses"),
            ("delete from t where (id = 1", "parentheses")):
        try:
            probe(stmt)
        except SystemExit as e:
            assert why in str(e), (stmt, str(e))
        else:
            raise AssertionError(f"probe guessed at: {stmt}")


class TextConn:
    """Answers the text pythia runs with no binds: the row-set probes."""

    def __init__(self, count=2, fingerprint=-5, sample=((1, "DRAFT"), (2, "DRAFT")), fail=None):
        self.count, self.fingerprint, self.sample, self.fail = count, fingerprint, sample, fail
        self.ran = []

    def cursor(self):
        conn = self

        class Cursor(CatalogCursor):
            def execute(self, sql, params=None):
                assert params is None, "statement text runs with no binds"
                conn.ran.append(sql)
                self.rowcount = -1
                if conn.fail:
                    raise DriverError(208, b"Invalid object name 't_nope'.DB-Lib error")
                if "checksum_agg" in sql:
                    self.description, self._rows = [("ROW_COUNT",), ("FINGERPRINT",)], [
                        (conn.count, conn.fingerprint)]
                else:
                    self.description, self._rows = [("id",), ("status",)], list(conn.sample)
        return Cursor(conn)


def test_the_row_set_is_measured_or_refused():
    conn = TextConn()
    got = write.measure_row_set(conn, "[app_owner].[t_order]", "status = '50%'")
    assert (got["count"], got["hash"], got["columns"]) == (2, "-5", ["ID", "STATUS"])
    assert got["sample"] == [["1", "DRAFT"], ["2", "DRAFT"]] and got["truncated"] is False
    assert all("from [app_owner].[t_order] where (status = '50%')" in sql for sql in conn.ran)
    got = write.measure_row_set(TextConn(sample=[(i, "x") for i in range(11)]), "t", None)
    assert len(got["sample"]) == 10 and got["truncated"] is True and got["predicate"] == ""
    expect_exit(lambda: write.measure_row_set(TextConn(fail=True), "t_nope", "id = 1"),
                "could not measure", "Invalid object name 't_nope'", "Revalidation is mandatory")


def test_a_snapshot_is_the_definition_or_a_refusal():
    proc = {"type": "PROCEDURE", "name": "p_total", "schema": None}
    head = ("objid", "definition")
    conn = CatalogConn({"module-definition.sql": (head, [(7, "create procedure p_total as select 1")])})
    assert write.snapshot(conn, "app_owner", "source", proc) == {
        "p_total": "create procedure p_total as select 1"}
    assert conn.asked == [("module-definition.sql", {"q": "[app_owner].[p_total]"})]
    conn = CatalogConn({"module-definition.sql": (head, [(None, None)])})
    assert write.snapshot(conn, "app_owner", "source", proc) == {}          # a new object
    conn = CatalogConn({"module-definition.sql": (head, [(7, None)])})
    expect_exit(lambda: write.snapshot(conn, "app_owner", "source", proc),
                "WITH ENCRYPTION", "nothing to snapshot")
    col = {"type": "COMMENT", "name": "t_order.status", "schema": "app_owner",
           "table": "t_order", "column": "status"}
    conn = CatalogConn({"comment-current.sql": (("comment",), [("DRAFT until paid",)])})
    assert write.snapshot(conn, "app_owner", "comments", col) == {"t_order.status": "DRAFT until paid"}
    assert conn.asked == [("comment-current.sql", {"s": "app_owner", "t": "t_order", "c": "status"})]
    conn = CatalogConn({"comment-current.sql": (("comment",), [])})
    assert write.snapshot(conn, "app_owner", "comments", col) == {}
    assert write.snapshot(conn, "app_owner", "data_dml", None) == {}


def test_a_login_that_can_do_far_more_is_named():
    def power(sysadmin, owner):
        conn = CatalogConn({"session-power.sql": (("is_sysadmin", "is_db_owner", "login_name"),
                                                   [(sysadmin, owner, "app_deploy")])})
        return write.privilege_warning(conn, "app_owner")
    assert "sysadmin" in power(1, 1) and "app_deploy" in power(1, 1)
    assert "db_owner" in power(0, 1)
    assert power(0, 0) is None


def test_destruction_is_named():
    d = write.destructive_reason
    assert d("drop table t_order", "structural").startswith("DROP removes")
    assert "TRUNCATE" in d("truncate table t_order", "structural")
    assert "column or constraint" in d("alter table t drop column x", "structural")
    assert "type" in d("alter table t alter column x bigint", "structural")
    assert "sp_rename" in d("exec sp_rename 'dbo.t', 't2'", "structural")
    assert "every row" in d("delete from t_order", "data_dml")
    assert "every row" in d("update t_order set x = 1", "data_dml")
    assert "always true" in d("update t set x = 1 where 1 = 1", "data_dml")
    assert d("delete from t where id = 1", "data_dml") is None
    assert "REVOKE" in d("revoke select on t from app_ro", "grants")
    assert "DENY" in d("deny select on t to app_ro", "grants")
    assert "public" in d("grant select on t to public", "grants")
    assert d("exec sp_addextendedproperty @name = N'MS_Description', @value = N'drop table x'",
             "comments") is None


def test_restore_puts_back_or_drops():
    r = write.restore_statement
    proc = {"type": "PROCEDURE", "name": "p_total", "schema": None}
    assert r("source", proc, "-- head\nCREATE PROCEDURE app_owner.p_total AS\nSELECT 1", {}) == \
        "-- head\nCREATE OR ALTER PROCEDURE app_owner.p_total AS\nSELECT 1"
    assert r("source", proc, "create or alter procedure p as select 1", {}) == \
        "create or alter procedure p as select 1"
    assert r("source", proc, "", {"drop": "[app_owner].[p_total]"}) == \
        "DROP PROCEDURE [app_owner].[p_total]"
    view = {"type": "VIEW", "name": "v_x", "schema": None}
    assert r("source", view, "", {"drop": "[app_owner].[v_x]"}) == "DROP VIEW [app_owner].[v_x]"
    com = {"type": "COMMENT", "name": "t_order.status", "schema": "app_owner",
           "table": "t_order", "column": "status", "kind": "TABLE"}
    assert r("comments", com, "it's", {"schema": "app_owner"}) == (
        "EXEC sys.sp_updateextendedproperty @name = N'MS_Description', @value = N'it''s', "
        "@level0type = N'SCHEMA', @level0name = N'app_owner', @level1type = N'TABLE', "
        "@level1name = N't_order', @level2type = N'COLUMN', @level2name = N'status'")
    assert r("comments", com, "", {"schema": "app_owner"}).startswith(
        "EXEC sys.sp_dropextendedproperty @name = N'MS_Description', @level0type")
    assert write.classify(r("comments", com, "", {"schema": "app_owner"}))[0] == "comments"
    assert r("comments", com, "x", {"schema": "app_owner", "exists_after": False}).startswith(
        "EXEC sys.sp_addextendedproperty @name = N'MS_Description', @value = N'x'")


def test_the_changed_object_is_read_from_the_statement():
    c = write.changed_object
    assert c("alter table [App_Owner].[T_Order] drop column note", "structural", None,
             "app_owner") == ("App_Owner", "T_Order")
    assert c("drop table if exists t_old", "structural", None, "app_owner") == ("app_owner", "t_old")
    assert c("drop view reporting.v_paid", "structural", None, "app_owner") == ("reporting", "v_paid")
    assert c("create unique nonclustered index ix on app_owner.t_order (status)", "structural",
             None, "dbo") == ("app_owner", "t_order")
    assert c("truncate table t_order", "structural", None, "app_owner") == ("app_owner", "t_order")
    assert c("exec sp_rename 'app_owner.t_order.note', 'remark', 'COLUMN'", "structural",
             None, "dbo") == ("app_owner", "t_order")
    assert c("exec sp_rename N't_order', 't_orders'", "structural", None, "app_owner") == \
        ("app_owner", "t_order")
    assert c("create table t (id int)", "structural", None, "app_owner") is None
    proc = {"type": "PROCEDURE", "name": "p_a", "schema": None}
    assert c("create proc p_a as select 1", "source", proc, "app_owner") == ("app_owner", "p_a")


class TxnConn:
    """A session with SQL Server's nested transactions, as the driver spike
    measured them: @@TRANCOUNT, the transaction's id, and a trigger whose
    COMMIT ends one level (committing only at the outermost) and whose
    ROLLBACK ends them all. Error 3609 when it leaves @@TRANCOUNT at 0."""

    def __init__(self, trigger=(), triggers=(), fail=None, ids=True):
        self.count, self.txn = 1, 100 if ids else None
        self.ids = iter(range(101, 200)) if ids else iter(lambda: None, 0)
        self.trigger, self.triggers, self.fail = list(trigger), list(triggers), fail
        self.committed, self.ran = False, []

    def cursor(self):
        return TxnCursor(self)

    def statement(self, sql):
        self.ran.append("STATEMENT")
        for action in self.trigger:
            if action == "commit":
                self.count -= 1
                if self.count == 0:
                    self.committed, self.txn = True, next(self.ids)
            elif action == "rollback":
                self.count, self.txn = 0, next(self.ids)
            elif action == "begin":
                if self.count == 0:
                    self.txn = next(self.ids)
                self.count += 1
        if self.fail:
            if self.fail[0] == 1205:          # a deadlock victim: SQL Server rolls back
                self.count, self.txn = 0, next(self.ids)
            raise DriverError(*self.fail)     # a trigger's own error comes first
        if self.count == 0:
            raise DriverError(3609, b"The transaction ended in the trigger. The batch "
                              b"has been aborted.DB-Lib error message 20018, severity 16")
        return 2


class TxnCursor(CatalogCursor):
    def execute(self, sql, params=None):
        self.description, self._rows, self.rowcount = None, [], -1
        name = QUERY_TEXT.get(sql)
        if name is None:
            self.rowcount = self.conn.statement(sql)
            return
        self.conn.ran.append(name)
        if name == "rehearsal-begin.sql":
            self.conn.count += 1
        elif name == "rehearsal-level-up.sql":
            self.conn.count = min(self.conn.count, 1)
        elif name == "transaction-state.sql":
            self.description, self._rows = [("TRANCOUNT",), ("TXN",)], [
                (self.conn.count, self.conn.txn)]
        elif name == "triggers-enabled.sql":
            self.description = [("SCHEMA_NAME",), ("TRIGGER_NAME",), ("DEFINITION",)]
            self._rows = self.conn.triggers


DML = "update app_owner.t_order set status = 'PAID' where id = 1"
AUDIT = ("app_owner", "trg_order_audit",
         "create trigger trg_order_audit on t_order after update as insert t_order_audit "
         "select id from inserted -- never commit here")


def rehearse_dml(conn):
    return write.rehearse(conn, "app_owner", "data_dml", DML, None, {}, DriverError)


def test_a_rehearsal_runs_one_level_down_and_comes_back_up():
    conn = TxnConn(triggers=[AUDIT])
    out = rehearse_dml(conn)
    assert out["error"] is None and "escaped" not in out and out["rows"] == 2
    assert conn.ran.index("rehearsal-begin.sql") < conn.ran.index("STATEMENT") \
        < conn.ran.index("rehearsal-level-up.sql")
    assert conn.count == 1 and not conn.committed           # core's level, still open
    conn = TxnConn(fail=(547, b"The UPDATE statement conflicted with the CHECK constraint"))
    out = rehearse_dml(conn)
    assert out["error"].startswith("547: The UPDATE statement conflicted")
    assert "escaped" not in out and "triggers-enabled.sql" not in conn.ran


def test_a_trigger_that_commits_once_commits_nothing():
    conn = TxnConn(trigger=["commit"], triggers=[AUDIT])
    out = rehearse_dml(conn)
    assert out["error"] is None and "escaped" not in out
    assert not conn.committed and conn.count == 1
    assert any("3609" in n and "COMMIT" in n for n in out["notes"]), out["notes"]
    conn = TxnConn(trigger=["commit", "begin"])
    assert "escaped" not in rehearse_dml(conn) and not conn.committed


def test_a_trigger_that_commits_past_the_rehearsal_is_reported_escaped():
    committer = ("app_owner", "trg_settle",
                 "create trigger trg_settle on t_order after update as "
                 "while @@trancount > 0 commit")
    for trigger in (["commit", "commit"], ["commit", "commit", "begin"]):
        conn = TxnConn(trigger=trigger, triggers=[AUDIT, committer])
        out = rehearse_dml(conn)
        assert conn.committed, trigger
        assert out.get("escaped") and "trg_settle" in out["escaped"], (trigger, out)
        assert "trg_order_audit" not in out["escaped"]       # its COMMIT is a comment
    out = rehearse_dml(TxnConn(trigger=["commit", "commit"]))
    assert out.get("escaped")                                  # a commit nobody can name
    out = rehearse_dml(TxnConn(trigger=["commit", "commit"], triggers=[committer], ids=False))
    assert out.get("escaped"), out          # the depth alone tells, with no transaction id


def test_a_trigger_that_rolls_back_wrote_nothing_unless_one_could_commit():
    guard = ("app_owner", "trg_guard", "create trigger trg_guard on t_order after update "
             "as if exists (select 1 from inserted where total < 0) rollback")
    out = rehearse_dml(TxnConn(trigger=["rollback"], triggers=[AUDIT, guard]))
    assert "escaped" not in out
    assert "3609" in out["error"] and "rolled the statement back" in out["error"]
    assert "nothing was written" in out["error"]
    for doubt, needle in (
            (("app_owner", "trg_x", None), "trg_x (its text cannot be read)"),
            (("app_owner", "trg_y", "create trigger trg_y on t after update as "
              "exec app_owner.p_audit"), "trg_y"),
            (("", "ddl_watch", "create trigger ddl_watch on database for create_table "
              "as exec sp_executesql N'commit'"), "ddl_watch")):
        out = rehearse_dml(TxnConn(trigger=["rollback"], triggers=[guard, doubt]))
        assert out.get("escaped") and needle in out["escaped"], (doubt, out)
    out = rehearse_dml(TxnConn(fail=(1205, b"Transaction was deadlocked"), triggers=[AUDIT]))
    assert "escaped" not in out and "rolled the deadlock victim's" in out["error"]
    out = rehearse_dml(TxnConn(trigger=["rollback"], triggers=[AUDIT],
                               fail=(50000, b"v too large")))
    assert "explains it" in out.get("escaped", ""), out       # a THROW after a COMMIT?
    out = rehearse_dml(TxnConn(trigger=["rollback"], triggers=[guard],
                               fail=(50000, b"total below zero")))
    assert "escaped" not in out and out["error"].startswith("50000: total below zero")
    out = rehearse_dml(TxnConn(trigger=["rollback"], triggers=[AUDIT]))
    assert "explains it" in out.get("escaped", ""), out       # no visible trigger rolls back
    conn = TxnConn(trigger=["rollback"], triggers=[guard])
    conn.cursor = lambda: (_ for _ in ()).throw(DriverError(10054, b"connection reset")) \
        if conn.ran.count("STATEMENT") else TxnCursor(conn)
    assert rehearse_dml(conn).get("escaped")                    # a dead session: cannot tell


def test_an_escaped_outcome_still_says_how_to_restore():
    ident = write.parse_object(
        "exec sys.sp_updateextendedproperty @name = N'MS_Description', @value = N'x', "
        "@level0type = N'SCHEMA', @level0name = N'app_owner', @level1type = N'TABLE', "
        "@level1name = N't_order'", "comments")
    stmt = ("exec sys.sp_updateextendedproperty @name = N'MS_Description', @value = N'x', "
            "@level0type = N'SCHEMA', @level0name = N'app_owner', @level1type = N'TABLE', "
            "@level1name = N't_order'")
    conn = TxnConn(trigger=["commit", "commit"])
    out = write.rehearse(conn, "app_owner", "comments", stmt, ident, {"t_order": "old"},
                         DriverError)
    assert out.get("escaped")
    assert write.restore_statement("comments", ident, "old", out).startswith(
        "EXEC sys.sp_updateextendedproperty @name = N'MS_Description', @value = N'old'")
    stmt = ("exec sys.sp_dropextendedproperty @name = N'MS_Description', "
            "@level0type = N'SCHEMA', @level0name = N'app_owner', @level1type = N'TABLE', "
            "@level1name = N't_order'")
    ident = write.parse_object(stmt, "comments")
    out = write.rehearse(TxnConn(trigger=["commit", "commit"]), "app_owner", "comments",
                         stmt, ident, {"t_order": "old"}, DriverError)
    assert write.restore_statement("comments", ident, "old", out).startswith(
        "EXEC sys.sp_addextendedproperty @name = N'MS_Description', @value = N'old'")


def test_the_engine_answers_the_write_tier():
    assert engine_problems(SqlServerEngine(), tiers=("connect", "read", "write")) == []
    from pythia_core import policy
    notes = SqlServerEngine.rollback_notes
    assert set(notes) == set(policy.GROUPS) and all(notes.values()), notes
    assert notes["data_dml"].startswith("No") and notes["source"].startswith("Yes")


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
