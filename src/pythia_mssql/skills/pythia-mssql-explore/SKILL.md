---
name: pythia-mssql-explore
description: Use when explaining, investigating or reading SQL Server objects - what a procedure does, where a table is used, why something fails, what a schema holds. Asks the live database through pythia-mssql read commands, never a dump, SSMS scripts or memory.
---

# Explore the live database

**Announce at start:** "Using pythia-mssql-explore to read the live database."

**Phase:** Learn — facts from the catalog, before any opinion

A repository's SQL files drift from the database: a procedure altered in
SSMS, an index added by hand, a view nobody scripted out. An explanation
built on the dump is an explanation of a database that does not exist.

## The Iron Law

```
EVERY FACT COMES FROM THE LIVE CATALOG, WITH THE COMMAND THAT SHOWED IT
```

## The commands

| Question | Command |
|---|---|
| Where am I, and where do unqualified names land? | `pythia-mssql check` |
| Which objects match a name? | `pythia-mssql ls "t_order%"` |
| What does this procedure / function / view / trigger say? | `pythia-mssql src <name>` |
| What columns does this table or view have? | `pythia-mssql cols <name>` |
| What statements would create it? | `pythia-mssql ddl <name>` |
| Where is this text used in module code? | `pythia-mssql grep <text>` |
| What does it use? | `pythia-mssql deps <name>` |
| What uses it? | `pythia-mssql impact <name>` (see `pythia-mssql-impact`) |
| What would fail if it ran now? | `pythia-mssql errors [<name>]` |

`--json` gives structured output on every command. Line numbers in `src`
are SQL Server's own, so they match the line in an error message.

## Reading the output honestly

- **Truncation is announced.** No `-- truncated` line means you saw
  everything. With one, say so, or fetch the rest with `--offset` /
  `--limit 0`.
- **`[text]` rows are leads, not proofs.** Dynamic SQL (`EXEC` of a string,
  `sp_executesql`) is not in the catalog; pythia-mssql finds those names in
  module text and marks them. Say which rows are which.
- **`-- blind spot:` lines are part of the answer.** Other databases,
  linked servers and dynamic SQL are not seen. Relay them; never call a
  dependency list complete when one is printed.
- **`errors` binds every module now**, the way SQL Server would when it
  runs it. SQL Server accepts a procedure that names a table that does not
  exist (deferred name resolution) — `errors` is where that shows. Code
  inside dynamic SQL is never checked: a `NOT VERIFIED` line is never "no
  errors".

## Red flags

| Thought | Reality |
|---------|---------|
| "The migration file shows the table" | The database may not. `pythia-mssql cols`. |
| "`errors` printed nothing, so it is clean" | Only if no NOT VERIFIED line was printed. |
| "I'll open connections.json to see the host" | Never: `pythia-mssql connections` lists it without passwords. |
| "I'll check it in sqlcmd quickly" | Read commands answer it, with truncation and blind spots said. |

## Hand-off

Explaining only → done, with the commands quoted. A change follows →
`pythia-mssql-impact` before any code is written.
