"""Webhook fixture transports never contact a real destination."""
import hashlib
import hmac
import json
import os
import socket
import stat
import time

import pytest
from sqlalchemy import select

from parity.db import DB, uid
from parity import automation_notifications as notifications
from parity.automation_notifications import ConnectionStore, HTTPResult, Notifications, NotificationError, safe_post
from parity.automation_schema import (automations, automation_revisions, automation_evaluations,
                                      automation_alerts, deliveries)
from parity.monitor_schema import monitor_events


@pytest.fixture
def db(database_url):
    result = DB(database_url)
    yield result
    result.engine.dispose()


@pytest.fixture
def store(tmp_path):
    return ConnectionStore(tmp_path / 'private')


def seed(db, store, *, enabled=True, authorize=True, payload=None):
    connection = store.save({'name': 'Ops webhook', 'url': 'https://hooks.example.test/path?token=private',
                             'secret': 'private-signing-secret', 'enabled': enabled})
    now = time.time()
    automation, revision, evaluation, alert, delivery = (uid() for _ in range(5))
    with db.tx() as c:
        c.execute(automations.insert().values(id=automation, name='Budget', revision_id=revision,
                                            paused=False, created_at=now, updated_at=now))
        c.execute(automation_revisions.insert().values(id=revision, automation_id=automation, number=1,
            plan={'rules': [{'id': 'budget', 'connections': [connection['id']] if authorize else []}]}, created_at=now))
        c.execute(automation_evaluations.insert().values(id=evaluation, automation_id=automation,
            revision_id=revision, at=now, status='ok', inputs=[], outputs={'cost': '123.45'}))
        c.execute(automation_alerts.insert().values(id=alert, automation_id=automation, revision_id=revision,
            rule_id='budget', evaluation_id=evaluation, name='Over budget', status='open', kind='triggered', at=now))
        c.execute(deliveries.insert().values(id=delivery, alert_id=alert, automation_id=automation,
            revision_id=revision, connection_id=connection['id'], payload=payload or {'cost': '123.45', 'alert_id': alert},
            status='queued', attempts=0, generation=0, lease_until=0, available_at=0, created_at=now))
    return delivery, automation, revision, connection


def row(db, identity):
    return db.one(select(deliveries).where(deliveries.c.id == identity))


def test_private_store_omits_secrets_and_preserves_omitted_configuration(store, monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: pytest.fail('Saving a connection must not resolve DNS'))
    safe = store.save({'name': 'Operations', 'url': 'https://hooks.example.test/send?token=secret', 'secret': 'sensitive'})
    assert safe['enabled'] is False
    assert set(safe) == {'id', 'name', 'enabled', 'configured'}
    assert 'sensitive' not in json.dumps(store.list())
    changed = store.save({'name': 'Renamed', 'enabled': True}, safe['id'])
    assert changed['enabled'] is True
    assert store.get(safe['id'])['secret'] == 'sensitive'
    assert store.get(safe['id'])['url'].endswith('?token=secret')
    if os.name != 'nt':
        assert stat.S_IMODE(store.root.stat().st_mode) == 0o700
        assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    store.disable(safe['id'])
    assert store.list()[0]['enabled'] is False
    store.delete(safe['id'])
    assert store.delete(safe['id'])['deleted'] is False
    assert store.list() == []


@pytest.mark.parametrize('url', ['http://example.test/', 'https://user:password@example.test/',
    'https://example.test/#fragment', 'https://example.test/\r\nHeader:value', 'https://example.test:0/',
    'https://example.test:65536/', 'https://example.test\\@evil.test/', 'not a URL'])
def test_connection_rejects_unsafe_syntax_without_storing(store, url):
    with pytest.raises(ValueError):
        store.save({'name': 'Bad', 'url': url})
    assert store.list() == []


def test_connection_identifiers_and_failed_edits_cannot_escape_private_file(store):
    saved = store.save({'name': 'Valid', 'url': 'https://example.test/'})
    before = store.path.read_bytes()
    with pytest.raises(ValueError):
        store.save({'url': 'http://example.test/'}, saved['id'])
    for identity in ('../../outside', '', 'a/b'):
        with pytest.raises(ValueError):
            store.get(identity)
        with pytest.raises(ValueError):
            store.delete(identity)
    assert store.path.read_bytes() == before


