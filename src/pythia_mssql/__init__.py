"""pythia for SQL Server: T-SQL development for AI agents, over pythia-core.
Pre-alpha — see README.md for what works today."""
__version__ = "0.3.0.dev0"     # kept equal to pyproject.toml (tests/test_mssql.py)

from .engine import SqlServerEngine  # noqa: E402,F401 — needs __version__ first
