"""SQL Server's lint rules: what SQL Server accepts and a reviewer would not.

Each rule reads the statement as the lexer does — strings, [bracketed] and
"quoted" names, and comments blanked — so a keyword inside a literal or a
name never fires one. What SQL Server rejects itself is left to the
rehearsal.
"""
import re

from .write import _NAME, _SOURCE_HEAD, _qualified, extended_property, lex, parse_object


def _line(text, pos):
    return text.count("\n", 0, pos) + 1


def _hits(stmt, pattern, message, skip=None):
    """(line, message) for every match in the statement's code; the line is
    where the named group `at` starts when the pattern has one."""
    code = lex(stmt).masked.lower()
    out = []
    for m in re.finditer(pattern, code):
        if skip and skip(code, m):
            continue
        at = m.start("at") if "at" in m.re.groupindex and m.group("at") else m.start()
        out.append((_line(stmt, at), message))
    return out


def _module(stmt, group, kind):
    ident = parse_object(stmt, group) if group == "source" else None
    return ident if ident and ident["type"] == kind else None


def trigger_commit(stmt, group, run):
    if not _module(stmt, group, "TRIGGER"):
        return []
    return _hits(stmt, r"\bcommit\b", "a trigger's COMMIT ends its caller's "
                 "transaction (error 3609) and commits work the caller may still "
                 "roll back — let the caller commit, and THROW to refuse a change")


def unsized_string(stmt, group, run):
    return _hits(stmt, r"\b(?P<at>n?varchar|n?char|varbinary|binary)\b(?!\s*\()",
                 "a string type without a length holds 1 character in a "
                 "declaration and 30 in CAST or CONVERT, and SQL Server cuts what "
                 "does not fit without a word — give the length")


def nolock(stmt, group, run):
    return _hits(stmt, r"\b(?P<at>nolock|readuncommitted)\b|\bread\s+uncommitted\b",
                 "NOLOCK / READ UNCOMMITTED reads rows mid-change: it can skip a "
                 "row, read one twice, or see data that is then rolled back — "
                 "READ COMMITTED SNAPSHOT keeps readers from blocking instead")


def _after_exists(code, m):
    return re.search(r"\bexists\s*\(\s*$", code[:m.start()]) is not None


def select_star(stmt, group, run):
    if group != "source":
        return []
    return _hits(stmt, r"\bselect\s+(?:distinct\s+|all\s+)?(?:top\s*(?:\([^)]*\)|\d+)\s+"
                 r"(?:percent\s+)?(?:with\s+ties\s+)?)?(?:[\w\]\"]+\s*\.\s*)?\*",
                 "SELECT * in stored code: a view keeps the column list it was "
                 "created with until sp_refreshview, and a procedure's result "
                 "changes shape when a column is added — name the columns",
                 skip=_after_exists)


def not_in_subquery(stmt, group, run):
    return _hits(stmt, r"\bnot\s+in\s*\(\s*select\b", "NOT IN (SELECT ...) is "
                 "never true when the subquery returns a NULL — use NOT EXISTS")


def deprecated_type(stmt, group, run):
    if group not in ("source", "structural"):
        return []
    return _hits(stmt, r"[\w\]\"]\s+(?P<at>text|ntext|image)\b"
                 r"(?=\s*(?:,|\)|\bnot\b|\bnull\b|\bcollate\b|\bconstraint\b|"
                 r"\bdefault\b|$))|\bcast\s*\([^()]*\bas\s+(?P<cast>text|ntext|image)\b",
                 "text, ntext and image are deprecated — varchar(max), "
                 "nvarchar(max) and varbinary(max) replace them")


def legacy_datetime(stmt, group, run):
    if group not in ("source", "structural"):
        return []
    return _hits(stmt, r"\b(?P<at>(?:small)?datetime)\b", "datetime rounds to "
                 "1/300 of a second and smalldatetime to the minute — datetime2, "
                 "or datetimeoffset for a moment in time, is exact")


def sp_prefix(stmt, group, run):
    if not _module(stmt, group, "PROCEDURE"):
        return []
    m = _SOURCE_HEAD.match(lex(stmt).uncommented)
    if not m or not m.group("name").strip('[]"').lower().startswith("sp_"):
        return []
    return [(_line(stmt, m.start("name")), "a procedure named sp_ is looked for in "
             "master first, and a system procedure of the same name wins — use "
             "another prefix")]


def nocount(stmt, group, run):
    if not _module(stmt, group, "PROCEDURE"):
        return []
    if re.search(r"\bset\s+nocount\s+on\b", lex(stmt).masked.lower()):
        return []
    return [(1, "no SET NOCOUNT ON: every statement sends a row-count message, "
             "and some clients read it as a result set")]


def table_comment(stmt, group, run):
    if group != "structural":
        return []
    m = re.match(r"\s*create\s+table\s+" + _NAME, lex(stmt).uncommented, re.I)
    if not m:
        return []
    table = _qualified(m)[1]
    for other in run:
        verb, args = extended_property(other) if re.match(
            r"\s*exec", lex(other).masked, re.I) else (None, None)
        if verb in ("add", "update") and not args.get("level2name") and \
                str(args.get("level1name") or "").lower() == table.lower():
            return []
    return [(_line(stmt, m.start("name")), f"table {table} has no MS_Description in "
             "this change — say what a row is, in the same change that creates it")]


RULES = [
    {"id": "mssql-trigger-commit", "severity": "error",
     "summary": "a trigger never commits its caller's transaction",
     "check": trigger_commit},
    {"id": "mssql-unsized-string", "severity": "error",
     "summary": "char, varchar, nchar, nvarchar, binary and varbinary carry a length",
     "check": unsized_string},
    {"id": "mssql-nolock", "severity": "warn",
     "summary": "no NOLOCK or READ UNCOMMITTED", "check": nolock},
    {"id": "mssql-select-star", "severity": "warn",
     "summary": "no SELECT * in views, procedures and functions", "check": select_star},
    {"id": "mssql-not-in-subquery", "severity": "warn",
     "summary": "NOT EXISTS over NOT IN (SELECT ...)", "check": not_in_subquery},
    {"id": "mssql-deprecated-type", "severity": "warn",
     "summary": "no text, ntext or image", "check": deprecated_type},
    {"id": "mssql-datetime", "severity": "info",
     "summary": "datetime2 over datetime and smalldatetime", "check": legacy_datetime},
    {"id": "mssql-sp-prefix", "severity": "warn",
     "summary": "no procedure named sp_", "check": sp_prefix},
    {"id": "mssql-nocount", "severity": "info",
     "summary": "procedures SET NOCOUNT ON", "check": nocount},
    {"id": "mssql-table-comment", "severity": "warn",
     "summary": "every new table carries an MS_Description in the same change",
     "check": table_comment},
]
