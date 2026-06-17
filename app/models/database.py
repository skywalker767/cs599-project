"""SQLAlchemy database models and session management."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import get_settings

Base = declarative_base()


class TaskORM(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(String(32), nullable=False, default="pending")
    task_type = Column(String(32), nullable=False, default="unknown")
    description = Column(Text, nullable=False)
    title = Column(String(256), nullable=False, default="")
    data_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False},
        )
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)
    return _SessionLocal


def init_db() -> None:
    get_settings().ensure_dirs()
    Base.metadata.create_all(bind=get_engine())


def get_db() -> Session:
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


def save_task_record(db: Session, record_dict: dict) -> None:
    task_id = record_dict["task_id"]
    existing = db.query(TaskORM).filter(TaskORM.task_id == task_id).first()
    payload = json.dumps(record_dict, default=str)

    if existing:
        existing.status = record_dict.get("status", existing.status)
        existing.task_type = record_dict.get("task_type", existing.task_type)
        existing.description = record_dict.get("description", existing.description)
        existing.title = record_dict.get("title", existing.title)
        existing.data_json = payload
        existing.updated_at = datetime.utcnow()
    else:
        row = TaskORM(
            task_id=task_id,
            status=record_dict.get("status", "pending"),
            task_type=record_dict.get("task_type", "unknown"),
            description=record_dict.get("description", ""),
            title=record_dict.get("title", ""),
            data_json=payload,
        )
        db.add(row)
    db.commit()


def load_task_record(db: Session, task_id: str) -> Optional[dict]:
    row = db.query(TaskORM).filter(TaskORM.task_id == task_id).first()
    if not row:
        return None
    data = json.loads(row.data_json)
    data.setdefault("task_id", row.task_id)
    data.setdefault("status", row.status)
    data.setdefault("task_type", row.task_type)
    data.setdefault("description", row.description)
    data.setdefault("title", row.title)
    data.setdefault("created_at", row.created_at.isoformat() if row.created_at else None)
    data.setdefault("updated_at", row.updated_at.isoformat() if row.updated_at else None)
    return data


def list_task_records(db: Session, limit: int = 50, offset: int = 0) -> list[dict]:
    rows = db.query(TaskORM).order_by(TaskORM.created_at.desc()).offset(offset).limit(limit).all()
    results = []
    for row in rows:
        data = json.loads(row.data_json)
        data.setdefault("task_id", row.task_id)
        data.setdefault("status", row.status)
        data.setdefault("task_type", row.task_type)
        results.append(data)
    return results


def count_task_records(db: Session) -> int:
    return db.query(TaskORM).count()


def delete_task_record(db: Session, task_id: str) -> bool:
    row = db.query(TaskORM).filter(TaskORM.task_id == task_id).first()
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True
