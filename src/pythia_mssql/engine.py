"""SQL Server, through pymssql, as a pythia-core engine.

It answers the connect tier (here) and the read tier (read.py). SQL Server
runs DDL inside a transaction, as PostgreSQL does, so the write tier will
rehearse each statement the same way (Phase 4b).
"""
import sys

from . import __version__, read
from .catalog import QUERY_BINDS, QUERY_DIR, fold, q  # noqa: F401 — QUERY_* re-exported

CONFIG_REL = ".pythia/mssql/connections.json"
REQUIRED = ("host", "database", "user")
ENCRYPT = ("off", "request", "require")


class SqlServerEngine:
    name = "mssql"
    label = "SQL Server"
    command = "pythia-mssql"
    env_prefix = "PYTHIA_MSSQL"
    version = __version__
    bind_style = "pyformat"
    default_port = 1433

    # --- the connection's life ------------------------------------------------

    def driver_errors(self):
        try:
            import pymssql
        except ModuleNotFoundError:
            sys.exit("The 'pymssql' package is required to connect: "
                     "pip install pymssql")
        return (pymssql.Error,)

    def connect(self, entry):
        import pymssql
        gaps = [k for k in REQUIRED if not entry.get(k)]
        if gaps:
            sys.exit(f"Connection is missing {', '.join(map(repr, gaps))} — "
                     f"fill in {CONFIG_REL}.")
        encrypt = str(entry.get("encrypt") or "request").lower()
        if encrypt not in ENCRYPT:
            sys.exit(f'"encrypt" must be one of {", ".join(ENCRYPT)} — got '
                     f"{entry.get('encrypt')!r} in {CONFIG_REL}.")
        # autocommit off: every command runs in a transaction that only an
        # approved write ever commits — closing rolls the rest back
        return pymssql.connect(
            server=entry["host"], port=str(entry.get("port") or self.default_port),
            database=entry["database"], user=entry["user"],
            password=entry.get("password") or "", autocommit=False,
            login_timeout=int(entry.get("login_timeout") or 10),
            appname=self.command, encryption=encrypt)

    def session(self, conn, readonly):
        # SQL Server has no read-only transaction (SET TRANSACTION READ ONLY
        # is a syntax error). The second line of defence for a read command
        # is that its transaction is never committed: core closes the
        # connection, and SQL Server rolls back whatever is open. A read-only
        # login (db_datareader) is the first line; doctor says so.
        return conn

    def close(self, conn):
        conn.close()

    def connect_failure(self, exc, conn_name, entry):
        """Name the next step for the failures SQL Server has already
        diagnosed: its error number when it sent one, else the text."""
        number, message = read.error_text(exc)
        low = message.lower()
        who = entry.get("user") or "<the login>"
        head = f"Could not connect using connection {conn_name!r}: {message}"
        if number == 18456 or "login failed" in low:
            return (f"{head}\nLogin failed for {who}: a wrong password, a "
                    "disabled login, or a server that only allows Windows "
                    f"authentication. Check the entry in {CONFIG_REL}.")
        if number == 4060 or "cannot open database" in low:
            return (f"{head}\nThe login works, but cannot open database "
                    f"{entry.get('database')!r}: it does not exist, or {who} "
                    "has no user in it. A DBA maps one:\n  CREATE USER "
                    f"[{who}] FOR LOGIN [{who}];")
        # FreeTDS reports a failed TLS handshake as its generic 20002 too
        if "ssl" in low or "tls" in low or "encrypt" in low:
            return (f"{head}\nThe TLS handshake failed. Try \"encrypt\": "
                    f"\"request\" in {CONFIG_REL}, or ask a DBA which TLS "
                    "versions the server accepts.")
        if number in (20009, 20002) or "unavailable or does not exist" in low \
                or "unable to connect" in low:
            return (f"{head}\nNothing answered at {self.target_of(entry)}. "
                    "Check host and port, that TCP/IP is enabled on the "
                    "server, and that a firewall lets this machine through.")
        return (f"{head}\nCheck host/port/database, the credentials, and that "
                "the server is reachable from here. Use --conn NAME to try a "
                "different entry.")

    def schema_of(self, entry):
        # names are kept as typed: SQL Server compares them by the database's
        # collation, usually without regard to case
        return fold(entry.get("schema") or "dbo")

    def target_of(self, entry):
        host = entry.get("host")
        if not host:
            return ""
        target = f"{host}:{entry.get('port') or self.default_port}"
        return f"{target}/{entry['database']}" if entry.get("database") else target

    # --- what check asks --------------------------------------------------------

    def server_version(self, conn):
        version, edition, database = q(conn, "server-version.sql")[1][0]
        return f"SQL Server {version} ({edition}) — database {database}"

    def current_schema(self, conn):
        rows = q(conn, "current-schema.sql")[1]
        return rows[0][0] if rows and rows[0] and rows[0][0] else None

    # --- the read tier (read.py) -------------------------------------------------

    def object_names(self, conn, schema, pattern, fetch):
        return read.object_names(conn, schema, pattern, fetch)

    def source(self, conn, schema, name):
        return read.source(conn, schema, name)

    def columns(self, conn, schema, name):
        return read.columns(conn, schema, name)

    def ddl(self, conn, schema, name):
        return read.ddl(conn, schema, name)

    def grep(self, conn, schema, text, fetch):
        return read.grep(conn, schema, text, fetch)

    def dependencies(self, conn, schema, name, depth):
        return read.dependencies(conn, schema, name, depth)

    def dependents(self, conn, schema, name, depth):
        return read.dependents(conn, schema, name, depth)

    def compile_errors(self, conn, schema, name):
        return read.compile_errors(conn, schema, name, self.driver_errors())
