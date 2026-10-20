#!/usr/bin/env python3
"""pythia-mssql against a real SQL Server — a disposable one only.

1. Always (when PYTHIA_MSSQL_LIVE_HOST is set): connect and `check`.
2. With PYTHIA_MSSQL_LIVE_DISPOSABLE=1 only: the database pythia_live is
   dropped and created, tests/fixtures/app_owner.sql is loaded into it, a
   login pythia_agent is made (db_datareader, VIEW DEFINITION, default
   schema app_owner), and every read command runs through the command line
   as that login.
3. Then the fixture is loaded again, the login may write (db_datawriter,
   db_ddladmin), and every write path runs through the gate: preview,
   approve, confirm and restore; a new object undone by a DROP; rows that
   move; a comment; a DROP COLUMN that breaks a view, a verification that
   moved, written-but-broken; and triggers that COMMIT or ROLLBACK inside
   the rehearsal. Then a release in GO batches through `deploy`, a lint
   error in a real preview, and a write under an autopilot lease.

Never point this at a shared server: it creates a login and drops a
database. Skipped unless PYTHIA_MSSQL_LIVE_HOST is set:

    PYTHIA_MSSQL_LIVE_HOST=127.0.0.1 PYTHIA_MSSQL_LIVE_PORT=1433 \\
    PYTHIA_MSSQL_LIVE_USER=sa PYTHIA_MSSQL_LIVE_PASSWORD=... \\
    PYTHIA_MSSQL_LIVE_DISPOSABLE=1 python tests/live_check.py
"""
import contextlib
import io
import json
import os
import pathlib
import re
import secrets
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
for candidate in (os.environ.get("PYTHIA_CORE_SRC"), ROOT.parent / "pythia-core" / "src"):
    if candidate and pathlib.Path(candidate).is_dir():
        sys.path.insert(1, str(candidate))
        break

DB = "pythia_live"
AGENT = "pythia_agent"


def ok(what):
    print(f"PASS {what}")


def admin_entry():
    env = os.environ
    return {"host": env["PYTHIA_MSSQL_LIVE_HOST"],
            "port": int(env.get("PYTHIA_MSSQL_LIVE_PORT") or 1433),
            "user": env.get("PYTHIA_MSSQL_LIVE_USER") or "sa",
            "password": env["PYTHIA_MSSQL_LIVE_PASSWORD"]}


@contextlib.contextmanager
def admin(entry, database="master"):
    import pymssql
    conn = pymssql.connect(server=entry["host"], port=str(entry["port"]),
                           user=entry["user"], password=entry["password"],
                           database=database, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


def batches(script):
    """The batches of a script, cut at GO lines as sqlcmd cuts them."""
    return [b.strip() for b in re.split(r"(?im)^\s*go\s*$", script) if b.strip()]


def run_batches(entry, database, script):
    with admin(entry, database) as conn:
        cur = conn.cursor()
        for batch in batches(script):
            cur.execute(batch)


def scalar(entry, sql, database=DB):
    with admin(entry, database) as conn:
        cur = conn.cursor()
        cur.execute(sql)
        row = cur.fetchone()
        return row[0] if row else None


class Project:
    """A project folder whose connection is the agent login: the journal and
    the grants outlive a single command."""

    def __init__(self, entry):
        self.td = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.td.name)
        self.state = state = self.root / ".pythia" / "mssql"
        state.mkdir(parents=True)
        path = state / "connections.json"
        path.write_text(json.dumps({"live": entry}), encoding="utf-8")
        if os.name == "posix":
            os.chmod(path, 0o600)

    def run(self, *argv):
        """(exit code, stdout, the refusal message or '')"""
        from pythia_mssql import cli
        keep = os.getcwd()
        os.chdir(self.root)
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out), \
                    contextlib.redirect_stderr(io.StringIO()):
                code, why = cli.main(list(argv)) or 0, ""
        except SystemExit as e:
            code, why = (e.code, "") if isinstance(e.code, int) else (1, str(e))
        finally:
            os.chdir(keep)
        return code, out.getvalue(), why

    def json(self, *argv):
        code, out, why = self.run(*argv, "--json")
        assert code == 0, (argv, why, out)
        return json.loads(out.strip().splitlines()[-1])

    def file(self, name, text):
        (self.root / name).write_text(text, encoding="utf-8")
        return name

    def preview(self, name, text):
        return self.json("apply", self.file(name, text))

    def approve(self, token):
        """The developer's own act, at their own console."""
        from pythia_core import human
        human.FORCE_CONSOLE = True
        try:
            code, _, why = self.run("approve", token)
            assert code == 0, why
        finally:
            human.FORCE_CONSOLE = False

    def confirm(self, *argv):
        """(exit code, the last JSON line or None, the refusal)"""
        code, out, why = self.run(*argv, "--json")
        lines = out.strip().splitlines()
        return code, (json.loads(lines[-1]) if lines and lines[-1].startswith("{")
                      else None), why

    def policy(self, **groups):
        (self.state / "policy.json").write_text(json.dumps(groups), encoding="utf-8")


