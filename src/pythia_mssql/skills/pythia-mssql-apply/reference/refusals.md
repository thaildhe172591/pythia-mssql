# Refusals and the way forward

`pythia-mssql apply` refuses what it cannot rehearse, verify or undo
honestly. Each refusal exits 1 and writes nothing. Relay the reason, then
offer the way forward below — never run the statement another way.

| Refused | Why | Way forward |
|---|---|---|
| Several statements in one file (a second one on its own line counts, `;` or not) | each is previewed, approved and journaled on its own | one file per statement, applied in order — or `pythia-mssql deploy` |
| `GO` | separates batches in a script | `pythia-mssql deploy` takes scripts |
| `EXEC` of a procedure | runs a body that can do anything | apply the statements it would run, or the developer runs it by hand |
| `IF`, `WHILE`, `DECLARE`, `BEGIN ... END` | an anonymous batch can do anything; no policy group fits | put the logic in a procedure and apply that |
| `WITH ... UPDATE/DELETE`, `MERGE` | hides which rows it touches | a plain INSERT, UPDATE or DELETE |
| `UPDATE`/`DELETE` with `TOP`, `OUTPUT`, `FROM` or a join, a subquery, `WHERE CURRENT OF`, unbalanced parentheses | its rows cannot be read and shown before it runs | a WHERE clause over the table's own columns |
| `SELECT` | apply takes writes; a SELECT can create a table with INTO | reads go through `ls`, `src`, `cols`, `grep` |
| `USE` | changes the database for what follows | `--conn` for a connection to that database |
| `ALTER DATABASE`, `BACKUP`, `RESTORE`, full-text | cannot run inside a transaction: no rehearsal, no rollback | the developer runs it by hand, with a DBA watching |
| logins, endpoints, server-level objects | live outside the database | a DBA runs it by hand |
| `CREATE TABLE #t` | dies with the connection, nothing left to verify | not needed through apply |
| `BEGIN TRAN`, `COMMIT`, `ROLLBACK`, `SET IMPLICIT_TRANSACTIONS` | pythia-mssql owns the transaction | drop the transaction control |
| an extended property other than `MS_Description`, or its arguments by position | only MS_Description is snapshotted and restorable | `@name = N'MS_Description'`, every argument named |
| a module `WITH ENCRYPTION` | nothing to snapshot, no way back | the developer decides by hand |
| a file that ends inside a quote, `[bracket]` or comment | cannot be read safely | close it |
| a schema other than the connection's | writing across schemas is refused | `--conn` for the connection that owns it |
| a group set to `deny` | the policy | relay it; loosening is the developer's `policy set`, at a console |

When the gate refuses, the developer may still decide to run the statement
by hand. Hand them the file and, for a definition, the restore from
`pythia-mssql history <name>` — never run it for them through sqlcmd.
