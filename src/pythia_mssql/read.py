"""The read tier for SQL Server: pythia's Learn movement, asked of the live
catalog.

SQL Server records more than PostgreSQL in one place that matters:
sys.sql_expression_dependencies sees into every module, procedures
included, and keeps a reference by name even when the object did not exist
yet. What it never sees is dynamic SQL — a name inside a string handed to
EXEC or sp_executesql. The dependency walks therefore ask twice, the catalog
and then a whole-word search of module text, and mark what only the search
vouches for (how = "text"), naming that blind spot every time.

`errors` binds each module now with sys.dm_sql_referenced_entities: a
missing table or column raises the error SQL Server would raise when the
module runs. sp_refreshsqlmodule would do the same, but a failure there
rolls back the caller's whole transaction — useless inside a rehearsal
(DESIGN.md §8).
"""
import re

from pythia_core.output import TEXT_HOW

from .catalog import fold, like_contains, q

CATALOG_HOW = "catalog"
MODULE_TYPES = ("VIEW", "PROCEDURE", "FUNCTION", "TRIGGER")
COLUMN_TYPES = ("TABLE", "VIEW")

DDL_NOTE = ("-- rebuilt from the catalog by pythia-mssql; SSMS's Generate "
            "Scripts is the reference. GO ends each batch.")

BLIND_TEXT_IN = (
    "dynamic SQL (EXEC of a string, sp_executesql) is not in "
    "sys.sql_expression_dependencies, so module text is also matched by "
    "name ([text]): a variable or column with the same name gives a false "
    "match, and a name built from pieces at run time is not seen at all")
BLIND_TEXT_OUT = (
    "a module's text is read against the names of existing objects only for "
    "what the catalog did not record; a name built at run time is not seen")
BLIND_ELSEWHERE = (
    "other databases on this server reference objects here by three-part "
    "name, and linked servers by four: neither is seen from this database")


def resolve(conn, schema, name):
    """(objid, type, label, bare_name) of the object holding a name."""
    return q(conn, "resolve.sql", s=schema, n=fold(name))[1]


def object_names(conn, schema, pattern, fetch):
    return q(conn, "object-names.sql", s=schema, p=pattern, n=int(fetch))


def split_definition(definition):
    return str(definition).replace("\r\n", "\n").rstrip("\n").split("\n")


def source(conn, schema, name):
    rows = []
    for unit, definition in q(conn, "source.sql", s=schema, n=fold(name))[1]:
        if definition is None:
            continue                     # encrypted, or no VIEW DEFINITION
        rows.extend((unit, i, line)
                    for i, line in enumerate(split_definition(definition), 1))
    return rows


def columns(conn, schema, name):
    rel = [r for r in resolve(conn, schema, name) if r[1] in COLUMN_TYPES]
    if not rel:
        return None
    return q(conn, "columns.sql", objid=rel[0][0])


# --- ddl ----------------------------------------------------------------------------

def _literal(text):
    return "N'" + str(text).replace("'", "''") + "'"