def check_connect(entry):
    p = Project(dict(entry, database="master", schema="dbo"))
    doc = p.json("check")
    server = {r["ITEM"]: r["VALUE"] for r in doc["rows"]}["server"]
    assert server.startswith("SQL Server ") and "database master" in server, server
    ok(f"check: {server}")


def load_fixture(entry):
    with admin(entry) as conn:
        cur = conn.cursor()
        cur.execute(f"if db_id('{DB}') is not null begin "
                    f"alter database [{DB}] set single_user with rollback immediate; "
                    f"drop database [{DB}]; end")
        cur.execute(f"create database [{DB}]")
    run_batches(entry, DB, (ROOT / "tests" / "fixtures" / "app_owner.sql")
                .read_text(encoding="utf-8"))
    password = "Agent#" + secrets.token_hex(8)
    with admin(entry) as conn:
        cur = conn.cursor()
        cur.execute(f"if suser_id('{AGENT}') is not null drop login [{AGENT}]")
        cur.execute(f"create login [{AGENT}] with password = N'{password}', "
                    "check_policy = off")
    run_batches(entry, DB, f"""
create user [{AGENT}] for login [{AGENT}] with default_schema = app_owner;
GO
alter role db_datareader add member [{AGENT}];
GO
grant view definition to [{AGENT}];
""")
    return {"host": entry["host"], "port": entry["port"], "database": DB,
            "user": AGENT, "password": password, "schema": "app_owner"}


