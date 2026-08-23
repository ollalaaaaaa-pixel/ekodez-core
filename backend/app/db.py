import sqlite3
from typing import Any

from sqlalchemy import Engine, create_engine, event


def enable_sqlite_foreign_keys(engine: Engine) -> Engine:
    if engine.dialect.name != "sqlite":
        return engine

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection: object, _: object) -> None:
        if isinstance(dbapi_connection, sqlite3.Connection):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_app_engine(database_url: str, **kwargs: Any) -> Engine:
    return enable_sqlite_foreign_keys(create_engine(database_url, **kwargs))