def table_ddl(conn, objid):
    qname = q(conn, "table-head.sql", objid=objid)[1][0][0]
    body = []
    for (cname, dtype, nullable, dname, ddef, identity, seed, incr, computed,
         persisted, collation) in q(conn, "table-columns.sql", objid=objid)[1]:
        if computed is not None:
            col = f"    {cname} AS {computed}" + (" PERSISTED" if persisted else "")
        else:
            col = f"    {cname} {dtype}"
            if collation:
                col += f" COLLATE {collation}"
            if identity:
                col += f" IDENTITY({seed},{incr})"
            col += " NULL" if nullable else " NOT NULL"
            if ddef is not None:
                col += f" CONSTRAINT [{dname}] DEFAULT {ddef}" if dname else f" DEFAULT {ddef}"
        body.append(col)
    keys = {}
    for name, kind, itype, col, _ordinal, desc in q(conn, "table-keys.sql", objid=objid)[1]:
        keys.setdefault((name, kind, itype), []).append(col + (" DESC" if desc else ""))
    for (name, kind, itype), cols in keys.items():
        what = "PRIMARY KEY" if kind == "PK" else "UNIQUE"
        body.append(f"    CONSTRAINT {name} {what} {itype} ({', '.join(cols)})")
    fks = {}
    for name, col, rtable, rcol, on_delete, on_update in q(
            conn, "table-foreign-keys.sql", objid=objid)[1]:
        fk = fks.setdefault(name, {"cols": [], "rcols": [], "rtable": rtable,
                                   "del": on_delete, "upd": on_update})
        fk["cols"].append(col)
        fk["rcols"].append(rcol)
    for name, fk in fks.items():
        text = (f"    CONSTRAINT {name} FOREIGN KEY ({', '.join(fk['cols'])}) "
                f"REFERENCES {fk['rtable']} ({', '.join(fk['rcols'])})")
        for verb, action in (("DELETE", fk["del"]), ("UPDATE", fk["upd"])):
            if action and action != "NO_ACTION":
                text += f" ON {verb} {action.replace('_', ' ')}"
        body.append(text)
    body.extend(f"    CONSTRAINT {name} CHECK {definition}" for name, definition in
                q(conn, "table-checks.sql", objid=objid)[1])
    batches = [f"CREATE TABLE {qname} (\n" + ",\n".join(body) + "\n);"]
    indexes = {}
    for name, unique, itype, filt, col, included, desc in q(
            conn, "table-indexes.sql", objid=objid)[1]:
        ix = indexes.setdefault(name, {"unique": unique, "type": itype,
                                       "filter": filt, "keys": [], "incl": []})
        (ix["incl"] if included else ix["keys"]).append(col + (" DESC" if desc and not included else ""))
    for name, ix in indexes.items():
        text = (f"CREATE {'UNIQUE ' if ix['unique'] else ''}{ix['type']} INDEX "
                f"{name} ON {qname} ({', '.join(ix['keys'])})")
        if ix["incl"]:
            text += f" INCLUDE ({', '.join(ix['incl'])})"
        if ix["filter"]:
            text += f" WHERE {ix['filter']}"
        batches.append(text + ";")
    for schema_name, table_name, column, comment in q(
            conn, "table-comments.sql", objid=objid)[1]:
        text = (f"EXEC sys.sp_addextendedproperty @name = N'MS_Description', "
                f"@value = {_literal(comment)}, @level0type = N'SCHEMA', "
                f"@level0name = {_literal(schema_name)}, @level1type = N'TABLE', "
                f"@level1name = {_literal(table_name)}")
        if column is not None:
            text += f", @level2type = N'COLUMN', @level2name = {_literal(column)}"
        batches.append(text + ";")
    batches.extend(str(d).strip() for (d,) in q(conn, "table-triggers.sql", objid=objid)[1]
                   if d is not None)
    return "\nGO\n".join(batches) + "\nGO"


def sequence_ddl(conn, objid):
    (qname, dtype, start, incr, low, high, cycling, cache,
     cached) = q(conn, "sequence-ddl.sql", objid=objid)[1][0]
    text = (f"CREATE SEQUENCE {qname} AS {dtype} START WITH {start} INCREMENT BY "
            f"{incr} MINVALUE {low} MAXVALUE {high} {'CYCLE' if cycling else 'NO CYCLE'} ")
    text += f"CACHE {cache}" if cached and cache else ("CACHE" if cached else "NO CACHE")
    return text + ";\nGO"


def ddl(conn, schema, name):
    objs = resolve(conn, schema, name)
    if not objs:
        return ""
    objid, otype, label, _bare = objs[0]
    if otype == "TABLE":
        return DDL_NOTE + "\n\n" + table_ddl(conn, objid)
    if otype == "SEQUENCE":
        return sequence_ddl(conn, objid)
    if otype in MODULE_TYPES:
        defs = [d for _u, d in q(conn, "source.sql", s=schema, n=fold(name))[1]]
        if not defs or defs[0] is None:
            return (f"-- {label}: no definition is readable — the module is "
                    "encrypted, or this account lacks VIEW DEFINITION")
        return str(defs[0]).replace("\r\n", "\n").strip() + "\nGO"
    return (f"-- {label}: pythia-mssql does not rebuild the DDL of a {otype} "
            "yet; SSMS's Generate Scripts is the reference")


GREP_COLS = ("NAME", "TYPE", "LINE", "TEXT")


