"""The `pythia-mssql` command: pythia-core's command line, handed this engine."""
from pythia_core import cli

from .engine import SqlServerEngine


def main(argv=None):
    return cli.main(SqlServerEngine(), argv)