def check_reads(agent):
    p = Project(agent)
    doc = p.json("check")
    assert doc["schema_drift"] is False, doc
    ok("check: the agent login lands unqualified names in app_owner")

    names = [r["NAME"] for r in p.json("ls", "t_order%")["rows"]]
    assert names == ["t_order", "t_order_audit", "t_order_line"], names
    ok("ls: objects by LIKE pattern")

    rows = p.json("src", "f_order_total")["rows"]
    assert rows[0]["LINE"] == 1 and rows[0]["TEXT"].startswith("create function")
    assert rows[2]["TEXT"].strip() == "-- the total of one order", rows[2]
    ok("src: the definition as SQL Server keeps it, its own line numbers")

    cols = {r["COLUMN_NAME"]: r for r in p.json("cols", "t_order")["rows"]}
    assert cols["status"]["DATA_TYPE"] == "varchar(10)"
    assert cols["status"]["COMMENT"] == "DRAFT until paid"
    assert cols["total"]["DATA_TYPE"] == "numeric(12,2)" and cols["total"]["NULLABLE"] == "NO"
    lines = {r["COLUMN_NAME"]: r for r in p.json("cols", "t_order_line")["rows"]}
    assert lines["id"]["COLUMN_DEFAULT"] == "IDENTITY" and "qty" in lines["amount"]["COLUMN_DEFAULT"]
    ok("cols: types, defaults, identity, computed columns, comments")

    hits = [(r["NAME"], r["LINE"]) for r in p.json("grep", "t_order where")["rows"]]
    assert hits == [("f_order_total", 4)], hits
    ok("grep: every module line holding a text, with its line number")

    deps = [(r["NAME"], r["TYPE"]) for r in p.json("deps", "f_order_total")["rows"]]
    assert ("t_order", "TABLE") in deps, deps
    ok("deps: what a function references")

    doc = p.json("impact", "t_order", "--depth", "1")
    found = {(r["SCHEMA"], r["NAME"], r["HOW"]) for r in doc["rows"]}
    for want in (("app_owner", "v_order_summary", "catalog"),
                 ("app_owner", "f_order_total", "catalog"),
                 ("app_owner", "p_order_paid", "catalog"),
                 ("app_owner", "trg_order_audit", "catalog"),
                 ("app_owner", "t_order_line", "catalog"),
                 ("reporting", "v_paid", "catalog"),
                 ("app_owner", "p_order_count", "text")):
        assert want in found, (want, found)
    assert doc["summary"]["needs_review"] and doc["summary"]["other_schemas"] == ["reporting.v_paid"]
    assert all(r["TYPE"] for r in doc["rows"]), doc["rows"]           # constraints count as their table
    seq = {(r["NAME"], r["TYPE"]) for r in p.json("impact", "seq_order", "--depth", "1")["rows"]}
    assert seq == {("t_order", "TABLE")}, seq                     # through its default
    assert any("dynamic SQL" in b for b in doc["blind_spots"])
    ok("impact: catalog dependents, triggers, foreign keys, another schema, "
       "dynamic SQL as [text]")

    doc = p.json("errors")
    assert [(r["NAME"], r["MESSAGE"]) for r in doc["rows"]] == [
        ("p_broken", "2020: references what does not exist: app_owner.t_missing")], doc
    assert "p_order_count" in doc["blind_spot"], doc
    doc = p.json("errors", "f_order_total")
    assert doc["rows"] == [] and doc["verified"] is True, doc
    doc = p.json("errors", "t_order")
    assert doc["verified"] is False and "not a view" in doc["blind_spot"]
    ok("errors: SQL Server binds each module now; dynamic SQL named as unchecked")
    return p


def ddl_round_trip(entry, p):
    before = p.json("ddl", "t_order")["rows"][0]["DDL"]
    for want in ("CONSTRAINT [pk_t_order] PRIMARY KEY CLUSTERED ([id])",
                 "CONSTRAINT [df_t_order_status] DEFAULT ('DRAFT')",
                 "CREATE NONCLUSTERED INDEX [ix_order_status]",
                 "INCLUDE ([total])", "N'DRAFT until paid'",
                 "create trigger app_owner.trg_order_audit"):
        assert want in before, (want, before)
    run_batches(entry, DB, "alter table app_owner.t_order_line drop constraint fk_line_order;\n"
                           "GO\ndrop table app_owner.t_order;")
    run_batches(entry, DB, before)
    after = p.json("ddl", "t_order")["rows"][0]["DDL"]
    assert after == before, (before, after)
    ok("ddl round trip: drop, run the rebuilt DDL, rebuild — identical")


def definition(entry, name):
    return scalar(entry, f"select object_definition(object_id('{name}'))")


def comment(entry, column):
    return scalar(entry, "select cast(value as nvarchar(4000)) from sys.extended_properties "
                         "where major_id = object_id('app_owner.t_order') and name = "
                         f"'MS_Description' and minor_id = columnproperty(major_id, "
                         f"'{column}', 'ColumnId')")


CENTS = """create or alter function app_owner.f_order_total(@id bigint) returns numeric(12,2) as
begin
    -- the total of one order, in cents
    return (select total * 100 from app_owner.t_order where id = @id);
end
"""


def check_writes(entry):
    from pythia_core import human
    human.FORCE_CONSOLE = False             # no person here unless one approves
    agent = load_fixture(entry)
    run_batches(entry, DB, f"alter role db_datawriter add member [{AGENT}];\nGO\n"
                           f"alter role db_ddladmin add member [{AGENT}];")
    p = Project(agent)
    try:
        _source(entry, p)
        _rows_and_comments(entry, p)
        _breakage(entry, p)
        _triggers(entry, p)
        _release(entry, p)
        _lint(entry, p)
        _lease(entry, p)
    finally:
        human.FORCE_CONSOLE = None


