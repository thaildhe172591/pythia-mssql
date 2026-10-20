---
name: pythia-mssql-impact
description: Use before proposing or writing any change to a SQL Server object - a procedure, function, trigger, view, table, column, sequence or type. Impact analysis comes first, because what depends on an object decides how careful the change must be.
---

# Impact Before Change

**Announce at start:** "Using pythia-mssql-impact to measure the blast radius first."

**Phase:** Learn — and the first Ask gate: a large blast radius reaches the developer before any code is written

A dropped column breaks every view and procedure that reads it — when they
next run, not when the column goes: SQL Server keeps a module whose names
no longer resolve. The cost of knowing first is one command.

## The Iron Law

```
NO CHANGE PROPOSED WITHOUT ITS IMPACT MEASURED FIRST
```

## The Workflow

1. `pythia-mssql impact <name> --depth 2` — everything that depends on it,
   as a tree, ending with the summary:
   `-- impact: N dependent objects (... matched by name as text ...)`.
2. `pythia-mssql deps <name> --depth 2` — the other direction, what it uses;
   read it when the change touches calls or table access.
3. `pythia-mssql errors` — the baseline. Anything broken before the change
   must not be blamed on it later.

## Reading the numbers

| Result | What to do |
|---|---|
| 0 dependents | Say so, with the output as evidence, and proceed. |
| 1–9 dependents | List them to the developer alongside the proposal. |
| `! show this list to the developer` (10+, or one in another schema) | Show the tree and get an explicit go-ahead **before writing any code**. |
| `[text]` rows | Leads found by name in module text (dynamic SQL): name them as such. |
| `-- blind spot:` lines | Relay them. Never call the list complete. |

What counts: views, procedures, functions and triggers that reference it,
triggers on a table, foreign keys pointing at it, and check and default
constraints (counted as their table — a default drawing from a sequence
makes the table depend on it). A `WITH SCHEMABINDING` view blocks the
change outright: the rehearsal fails rather than breaks it.

## Red Flags — STOP if you catch yourself thinking

| Thought | Reality |
|---------|---------|
| "It's just a small helper" | Helpers are the most-depended-on objects there are. |
| "I'll check impact after writing the code" | Then the number cannot change the design. Too late. |
| "The catalog shows no dependents, so nothing calls it" | Dynamic SQL, other databases and linked servers are not in it — read the `[text]` rows and blind spots. |
| "apply's preview shows what breaks anyway" | That confirms a number you should already know; it is not discovery. |

## Hand-off

Impact known and acceptable → write the change (one statement per file) →
`pythia-mssql-apply` to land it through the gate.
