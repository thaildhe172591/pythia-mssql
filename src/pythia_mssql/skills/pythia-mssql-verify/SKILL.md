---
name: pythia-mssql-verify
description: Use before claiming any SQL Server change is done, fixed, working or safe - after an apply, a deploy, a restore, or a fix to a broken procedure. Evidence first - exit codes, errors, the dependents - and "broken", "not verified" or "WRITTEN?" said plainly.
---

# Evidence before "done"

**Announce at start:** "Using pythia-mssql-verify — evidence before done."

**Phase:** Do — the last step of every change

SQL Server accepts a procedure that references a table that does not
exist; it fails when it runs. "It applied" is not "it works", and a claim
of done without evidence costs the developer the debugging later.

## The Iron Law

```
NO COMPLETION CLAIM WITHOUT THE EVIDENCE PRINTED IN THIS SESSION
```

## The Checklist

1. **Every write's exit code, unpiped.** 0 clean, 3 written-but-broken —
   or `WRITTEN?`, a trigger that ended the transaction. A 3 means the
   report starts with "broken" or "may be written".
2. **`pythia-mssql errors <name>`** for each object you touched, and for
   each dependent that `impact` listed. Compare with the baseline taken
   before the change: only new findings are yours.
3. **`NOT VERIFIED` is reported as such.** Code inside dynamic SQL, and a
   grant's effect, are never checked: say "applied, not verified" for
   them, never "clean".
4. **The dependents.** If the change altered a column, a parameter or a
   result set, read the `[text]` rows from `impact` again — they are where
   a run-time failure hides.
5. **`pythia-mssql lint`** on the change's files is clean of errors.
6. **The journal.** `pythia-mssql history <name>` shows the entry; quote its
   restore command in the report for a change the developer may want back.

## How to report

```
Applied f_order_total (FUNCTION) — exit 0.
errors f_order_total: none.
Dependents: v_order_summary [catalog], p_order_count [text] — errors: none;
p_order_count builds dynamic SQL: not verified there.
Restore if needed: pythia-mssql journal restore <entry>
```

Say "broken" first when it is; say "not verified" plainly when it is.

## Red Flags — STOP if you catch yourself thinking

| Thought | Reality |
|---------|---------|
| "apply printed Applied" | Read the exit code and the rehearsal lines, not the word. |
| "errors printed nothing" | With no NOT VERIFIED line, that is evidence. With one, it is not. |
| "The procedure compiled, so it works" | Deferred name resolution: it compiles with a missing table. `errors` binds it. |
| "I'll verify after reporting" | Then the report is a guess. |
