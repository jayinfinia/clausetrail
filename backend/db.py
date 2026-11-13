import uuid
from datetime import datetime, timezone
from sqlalchemy import create_engine, inspect, text, String, Text, Integer, JSON, DateTime, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from backend import config

def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def uid():
    return str(uuid.uuid4())

class Base(DeclarativeBase):
    pass

class Record(Base):
    __tablename__ = 'agreements'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    filename: Mapped[str] = mapped_column(String(250))
    scope: Mapped[str] = mapped_column(String(80), index=True)
    digest: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(30), default='upload')
    source_id: Mapped[str] = mapped_column(String(300), default='')
    source_version: Mapped[str] = mapped_column(String(100), default='1')
    path: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default='queued')
    blocks: Mapped[list] = mapped_column(JSON, default=list)
    proposals: Mapped[dict] = mapped_column(JSON, default=dict)
    approved: Mapped[dict] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    executed: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Agreement Labeling Framework labels (relationship type, owner, components...).
    # Classification metadata, editable with an edit log; not evidence-backed contract facts.
    labels: Mapped[dict] = mapped_column(JSON, default=dict)
    rel_path: Mapped[str] = mapped_column(String(500), default='')
    created: Mapped[datetime] = mapped_column(DateTime, default=now)
    __mapper_args__ = {'version_id_col': revision, 'version_id_generator': False}

class Job(Base):
    __tablename__ = 'jobs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    record_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(30), default='queued')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(String(80), default='')
    updated: Mapped[datetime] = mapped_column(DateTime, default=now)

class Audit(Base):
    __tablename__ = 'audit'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(80))
    record_id: Mapped[str] = mapped_column(String(36), index=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created: Mapped[datetime] = mapped_column(DateTime, default=now)

class Batch(Base):
    __tablename__ = 'import_batches'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    actor: Mapped[str] = mapped_column(String(80))
    scope: Mapped[str] = mapped_column(String(80))
    filename: Mapped[str] = mapped_column(String(250))
    rows: Mapped[list] = mapped_column(JSON, default=list)
    changes: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default='preview')
    created: Mapped[datetime] = mapped_column(DateTime, default=now)

class Setting(Base):
    __tablename__ = 'settings'
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)

class SchemaVersion(Base):
    __tablename__ = 'schema_version'
    version: Mapped[int] = mapped_column(Integer, primary_key=True)

engine = create_engine(config.DATABASE_URL, connect_args={'check_same_thread': False, 'timeout': 30} if config.DATABASE_URL.startswith('sqlite') else {}, pool_pre_ping=True)
Session = sessionmaker(engine, expire_on_commit=False)

def migrate():
    config.initialize()
    Base.metadata.create_all(engine)
    # Version 2: framework labels and source folder path on agreements.
    existing = {c['name'] for c in inspect(engine).get_columns('agreements')}
    with engine.begin() as conn:
        if 'labels' not in existing:
            conn.execute(text("ALTER TABLE agreements ADD COLUMN labels JSON"))
        if 'rel_path' not in existing:
            conn.execute(text("ALTER TABLE agreements ADD COLUMN rel_path VARCHAR(500) DEFAULT ''"))
    with Session() as db:
        for version in (1, 2):
            if db.get(SchemaVersion, version) is None:
                db.add(SchemaVersion(version=version))
        db.commit()

def audit(db, actor, action, record_id, detail=None):
    db.add(Audit(actor=actor, action=action, record_id=record_id, detail=detail or {}))
