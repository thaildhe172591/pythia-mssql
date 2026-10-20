---
name: pythia-mssql-autopilot
description: Use when the developer wants the agent to work on SQL Server without approving every write - "do it all without asking me", "just apply them", "tự động hoàn toàn". Asks once for a lease that names exactly what it covers, then reports every write landed under it.
---

# Autopilot — one lease, never a blank cheque

**Announce at start:** "Using pythia-mssql-autopilot — one request, covering only what the task needs."

**Phase:** Ask → Do — the lease card is the one Ask; every covered write is a Do that is reported

A lease is the developer's delegation, not yours. It covers one connection,
the statement groups it names, a time and a number of writes. Inside it,
covered writes land without a per-write approval — still snapshotted,
rehearsed, verified and journaled. Outside it, the normal gate applies.

## The Iron Law

```
ASK FOR THE NARROWEST LEASE THAT FITS, AND REPORT EVERY WRITE UNDER IT
```

## The Workflow

1. **Settle the task first.** Open decisions are asked before any lease
   (`using-pythia-mssql`).
2. **Request the narrowest lease that fits:**
   `pythia-mssql autopilot request --groups source,comments --hours 2
   --max-writes 30 --note "rename the order procedures"`. Name only the
   groups the task needs; add `--destructive` only when the developer asked
   for drops.
3. **Ask once, through the doors** — exactly as `pythia-mssql-apply` does,
   with the request's 8-digit token: AskUserQuestion with the output of
   `pythia-mssql approve --card <token>`, then the `pythia_mssql_approve`
   tool, then the developer's terminal. `pythia-mssql autopilot on` is the
   developer's own command, at a console — never yours.
4. **Work:** `pythia-mssql apply <file>` and `pythia-mssql deploy <files>`
   land what the lease covers, with no `--confirm`. When one prints
   `! not landed under autopilot — <why>`, that write needs its own
   approval: relay its preview and ask, as `pythia-mssql-apply` does.
5. **Stop when the lease pauses.** A write that breaks something, a
   `WRITTEN?` (a trigger ended the transaction), or five failures in a row
   pause it: show the developer the result before anything else. Exit 3 is
   still "broken", never "done".
6. **Report:** `pythia-mssql autopilot report` lists every write with its
   verdict and its restore. Relay it at the end, and `pythia-mssql
   autopilot off` when the task is done.

## What a lease never covers

Another connection, or one marked `"protected": true` (or an `"env"` of
prod / production / prd / live) in the connections file; a group the card
did not name; a destructive statement the card did not include; an UPDATE
or DELETE of more than 1000 rows; a change with a lint error; anything
after it expired, was spent, revoked or paused.

## Red Flags — STOP if you catch yourself thinking

| Thought | Reality |
|---------|---------|
| "I'll ask for all groups, to be safe" | Safe for whom? Ask for what the task needs. |
| "It paused, but the next write is unrelated" | Paused means stop and show the developer. |
| "Covered writes don't need reporting" | Every one is reported: `autopilot report`. |
| "I'll approve my own request" | Approval is the developer's, through a door. The guard denies the rest. |
