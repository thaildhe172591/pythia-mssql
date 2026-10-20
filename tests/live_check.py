#!/usr/bin/env python3
"""pythia-mssql against a real SQL Server — a disposable one only.

1. Always (when PYTHIA_MSSQL_LIVE_HOST is set): connect and `check`.
2. With PYTHIA_MSSQL_LIVE_DISPOSABLE=1 only: the database pythia_live is
   dropped and created, tests/fixtures/app_owner.sql is loaded into it, a
   login pythia_agent is made (db_datareader, VIEW DEFINITION, default
   schema app_owner), and every read command runs through the command line
   as that login.

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
        return cur.fetchone()[0]


class Project:
    """A project folder whose connection is the agent login."""

    def __init__(self, entry):
        self.td = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.td.name)
        state = self.root / ".pythia" / "mssql"
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
    print("OK")


if __name__ == "__main__":
    main()
