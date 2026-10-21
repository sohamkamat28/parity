import time, uuid
from contextlib import contextmanager
from sqlalchemy import (create_engine, MetaData, Table, Column, String, Text, Integer,
                        Float, Boolean, JSON, ForeignKey, UniqueConstraint, event)
from pgvector.sqlalchemy import Vector
from . import config

def uid():
    return uuid.uuid4().hex

meta = MetaData()
sources = Table("sources", meta,
    Column("id", String, primary_key=True), Column("name", String, nullable=False),
    Column("root_url", Text, nullable=False), Column("config", JSON, nullable=False),
    Column("enabled", Boolean, default=True), Column("paused", Boolean, default=True),
    Column("generation", Integer, default=0), Column("lease_run", String),
    Column("lease_until", Float, default=0), Column("next_due", Float, default=0),
    Column("created_at", Float, default=time.time), Column("removed_at", Float))
runs = Table("runs", meta,
    Column("id", String, primary_key=True), Column("source_id", ForeignKey("sources.id"), index=True),
    Column("status", String, nullable=False), Column("created_at", Float, default=time.time),
    Column("started_at", Float), Column("finished_at", Float),
    Column("generation", Integer), Column("metrics", JSON, default=dict),
    Column("error", Text))
pages = Table("pages", meta,
    Column("id", String, primary_key=True), Column("source_id", ForeignKey("sources.id"), index=True),
    Column("url", Text, nullable=False), Column("title", Text, default=""),
    Column("availability", String, default="unknown"), Column("health", String, default="healthy"),
    Column("current_id", String), Column("last_version_id", String),
    Column("checked_at", Float), Column("verified_at", Float),
    Column("missing_count", Integer, default=0), Column("missing_at", Float),
    Column("missing_run", String), Column("etag", Text), Column("last_modified", Text),
    Column("audit_at", Float, default=0), Column("last_error", Text),
    UniqueConstraint("source_id", "url"))
versions = Table("versions", meta,
    Column("id", String, primary_key=True), Column("page_id", ForeignKey("pages.id"), index=True),
    Column("number", Integer, nullable=False), Column("title", Text),
    Column("content", Text), Column("hash", String), Column("raw_hash", String),
    Column("raw_key", Text), Column("observed_at", Float), Column("indexed_at", Float),
    Column("signature", String), Column("sections", JSON),
    UniqueConstraint("page_id", "number"))
cache = Table("embedding_cache", meta,
    Column("id", String, primary_key=True), Column("key", String, unique=True),
    Column("signature", String), Column("input", Text), Column("vector", Vector(384).with_variant(JSON, "sqlite")))
chunks = Table("chunks", meta,
    Column("id", String, primary_key=True), Column("version_id", ForeignKey("versions.id"), index=True),
    Column("ordinal", Integer), Column("heading", Text), Column("locator", Text),
    Column("text", Text), Column("cache_id", ForeignKey("embedding_cache.id")),
    UniqueConstraint("version_id", "ordinal"))
intervals = Table("intervals", meta,
    Column("id", String, primary_key=True), Column("page_id", ForeignKey("pages.id"), index=True),
    Column("version_id", ForeignKey("versions.id")), Column("start", Float), Column("end", Float))
events = Table("events", meta,
    Column("id", String, primary_key=True), Column("page_id", ForeignKey("pages.id"), index=True),
    Column("run_id", ForeignKey("runs.id")), Column("kind", String),
    Column("old_version_id", String), Column("new_version_id", String),
    Column("at", Float), Column("detail", JSON, default=dict))
observations = Table("observations", meta,
    Column("id", String, primary_key=True), Column("run_id", ForeignKey("runs.id"), index=True),
    Column("url", Text), Column("at", Float), Column("status", Integer),
    Column("outcome", String), Column("detail", Text))
schema = Table("schema_version", meta, Column("number", Integer, primary_key=True))

chat_conversations = Table("chat_conversations", meta,
    Column("id", String, primary_key=True), Column("title", Text, nullable=False),
    Column("created_at", Float, nullable=False), Column("updated_at", Float, nullable=False))
chat_messages = Table("chat_messages", meta,
    Column("id", String, primary_key=True),
    Column("conversation_id", ForeignKey("chat_conversations.id"), nullable=False, index=True),
    Column("ordinal", Integer, nullable=False), Column("role", String, nullable=False),
    Column("content", Text, nullable=False), Column("citations", JSON, nullable=False, default=list),
    Column("warnings", JSON, nullable=False, default=list), Column("evidence", JSON, nullable=False, default=list),
    Column("context", JSON, nullable=False, default=dict), Column("status", String, nullable=False),
    Column("model", String), Column("elapsed_ms", Integer, default=0),
    Column("created_at", Float, nullable=False), UniqueConstraint("conversation_id", "ordinal"))
# Retained only for lossless migration/backup of existing installations.
_legacy_session_records = Table("demo_sessions", meta,
    Column("id", String, primary_key=True), Column("name", Text, nullable=False),
    Column("static_source_id", ForeignKey("sources.id")),
    Column("browser_source_id", ForeignKey("sources.id")), Column("portal_url", Text, nullable=False),
    Column("created_at", Float, nullable=False, default=time.time))

from . import monitor_schema, job_schema, search_schema, automation_schema
_V3_TABLES = tuple(monitor_schema.register(meta).values()) + tuple(job_schema.register(meta).values()) + tuple(search_schema.register(meta).values())
_V5_TABLES = tuple(automation_schema.register(meta).values())
SCHEMA_VERSION = 5
_V2_TABLES = (chat_conversations, chat_messages, _legacy_session_records)


