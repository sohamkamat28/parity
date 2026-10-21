"""Additive structured monitoring schema, registered by parity.db."""
from sqlalchemy import Table, Column, String, Text, Float, Integer, Boolean, JSON, ForeignKey, UniqueConstraint


def register(meta):
    specs = {
        'monitors': [Column('id', String, primary_key=True), Column('source_id', ForeignKey('sources.id'), index=True), Column('name', Text), Column('instructions', Text), Column('revision_id', String), Column('paused', Boolean, default=False), Column('created_at', Float), Column('updated_at', Float)],
        'monitor_revisions': [Column('id', String, primary_key=True), Column('monitor_id', ForeignKey('monitors.id'), index=True), Column('number', Integer), Column('fields', JSON), Column('root_url', Text), Column('created_at', Float), UniqueConstraint('monitor_id', 'number')],
        'monitor_captures': [Column('id', String, primary_key=True), Column('source_id', String, index=True), Column('run_id', String), Column('page_id', String), Column('url', Text), Column('observed_at', Float), Column('status', Integer), Column('content_type', Text), Column('sha256', String), Column('raw_key', Text)],
        'monitor_drafts': [Column('id', String, primary_key=True), Column('source', JSON), Column('source_id', String), Column('instructions', Text), Column('capture_id', ForeignKey('monitor_captures.id')), Column('candidates', JSON), Column('fields', JSON), Column('created_at', Float), Column('activated_id', String)],
        'monitor_observations': [Column('id', String, primary_key=True), Column('monitor_id', ForeignKey('monitors.id'), index=True), Column('revision_id', ForeignKey('monitor_revisions.id'), index=True), Column('field_id', String, index=True), Column('capture_id', ForeignKey('monitor_captures.id')), Column('run_id', String), Column('page_id', String), Column('url', Text), Column('at', Float, index=True), Column('status', String), Column('value', JSON), Column('raw_text', Text), Column('unit', Text), Column('period', Text), Column('locator', Text), Column('fingerprint', String), Column('error', Text), Column('changed', Boolean), Column('kind', String)],
        'monitor_field_states': [Column('id', String, primary_key=True), Column('monitor_id', ForeignKey('monitors.id'), index=True), Column('revision_id', ForeignKey('monitor_revisions.id')), Column('field_id', String, index=True), Column('observation_id', String), Column('capture_id', String), Column('value', JSON), Column('raw_text', Text), Column('unit', Text), Column('period', Text), Column('locator', Text), Column('fingerprint', String), Column('last_checked_at', Float), Column('last_verified_at', Float), Column('last_changed_at', Float), Column('status', String), Column('error', Text), UniqueConstraint('revision_id', 'field_id')],
        'monitor_changes': [Column('id', String, primary_key=True), Column('monitor_id', ForeignKey('monitors.id'), index=True), Column('revision_id', String), Column('field_id', String, index=True), Column('observation_id', String), Column('previous_observation_id', String), Column('kind', String), Column('at', Float, index=True), Column('detail', JSON)],
        'monitor_list_items': [Column('monitor_id', ForeignKey('monitors.id'), primary_key=True), Column('field_id', String, primary_key=True), Column('item_key', String(64), primary_key=True), Column('first_observed_at', Float, nullable=False)],
        'monitor_events': [Column('id', Integer, primary_key=True, autoincrement=True), Column('source_id', String), Column('monitor_id', String), Column('kind', String), Column('at', Float), Column('detail', JSON)],
        'dashboard_preferences': [Column('id', String, primary_key=True), Column('value', JSON), Column('updated_at', Float)],
    }
    tables = {name: meta.tables[name] if name in meta.tables else Table(name, meta, *cols) for name, cols in specs.items()}
    globals().update(tables)
    return tables
