# pythia-mssql

pythia for SQL Server: T-SQL development for AI agents, built on
[pythia-core](https://github.com/thaildhe172591/pythia-core). It aims to do
what [pythia](https://github.com/thaildhe172591/pythia) does on Oracle and
[pythia-postgres](https://github.com/thaildhe172591/pythia-postgres) does on
PostgreSQL: the agent learns from the live catalog, asks a person before
any write, and writes only through a gate that snapshots, verifies and
reports honestly.

**Pre-alpha (Phase 4b).** It reads everything pythia's Learn movement
needs, and writes through one gate.

| Works today | Next |
|---|---|
| `check`, `ls`, `src`, `cols`, `ddl`, `grep`, `deps`, `impact`, `errors`, `connections`; `apply`, `approve`, `journal`, `policy` | the harness — guard, `install`, `doctor`, the chat doors and skills — with `deploy`, autopilot and lint (4c) |

## Install (from git while pre-alpha)

```bash
pip install "git+https://github.com/thaildhe172591/pythia-core" \
            "git+https://github.com/thaildhe172591/pythia-mssql"
```

That brings [pymssql](https://pypi.org/project/pymssql/), whose wheels carry
FreeTDS: no ODBC driver needs installing, on Windows, macOS or Linux.

## Connections

`.pythia/mssql/connections.json` in the project root, owner-readable only
(`chmod 600`), and out of git. Template:
[examples/connections.example.json](examples/connections.example.json).

```json
{
  "default": "dev",
  "dev": { "host": "db-dev", "port": 1433, "database": "app",
           "user": "app_agent", "password": "...", "schema": "app_owner",
           "encrypt": "request" }
}
```

- `host`, `database`, `user` are required; SQL Server authentication only
  (a login and password).
- `encrypt` is `off`, `request` (the default: TLS when the server offers
  it) or `require`. FreeTDS does not validate the server's certificate.
- `schema` is spelled as the catalog spells it (default `dbo`). `check`
  warns when the login's default schema — where an unqualified name lands —
  is another one; set it with `ALTER USER app_agent WITH DEFAULT_SCHEMA =
  app_owner`.
- The entry is picked by `--conn NAME`, then `PYTHIA_MSSQL_CONNECTION`, then
  the only entry, the folder directly under the project root, then
  `"default"`. `PYTHIA_MSSQL_CONFIG` points at another file.

pythia for Oracle keeps `.pythia/connections.json` and pythia-postgres
`.pythia/postgres/`; pythia-mssql reads neither.

## Commands

```bash
pythia-mssql check                 # server, database, default schema drift
pythia-mssql ls "t_order%"         # objects by LIKE pattern
pythia-mssql src f_order_total     # a module's definition, SQL Server's line numbers
pythia-mssql cols t_order          # columns, types, defaults, identity, comments
pythia-mssql ddl t_order           # CREATE TABLE and its batches, rebuilt from the catalog
pythia-mssql grep "t_order where"  # every module line holding a text
pythia-mssql deps f_order_total    # what it references
pythia-mssql impact t_order        # what references it: run before changing it
pythia-mssql errors [NAME]         # every module bound now, as SQL Server would run it
```

`--json` gives one envelope per command; `--limit`, `--max-lines` and
`--offset` window long output, and any truncation says how to fetch the
rest.

### What the catalog cannot see, and how pythia-mssql says so

- **`impact` asks twice.** `sys.sql_expression_dependencies` records what
  every view, procedure, function and trigger references — by name too,
  when the object did not exist yet. Triggers on a table and foreign keys
  that point at it are added, and a check or default constraint counts as
  its table. Dynamic SQL (`EXEC` of a string, `sp_executesql`) is not in the
  catalog: module text is searched for the name as a whole word and those
  rows are marked `[text]`. Other databases and linked servers are never
  seen. Each blind spot is printed every time.
- **`errors` binds every module now**, with
  `sys.dm_sql_referenced_entities`: a missing column or object raises the
  error SQL Server would raise when the module runs. A module holding
  dynamic SQL is named as not checked inside its strings.
- **`ddl` of a table is rebuilt, not dumped**, and ends each batch with
  `GO`; the live check drops the table, runs the DDL, rebuilds it and
  compares. SSMS's Generate Scripts stays the reference for anything it
  does not cover yet.
- **Reads never commit.** SQL Server has no read-only transaction, so every
  read command runs in a transaction that closing the connection rolls
  back. A read-only login (`db_datareader` plus `VIEW DEFINITION`) is the
  first line.

### Writing: the gate

```bash
pythia-mssql apply change.sql                   # preview: rehearsed, rolled back, nothing written
pythia-mssql approve 3fa9c1                     # the developer approves, at their own console
pythia-mssql apply change.sql --confirm 3fa9c1  # writes it — only as approved
pythia-mssql journal restore <entry>            # undo is a write too: preview, approve, confirm
pythia-mssql policy                             # which groups may be written, and is rollback real?
```

Until the harness arrives (4c), the developer approves in their own
terminal: there is no hook to read a chat answer and no MCP approver yet,
so the preview names no other door.

### One statement: `apply`

One statement per file. A module (`CREATE [OR ALTER] PROCEDURE`, `FUNCTION`,
`VIEW`, `TRIGGER`) takes its whole batch, as SQL Server does; anything else
ends at its `;`. `apply` sorts the statement into a group, and the policy
decides: `source` and `comments` (an `MS_Description` through
`sp_addextendedproperty`, `sp_updateextendedproperty` or
`sp_dropextendedproperty`, its arguments named) need the developer's
approval; `data_dml`, `structural` (DDL, `sp_rename`) and `grants` (`GRANT`,
`REVOKE`, `DENY`, users, roles) are denied until the developer runs
`pythia-mssql policy set <group> confirm` at a console. `session` (`SET`) is
allowed.

What the preview shows, and why it can be trusted:

- **A rehearsal, not a prediction.** The statement ran inside a transaction
  and was rolled back. Every module that depends on what changed — and the
  module itself — is bound with `sys.dm_sql_referenced_entities` before and
  after, and what fails only after is what the statement broke: an `ALTER
  TABLE ... DROP COLUMN` names the view it would break. The diff compares
  the definition before and after, both as SQL Server keeps them (it keeps
  `CREATE OR ALTER` as `create`, padded with spaces).
- **Rows are shown and revalidated.** An UPDATE or DELETE is approved on its
  rows: the count, a sample, and `CHECKSUM_AGG(BINARY_CHECKSUM(*))` over
  them. If any row joins, leaves or changes before the confirm, the confirm
  is refused.
- **The confirm is the same rehearsal, committed only if it still
  matches.** Same token (the file, the object as it stood, the rows), same
  row count, and nothing broken that the approved preview did not show.
- **A trigger cannot commit the rehearsal.** In SQL Server a trigger's
  `COMMIT` or `ROLLBACK` ends the caller's transaction. The statement runs
  one transaction level down, so a trigger's single `COMMIT` ends only that
  level and commits nothing (the preview says so: run any other way, the
  statement ends with error 3609). If the transaction ends anyway — a
  trigger that commits twice, or loops — pythia-mssql reads every trigger
  in the database: when one could have committed (it says `COMMIT`, runs
  other code, or cannot be read), or nothing visible explains it, the write
  is reported **`WRITTEN?`** with exit 3 and the restore, never "nothing was
  written". Only a trigger that rolls back, with none able to commit, is a
  plain refusal.
- **Refused, with the reason:** `EXEC` of a procedure, control flow (`IF`,
  `WHILE`, `DECLARE`, `BEGIN ... END`), `SELECT`, `WITH`, `MERGE`, `USE`,
  transaction control, temporary objects, logins and other server-level
  objects, statements that cannot run in a transaction (`ALTER DATABASE`,
  `BACKUP`, full-text), extended properties other than `MS_Description`,
  `GO`, several statements in one file (a second statement on its own line
  counts, `;` or not), an UPDATE or DELETE whose rows cannot be read
  beforehand (`TOP`, `OUTPUT`, `FROM` or a join, a subquery, `WHERE CURRENT
  OF`, parentheses that do not balance), and a module `WITH ENCRYPTION`
  (nothing to snapshot).

A rehearsal waits at most 5 s for a lock (`SET LOCK_TIMEOUT`); SQL Server
has no session statement timeout. It still fires triggers and draws
`IDENTITY` values and sequence numbers, and the preview of a DML statement
says so. Exit codes follow pythia: `0` clean, `1` refused, `3` written but
broken (with the restore command).

### Least privilege

The read commands need `db_datareader` on the database and `VIEW
DEFINITION` (without it, module definitions read as empty, and every
trigger's text is unknown — so a rehearsal that ends its transaction is
always reported `WRITTEN?`). Writing needs what the statement needs:
`db_datawriter` for rows, `db_ddladmin` or `ALTER` on the schema for code
and DDL. The preview warns when the login is `sysadmin` or `db_owner`. The
live check runs every read command as a read-only login, and every write
as one with `db_datawriter` and `db_ddladmin`.

## Tests

```bash
python tests/test_mssql.py    # no database, no pymssql — mutation-checked
python tests/live_check.py    # a disposable server only (see its docstring)
```

CI runs the suite on Ubuntu, Windows and macOS, Python 3.9 and 3.13, and
the live check against SQL Server 2022 in a service container. It tests
against the pythia-core branch of the same name when one exists.

## License

MIT
