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
    Column("created_at", Float, default=time.time))
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
demo_sessions = Table("demo_sessions", meta,
    Column("id", String, primary_key=True), Column("name", Text, nullable=False),
    Column("static_source_id", ForeignKey("sources.id")),
    Column("browser_source_id", ForeignKey("sources.id")), Column("portal_url", Text, nullable=False),
    Column("created_at", Float, nullable=False, default=time.time))

SCHEMA_VERSION = 2
_V2_TABLES = (chat_conversations, chat_messages, demo_sessions)


def migrate(connection):
    """Apply additive migrations under the caller's transaction and schema lock.

    The original release wrote schema_version=1. Keeping that table means old
    databases can be upgraded without rewriting any source, vector or history.
    """
    schema.create(connection, checkfirst=True)
    numbers = list(connection.execute(schema.select()).scalars())
    version = max(numbers, default=0)
    if version > SCHEMA_VERSION:
        raise RuntimeError("Database schema is newer than this Parity installation")
    if version < 1:
        meta.create_all(connection, tables=[t for t in meta.sorted_tables if t not in _V2_TABLES])
        connection.execute(schema.insert().values(number=1))
        version = 1
    if version == 1:
        for table in _V2_TABLES:
            table.create(connection, checkfirst=True)
        connection.execute(schema.delete())
        connection.execute(schema.insert().values(number=2))

class DB:
    def __init__(self, url=None):
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
            migrate(c)
            if self.engine.dialect.name == "postgresql":
                c.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_chunks_fts ON chunks USING GIN (to_tsvector('simple', text))")

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
