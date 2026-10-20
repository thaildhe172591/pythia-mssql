# pythia-mssql

pythia for SQL Server: T-SQL development for AI agents, built on
[pythia-core](https://github.com/thaildhe172591/pythia-core). It aims to do
what [pythia](https://github.com/thaildhe172591/pythia) does on Oracle and
[pythia-postgres](https://github.com/thaildhe172591/pythia-postgres) does on
PostgreSQL: the agent learns from the live catalog, asks a person before
any write, and writes only through a gate that snapshots, verifies and
reports honestly.

**Pre-alpha (Phase 4a).** It reads everything pythia's Learn movement
needs, and writes nothing yet.

| Works today | Next |
|---|---|
| `check`, `ls`, `src`, `cols`, `ddl`, `grep`, `deps`, `impact`, `errors`, `connections` | the write gate (4b); the harness, deploy, autopilot and lint (4c) |

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

### Least privilege

The read commands need `db_datareader` on the database and `VIEW
DEFINITION` (without it, module definitions read as empty). The live check
runs every read command as such a login.

## Tests

```bash
python tests/test_mssql.py    # no database, no pymssql
python tests/live_check.py    # a disposable server only (see its docstring)
```

CI runs the suite on Ubuntu, Windows and macOS, Python 3.9 and 3.13, and
the live check against SQL Server 2022 in a service container. It tests
against the pythia-core branch of the same name when one exists.

## License

MIT
