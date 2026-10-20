---
name: pythia-mssql-deploy
description: Use when landing several SQL Server statements together - a release script, a migration, DDL followed by the data change that needs it, a script with GO batches, or more than one file of changes. pythia-mssql deploy rehearses the whole release in one transaction and lands all of it or none of it, under one approval.
---

# Deploy a release as one transaction

**Announce at start:** "Using pythia-mssql-deploy — the release is rehearsed as one, then approved as one."

**Phase:** Ask → Do — one card for the whole release is the Ask; the confirm is the Do

SQL Server runs DDL inside a transaction, so a whole release can be
rehearsed and committed as one: if statement 7 fails, statements 1–6 are
not left half-landed. Running a migration through `sqlcmd -i` gives that
up, and the snapshot, the rehearsal and the journal with it.

## The Iron Law

```
A RELEASE LANDS WHOLE, AS APPROVED, OR NOT AT ALL
```

## The Workflow

1. **Impact first** (`pythia-mssql-impact`) for every object the release
   changes.
2. **The scripts:** T-SQL in the order it must run — one file or several,
   named in that order on the command line. Batches end at a `GO` line;
   inside a batch a statement ends at its `;`, and a module (`CREATE [OR
   ALTER] PROCEDURE`, `FUNCTION`, `VIEW`, `TRIGGER`) takes the rest of its
   batch as its body — put `GO` after it. No `GO n`, no `BEGIN TRAN` /
   `COMMIT` (pythia-mssql owns the transaction), no `SET`, no `USE`, no
   `EXEC` of a procedure, nothing that cannot run in a transaction
   (`pythia-mssql-apply` lists each refusal and its way forward).
3. **Preview:** `pythia-mssql deploy 01_schema.sql 02_data.sql`. Every
   statement runs in order inside one transaction — an UPDATE of a column
   added two statements earlier is rehearsed against that column — and then
   everything rolls back. It prints one card: every statement, the rows each
   DML statement touches, what the rehearsal of the whole broke or could
   not verify, and one 10-digit token.
4. **Relay the card verbatim**, then ask through the doors exactly as
   `pythia-mssql-apply` does — AskUserQuestion with the output of
   `pythia-mssql approve --card <token>`, then the `pythia_mssql_approve`
   tool, then `pythia-mssql approve <token>` in the developer's terminal. A
   statement's own token is refused: a release is approved as a whole.
5. **Confirm:** `pythia-mssql deploy 01_schema.sql 02_data.sql --confirm
   <token>`, with the same files in the same order. It checks every
   statement is byte-identical to what was approved before anything runs,
   then runs the release again in one transaction and commits only if every
   statement still matches — its object, its rows, its verification.
   Otherwise the whole release rolls back, says which statement moved, and
   the approval stays unspent.
6. **Verify** (`pythia-mssql-verify`): exit 0 clean, 3 written but broken.

## When a trigger ends the transaction

A release runs one transaction. If a trigger fired by statement 4 commits
past the rehearsal, statements 1–4 may already be committed: the output says
**`WRITTEN?`**, names them, lists every restore newest first, and exits 3.
Stop and show the developer before anything else runs.

## Policy and undo

Every group in the release must be allowed: `structural` and `data_dml`
are `deny` until the developer runs `pythia-mssql policy set <group>
confirm` at a console. After commit, modules and MS_Description are
restorable statement by statement (`pythia-mssql journal restore <entry>`,
newest first, as the report lists them); added columns and changed rows are
not.

## Red Flags — STOP if you catch yourself thinking

| Thought | Reality |
|---------|---------|
| "sqlcmd -i is how migrations run" | Not here: no rehearsal, no snapshot, no all-or-nothing. The guard denies it. |
| "I'll apply the statements one by one" | Then a failure halfway leaves a half release. Deploy them together. |
| "Just one more statement after approval" | The scripts changed: nothing runs. Preview again. |
| "It rolled back, so I'll retry with --yes" | `--yes` is the developer's flag. Find what moved, preview again. |

## When NOT to use this skill

- One statement → `pythia-mssql-apply`.
- A statement that cannot run in a transaction (`ALTER DATABASE`,
  `BACKUP`, full-text) → the developer runs it by hand.
