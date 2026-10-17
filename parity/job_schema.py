"""Additive schema for persisted crawling and independent indexing."""
from sqlalchemy import Table, Column, String, Text, Integer, Float, JSON, ForeignKey, UniqueConstraint

NAMES = ('run_state', 'url_jobs', 'index_jobs', 'index_state', 'worker_status', 'origin_locks', 'resource_locks')


def register(meta):
    if 'run_state' in meta.tables:
        result = {name: meta.tables[name] for name in NAMES}
        globals().update(result)
        return result
    run_state = Table('run_state', meta,
        Column('run_id', ForeignKey('runs.id'), primary_key=True),
        Column('source_snapshot', JSON, nullable=False), Column('monitor_revisions', JSON, nullable=False),
        Column('initialized_at', Float), Column('known_count', Integer, default=0))
    url_jobs = Table('url_jobs', meta,
        Column('id', String, primary_key=True), Column('run_id', ForeignKey('runs.id'), nullable=False, index=True),
        Column('source_id', ForeignKey('sources.id'), nullable=False, index=True),
        Column('url', Text, nullable=False), Column('depth', Integer, nullable=False),
        Column('status', String, nullable=False, index=True), Column('attempts', Integer, default=0),
        Column('generation', Integer, default=0), Column('owner', String), Column('lease_until', Float, default=0),
        Column('available_at', Float, default=0, index=True), Column('created_at', Float, nullable=False),
        Column('finished_at', Float), Column('error', Text), Column('http_status', Integer),
        Column('metrics', JSON, default=dict), UniqueConstraint('run_id', 'url'))
    index_jobs = Table('index_jobs', meta,
        Column('id', String, primary_key=True), Column('version_id', ForeignKey('versions.id'), nullable=False, unique=True),
        Column('status', String, nullable=False, index=True), Column('attempts', Integer, default=0),
        Column('generation', Integer, default=0), Column('owner', String), Column('lease_until', Float, default=0),
        Column('available_at', Float, default=0), Column('created_at', Float, nullable=False),
        Column('finished_at', Float), Column('error', Text))
    index_state = Table('index_state', meta,
        Column('version_id', ForeignKey('versions.id'), primary_key=True),
        Column('status', String, nullable=False), Column('model_signature', String),
        Column('updated_at', Float, nullable=False), Column('error', Text))
    worker_status = Table('worker_status', meta,
        Column('id', String, primary_key=True), Column('role', String, nullable=False),
        Column('heartbeat_at', Float, nullable=False), Column('status', String), Column('detail', Text))
    origin_locks = Table('origin_locks', meta,
        Column('origin', String, primary_key=True), Column('owner', String),
        Column('lease_until', Float, default=0), Column('next_allowed_at', Float, default=0))
    resource_locks = Table('resource_locks', meta,
        Column('name', String, primary_key=True), Column('owner', String), Column('lease_until', Float, default=0))
    result = {name: meta.tables[name] for name in NAMES}
    globals().update(result)
    return result