def grep(conn, schema, text, fetch):
    needle = str(text).lower()
    out = []
    for unit, otype, definition in q(conn, "grep.sql", s=schema,
                                     p=like_contains(text))[1]:
        for i, line in enumerate(split_definition(definition or ""), 1):
            if needle in line.lower():
                out.append((unit, otype, i, line.strip()))
                if len(out) >= fetch:
                    return GREP_COLS, out
    return GREP_COLS, out


# --- dependency walks -----------------------------------------------------------------

def word_re(name):
    """name as a whole word, bracketed or not, in any case."""
    return re.compile(r"(?<![\w@#$])\[?" + re.escape(name) + r"\]?(?![\w$#])", re.I)


def walk(roots, depth, children):
    """Depth-first from each root, in the order a tree is read. An object
    reached twice is listed twice (that is the graph) but walked once."""
    rows, seen = [], {r[0] for r in roots}

    def visit(node, level):
        if level > depth:
            return
        for schema, name, otype, objid, how in children(node):
            rows.append((level, schema, name, otype, how))
            if objid is not None and objid not in seen:
                seen.add(objid)
                visit((objid, otype, name, schema), level + 1)

    for objid, otype, label, bare_name in roots:
        visit((objid, otype, bare_name, None), 1)
    return rows


def dependents(conn, schema, name, depth):
    roots = resolve(conn, schema, name)
    if not roots:
        return None

    def children(node):
        objid, _otype, bare_name, node_schema = node
        out = [(s, n, t, o, CATALOG_HOW) for s, n, t, o in q(
            conn, "dependents-catalog.sql", objid=objid,
            s=node_schema or schema, n=bare_name)[1]]
        seen = {o for *_, o, _ in out}
        pattern = word_re(bare_name)
        for s, n, t, o, definition in q(conn, "dependents-text.sql",
                                        p=like_contains(bare_name), objid=objid)[1]:
            if o not in seen and pattern.search(definition or ""):
                seen.add(o)
                out.append((s, n, t, o, TEXT_HOW))
        return out

    return walk(roots, depth, children), [BLIND_TEXT_IN, BLIND_ELSEWHERE]


def dependencies(conn, schema, name, depth):
    roots = resolve(conn, schema, name)
    if not roots:
        return None

    def children(node):
        return [(s, n, t, o, CATALOG_HOW) for s, n, t, o in
                q(conn, "dependencies-catalog.sql", objid=node[0])[1]]

    return walk(roots, depth, children), [BLIND_TEXT_OUT, BLIND_ELSEWHERE]


# --- errors -----------------------------------------------------------------------------

def error_text(exc):
    """(number, first line of the message) of a driver error."""
    args = getattr(exc, "args", ()) or ()
    number = args[0] if args and isinstance(args[0], int) else None
    raw = args[1] if len(args) > 1 else (args[0] if args else exc)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    first = str(raw).split("DB-Lib error message")[0].strip().splitlines()
    return number, (first[0] if first else str(exc)).strip()


def bind_findings(conn, modules, errors):
    """{(name, type, message)} for each module that does not bind now. The
    open transaction survives each failure (DESIGN.md §8)."""
    found = set()
    for name, otype, qualified in modules:
        try:
            q(conn, "referenced-check.sql", q=qualified)
        except errors as exc:
            number, message = error_text(exc)
            if number == 2020:
                # SQL Server's catch-all for a reference it cannot bind;
                # the catalog still has the missing names
                missing = [m for (m,) in q(conn, "unresolved.sql", q=qualified)[1]]
                if missing:
                    message = f"references what does not exist: {', '.join(missing)}"
            found.add((name, otype, f"{number}: {message}" if number else message))
    return found


def compile_errors(conn, schema, name, errors=Exception):
    if name is not None and not resolve(conn, schema, name):
        return None
    mods = q(conn, "modules.sql", s=schema, n=fold(name) if name is not None else None)[1]
    if name is not None and not mods:
        return [], (f"{name} is not a view, procedure, function or trigger: "
                    "there is no module for SQL Server to bind")
    found = bind_findings(conn, [(n, t, qn) for n, t, qn, _ in mods], errors)
    rows = sorted((n, t, None, None, "error", m) for n, t, m in found)
    dynamic = [n for n, _t, _qn, dyn in mods if dyn]
    blind = None
    if dynamic:
        blind = (f"dynamic SQL inside {', '.join(dynamic)} is bound only when it "
                 "runs, so nothing inside its strings was checked")
    return rows, blind
