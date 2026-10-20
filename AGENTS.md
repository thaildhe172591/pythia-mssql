# Working in this repository / with this tool

pythia-mssql is pythia for SQL Server, on pythia-core. It is pre-alpha
(Phase 4a): it reads everything pythia's Learn movement needs, and writes
nothing yet.

## Using pythia-mssql as an agent (Phase 4a)

1. **Ask the database, never the dump.** `ls`, `src`, `cols`, `ddl`, `grep`
   against the live schema; `check` says where unqualified names land (the
   login's default schema).
2. **Impact before change.** Run `pythia-mssql impact <NAME>` before
   proposing any modification. When it prints `! show this list to the
   developer` (10 or more dependents, or one in another schema), show the
   developer the list before writing code. Rows marked `[text]` are leads
   found by name in module text (dynamic SQL), not proofs. Relay the `blind
   spot` lines, and never call an impact list complete.
3. **"Not verified" is said plainly.** `errors` binds every module now, the
   way SQL Server would when it runs; dynamic SQL inside a module is named
   as unchecked. Never report a `NOT VERIFIED` line as "no errors".
4. **Truncation is always announced.** If output has no truncation marker,
   you saw everything. If it has one, say so or fetch the rest with
   `--offset`.
5. **It writes nothing yet, so neither do you through it.** Until `apply`
   exists (Phase 4b), propose a change as a file and let the developer run
   it. Never write through `sqlcmd`, SSMS or a driver script on
   pythia-mssql's behalf.
6. **Never open `.pythia/mssql/connections.json`.** It holds passwords.
   `pythia-mssql connections` lists the names, users, schemas and targets
   without them.
7. **Exit codes are the verdict:** `0` clean, `1` refused. Relay the reason;
   do not route around it. Never read `$?` through a pipe.

## Changing pythia-mssql itself

- Run the suite before calling a change done: `python tests/test_mssql.py`
  (no database, no pymssql). Against a disposable server, also
  `python tests/live_check.py`. TDD: the failing test comes first.
- CI runs Ubuntu, Windows and macOS on Python 3.9 and 3.13: build paths with
  `pathlib` / `os.path.join`, and use no stdlib API newer than 3.9.
- **Queries:** every SQL statement lives in `src/pythia_mssql/queries/`,
  one per file, pyformat binds only (`%(s)s`), a literal `%` written `%%`
  (the engine turns it back into `%`: pymssql never does), never a `%(`
  that is not a bind (pymssql reads it as one even inside a literal), the
  `-- Purpose / -- Binds / -- Returns` header, and an entry in
  `QUERY_BINDS`. SQL Server 2016 is the floor: no `STRING_AGG`, no
  `STRING_SPLIT(..., 1)`.
- **Dependencies:** pythia-core and pymssql, nothing else (a test enforces
  it).
- **Engine-neutral logic goes to pythia-core.** If an answer would be the
  same on PostgreSQL or MongoDB, it does not belong here (DESIGN.md §3).
- **Docs never contradict code:** a behaviour change updates the docstring,
  README.md and CHANGELOG.md in the same change.
- **Versions** agree in pyproject.toml and `pythia_mssql.__version__`.

## Never

- Read or write pythia for Oracle's files (`.pythia/connections.json`,
  `.pythia/journal/`) or another engine's (`.pythia/postgres/`), or take
  their commands or variables.
- Point the live check at a shared server: it creates a login and drops a
  database.
- Put real-world identifiers anywhere (hosts, schemas, tenants,
  credentials). Examples use APP_OWNER, PKG_ORDER, T_ORDER. Everything
  shipped is English.
