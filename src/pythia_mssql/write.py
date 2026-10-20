"""The write tier for SQL Server: reading T-SQL, and rehearsing a statement
inside the transaction pythia-core owns.

SQL Server runs DDL inside a transaction, so a statement can be run,
checked and rolled back. What PostgreSQL's plpgsql_check does there,
sys.dm_sql_referenced_entities does here: every module that depends on what
changed is bound before and after the statement, and what fails only after
is what the statement broke. sp_refreshsqlmodule cannot be used — when it
fails it rolls back the caller's whole transaction. A trigger can end the
caller's transaction too, with COMMIT or ROLLBACK: the statement runs one
transaction level down, and a transaction that ends anyway is reported as
escaped unless the database's triggers show it was rolled back.

A statement is read with T-SQL's own quoting: '...' and N'...' strings
(doubled quotes inside), [bracketed] and "quoted" identifiers, -- and
nested /* */ comments. A module (CREATE PROCEDURE and the like) takes its
whole batch, as SQL Server does; anything else ends at its ';'.
"""
import re
import sys

from .catalog import fold, q, sql_of
from .read import MODULE_TYPES, bind_findings, dependents, error_text

SAMPLE_ROWS = 10
LOCK_TIMEOUT = "5 s"


class Lexed:
    def __init__(self, masked, cuts, unterminated, uncommented):
        self.masked = masked                # same length; literal and comment contents blanked
        self.uncommented = uncommented      # same length; only comments blanked
        self.cuts = cuts                    # positions of statement-ending ;
        self.unterminated = unterminated    # ends inside a quote or a comment


