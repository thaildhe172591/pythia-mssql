"""Where pythia-mssql's SQL lives and how it is run.

Every statement is a file in queries/, under pythia-core's contract:
pyformat binds, a header, and its binds declared here; a literal % is
written %%. pymssql never turns %% back into % (with parameters or
without), so q() does it, once, as a file is loaded — the query files keep
the same reviewable contract as every other engine's.
"""
import pathlib

from pythia_core.queries import load_query, run_query

QUERY_DIR = pathlib.Path(__file__).resolve().parent / "queries"

QUERY_BINDS = {
    "server-version.sql": set(),
    "current-schema.sql": set(),
    "resolve.sql": {"s", "n"},
    "object-names.sql": {"s", "p", "n"},
    "source.sql": {"s", "n"},
    "columns.sql": {"objid"},
    "table-head.sql": {"objid"},
    "table-columns.sql": {"objid"},
    "table-keys.sql": {"objid"},
    "table-foreign-keys.sql": {"objid"},
    "table-checks.sql": {"objid"},
    "table-indexes.sql": {"objid"},
    "table-triggers.sql": {"objid"},
    "table-comments.sql": {"objid"},
    "sequence-ddl.sql": {"objid"},
    "grep.sql": {"s", "p"},
    "dependents-catalog.sql": {"objid", "s", "n"},
    "dependents-text.sql": {"p", "objid"},
    "dependencies-catalog.sql": {"objid"},
    "modules.sql": {"s", "n"},
    "referenced-check.sql": {"q"},
    "unresolved.sql": {"q"},
}


def sql_of(name):
    return load_query(QUERY_DIR, name).replace("%%", "%")


def q(conn, name, **binds):
    """(COLUMNS, rows) for one query file. Column names are upper case, as
    every pythia engine reports them."""
    cols, rows = run_query(conn, sql_of(name), binds)
    return [str(c).upper() for c in cols], rows


def fold(name):
    """A name as the catalog holds it: [bracketed] or "quoted" taken exactly,
    the quoting removed. SQL Server compares names by the database's
    collation — usually case-insensitive — so case is left as typed."""
    name = str(name).strip()
    if len(name) >= 2 and name[0] == "[" and name[-1] == "]":
        return name[1:-1].replace("]]", "]")
    if len(name) >= 2 and name[0] == name[-1] == '"':
        return name[1:-1].replace('""', '"')
    return name


def like_contains(text):
    """A LIKE pattern matching text anywhere, with LIKE's own wildcards in it
    escaped (the queries declare ESCAPE '\\')."""
    esc = "".join("\\" + ch if ch in "\\%_[" else ch for ch in str(text))
    return f"%{esc}%"
