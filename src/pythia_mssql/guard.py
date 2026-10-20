"""The harness tier: what pythia-core's guard and install need to know
about SQL Server. The guard denies sqlcmd (and osql, bcp, Invoke-Sqlcmd,
sqlpackage) when it would write around the gate; reads through sqlcmd are
left to the client's own prompt.

The patterns read a shell command for what it names, never for what it
means, so a write spelled in a way they do not list gets through, and a
read that merely mentions DROP TABLE is denied. The gate behind them holds
either way (pythia-core's SECURITY.md).
"""
import pathlib

CLIENTS = r"sqlcmd|osql|isql|bcp|mssql-cli|invoke-sqlcmd|sqlpackage"

# matched against the whole command, quoted SQL included
WRITE_SQL = "|".join((
    r"\b(create|alter|drop|truncate|grant|revoke|deny|merge|dbcc|backup|"
    r"restore|reconfigure|kill|shutdown|bulk\s+insert|enable\s+trigger|"
    r"disable\s+trigger|update\s+statistics)\b",
    # INTO and FROM are optional in T-SQL
    r"\binsert\s+(into\b|top\b|[\w\[\]\"#@.]+)",
    r"\bdelete\s+(from\b|top\b|[\w\[\]\"#@.]+)",
    r"\bupdate\s+(top\s*\([^)]*\)\s+)?[\w\[\]\".#@]+(\s+(as\s+)?\w+)?\s+set\b",
    # a procedure can do anything; first in a batch it needs no EXEC
    r"\bexec(ute)?\b",
    r"\b(sp|xp)_\w+",
    r"\bselect\b[^;]*\binto\b",                # SELECT ... INTO makes a table
    r"\bnext\s+value\s+for\b",                 # a sequence advances, committed or not
    r":r\s+\S",                                # sqlcmd reading a script file
))

# matched with quoted text emptied: what the shell hands the client
SCRIPT = "|".join((
    r"(?-i:(^|\s)(-i\s*\S|--input-file(=|\s)))",   # sqlcmd/osql -i (-I is not)
    r"(^|\s)-inputfile\b",                          # Invoke-Sqlcmd -InputFile
    r"(^|[^<])<(?![<(&])\s*\S",                     # stdin from a file, not <<, <(
    r"\|\s*(\S*[/\\])?(sqlcmd|osql|isql|mssql-cli|invoke-sqlcmd)\b",
    r"\bbcp\s+\S+\s+in\b",                          # a file into a table
    r"\bsqlpackage\b.*[/-](a|action)\s*[:=]\s*(publish|import)\b",
))

TEMPLATE = {
    "default": "dev",
    "dev": {
        "host": "",
        "port": 1433,
        "database": "",
        "user": "",
        "password": "",
        "schema": "app_owner",
        "encrypt": "request",
    },
}

SKILLS_DIR = pathlib.Path(__file__).resolve().parent / "skills"
