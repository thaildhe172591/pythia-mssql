# Changelog

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