def _source(entry, p):
    original = definition(entry, "app_owner.f_order_total")
    doc = p.preview("cents.sql", CENTS)
    assert doc["created"] is False and doc["rehearsal"]["verified"] is True, doc
    assert doc["rehearsal"]["broken"] == [] and doc["changed_lines"] > 0, doc
    assert definition(entry, "app_owner.f_order_total") == original
    ok("apply: a module previewed — rehearsed, verified, rolled back")
    token = doc["token"]
    code, _, why = p.confirm("apply", "cents.sql", "--confirm", token)
    assert code == 1 and "no developer approval" in why.lower(), why
    p.approve(token)
    code, res, why = p.confirm("apply", "cents.sql", "--confirm", token)
    assert code == 0 and res["applied"] is True, (code, why, res)
    assert "in cents" in definition(entry, "app_owner.f_order_total")
    code, _, why = p.confirm("apply", "cents.sql", "--confirm", token)
    assert code == 1, why
    ok("approved and confirmed: written once; the token does not write twice")
    eid = res["restore"].split()[-1]
    doc = p.json("journal", "restore", eid)
    p.approve(doc["token"])
    code, res, why = p.confirm("journal", "restore", eid, "--confirm", doc["token"])
    assert code == 0, (code, why, res)
    # SQL Server keeps CREATE OR ALTER as "create   function": the words differ
    # only in the spaces where OR ALTER stood
    assert definition(entry, "app_owner.f_order_total").split() == original.split()
    ok("journal restore: previewed, approved, written — the original is back")

    p.policy(structural="confirm")
    doc = p.preview("new.sql", "create procedure app_owner.p_new as select 1 as one")
    assert doc["created"] is True, doc
    p.approve(doc["token"])
    code, res, why = p.confirm("apply", "new.sql", "--confirm", doc["token"])
    assert code == 0 and res["restore_is_drop"] is True, (why, res)
    eid = res["restore"].split()[-1]
    doc = p.json("journal", "restore", eid)
    p.approve(doc["token"])
    assert p.confirm("journal", "restore", eid, "--confirm", doc["token"])[0] == 0
    assert scalar(entry, "select object_id('app_owner.p_new')") is None
    ok("a new object: its undo is a DROP, and says so")

    code, _, why = p.run("apply", p.file("bad.sql", "create or alter procedure "
                                         "app_owner.p_bad as selec 1"))
    assert code == 1 and "Rehearsal failed" in why and "nothing was written" in why.lower(), why
    ok("a statement that fails in rehearsal has nothing to approve")
    code, out, why = p.run("apply", p.file("session.sql", "set ansi_warnings on"))
    assert code == 0 and "Session setting applied" in out, (why, out)
    ok("a session setting says it ends with the connection")