def test_success_is_signed_idempotent_and_has_committed_safe_event(db, store):
    identity, _, _, _ = seed(db, store)
    calls = []
    def transport(url, payload, headers, timeout):
        calls.append((url, payload, headers, timeout))
        return HTTPResult(204, {})
    worker = Notifications(db, store, transport)
    assert worker.once()['status'] == 'succeeded'
    assert worker.once() is None
    assert len(calls) == 1
    _, payload, headers, timeout = calls[0]
    assert headers['Idempotency-Key'] == identity and timeout <= 10
    assert headers['X-Parity-Signature'] == 'sha256=' + hmac.new(
        b'private-signing-secret', payload, hashlib.sha256).hexdigest()
    saved = row(db, identity)
    assert saved['attempts'] == 1 and saved['http_status'] == 204
    event = db.one(select(monitor_events).where(monitor_events.c.kind == 'delivery_updated'))
    assert event['detail']['status'] == 'succeeded'
    assert 'private' not in json.dumps(event)


@pytest.mark.parametrize('status', [301, 302, 307, 308, 400, 401, 403, 404, 410])
def test_permanent_failure_and_redirect_never_retry_or_follow(db, store, status):
    identity, _, _, _ = seed(db, store)
    calls = []
    def transport(*args, **kwargs):
        calls.append(1)
        return HTTPResult(status, {'location': 'https://another.test/private'})
    worker = Notifications(db, store, transport)
    assert worker.once()['status'] == 'failed'
    assert worker.once() is None
    assert row(db, identity)['http_status'] == status
    assert len(calls) == 1


def test_transient_failures_stop_after_five_attempts_with_stable_key(db, store):
    identity, _, _, _ = seed(db, store)
    keys = []
    def transport(url, payload, headers, timeout):
        keys.append(headers['Idempotency-Key'])
        return HTTPResult(503, {'retry-after': '9999999999'})
    worker = Notifications(db, store, transport)
    for index in range(5):
        before = time.time()
        result = worker.once()
        saved = row(db, identity)
        assert saved['attempts'] == index + 1
        if index < 4:
            assert result['status'] == 'queued'
            assert 86399 <= saved['available_at'] - before <= 86402
            with db.tx() as c:
                c.execute(deliveries.update().where(deliveries.c.id == identity).values(available_at=0))
        else:
            assert result['status'] == 'failed'
    assert keys == [identity] * 5
    assert worker.once() is None


@pytest.mark.parametrize('change', ['paused', 'archived', 'revision', 'connection_disabled', 'deleted'])
def test_pause_revision_and_connection_changes_fence_pending_send(db, store, change):
    identity, automation, _, connection = seed(db, store)
    calls = []
    worker = Notifications(db, store, lambda *a, **k: calls.append(1))
    claim = worker.claim()
    if change in ('paused', 'archived', 'revision'):
        values = {'paused': True} if change == 'paused' else {'archived_at': time.time()} if change == 'archived' else {'revision_id': uid()}
        with db.tx() as c:
            c.execute(automations.update().where(automations.c.id == automation).values(**values))
    elif change == 'connection_disabled':
        store.disable(connection['id'])
    else:
        store.delete(connection['id'])
    assert worker.deliver(claim)['status'] == 'disabled'
    assert calls == []
    assert row(db, identity)['status'] == 'disabled'


def test_rule_must_explicitly_authorize_connection(db, store):
    identity, _, _, _ = seed(db, store, authorize=False)
    worker = Notifications(db, store, lambda *a, **k: pytest.fail('No authorized action'))
    assert worker.once() is None
    assert row(db, identity)['status'] == 'disabled'


