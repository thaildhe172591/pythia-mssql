# Changelog

## 0.3.0.dev0 — unreleased

Phase 4c of the plan in pythia-core's DESIGN.md: the harness, release and
lint tiers, and the skill pack. Phase 4 is complete.

- **The guard (`guard.py`):** `sqlcmd`, `osql`, `isql`, `mssql-cli` and
  `Invoke-Sqlcmd` given write SQL — DDL, DML with or without INTO and FROM,
  `EXEC` and any `sp_` or `xp_` procedure (first in a batch it needs no
  EXEC), `SELECT ... INTO`, `NEXT VALUE FOR`, `:r` — or a script (`-i`,
  `--input-file`, `-InputFile`, `< file`, a pipe; `-I` is not a script);
  `bcp ... in`; `sqlpackage` Publish and Import. Denied behind `docker
  exec`, `ssh`, `sudo` and `bash -c` too; reads are left to the client.
- **`install`, `doctor`, `hook`, `mcp`, `skill lint`** over pythia-core,
  field-tested in a scratch project: `doctor` passes, the brief carries the
  STATE lines, the guard denies `sqlcmd -Q "drop table ..."` and allows a
  pythia-mssql read.
- **`deploy`:** a release cut at `GO` lines and then at `;`, a module's body
  running to the end of its batch (never cut at a `;` inside it), rehearsed
  and committed as one transaction under one approval. `GO n` is refused.
- **`lint` and ten T-SQL rules:** a trigger that commits and a string type
  without a length (errors); NOLOCK, `SELECT *` in stored code, `NOT IN
  (SELECT ...)`, `text`/`ntext`/`image`, a procedure named `sp_`, a new table
  without an MS_Description (warnings); `datetime` and a procedure without
  `SET NOCOUNT ON` (notes).
- **Seven skills:** `using-pythia-mssql` (the router),
  `pythia-mssql-explore`, `-impact`, `-apply` (with its refusals), `-deploy`,
  `-autopilot`, `-verify` — `WRITTEN?` named where it can appear.
- **The live check** also deploys a release in GO batches (rows that move
  roll it back whole; a failure at statement 2 keeps nothing), sees a lint
  error in a real preview, and lands a write under an autopilot lease.
- Tests for every guard word and rule, mutation-checked.

## 0.2.0.dev0 — unreleased

Phase 4b of the plan in pythia-core's DESIGN.md: SQL Server's write tier,
on pythia-core 0.9.0.dev0.

- **`apply`, `approve`, `journal`, `policy`** over pythia-core's gate:
  snapshot, impact, rehearse, preview, a person's approval, commit, report.
- **A T-SQL reader:** `'...'` and `N'...'` strings, `[bracketed]` and
  `"quoted"` names, `--` and nested `/* */` comments, `GO` lines. A module
  takes its whole batch; anything else ends at its `;`. A second statement
  on a line of its own is caught even without a `;`.
- **Classification refuses what no group honestly fits:** `EXEC` of a
  procedure, control flow, `SELECT`, `WITH`, `MERGE`, `USE`, transaction
  control, temporary objects, server-level objects, statements that cannot
  run in a transaction, extended properties other than `MS_Description`
  (and any given by position), `GO`.
- **The rehearsal binds the modules around a change** with
  `sys.dm_sql_referenced_entities` before and after the statement, so an
  `ALTER TABLE ... DROP COLUMN` names the view it breaks.
- **A trigger cannot commit a rehearsal.** The statement runs one
  transaction level down, so a trigger's single `COMMIT` commits nothing. A
  transaction that ends anyway (`@@TRANCOUNT` 0, or a new transaction id)
  is reported `escaped` — exit 3, never "nothing was written" — unless the
  database's triggers show it was rolled back (pymssql reports a trigger's
  own RAISERROR or THROW, not 3609, so the triggers decide, not the error
  number).
- **Rows are revalidated** with `CHECKSUM_AGG(BINARY_CHECKSUM(*))`, and an
  UPDATE or DELETE whose rows cannot be read beforehand is refused —
  including a WHERE clause whose parentheses do not balance, which would
  put a statement of its own into the probe that runs before approval.
- **`MS_Description` is snapshotted and restored:** updated back, added
  back, or dropped again. An encrypted module is refused: there is nothing
  to snapshot.
- **`tests/live_check.py` writes on a real server:** preview, approve,
  confirm and restore; a new object undone by a DROP; rows that move; a
  comment; a DROP COLUMN that breaks a view, a verification that moved,
  written-but-broken; and triggers that COMMIT once, commit past the
  rehearsal, roll back, or fire on DDL.

## 0.1.0.dev0 — unreleased

Phase 4a of the plan in pythia-core's DESIGN.md: SQL Server's connect and
read tiers, on pythia-core 0.8.0.dev0.

- **The driver is pymssql** (DESIGN.md §8, settled by a spike): wheels with
  FreeTDS inside for Windows, macOS and Linux on Python 3.9–3.13, so no ODBC
  driver needs installing; every server error raised with its number (the
  pure-Python python-tds left an error in `cursor.messages` instead);
  pyformat binds; TLS with `"encrypt": "require"`. mssql-python needs Python
  3.10 or later, pyodbc a system ODBC driver.
- **`pythia-mssql check`, `ls`, `src`, `cols`, `ddl`, `grep`, `deps`,
  `impact`, `errors`**, over pythia-core's command line.
- **`impact` asks twice:** `sys.sql_expression_dependencies` (modules,
  references by name to objects that did not exist yet, check and default
  constraints counted as their table), triggers, foreign keys — and then a
  whole-word search of module text for what only dynamic SQL names, marked
  `[text]`.
- **`errors` binds every module now** with `sys.dm_sql_referenced_entities`,
  the way SQL Server would when it runs: a missing column (207) or object
  (named from the catalog behind SQL Server's generic 2020). Dynamic SQL is
  named as unchecked. `sp_refreshsqlmodule` is not used: when it fails it
  rolls back the caller's whole transaction.
- **`ddl` of a table is rebuilt from the catalog** — columns, identity,
  computed columns, defaults, keys, foreign keys, checks, indexes (with
  INCLUDE and filters), comments (MS_Description) and triggers, in batches
  ended by GO — and the live check proves the round trip.
- **Read commands never commit:** SQL Server has no read-only transaction,
  so each runs in one that closing the connection rolls back.
- **`tests/live_check.py`** runs every read command against a disposable
  SQL Server 2022 as a least-privilege login (db_datareader, VIEW
  DEFINITION); CI runs it in a service container.