def _rows_and_comments(entry, p):
    p.policy(data_dml="confirm", structural="confirm")
    audit = scalar(entry, "select count(*) from app_owner.t_order_audit")
    paid = "update app_owner.t_order set total = total + 1 where status = 'DRAFT'"
    doc = p.preview("paid.sql", paid)
    assert doc["row_set"]["count"] == 2 and doc["rehearsal"]["rows"] == 2, doc
    assert any("triggers" in n for n in doc["rehearsal"]["notes"]), doc
    p.approve(doc["token"])
    run_batches(entry, DB, "insert into app_owner.t_order (status, total) values ('DRAFT', 5)")
    code, _, why = p.confirm("apply", "paid.sql", "--confirm", doc["token"])
    assert code == 1 and "2 rows" in why and "3" in why, why
    doc = p.preview("paid.sql", paid)
    p.approve(doc["token"])
    code, res, why = p.confirm("apply", "paid.sql", "--confirm", doc["token"])
    assert code == 0 and res["rows"] == 3, (why, res)
    assert scalar(entry, "select sum(total) from app_owner.t_order where status = 'DRAFT'") == 38
    assert scalar(entry, "select count(*) from app_owner.t_order_audit") == audit + 3
    ok("DML: approved on its rows; rows that moved are refused, then written")

    stmt = ("exec sys.sp_updateextendedproperty @name = N'MS_Description', "
            "@value = N'Set when it''s paid', @level0type = N'SCHEMA', "
            "@level0name = N'app_owner', @level1type = N'TABLE', @level1name = N't_order', "
            "@level2type = N'COLUMN', @level2name = N'status'")
    doc = p.preview("comment.sql", stmt)
    assert doc["object"] == "t_order.status" and doc["type"] == "COMMENT", doc
    p.approve(doc["token"])
    code, res, why = p.confirm("apply", "comment.sql", "--confirm", doc["token"])
    assert code == 0 and comment(entry, "status") == "Set when it's paid", (why, res)
    eid = res["restore"].split()[-1]
    doc = p.json("journal", "restore", eid)
    p.approve(doc["token"])
    assert p.confirm("journal", "restore", eid, "--confirm", doc["token"])[0] == 0
    assert comment(entry, "status") == "DRAFT until paid"
    add = stmt.replace("sp_updateextendedproperty", "sp_addextendedproperty") \
        .replace("N'status'", "N'total'")
    doc = p.preview("comment.sql", add)
    p.approve(doc["token"])
    code, res, _ = p.confirm("apply", "comment.sql", "--confirm", doc["token"])
    eid = res["restore"].split()[-1]
    doc = p.json("journal", "restore", eid)
    p.approve(doc["token"])
    assert p.confirm("journal", "restore", eid, "--confirm", doc["token"])[0] == 0
    assert comment(entry, "total") is None
    ok("comments: MS_Description written and restored — updated, or dropped again")


def _breakage(entry, p):
    run_batches(entry, DB, "alter table app_owner.t_order add note nvarchar(40) null;\nGO\n"
                           "create view app_owner.v_note as select id, note from app_owner.t_order;")
    drop = "alter table app_owner.t_order drop column note"
    doc = p.preview("drop.sql", drop)
    assert [b[0] for b in doc["rehearsal"]["broken"]] == ["v_note"], doc["rehearsal"]
    assert "column or constraint" in doc["destructive"], doc
    p.approve(doc["token"])
    run_batches(entry, DB, "create view app_owner.v_note2 as select note from app_owner.t_order;")
    code, _, why = p.confirm("apply", "drop.sql", "--confirm", doc["token"])
    assert code == 1 and "v_note2" in why and "moved" in why, why
    assert scalar(entry, "select columnproperty(object_id('app_owner.t_order'), 'note', 'ColumnId')")
    ok("a verification that moved after approval is rolled back")
    doc = p.preview("drop.sql", drop)
    p.approve(doc["token"])
    code, res, why = p.confirm("apply", "drop.sql", "--confirm", doc["token"])
    assert code == 3 and {b[0] for b in res["broken"]} == {"v_note", "v_note2"}, (code, why, res)
    assert scalar(entry, "select columnproperty(object_id('app_owner.t_order'), "
                         "'note', 'ColumnId')") is None
    ok("an approved breakage lands, and exits 3 with what broke")