def migrate(connection,upgrade=False):
    """Apply additive migrations under the caller's transaction and schema lock.

    The original release wrote schema_version=1. Keeping that table means old
    databases can be upgraded without rewriting any source, vector or history.
    """
    schema.create(connection, checkfirst=True)
    numbers = list(connection.execute(schema.select()).scalars())
    version = max(numbers, default=0)
    if version > SCHEMA_VERSION:
        raise RuntimeError("Database schema is newer than this Parity installation")
    if version and version<SCHEMA_VERSION and not upgrade:
        raise RuntimeError('Database upgrade required. Stop Parity, then run python scripts/database.py --upgrade to create a verified backup and apply the additive migration.')
    if version < 1:
        meta.create_all(connection, tables=[t for t in meta.sorted_tables if t not in (*_V2_TABLES,*_V3_TABLES,*_V5_TABLES)])
        connection.execute(schema.insert().values(number=1))
        version = 1
    if version == 1:
        for table in _V2_TABLES:
            table.create(connection, checkfirst=True)
        connection.execute(schema.delete())
        connection.execute(schema.insert().values(number=2))
        version = 2
    if version == 2:
        meta.create_all(connection, tables=[t for t in meta.sorted_tables if t in _V3_TABLES])
        # Projection rebuild uses preserved chunk identities and stored vectors; no model calls.
        connection.exec_driver_sql('''INSERT INTO search_projection
            (chunk_id,source_id,page_id,version_id,text,heading,locator,model_signature,vector)
            SELECT ch.id,p.source_id,p.id,v.id,ch.text,ch.heading,ch.locator,ec.signature,ec.vector
            FROM chunks ch JOIN versions v ON ch.version_id=v.id JOIN pages p ON v.page_id=p.id
            JOIN embedding_cache ec ON ch.cache_id=ec.id WHERE v.indexed_at IS NOT NULL''')
        connection.execute(schema.delete())
        connection.execute(schema.insert().values(number=3))
        version = 3
    if version == 3:
        from sqlalchemy import inspect
        if 'removed_at' not in {column['name'] for column in inspect(connection).get_columns('sources')}:
            connection.exec_driver_sql('ALTER TABLE sources ADD COLUMN removed_at FLOAT')
        monitor_schema.monitor_list_items.create(connection,checkfirst=True)
        backfill_list_items(connection)
        connection.exec_driver_sql('CREATE INDEX IF NOT EXISTS ix_monitor_series ON monitor_observations (monitor_id, field_id, at, id)')
        connection.execute(schema.delete())
        connection.execute(schema.insert().values(number=4))
        version = 4
    if version == 4:
        meta.create_all(connection, tables=list(_V5_TABLES))
        connection.exec_driver_sql('CREATE INDEX IF NOT EXISTS ix_automation_series ON automation_evaluations (automation_id, at, id)')
        connection.execute(schema.delete())
        connection.execute(schema.insert().values(number=5))

def backfill_list_items(connection):
    from sqlalchemy import select,func
    from .structured import fingerprint
    if connection.dialect.name=='postgresql':
        from sqlalchemy.dialects.postgresql import insert
        is_list=func.json_typeof(monitor_schema.monitor_observations.c.value)=='array'
    else:
        from sqlalchemy.dialects.sqlite import insert
        is_list=func.json_type(monitor_schema.monitor_observations.c.value)=='array'
    observations=monitor_schema.monitor_observations;items=monitor_schema.monitor_list_items
    statement=select(observations.c.monitor_id,observations.c.field_id,observations.c.value,observations.c.at).where(
        observations.c.status=='ok',is_list).order_by(observations.c.at,observations.c.id)
    pending={}
    def flush():
        if pending:
            connection.execute(insert(items).values(list(pending.values())).on_conflict_do_nothing(index_elements=['monitor_id','field_id','item_key']))
            pending.clear()
    for row in connection.execute(statement.execution_options(stream_results=True)).mappings():
        for item in row['value']:
            if not isinstance(item,dict) or 'key' not in item:continue
            key=(row['monitor_id'],row['field_id'],fingerprint(str(item['key'])))
            pending.setdefault(key,dict(monitor_id=key[0],field_id=key[1],item_key=key[2],first_observed_at=row['at']))
            if len(pending)>=500:flush()
    flush()

class DB:
    def __init__(self, url=None, *, upgrade=False):
        self.engine = create_engine(url or config.DATABASE_URL, pool_pre_ping=True,
            connect_args={"check_same_thread": False, "timeout": 30} if (url or config.DATABASE_URL).startswith("sqlite") else {})
        if self.engine.dialect.name == "sqlite":
            @event.listens_for(self.engine, "connect")
            def setup(connection, _):
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA foreign_keys=ON")
        # SQLite's explicit BEGIN also makes DDL rollback on a failed migration.
        # Serialize initializers (including the independent MCP process).
        with self.tx() as c:
            if self.engine.dialect.name == "postgresql":
                c.exec_driver_sql("SELECT pg_advisory_xact_lock(1936745081)")
                c.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
            migrate(c,upgrade=upgrade)
            if self.engine.dialect.name == "postgresql":
                c.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_chunks_fts ON chunks USING GIN (to_tsvector('simple', text))")
                c.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_projection_fts ON search_projection USING GIN (to_tsvector('simple', text))")
                c.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_projection_hnsw ON search_projection USING hnsw (vector vector_cosine_ops) WITH (m=16, ef_construction=100)")

    @contextmanager
    def tx(self):
        with self.engine.connect() as c:
            if self.engine.dialect.name == "sqlite":
                c.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    yield c
                    c.commit()
                except BaseException:
                    c.rollback()
                    raise
            else:
                with c.begin():
                    yield c

    def all(self, statement):
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(statement).mappings()]

    def one(self, statement):
        rows = self.all(statement)
        return rows[0] if rows else None
