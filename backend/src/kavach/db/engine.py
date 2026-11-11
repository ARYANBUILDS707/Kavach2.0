"""PostgreSQL engine and session lifecycle; creating them does not open a connection."""

from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

CONNECT_TIMEOUT_SECONDS = 5
# Bounds any single statement; the ingestion deadline (D08) is enforced separately later.
STATEMENT_TIMEOUT_MS = 30_000


def create_db_engine(database_url: SecretStr) -> Engine:
    return create_engine(
        database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=10,
        pool_recycle=1800,
        # Bound parameters may later carry sensitive values; keep them out of error messages.
        hide_parameters=True,
        connect_args={
            "connect_timeout": CONNECT_TIMEOUT_SECONDS,
            "application_name": "kavach-backend",
            "options": f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
        },
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Use `factory.begin()` for a unit of work: commit on success, roll back on error."""
    return sessionmaker(bind=engine, expire_on_commit=False)


def check_database(engine: Engine) -> None:
    """Raise if PostgreSQL cannot execute a trivial statement."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1")).scalar_one()
