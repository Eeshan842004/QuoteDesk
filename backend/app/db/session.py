"""Engine + session factory. SQLite locally, Neon Postgres (psycopg 3) in production."""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings
from .models import AppState, Base


def normalize_url(url: str) -> str:
    """Accept postgres:// and postgresql:// URLs (as Neon shows them) and use the psycopg 3 driver."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    url = normalize_url(get_settings().database_url)
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5, pool_recycle=280)


@lru_cache(maxsize=1)
def _factory() -> sessionmaker:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    s = _factory()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    with session_scope() as s:
        yield s


def get_state(s: Session, key: str, default=None):
    row = s.get(AppState, key)
    return row.value if row and row.value is not None else default


def set_state(s: Session, key: str, value) -> None:
    row = s.get(AppState, key)
    if row:
        row.value = value
    else:
        s.add(AppState(key=key, value=value))
