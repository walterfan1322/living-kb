from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from living_kb.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, future=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
_schema_ready = False


def get_session() -> Generator[Session, None, None]:
    global _schema_ready
    if not _schema_ready and settings.is_sqlite:
        init_db()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    global _schema_ready
    if _schema_ready:
        return

    from living_kb import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    if settings.is_sqlite:
        _run_lightweight_migrations()
    _schema_ready = True


def _run_lightweight_migrations() -> None:
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    table_columns = {
        table_name: {column["name"] for column in inspector.get_columns(table_name)}
        for table_name in inspector.get_table_names()
    }
    statements: list[str] = []

    if "knowledge_pages" in table_columns and "review_notes" not in table_columns["knowledge_pages"]:
        statements.append("ALTER TABLE knowledge_pages ADD COLUMN review_notes TEXT")
    if "knowledge_pages" in table_columns and "search_text" not in table_columns["knowledge_pages"]:
        statements.append("ALTER TABLE knowledge_pages ADD COLUMN search_text TEXT DEFAULT ''")

    if "health_findings" in table_columns:
        if "review_notes" not in table_columns["health_findings"]:
            statements.append("ALTER TABLE health_findings ADD COLUMN review_notes TEXT")
        if "resolved_at" not in table_columns["health_findings"]:
            statements.append("ALTER TABLE health_findings ADD COLUMN resolved_at DATETIME")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