def _triggers(entry, p):
    run_batches(entry, DB, "create table app_owner.t_hold (id int primary key, v int);\nGO\n"
                           "insert into app_owner.t_hold values (1, 0);\nGO\n"
                           "create trigger app_owner.trg_hold on app_owner.t_hold after update "
                           "as begin commit; end")
    value = "select v from app_owner.t_hold where id = 1"
    doc = p.preview("hold.sql", "update app_owner.t_hold set v = 1 where id = 1")
    assert any("3609" in n for n in doc["rehearsal"]["notes"]), doc["rehearsal"]
    assert scalar(entry, value) == 0
    p.approve(doc["token"])
    code, res, why = p.confirm("apply", "hold.sql", "--confirm", doc["token"])
    assert code == 0 and scalar(entry, value) == 1, (code, why, res)
    ok("a trigger's single COMMIT commits nothing in a preview; the approval does")

    run_batches(entry, DB, "alter trigger app_owner.trg_hold on app_owner.t_hold after update "
                           "as begin while @@trancount > 0 commit; end")
    code, out, why = p.run("apply", p.file("hold.sql", "update app_owner.t_hold set v = 2 "
                                                       "where id = 1"))
    assert code == 3 and "WRITTEN?" in out and "trg_hold" in out, (code, why, out)
    assert "nothing was written" not in (out + why).lower()
    assert scalar(entry, value) == 2                       # committed by the trigger
    ok("a trigger that commits past the rehearsal: WRITTEN?, exit 3 — never 'nothing written'")

    run_batches(entry, DB, "alter trigger app_owner.trg_hold on app_owner.t_hold after update "
                           "as begin if exists (select 1 from inserted where v > 100) begin "
                           "raiserror('v too large', 16, 1); rollback; end end")
    code, _, why = p.run("apply", p.file("hold.sql", "update app_owner.t_hold set v = 101 "
                                                     "where id = 1"))
    assert code == 1 and "v too large" in why and "nothing was written" in why, why
    assert scalar(entry, value) == 2
    ok("a trigger that rolls back: refused, and nothing was written")

    run_batches(entry, DB, "create trigger ddl_hold on database for create_procedure "
                           "as begin commit; end")
    try:
        doc = p.preview("ddl.sql", "create procedure app_owner.p_ddl as select 1 as one")
        assert any("3609" in n for n in doc["rehearsal"]["notes"]), doc["rehearsal"]
        assert scalar(entry, "select object_id('app_owner.p_ddl')") is None
    finally:
        run_batches(entry, DB, "drop trigger ddl_hold on database")
    ok("a DDL trigger's COMMIT commits nothing either")


RELEASE = """-- release 7: a note on every order
alter table app_owner.t_order add note nvarchar(40) null;
GO
update app_owner.t_order set note = N'first' where id = 1;
exec sys.sp_addextendedproperty @name = N'MS_Description', @value = N'free text',
    @level0type = N'SCHEMA', @level0name = N'app_owner', @level1type = N'TABLE',
    @level1name = N't_order', @level2type = N'COLUMN', @level2name = N'note';
GO
create or alter procedure app_owner.p_order_note @id bigint as
begin
    set nocount on;
    select note from app_owner.t_order where id = @id;
end
GO
"""
HAS_NOTE = "select count(*) from sys.columns where object_id = object_id('app_owner.t_order') " \
           "and name = 'note'"


def _release(entry, p):
    """deploy: GO batches, rehearsed as one transaction, landed as one, or not at all."""
    p.policy(data_dml="confirm", structural="confirm")
    p.file("rel.sql", RELEASE)
    code, doc, why = p.confirm("deploy", "rel.sql")
    assert code == 0, (why, doc)
    assert [(m["line"], m["group"]) for m in doc["members"]] == [
        (2, "structural"), (4, "data_dml"), (5, "comments"), (9, "source")], doc["members"]
    # the UPDATE was rehearsed against the column the release adds before it
    assert doc["members"][1]["row_set"]["count"] == 1, doc["members"][1]
    assert scalar(entry, HAS_NOTE) == 0
    ok("deploy previews GO batches as one transaction: DML on the column it adds")

    code, _, why = p.run("approve", "--card", doc["members"][1]["token"])
    assert code == 1 and "approved as a whole" in why, why
    p.approve(doc["batch"])
    run_batches(entry, DB, "update app_owner.t_order set total = total + 1 where id = 1")
    code, _, why = p.confirm("deploy", "rel.sql", "--confirm", doc["batch"])
    assert code == 1 and "statement 2" in why and "nothing was written" in why.lower(), why
    assert scalar(entry, HAS_NOTE) == 0           # statement 1 did not land either
    ok("a release whose rows moved after approval rolls back whole")

    code, doc, why = p.confirm("deploy", "rel.sql")
    p.approve(doc["batch"])
    code, res, why = p.confirm("deploy", "rel.sql", "--confirm", doc["batch"])
    assert code == 0 and res["applied"], (why, res)
    assert scalar(entry, "select note from app_owner.t_order where id = 1") == "first"
    assert comment(entry, "note") == "free text"
    assert scalar(entry, "select object_id('app_owner.p_order_note')") is not None
    ok("an approved release lands whole, in one commit")

    p.file("bad.sql", "alter table app_owner.t_order add note2 int;\nGO\n"
                      "update app_owner.t_order set nope = 1 where id = 1;\n")
    code, _, why = p.run("deploy", "bad.sql")
    assert code == 1 and "bad.sql:3" in why and "nope" in why, why
    assert scalar(entry, "select count(*) from sys.columns where object_id = "
                         "object_id('app_owner.t_order') and name = 'note2'") == 0
    ok("a release that fails at statement 2 keeps nothing of statement 1")


