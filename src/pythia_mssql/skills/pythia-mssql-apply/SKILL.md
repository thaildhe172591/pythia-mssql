---
name: pythia-mssql-apply
description: Use when landing any change in SQL Server - creating or altering a procedure, function, view or trigger, an MS_Description, DDL, a GRANT/REVOKE/DENY, an INSERT/UPDATE/DELETE, or restoring a previous version. Every write goes through pythia-mssql apply - one statement, rehearsed, previewed, approved by the developer, then committed.
---

# Apply through the gate

**Announce at start:** "Using pythia-mssql-apply — preview first, then the developer approves."

**Phase:** Ask → Do — the preview is the Ask, the confirm is the Do

SQL Server runs DDL inside a transaction, so pythia-mssql rehearses every
statement for real — runs it, binds every module around it, rolls it back —
and shows the developer the result before anything is kept. sqlcmd, SSMS, a
driver script or an MCP SQL tool would write with no snapshot, no rehearsal
and no journal; the guard denies them.

## The Iron Law

```
NO WRITE WITHOUT A PREVIEW THE DEVELOPER SAW AND APPROVED
```

## The Workflow

1. **Impact first** (`pythia-mssql-impact`) — the number was known before
   the code was written.
2. **One statement per file**, linted first: `pythia-mssql lint <files>` — a
   change's files in one run, since an MS_Description in one counts for the
   table in another. Errors are fixed, not argued. A `CREATE OR ALTER
   PROCEDURE` takes its whole file, with no `GO`. Several statements, `EXEC`,
   control flow and anything that cannot run in a transaction are refused —
   see `reference/refusals.md` for each refusal and its way forward.
3. **Preview:** `pythia-mssql apply change.sql`. Nothing is kept. It prints:
   - the diff of the definition before and after, as SQL Server keeps both
     (it stores `CREATE OR ALTER` as `create`, padded with spaces);
   - the rehearsal: `nothing broke`, what it **would break**, or
     `NOT VERIFIED` with the reason;
   - the rows a DML statement touched, with a sample;
   - notes and warnings: a trigger's COMMIT, `! DESTRUCTIVE`;
   - a token, and the approval doors.
4. **Relay the preview verbatim** — diff, rehearsal, rows, notes. Do not
   summarise away a broken dependent or a NOT VERIFIED line.
5. **Ask, through the first door that works** — the next one unasked when
   a door fails (the hook or the tool result says which):
   1. **AskUserQuestion** (Claude Code): run
      `pythia-mssql approve --card <token>` and ask with exactly its output,
      options Approve / Reject, never with answers filled in. The answer
      hook records the approval.
   2. **The `pythia_mssql_approve` tool** (MCP; Codex starts here), with the
      token. The developer answers its prompt.
   3. **The developer's terminal:** relay `pythia-mssql approve <token>`.

   Never mint a grant, pipe anything into `approve --hook`, or set
   `PYTHIA_MSSQL_CI` — the guard denies all three. A Reject means stop and
   ask what should change.
6. **Confirm:** `pythia-mssql apply change.sql --confirm <token>`. It
   rehearses again and commits only if the file, the object, the rows and
   the verification still match what was approved; otherwise it rolls back
   and names what moved — preview again and get the new token approved.
7. **Verify** (`pythia-mssql-verify`) before any "done".

## Exit codes are the verdict

| Exit | Meaning | You say |
|---|---|---|
| 0 | written and verified (or NOT VERIFIED, said plainly) | what landed, and what was not checked |
| 1 | refused, nothing written | the reason, verbatim; never route around it |
| 3 | written **but broken** — or **`WRITTEN?`** | "broken" first: the errors and the printed restore command; the developer chooses fix-forward or restore |

**`WRITTEN?`** means a trigger ended the transaction the rehearsal ran in:
the preview itself may have committed the statement, approved or not. Stop,
relay the output verbatim, and let the developer look at the table and its
triggers before anything else runs. Never call it refused or unwritten.

Never read the exit code through a pipe: `pythia-mssql apply ... | tail`
returns tail's code.

## Policy

`data_dml`, `structural` and `grants` are `deny` by default; `source` and
`comments` need the developer's approval. A deny is relayed with its reason.
`pythia-mssql policy` shows the policy and whether rollback is real per
group. Loosening it (`policy set`) and `--yes` are the developer's acts, at
a console — never yours.

## Restore is a write

`pythia-mssql history <name>` lists every version the journal holds;
`pythia-mssql journal restore <entry>` previews putting one back, and goes
through the same approval and `--confirm <token>`. Only definitions and
MS_Description have a restore: rows, a dropped column or a revoked grant do
not come back.

## Red Flags — STOP if you catch yourself thinking

| Thought | Reality |
|---------|---------|
| "It's a one-line fix, sqlcmd is faster" | Faster to write, and the only copy of what it replaced is gone. |
| "The developer said go ahead earlier" | They approve a token, after seeing its preview. |
| "Exit 3, but it mostly worked" | Exit 3 is broken. Say so first. |
| "WRITTEN? — it was only a preview" | A trigger may have committed it. Stop and show the developer. |
| "I'll split the script and apply each part quietly" | Each part is previewed and approved on its own. |
| "The preview is long, I'll summarise" | The developer approves what they saw. Relay it. |
