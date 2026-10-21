# Working in this repository / with this tool

pythia-mssql is pythia for SQL Server, on pythia-core. It is alpha (0.1.0):
it reads everything pythia's Learn movement needs, and writes through one
gate. `pythia-mssql install` wires a project: the guard, the session brief
and the `pythia-mssql-*` skills (`using-pythia-mssql` routes).

## Using pythia-mssql as an agent (Phase 4c)

1. **Ask the database, never the dump.** `ls`, `src`, `cols`, `ddl`, `grep`
   against the live schema; `check` says where unqualified names land (the
   login's default schema).
2. **Lint before apply.** `pythia-mssql lint <files>` — a change's files in
   one run. Errors are fixed, not argued; the team's `.pythia/mssql/
   conventions.md`, when it exists, is read before writing any object.
3. **Impact before change.** Run `pythia-mssql impact <NAME>` before
   proposing any modification. When it prints `! show this list to the
   developer` (10 or more dependents, or one in another schema), show the
   developer the list before writing code. Rows marked `[text]` are leads
   found by name in module text (dynamic SQL), not proofs. Relay the `blind
   spot` lines, and never call an impact list complete.
4. **Writes go through `pythia-mssql apply` (one statement per file) or
   `pythia-mssql deploy` (a release, one transaction) only.** Never write
   through `sqlcmd`, SSMS, `Invoke-Sqlcmd`, `bcp`, `sqlpackage` or a driver
   script: those have no snapshot, no rehearsal and no journal. Where
   `pythia-mssql install` wired the hooks, the guard denies them; where it
   did not, this rule still binds. No `STATE` line at session start means
   the hooks are not running: say so, and ask the developer to run
   `pythia-mssql doctor`.
5. **The developer sees every preview.** Relay `apply`'s preview verbatim:
   the diff, the rehearsal (what broke, or NOT VERIFIED), the rows, the
   destructive and trigger notes. Then ask through the first door that
   works, moving to the next unasked when one fails: on Claude Code an
   `AskUserQuestion` whose text is the output of `pythia-mssql approve
   --card <token>` verbatim (options Approve / Reject); then the
   `pythia_mssql_approve` tool (MCP — where Codex starts); then the
   developer's terminal, `pythia-mssql approve <token>`. Pass
   `--confirm <token>` only after the approval arrives. `--yes` and
   loosening `policy` are the developer's actions, at a console.
6. **Autopilot is the developer's delegation, not yours.** When they want
   you to work without per-write approvals, request the narrowest lease
   that fits (`pythia-mssql autopilot request`) and ask once through a door.
   Inside it, covered writes land without asking; outside it, the normal
   gate applies. A paused lease means stop and show the developer. Report
   every write with `pythia-mssql autopilot report`.
7. **Scope is what was asked.** Dependents that break are reported with a
   proposal, never fixed on your own initiative.
8. **Exit codes are the verdict:** `0` clean · `1` refused (relay the
   reason; do not route around it) · `3` written but broken — never report
   success; show the errors and the printed restore command. Never read
   `$?` through a pipe.
9. **`WRITTEN?` means it may be written.** When a trigger ended the
   transaction a rehearsal runs in, the preview itself may have committed
   the statement. Stop, show the developer the output verbatim, and let
   them look before anything else runs — never call it refused or
   unwritten.
10. **Restores are writes.** `journal restore` previews and needs the same
    approval as any apply.
11. **"Not verified" is said plainly.** `errors` binds every module now, the
    way SQL Server would when it runs; dynamic SQL inside a module is named
    as unchecked. Never report a `NOT VERIFIED` line as "no errors".
12. **Truncation is always announced.** If output has no truncation marker,
    you saw everything. If it has one, say so or fetch the rest with
    `--offset`.
13. **Never open `.pythia/mssql/connections.json`, or anything under
    `.pythia/mssql/grants/`.** The first holds passwords;
    `pythia-mssql connections` lists the names, users, schemas and targets
    without them. A grant written by anyone but `approve` is a forged
    approval.

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
- **Skills:** `src/pythia_mssql/skills/<name>/SKILL.md`, `name` = folder,
  prefixed `pythia-mssql-` (or `using-pythia-mssql`), description opening
  with `Use when` / `Use before`, a `**Phase:**` line, at most 150 lines
  (detail in `reference/`), and a row in `using-pythia-mssql`'s routing
  table. A test holds every one to it.
- **Docs never contradict code:** a behaviour change updates the docstring,
  README.md and README.vi.md, CHANGELOG.md and the affected skill in the
  same change. A test holds README.vi.md to README.md's headings and
  commands; the prose is translated by hand.
- **Versions** agree in pyproject.toml and `pythia_mssql.__version__`, the
  version has its CHANGELOG.md entry, and pythia-core is asked for within
  one release series (`pythia-core>=0.1.0,<0.2`). A test holds all three.

## Releasing

1. Once per project: a PyPI trusted publisher (pypi.org → your account →
   Publishing → add a pending publisher: project `pythia-mssql`, owner
   `thaildhe172591`, repository `pythia-mssql`, workflow `release.yml`,
   environment `pypi`). No token is stored anywhere.
2. pythia-core's release of the series is on PyPI first: this package asks
   for it.
3. The version in pyproject.toml and `__version__`, its CHANGELOG.md entry
   dated, and CI green on main.
4. `git tag vX.Y.Z && git push origin vX.Y.Z`: the `release` workflow runs
   the suite against pythia-core's main, checks the tag against the version
   and the changelog, and publishes.

## Never

- Read or write pythia for Oracle's files (`.pythia/connections.json`,
  `.pythia/journal/`) or another engine's (`.pythia/postgres/`), or take
  their commands or variables.
- Point the live check at a shared server: it creates a login and drops a
  database.
- Field-test `pythia-mssql install` inside this repository:
  `src/pythia_mssql/skills/` is the source pack. Use a scratch directory.
- Put real-world identifiers anywhere (hosts, schemas, tenants,
  credentials). Examples use APP_OWNER, PKG_ORDER, T_ORDER. Everything
  shipped is English, but for README.vi.md, the README's translation.