def _lint(entry, p):
    code, doc, why = p.confirm("apply", p.file("tag.sql", (
        "create or alter procedure app_owner.p_tag @id bigint as\n"
        "begin\n    set nocount on;\n    declare @tag varchar;\n"
        "    select @tag = status from app_owner.t_order where id = @id;\n"
        "    select @tag as tag;\nend")))
    assert code == 0, why
    found = [(f["rule"], f["line"], f["severity"]) for f in doc["lint"]]
    assert ("mssql-unsized-string", 4, "error") in found, found
    code, _, why = p.run("lint", "tag.sql")
    assert code == 1, why
    ok("lint: an unsized varchar is an error in a real preview, and lint exits 1")


def _lease(entry, p):
    """autopilot: one approved lease lands covered writes, and nothing else."""
    from pythia_core import human
    code, doc, why = p.confirm("autopilot", "request", "--groups", "comments",
                               "--max-writes", "2")
    assert code == 0 and len(doc["token"]) == 8, why
    text = ("exec sys.sp_updateextendedproperty @name = N'MS_Description', "
            "@value = N'orders, under a lease', @level0type = N'SCHEMA', "
            "@level0name = N'app_owner', @level1type = N'TABLE', @level1name = N't_order'")
    code, doc2, _ = p.confirm("apply", p.file("c1.sql", text))
    assert code == 0 and doc2["will_apply"] is False         # a request is no lease
    human.FORCE_CONSOLE = True
    try:
        code, _, why = p.run("approve", doc["token"])
        assert code == 0, why
    finally:
        human.FORCE_CONSOLE = False
    code, res, why = p.confirm("apply", "c1.sql")
    assert code == 0 and res["applied"] and res["confirmed_via"] == "autopilot", (why, res)
    assert scalar(entry, "select cast(value as nvarchar(4000)) from sys.extended_properties "
                         "where major_id = object_id('app_owner.t_order') and minor_id = 0 "
                         "and name = 'MS_Description'") == "orders, under a lease"
    code, doc3, why = p.confirm("apply", p.file("s1.sql", "alter table app_owner.t_order "
                                                          "add under_lease int"))
    assert code == 0 and doc3["will_apply"] is False, why
    assert "does not cover structural" in doc3["autopilot"]["why"], doc3["autopilot"]
    assert scalar(entry, "select count(*) from sys.columns where object_id = "
                         "object_id('app_owner.t_order') and name = 'under_lease'") == 0
    code, report, _ = p.confirm("autopilot", "report")
    assert [w["verdict"] for w in report["writes"]] == ["ok"], report
    assert p.run("autopilot", "off")[0] == 0
    ok("autopilot: an approved lease lands a covered write, and only that")


def main():
    env = os.environ
    if not env.get("PYTHIA_MSSQL_LIVE_HOST"):
        print("SKIP live check: PYTHIA_MSSQL_LIVE_HOST is not set")
        return
    entry = admin_entry()
    check_connect(entry)
    if env.get("PYTHIA_MSSQL_LIVE_DISPOSABLE") != "1":
        print("SKIP the read commands: PYTHIA_MSSQL_LIVE_DISPOSABLE=1 is not set, "
              "and they create a login and drop a database")
        return
    agent = load_fixture(entry)
    p = check_reads(agent)
    ddl_round_trip(entry, p)
    check_writes(entry)
    print("OK")


if __name__ == "__main__":
    main()