def lex(text):
    """Blank out string contents, delimited identifiers and comments (every
    position and newline kept, the quote characters too), and find the
    semicolons that end statements."""
    out, bare = list(text), list(text)
    cuts, unterminated = [], False
    n, i = len(text), 0

    def blank(a, b, comment=False):
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "
                if comment:
                    bare[k] = " "

    def closing(i, close):
        """Index just past the closing quote (a doubled one is an escape)."""
        j = i + 1
        while j < n:
            if text[j] == close:
                if text.startswith(close * 2, j):
                    j += 2
                    continue
                return j + 1, True
            j += 1
        return n, False

    while i < n:
        c = text[i]
        if text.startswith("--", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            blank(i, j, comment=True)
            i = j
        elif text.startswith("/*", i):
            depth, j = 1, i + 2                     # SQL Server nests them
            while j < n and depth:
                if text.startswith("/*", j):
                    depth, j = depth + 1, j + 2
                elif text.startswith("*/", j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            unterminated |= depth > 0
            blank(i, j, comment=True)
            i = j
        elif c in "'\"[":
            j, closed = closing(i, "]" if c == "[" else c)
            unterminated |= not closed
            blank(i + 1, j - 1 if closed else n)    # the delimiters stay
            i = j
        else:
            if c == ";":
                cuts.append(i)
            i += 1
    return Lexed("".join(out), cuts, unterminated, "".join(bare))


_GO = re.compile(r"(?im)^[ \t]*go(?:[ \t]+(\d+))?[ \t]*$")
_MODULE = re.compile(r"\s*(?:create(?:\s+or\s+alter)?|alter)\s+"
                     r"(proc|procedure|function|view|trigger)\b", re.I)


def _batches(text):
    """(offset, batch, repeat, where its GO stands) between GO lines, read
    where no string or comment hides them."""
    masked = lex(text).masked
    out, start = [], 0
    for m in _GO.finditer(masked):
        go = m.start() + len(m.group(0)) - len(m.group(0).lstrip())
        out.append((start, text[start:m.start()], int(m.group(1) or 1), go))
        start = m.end()
    out.append((start, text[start:], 1, len(text)))
    return out


def _pieces(offset, batch):
    """(offset, statement) in one batch: anything ends at its ';', but a
    module's body runs to the end of the batch, as in SQL Server."""
    lexed = lex(batch)
    out, start = [], 0
    for cut in lexed.cuts + [len(batch)]:
        if _MODULE.match(lexed.masked[start:]):
            # a module's body runs to the end of its batch, ';' or not
            out.append((offset + start, batch[start:]))
            return out
        if lexed.masked[start:cut].strip():
            out.append((offset + start, batch[start:cut]))
        start = cut + 1
    return out


def split_script(text):
    """(line, statement) for each statement of a script, cut where SQL
    Server's tools cut it: at GO lines, then at ';' outside a module. The
    line is where the statement's code starts."""
    out = []
    for offset, batch, repeat, go in _batches(text):
        for start, piece in _pieces(offset, batch):
            code = lex(piece).masked
            first = start + len(code) - len(code.lstrip())
            out.append((text.count("\n", 0, first) + 1, piece.strip()))
        if repeat != 1:
            out.append((text.count("\n", 0, go) + 1, f"GO {repeat}"))
    return out


def split_statements(text):
    return [s for _, s in split_script(text)]


def _code(stmt):
    """The statement's code: literals and comments blanked, lower case, one
    space between words."""
    return " ".join(lex(stmt).masked.lower().split())


TXN = ("pythia-mssql owns the transaction: it rolls a preview back and commits "
       "only an approved write. Leave transaction control out of the file.")
FLOW = ("T-SQL control flow (IF, WHILE, DECLARE, BEGIN ... END) is an anonymous "
        "batch: it can do anything, so no policy group honestly fits. Put the "
        "logic in a procedure and apply that.")
NONTX = ("This statement cannot run inside a transaction, so pythia-mssql can "
         "neither rehearse it nor roll it back. Run it by hand, with a DBA "
         "watching.")
SERVER = ("Logins and other server-level objects live outside this database, "
          "and pythia-mssql writes inside one database. A DBA runs it by hand.")
CANNOT = ("Cannot classify this statement, so it is refused rather than guessed "
          "at. apply takes one CREATE [OR ALTER] PROCEDURE / FUNCTION / VIEW / "
          "TRIGGER, an MS_Description extended property, INSERT / UPDATE / "
          "DELETE, DDL, GRANT / REVOKE / DENY or SET statement per file.")
MANY = ("{n} statements in one file — apply takes one statement per file, so "
        "each is previewed, approved and journaled on its own (deploy takes a "
        "script). End every statement with ';'.")

RULES = (
    (r"(begin (tran|transaction|distributed)|commit|rollback|save (tran|transaction)|"
     r"set (transaction|implicit_transactions))\b", None, TXN),
    (r"(if|while|declare|begin|return|print|raiserror|throw|waitfor|goto|break|"
     r"continue)\b", None, FLOW),
    (r"use\b", None, "USE changes the database for every later statement. Connect "
     "to the right database instead (a connection, --conn)."),
    (r"with\b", None, "A WITH statement is refused: a CTE in front of an UPDATE "
     "or DELETE hides which rows it touches. Write it as a plain statement."),
    (r"(select|values)\b", None, "apply takes writes; reads go through ls, src, "
     "cols and grep — and a SELECT can call a function that writes, or create a "
     "table with INTO, so it is refused, not run."),
    (r"exec(ute)?\b", "exec", None),
    (r"((create|alter|drop) database|backup|restore|reconfigure|"
     r"(create|alter|drop) fulltext)\b", None, NONTX),
    (r"((create|alter|drop) (login|server|endpoint|availability|credential|"
     r"master key|resource pool|workload)|alter server)\b", None, SERVER),
    (r"create (table|procedure|proc) #", None, "A temporary object dies with this "
     "connection, which ends after the command: nothing would be left to verify "
     "or undo."),
    (r"((create( or alter)?|alter) (proc|procedure|function|view|trigger))\b",
     "source", None),
    (r"update statistics\b", "structural", None),
    (r"(insert|update|delete|merge)\b", "data_dml", None),
    (r"(grant|revoke|deny)\b|(create|alter|drop) (user|role|application role)\b|"
     r"alter authorization\b", "grants", None),
    (r"set\b", "session", None),
    (r"(create|alter|drop|truncate|enable|disable)\b", "structural", None),
)

EXTPROP = ("sp_addextendedproperty", "sp_updateextendedproperty",
           "sp_dropextendedproperty")
_ARG = re.compile(r"@(\w+)\s*=\s*(N?'(?:[^']|'')*'|[\w.]+)", re.I)
_STARTERS = ("insert", "update", "delete", "merge", "truncate", "grant", "revoke",
             "deny", "exec", "execute", "declare", "use", "print")
_OBJECTS = ("table", "view", "procedure", "proc", "function", "trigger", "index",
            "schema", "sequence", "type", "synonym", "user", "role", "login",
            "database", "statistics", "unique", "clustered", "nonclustered")


def _unquote(value):
    v = value.strip()
    if v[:1] in "Nn" and v[1:2] == "'":
        v = v[1:]
    if v[:1] == "'" and v[-1:] == "'":
        return v[1:-1].replace("''", "'")
    return None if v.upper() == "NULL" else v


def _exec_target(code):
    m = re.match(r"exec(?:ute)?\s+(?:@\w+\s*=\s*)?([\w.\[\]\"]+)", code)
    return m.group(1).split(".")[-1].strip('[]"') if m else ""


def extended_property(stmt):
    """(verb, {argument: value}) of an MS_Description call, or (None, why)."""
    proc = _exec_target(_code(stmt))
    args = {k.lower(): _unquote(v) for k, v in _ARG.findall(lex(stmt).uncommented)}
    if not args:
        return None, (f"{proc}: the arguments must be named (@name = "
                      "N'MS_Description', @level0name = ...) — pythia reads them "
                      "by name, never by position.")
    if str(args.get("name") or "").lower() != "ms_description":
        return None, ("Only MS_Description — the comment SQL Server's tools read "
                      "— is snapshotted and restorable; other extended "
                      "properties are refused.")
    if str(args.get("level0type") or "").upper() != "SCHEMA" or \
            str(args.get("level1type") or "").upper() not in ("TABLE", "VIEW") or \
            str(args.get("level2type") or "COLUMN").upper() != "COLUMN":
        return None, ("Only a table's, a view's or a column's MS_Description is "
                      "snapshotted and restorable: @level0type = N'SCHEMA', "
                      "@level1type = N'TABLE' or N'VIEW', and optionally "
                      "@level2type = N'COLUMN'.")
    if not args.get("level0name") or not args.get("level1name"):
        return None, "Name the schema and the object: @level0name and @level1name."
    return proc.replace("sp_", "").replace("extendedproperty", ""), args


def _many_without_semicolons(stmt):
    """A second statement on a later line, with no ';' between: T-SQL makes
    the terminator optional, so a file can hold two statements that read as
    one."""
    lines = [ln.split() for ln in lex(stmt).masked.lower().split("\n")]
    words = [w for w in lines if w]
    for w in words[1:]:
        if w[0] in _STARTERS:
            return True
        if w[0] in ("create", "alter", "drop") and len(w) > 1 and w[1] in _OBJECTS:
            return True
    return False


def classify(text):
    """(group, None) or (None, why it is refused)."""
    lexed = lex(text)
    if lexed.unterminated:
        return None, ("The file ends inside a quote, a [bracket] or a comment, "
                      "so it cannot be read safely — refused.")
    repeats = [b[2] for b in _batches(text) if b[2] != 1]
    if repeats:
        return None, (f"GO {repeats[0]} runs its batch {repeats[0]} times; "
                      "pythia runs every statement once, as it was previewed. "
                      "Write each statement out in the script instead.")
    batches = [b for b in _batches(text) if lex(b[1]).masked.strip()]
    if len(batches) > 1:
        return None, ("GO separates batches in a script: apply takes one "
                      "statement per file, and deploy takes a script.")
    stmts = split_statements(text)
    if not stmts:
        return None, "The file holds no statement."
    for pattern, _group, why in RULES[:2]:  # BEGIN ... ; ... END reads as several
        if re.match(pattern, _code(stmts[0])):
            return None, why
    if len(stmts) > 1:
        return None, MANY.format(n=len(stmts))
    code = _code(stmts[0])
    for pattern, group, why in RULES:
        if re.match(pattern, code):
            if group == "exec":
                return _classify_exec(stmts[0], code)
            if group and group != "source" and _many_without_semicolons(stmts[0]):
                return None, MANY.format(n="Several")
            return group, why
    return None, CANNOT


def _classify_exec(stmt, code):
    proc = _exec_target(code).lower()
    if proc in EXTPROP:
        verb, why = extended_property(stmt)
        return ("comments", None) if verb else (None, why)
    if proc == "sp_rename":
        return "structural", None
    return None, ("EXEC runs a procedure's body, which can do anything — no "
                  "policy group honestly fits. Run it by hand, or apply the "
                  "statements it would run.")


def prepare_statement(text, group):
    return split_statements(text)[0]


_NAME = (r'(?P<schema>(?:\[(?:[^\]]|\]\])*\]|"(?:[^"]|"")*"|[\w@#$]+)\s*\.\s*)?'
         r'(?P<name>\[(?:[^\]]|\]\])*\]|"(?:[^"]|"")*"|[\w@#$]+)')
_SOURCE_HEAD = re.compile(r"\s*(?:create(?:\s+or\s+alter)?|alter)\s+"
                          r"(proc|procedure|function|view|trigger)\s+" + _NAME, re.I)
_KIND = {"proc": "PROCEDURE", "procedure": "PROCEDURE", "function": "FUNCTION",
         "view": "VIEW", "trigger": "TRIGGER"}


def _qualified(m):
    """(schema or None, name) from a match of _NAME, as SQL Server reads them."""
    part = m.group("schema")
    return (fold(part.strip().rstrip(".").strip()) if part else None,
            fold(m.group("name")))


def parse_object(stmt, group):
    """{type, name, schema or None} as SQL Server reads the name."""
    if group == "source":
        m = _SOURCE_HEAD.match(lex(stmt).uncommented)
        if not m:
            return None
        schema, name = _qualified(m)
        return {"type": _KIND[m.group(1).lower()], "name": name, "schema": schema}
    if group == "comments":
        verb, args = extended_property(stmt)
        if not verb:
            return None
        table, column = args["level1name"], args.get("level2name")
        return {"type": "COMMENT", "name": f"{table}.{column}" if column else table,
                "schema": args["level0name"], "table": table, "column": column,
                "kind": str(args["level1type"]).upper(), "value": args.get("value"),
                "verb": verb}
    return None


def destructive_reason(stmt, group):
    """Why no journal brings this statement's work back, or None."""
    code = _code(stmt)
    if group == "structural":
        if code.startswith("drop "):
            return "DROP removes the object and everything in it"
        if code.startswith("truncate "):
            return "TRUNCATE empties the table — no journal brings the rows back"
        if re.match(r"alter table\b.*\bdrop (column|constraint)\b", code):
            return "ALTER ... DROP removes a column or constraint, and a column's data"
        if re.match(r"alter table\b.*\balter column\b", code):
            return "changing a column's type rewrites it, and can lose data"
        if re.match(r"exec(ute)? (sys\.)?sp_rename\b", code):
            return ("sp_rename renames it, and breaks every module that still "
                    "uses the old name")
    if group == "data_dml" and re.match(r"(update|delete)\b", code):
        if not re.search(r"\bwhere\b", code):
            return "no WHERE clause — it touches every row in the table"
        if re.search(r"\bwhere\s*\(?\s*(1\s*=\s*1|0\s*=\s*0)\s*\)?\s*$", code):
            return "a WHERE clause that is always true touches every row"
    if group == "grants":
        if code.startswith("revoke "):
            return "REVOKE takes a privilege away from whoever relied on it"
        if code.startswith("deny "):
            return "DENY overrides every grant the principal holds, through any role"
        if re.search(r"\bto public\b", code):
            return "granted to public — every user in the database holds it"
        if re.match(r"drop (user|role)\b", code):
            return "DROP removes the principal and everything granted to it"
    return None


def _refuse_probe(why):
    sys.exit(f"Refused: {why} The rows an UPDATE or DELETE touches are shown "
             "and revalidated before it is approved, so a statement whose rows "
             "cannot be read beforehand is refused.")


def dml_probe(stmt):
    """(target, predicate or None) of an UPDATE or DELETE; None for INSERT.
    Read from the statement with its comments blanked, so a trailing comment
    never swallows what the probe appends."""
    code = _code(stmt)
    text = " ".join(lex(stmt).uncommented.split())
    if code.startswith("merge "):
        _refuse_probe("MERGE's row set cannot be shown before it runs; write "
                      "it as INSERT, UPDATE and DELETE.")
    if not re.match(r"(update|delete)\b", code):
        return None
    if re.match(r"(update|delete)\s+top\b", code):
        _refuse_probe("UPDATE / DELETE TOP (n): which rows is decided as it runs.")
    if re.search(r"\boutput\b", code):
        _refuse_probe("OUTPUT returns the rows it changed; apply the statement "
                      "without it.")
    if re.search(r"\bwhere current of\b", code):
        _refuse_probe("WHERE CURRENT OF needs a cursor.")
    if code.startswith("update "):
        m = re.match(r"update\s+" + _NAME + r"\s+set\b", text, re.I)
    else:
        m = re.match(r"delete\s+(?:from\s+)?" + _NAME + r"(?=\s|$)", text, re.I)
    if not m:
        _refuse_probe("the target table could not be read.")
    rest_code = _code(text[m.end():])
    depth = 0
    for ch in rest_code:
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if depth < 0:
            break
    if depth:
        # the probe runs `where (<predicate>)`: a predicate that closes it
        # would put a statement of its own into the probe's batch
        _refuse_probe("the WHERE clause's parentheses do not balance.")
    if re.search(r"\(\s*select\b", rest_code):
        _refuse_probe("a subquery in WHERE reads other tables as it runs.")
    if re.search(r"\b(from|join)\b", rest_code):
        _refuse_probe("FROM or a JOIN brings in another table; the rows it "
                      "touches cannot be read from its own WHERE.")
    target = text[m.start("schema") if m.group("schema") else m.start("name"):
                  m.end("name")].strip()
    w = re.search(r"\bwhere\b", text[m.end():], re.I)
    pred = text[m.end():][w.end():].strip() if w else None
    return target, pred or None


def _run_text(conn, sql):
    """Statement text runs exactly as written: no binds, so pymssql reads no
    placeholder in it."""
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall() if cur.description else []
        return cols, rows, cur.rowcount


def measure_row_set(conn, target, pred):
    def fill(name):
        return (sql_of(name).replace("/*TARGET*/", target)
                .replace("/*WHERE*/", f"({pred})" if pred else "1 = 1"))
    from .read import error_text as _err
    try:
        _, agg, _ = _run_text(conn, fill("row-set-count.sql"))
        cols, rows, _ = _run_text(conn, fill("row-set-sample.sql"))
    except Exception as e:                    # noqa: BLE001 — refused, not guessed
        sys.exit("Refused: pythia-mssql could not measure the rows this statement "
                 f"would touch.\n  {target} — {_err(e)[1]}\nRevalidation is "
                 "mandatory for UPDATE and DELETE, so a set that cannot be "
                 "measured cannot be approved.")
    n, fingerprint = agg[0]
    from pythia_core.output import cell
    return {"target": target, "predicate": pred or "", "count": int(n or 0),
            "hash": str(fingerprint), "columns": [str(c).upper() for c in cols],
            "sample": [[cell(v) for v in r] for r in rows[:SAMPLE_ROWS]],
            "truncated": len(rows) > SAMPLE_ROWS}


def _quoted(schema, name):
    return f"[{schema.replace(']', ']]')}].[{name.replace(']', ']]')}]"


def snapshot(conn, schema, group, ident):
    """What the statement could replace, as it stands: a module's definition,
    or a comment. An encrypted module has none to snapshot, and is refused."""
    if group == "source":
        objid, definition = q(conn, "module-definition.sql",
                              q=_quoted(ident.get("schema") or schema, ident["name"]))[1][0]
        if objid is None:
            return {}
        if definition is None:
            sys.exit(f"Refused: {ident['name']} exists but its definition cannot "
                     "be read — it is WITH ENCRYPTION, or this login lacks VIEW "
                     "DEFINITION — so there is nothing to snapshot and no way back.")
        return {ident["name"]: str(definition)}
    if group == "comments":
        rows = q(conn, "comment-current.sql", s=ident.get("schema") or schema,
                 t=ident["table"], c=ident.get("column"))[1]
        return {ident["name"]: rows[0][0] or ""} if rows else {}
    return {}


_TARGETS = (
    re.compile(r"\s*(?:alter|drop)\s+table\s+(?:if\s+exists\s+)?" + _NAME, re.I),
    re.compile(r"\s*drop\s+(?:view|proc|procedure|function|trigger|synonym)\s+"
               r"(?:if\s+exists\s+)?" + _NAME, re.I),
    re.compile(r"\s*(?:create|drop)\s+(?:unique\s+)?(?:(?:non)?clustered\s+)?"
               r"index\s+\S+\s+on\s+" + _NAME, re.I),
    re.compile(r"\s*truncate\s+table\s+" + _NAME, re.I),
)


def changed_object(stmt, group, ident, schema):
    """(schema, name) of what a statement changes, when it can be read."""
    if ident and group == "source":
        return ident.get("schema") or schema, ident["name"]
    text = lex(stmt).uncommented
    for pattern in _TARGETS:
        m = pattern.match(text)
        if m:
            s, n = _qualified(m)
            return s or schema, n
    m = re.match(r"\s*exec(?:ute)?\s+(?:sys\.)?sp_rename\s+N?'([^']*)'", text, re.I)
    if m:
        parts = [fold(p) for p in m.group(1).split(".")]
        return (parts[0], parts[1]) if len(parts) > 1 else (schema, parts[0])
    return None


def _modules_around(conn, schema, target):
    """The modules to bind before and after: the changed object and what
    depends on it, two levels down (a view on a view breaks too)."""
    if not target:
        return []
    t_schema, t_name = target
    mods = []
    found = dependents(conn, t_schema, t_name, 2)
    if found is not None:
        mods = [(n, t, _quoted(s, n)) for _lvl, s, n, t, _how in found[0]
                if t in MODULE_TYPES]
    return sorted(set(mods))


def rehearse(conn, schema, group, stmt, ident, snap, errors=Exception):
    """Run the statement in the open transaction and verify it. Core rolls
    back after a preview and commits an approved confirm.

    The statement runs one transaction level down. A trigger's COMMIT then
    ends only that level, so it commits nothing; core's level is the only
    one that commits. A trigger that commits further, or rolls back, ends
    core's transaction too: @@TRANCOUNT reaches 0, or the transaction's id
    changes. pythia then reads every trigger in the database — if one could
    have committed, the outcome is `escaped` (core exits 3); if none could,
    a trigger rolled the statement back and nothing was written."""
    _run_text(conn, sql_of("rehearsal-settings.sql"))
    checked = group in ("source", "structural")
    target = changed_object(stmt, group, ident, schema) if checked else None
    around = _modules_around(conn, schema, target) if checked else []
    before = bind_findings(conn, around, errors) if around else set()
    known = _known(group, ident, schema)
    _, txn = _transaction(conn)
    _run_text(conn, sql_of("rehearsal-begin.sql"))
    failure, rowcount = None, None
    try:
        _, _, rowcount = _run_text(conn, stmt)
    except errors as e:
        failure = e
    count, now = _transaction(conn)
    if count == 0 or now != txn:
        return _ended(conn, failure, count, known)
    if failure is not None:
        number, message = error_text(failure)
        return {"error": f"{number}: {message}" if number else message}
    _run_text(conn, sql_of("rehearsal-level-up.sql"))
    out = {"error": None, "object": None, "type": None, "after": stmt,
           "rows": None, "broken": [], "own_errors": [], "verified": True,
           "blind": None, "notes": [], **known}
    if count < 2:
        out["notes"].append("a trigger issued COMMIT inside the statement: the "
                            "extra transaction level pythia-mssql rehearses in "
                            "kept it from committing anything — run any other "
                            "way, this statement ends with error 3609")
    if group == "source":
        definition = q(conn, "module-definition.sql", q=known["drop"])[1][0][1]
        out["after"] = str(definition) if definition is not None else stmt
    elif group == "comments":
        now_ = snapshot(conn, schema, group, ident)
        out.update(after=now_.get(ident["name"], ""), exists_after=bool(now_))
    elif group == "data_dml":
        out["rows"] = rowcount
        out["notes"].append("a rehearsal fires the statement's triggers and draws "
                            "IDENTITY values and sequence numbers: rolling back "
                            "undoes the rows, not those")
    elif group == "grants":
        out.update(verified=False, blind="who can still do what after a GRANT, "
                   "REVOKE or DENY is not something a rehearsal can check")
    elif group == "structural" and target:
        out.update(object=target[1])
    if checked:
        if group == "source":
            around = sorted(set(around) | {(ident["name"], ident["type"], known["drop"])})
        after = bind_findings(conn, around, errors) if around else set()
        own = sorted(f for f in after if group == "source" and f[0] == ident["name"])
        out["own_errors"] = own
        out["broken"] = sorted(f for f in after - before if f not in own)
        if not target:
            out.update(verified=False, blind="what this statement changes could "
                       "not be read from it, so no module was bound to check it")
        else:
            out["notes"].append(f"bound {len(around)} module(s) — {target[1]} and "
                                "what depends on it — before and after")
    return out


def _known(group, ident, schema):
    """What the outcome says before the statement runs: enough to restore
    from, even when the rehearsal escapes."""
    if group == "source":
        return {"object": ident["name"], "type": ident["type"], "schema": schema,
                "drop": _quoted(ident.get("schema") or schema, ident["name"])}
    if group == "comments":
        return {"object": ident["name"], "type": "COMMENT", "schema": schema,
                "exists_after": ident.get("verb") != "drop"}
    return {"schema": schema}


def _transaction(conn):
    """(@@TRANCOUNT, transaction id); (0, None) when the session cannot say."""
    try:
        count, txn = q(conn, "transaction-state.sql")[1][0]
        return int(count), txn
    except Exception:                         # noqa: BLE001 — a dead session: none
        return 0, None


_COULD_COMMIT = re.compile(r"\b(commit|exec|execute|sp_executesql)\b")
_ROLLS_BACK = re.compile(r"\brollback\b")


def read_triggers(conn):
    """(could commit, roll back) over the enabled triggers in this database:
    the names of those that could end a transaction with COMMIT — one that
    says COMMIT, runs other code (EXEC, dynamic SQL) or cannot be read — and
    whether any says ROLLBACK. None when the triggers cannot be listed."""
    try:
        rows = q(conn, "triggers-enabled.sql")[1]
    except Exception:                         # noqa: BLE001 — cannot tell
        return None
    could, rolls = [], False
    for _schema, name, definition in rows:
        if definition is None:
            could.append(f"{name} (its text cannot be read)")
            continue
        code = _code(str(definition))
        if _COULD_COMMIT.search(code):
            could.append(name)
        rolls |= bool(_ROLLS_BACK.search(code))
    return could, rolls


def _ended(conn, failure, count, known):
    """The transaction core owns ended inside the statement. Nothing was
    written only when that is the one reading the evidence allows."""
    number, said = (error_text(failure) if failure is not None else
                    (None, "the transaction ended inside the statement"))
    said = f"{number}: {said}" if number else said
    found = read_triggers(conn)
    if found is None:
        why = "the triggers could not be listed, so none can be ruled out"
    elif found[0]:
        names = ", ".join(found[0][:5]) + (f" and {len(found[0]) - 5} more"
                                           if len(found[0]) > 5 else "")
        why = (f"{names} can commit (a trigger that says COMMIT, runs other "
               "code or cannot be read)")
    elif found[1]:
        # pymssql reports the trigger's own RAISERROR or THROW, not 3609
        return {"error": f"{said} — a trigger rolled the statement back. No "
                "trigger in this database can commit, so nothing was written."}
    elif count == 0 and number == 1205:
        return {"error": f"{said} — SQL Server rolled the deadlock victim's "
                "transaction back. No trigger in this database can commit, so "
                "nothing was written."}
    else:
        why = ("no trigger in this database explains it — a server-level "
               "trigger, or one in another database, may have committed it")
    return {**known, "error": said, "escaped": why}


def _literal(text):
    return "N'" + str(text).replace("'", "''") + "'"


def _property_call(verb, ident, schema, value=None):
    text = f"EXEC sys.sp_{verb}extendedproperty @name = N'MS_Description'"
    if verb != "drop":
        text += f", @value = {_literal(value)}"
    text += (f", @level0type = N'SCHEMA', @level0name = {_literal(ident.get('schema') or schema)}"
             f", @level1type = N'{ident.get('kind') or 'TABLE'}', @level1name = "
             f"{_literal(ident['table'])}")
    if ident.get("column"):
        text += f", @level2type = N'COLUMN', @level2name = {_literal(ident['column'])}"
    return text


def restore_statement(group, ident, before, outcome):
    """The statement that puts back what this one replaced."""
    if group == "comments":
        schema = outcome.get("schema")
        if not before:
            return _property_call("drop", ident, schema)
        verb = "update" if outcome.get("exists_after", True) else "add"
        return _property_call(verb, ident, schema, before)
    if before:
        m = re.search(r"\bcreate\b", lex(before).masked, re.I)
        if m and not re.match(r"\s+or\s+alter\b", lex(before).masked[m.end():], re.I):
            word = before[m.start():m.end()]
            more = " OR ALTER" if word.isupper() else " or alter"
            return before[:m.end()] + more + before[m.end():]
        return before
    return f"DROP {ident['type']} {outcome['drop']}"


def privilege_warning(conn, schema):
    rows = q(conn, "session-power.sql")[1]
    if not rows:
        return None
    sysadmin, owner, login = rows[0]
    if sysadmin:
        return (f"! {login} is sysadmin: it can do far more than this change needs. "
                "A login with only the rights the change needs is safer.")
    if owner:
        return (f"! {login} is db_owner of this database: it can do far more than "
                "this change needs.")
    return None