def test_expired_claim_is_reclaimed_with_new_generation_and_old_owner_cannot_send(db, store):
    identity, _, _, _ = seed(db, store)
    first = Notifications(db, store, lambda *a, **k: pytest.fail('Stale worker sent request'), worker_id='first')
    claim = first.claim()
    with db.tx() as c:
        c.execute(deliveries.update().where(deliveries.c.id == identity).values(lease_until=0))
    second = Notifications(db, store, lambda *a, **k: HTTPResult(200, {}), worker_id='second')
    recovered = second.claim()
    assert recovered['generation'] == claim['generation'] + 1
    with pytest.raises(ValueError, match='STALE_WORKER'):
        first.deliver(claim)
    assert second.renew(recovered)
    assert second.deliver(recovered)['status'] == 'succeeded'
    assert row(db, identity)['attempts'] == 2


def test_transport_exception_secrets_are_never_persisted(db, store):
    identity, _, _, _ = seed(db, store)
    def transport(*args, **kwargs):
        raise RuntimeError('https://hooks.example.test/?token=private-signing-secret response confidential')
    worker = Notifications(db, store, transport)
    assert worker.once()['error'] == 'delivery_error'
    assert 'private' not in json.dumps(row(db, identity))
    assert 'confidential' not in json.dumps(db.all(select(monitor_events)))


def test_oversized_payload_is_rejected_before_network(db, store):
    identity, _, _, _ = seed(db, store, payload={'value': 'x' * (64 * 1024)})
    worker = Notifications(db, store, lambda *a, **k: pytest.fail('Payload exceeds bound'))
    assert worker.once() == {'id': identity, 'status': 'failed', 'error': 'payload_too_large'}


@pytest.mark.parametrize('address', ['127.0.0.1', '10.1.2.3', '192.168.1.2', '169.254.169.254', '::1', '::ffff:127.0.0.1'])
def test_private_and_rebound_destinations_never_connect(monkeypatch, address):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET6 if ':' in address else socket.AF_INET,
        socket.SOCK_STREAM, 6, '', (address, 443))])
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('Private destination connected'))
    with pytest.raises(NotificationError, match='unsafe_destination'):
        safe_post('https://public-name.test/path', b'{}', {})


def test_post_preserves_query_tls_hostname_and_response_bound(monkeypatch):
    observed = {}
    class Socket:
        def settimeout(self, value):
            assert 0 < value <= 10
        def close(self):
            pass
        def shutdown(self, *args):
            pass
    class Context:
        def wrap_socket(self, sock, server_hostname):
            observed['hostname'] = server_hostname
            return sock
    class Response:
        status = 204
        def getheaders(self):
            return []
        def read(self, size):
            observed['response_bound'] = size
            return b''
    class Connection:
        def __init__(self, host, port):
            observed['connection'] = (host, port)
        def request(self, method, target, body, headers):
            observed.update(method=method, target=target, headers=headers)
        def getresponse(self):
            return Response()
        def close(self):
            pass
    monkeypatch.setattr(notifications, '_addresses', lambda url, deadline: ['93.184.216.34'])
    def connect(target, timeout):
        observed['socket_target'] = target
        return Socket()
    monkeypatch.setattr(socket, 'create_connection', connect)
    monkeypatch.setattr(notifications.ssl, 'create_default_context', lambda: Context())
    monkeypatch.setattr(notifications.http.client, 'HTTPConnection', Connection)
    result = safe_post('https://hooks.example.test/post?utm_token=a%2Bb&token=signed+query', b'{}', {'Idempotency-Key': 'delivery'})
    assert result.status == 204
    assert observed['socket_target'] == ('93.184.216.34', 443)
    assert observed['hostname'] == 'hooks.example.test'
    assert observed['target'] == '/post?utm_token=a%2Bb&token=signed+query'
    assert observed['headers']['Host'] == 'hooks.example.test'
    assert observed['response_bound'] == 4096


def test_retry_after_http_date_and_invalid_values_are_bounded():
    now = time.time()
    future = notifications.email.utils.formatdate(now + 120, usegmt=True)
    assert 119 <= notifications.retry_after({'Retry-After': future}, now) <= 120
    for value in ('nonsense', '-1', 'NaN'):
        assert notifications.retry_after({'retry-after': value}, now) == 0
