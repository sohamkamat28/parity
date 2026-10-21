"""Private webhook configuration and fenced, bounded notification delivery.

Only connection references belong in the database or an exported backup. The
worker resolves and validates the destination again for every delivery attempt.
An ambiguous remote timeout can cause a repeated POST; receivers should dedupe
the stable Idempotency-Key. No server-supplied response body is stored or logged.
"""
from __future__ import annotations

from dataclasses import dataclass
import email.utils
import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import re
import socket
import ssl
import tempfile
import threading
import time
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import and_, or_, select

from . import config
from .db import uid
from .fetch import FetchError, Fetcher

MAX_PAYLOAD = 64 * 1024
MAX_ATTEMPTS = 5
TIMEOUT = 10
_STORE_LOCK = threading.RLock()
_DNS_SLOTS = threading.BoundedSemaphore(2)


class NotificationError(ValueError):
    def __init__(self, code, *, transient=False):
        super().__init__(code)
        self.code = code
        self.transient = transient


def validate_url(url):
    """Validate syntax without making requests or rewriting signed query strings."""
    if not isinstance(url, str) or len(url) > 4096 or any(ord(c) < 33 or ord(c) == 127 for c in url):
        raise ValueError('Enter a valid public HTTPS webhook URL.')
    try:
        p = urlsplit(url)
        valid = (p.scheme.lower() == 'https' and p.hostname and not p.username
                 and not p.password and not p.fragment and (p.port is None or 1 <= p.port <= 65535))
        if not valid:
            raise ValueError()
        p.hostname.encode('idna')
        if '\\' in p.netloc:
            raise ValueError()
    except (ValueError, UnicodeError):
        raise ValueError('Enter a valid public HTTPS webhook URL without embedded credentials or a fragment.') from None
    return url


class ConnectionStore:
    """Atomic private local file. Public methods never return URL or secret."""
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else Path(config.DATA) / 'private'
        self.path = self.root / 'automation-connections.json'

    @staticmethod
    def _identifier(value):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', value):
            raise ValueError('Invalid connection identifier.')
        return value

    def _read(self):
        if self.root.is_symlink() or self.path.is_symlink():
            raise ValueError('Private connection configuration must not be a symbolic link.')
        if not self.path.exists():
            return {}
        try:
            if self.path.stat().st_size > 1024 * 1024:
                raise ValueError()
            content = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(content, dict) or not isinstance(content.get('connections'), dict):
                raise ValueError()
            records = content['connections']
            for identity, record in records.items():
                self._identifier(identity)
                if not isinstance(record, dict) or record.get('id') != identity:
                    raise ValueError()
            return records
        except (OSError, ValueError, TypeError):
            raise ValueError('Private connection configuration is unavailable or invalid.') from None

    def _write(self, records):
        if self.root.is_symlink() or self.path.is_symlink():
            raise ValueError('Private connection configuration must not be a symbolic link.')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        descriptor, temporary = tempfile.mkstemp(prefix='.connections-', dir=self.root)
        try:
            os.chmod(temporary, 0o600)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump({'version': 1, 'connections': records}, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _safe(record):
        return {'id': record['id'], 'name': record['name'],
                'enabled': record.get('enabled') is True, 'configured': bool(record.get('url'))}

    def list(self):
        with _STORE_LOCK:
            return [self._safe(value) for value in self._read().values()]

    def get(self, connection_id):
        """Internal worker access; callers must not serialize this record."""
        self._identifier(connection_id)
        with _STORE_LOCK:
            record = self._read().get(connection_id)
            return dict(record) if record else None

    def save(self, payload, connection_id=None):
        if not isinstance(payload, dict) or set(payload) - {'name', 'url', 'secret', 'enabled'}:
            raise ValueError('Connection accepts name, URL, optional signing secret and enabled state.')
        if connection_id is not None:
            self._identifier(connection_id)
        with _STORE_LOCK:
            records = self._read()
            if connection_id is not None and connection_id not in records:
                raise ValueError('Connection not found.')
            identity = connection_id or uid()
            record = dict(records.get(identity, {}))
            record.update(payload)
            record['id'] = identity
            name = record.get('name', '')
            if not isinstance(name, str) or not name.strip() or len(name) > 100 or any(ord(c) < 32 for c in name):
                raise ValueError('Enter a connection name of at most 100 characters.')
            record['name'] = name.strip()
            validate_url(record.get('url'))
            secret = record.get('secret', '')
            if not isinstance(secret, str) or len(secret) > 4096:
                raise ValueError('Signing secret must be text of at most 4096 characters.')
            record['secret'] = secret
            enabled = record.get('enabled', False)
            if not isinstance(enabled, bool):
                raise ValueError('Connection enabled state must be true or false.')
            record['enabled'] = enabled
            if len(records) >= 100 and identity not in records:
                raise ValueError('At most 100 webhook connections are supported.')
            records[identity] = record
            self._write(records)
            return self._safe(record)

    def delete(self, connection_id):
        self._identifier(connection_id)
        with _STORE_LOCK:
            records = self._read()
            existed = records.pop(connection_id, None) is not None
            if existed:
                self._write(records)
            return {'id': connection_id, 'deleted': existed}

    def disable(self, connection_id):
        return self.save({'enabled': False}, connection_id)


@dataclass(frozen=True)
class HTTPResult:
    status: int
    headers: dict


def _addresses(url, deadline):
    """Bound DNS wait and outstanding resolver threads, including stuck DNS."""
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not _DNS_SLOTS.acquire(timeout=max(0, remaining)):
        raise NotificationError('network_timeout', transient=True)
    ready = threading.Event()
    answer = {}
    def resolve():
        try:
            answer['addresses'] = Fetcher().addresses(url, {'root_url': url, 'config': {}})
        except Exception as error:
            answer['error'] = error
        finally:
            _DNS_SLOTS.release()
            ready.set()
    threading.Thread(target=resolve, name='parity-webhook-dns', daemon=True).start()
    if not ready.wait(max(0, deadline - time.monotonic())):
        raise NotificationError('network_timeout', transient=True)
    if 'error' in answer:
        error = answer['error']
        if isinstance(error, FetchError) and error.code == 'unsafe_destination':
            raise NotificationError('unsafe_destination') from None
        raise NotificationError('dns_error', transient=True) from None
    return answer['addresses']


def safe_post(url, payload, headers, timeout=TIMEOUT):
    """POST once, with pinned public addresses, original-host TLS and no redirects."""
    validate_url(url)
    if len(payload) > MAX_PAYLOAD:
        raise NotificationError('payload_too_large')
    deadline = time.monotonic() + min(TIMEOUT, max(.1, timeout))
    addresses = _addresses(url, deadline)
    p = urlsplit(url)
    sock = None
    connection = None
    timer = None
    try:
        # Interleave address families within four attempts and one total budget.
        families = {False: [], True: []}
        for address in addresses:
            families[':' in address].append(address)
        first = ':' in addresses[0]
        ordered = [families[version][index] for index in range(4)
                   for version in (first, not first) if index < len(families[version])][:4]
        for address in ordered:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                sock = socket.create_connection((address, p.port or 443), timeout=min(3, remaining))
                sock.settimeout(max(.01, min(3, deadline - time.monotonic())))
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=p.hostname)
                break
            except ssl.SSLCertVerificationError:
                if sock:
                    sock.close()
                raise NotificationError('tls_verification_failed') from None
            except OSError:
                if sock:
                    sock.close()
                sock = None
        if sock is None or deadline <= time.monotonic():
            raise NotificationError('network_timeout', transient=True)
        sock.settimeout(max(.01, deadline - time.monotonic()))
        def abort():
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        timer = threading.Timer(max(.01, deadline - time.monotonic()), abort)
        timer.daemon = True
        timer.start()
        connection = http.client.HTTPConnection(p.hostname, p.port or 443)
        connection.sock = sock
        connection.request('POST', urlunsplit(('', '', p.path or '/', p.query, '')), body=payload,
                           headers={'Host': p.netloc, 'Content-Type': 'application/json',
                                    'User-Agent': 'Parity/2.0 webhook', 'Accept-Encoding': 'identity', **headers})
        response = connection.getresponse()
        result = HTTPResult(response.status, {key.lower(): value for key, value in response.getheaders()})
        response.read(4096)
        return result
    except NotificationError:
        raise
    except (TimeoutError, OSError, http.client.HTTPException):
        raise NotificationError('network_error', transient=True) from None
    finally:
        if timer:
            timer.cancel()
        if connection:
            connection.close()
        elif sock:
            sock.close()


def retry_after(headers, now):
    value = next((v for k, v in headers.items() if k.lower() == 'retry-after'), '')
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        try:
            seconds = email.utils.parsedate_to_datetime(value).timestamp() - now
        except (ValueError, TypeError, OverflowError):
            return 0
    if not 0 <= seconds <= float('inf'):
        return 0
    return min(86400, seconds)


class Notifications:
    def __init__(self, service_or_db, store=None, transport=None, worker_id=None):
        self.db = getattr(service_or_db, 'db', service_or_db)
        self.store = store or ConnectionStore()
        self.transport = transport or safe_post
        self.worker_id = worker_id or 'notification-' + uid()
        self.lease_seconds = max(30, getattr(config, 'LEASE_SECONDS', 30))

    @staticmethod
    def _tables():
        from .automation_schema import automations, automation_revisions, automation_alerts, deliveries
        return automations, automation_revisions, automation_alerts, deliveries

    def _plan(self, c, row):
        revisions = self._tables()[1]
        return c.execute(select(revisions.c.plan).where(revisions.c.id == row['revision_id'])).scalar() or {}

    def _lock_sources(self, c, row, *, skip_locked=False):
        # Match calculation and monitor publication ordering: sources ->
        # automation -> job/delivery. Revision plans are immutable.
        from .db import sources
        identities = sorted({binding['source_id'] for binding in self._plan(c, row).get('inputs', [])
                             if binding.get('source_id')})
        if not identities:
            return True
        locked = c.execute(select(sources.c.id).where(sources.c.id.in_(identities)).order_by(sources.c.id)
                           .with_for_update(skip_locked=skip_locked)).scalars().all()
        return not skip_locked or len(locked) == len(identities)

    def _dependencies_eligible(self, c, plan):
        from .db import sources
        from .monitor_schema import monitors, monitor_revisions, monitor_field_states
        from .automation import definition_signature
        now = time.time()
        for binding in plan.get('inputs', []):
            source = c.execute(select(sources).where(sources.c.id == binding.get('source_id'))).mappings().first()
            monitor = c.execute(select(monitors).where(monitors.c.id == binding.get('monitor_id'))).mappings().first()
            if (not source or not source['enabled'] or source['paused'] or source['removed_at'] is not None
                    or not monitor or monitor['paused'] or monitor['source_id'] != source['id']):
                return False
            revision = c.execute(select(monitor_revisions).where(monitor_revisions.c.id == monitor['revision_id'])).mappings().first()
            definition = next((field for field in revision['fields'] if field['id'] == binding.get('field_id')), None) if revision else None
            if not definition or definition_signature(definition) != binding.get('signature'):
                return False
            state = c.execute(select(monitor_field_states).where(
                monitor_field_states.c.revision_id == monitor['revision_id'],
                monitor_field_states.c.field_id == binding.get('field_id'))).mappings().first()
            if (not state or state['status'] != 'ok' or not state['last_verified_at']
                    or now - state['last_verified_at'] > source['config']['interval']):
                return False
        return True

    def _eligible(self, c, row, automation):
        if not automation or automation['paused'] or automation['archived_at'] is not None:
            return False
        if automation['revision_id'] != row['revision_id']:
            return False
        _, _, alerts, _ = self._tables()
        plan = self._plan(c, row)
        rule_id = c.execute(select(alerts.c.rule_id).where(alerts.c.id == row['alert_id'])).scalar()
        return (any(rule.get('id') == rule_id and row['connection_id'] in rule.get('connections', [])
                    for rule in plan.get('rules', [])) and self._dependencies_eligible(c, plan))

    @staticmethod
    def _event(c, row, status, now):
        from .monitor_schema import monitor_events
        c.execute(monitor_events.insert().values(kind='delivery_updated', at=now, detail={
            'delivery_id': row['id'], 'automation_id': row['automation_id'],
            'alert_id': row['alert_id'], 'status': status}))

    def _disable(self, c, row, now, error='delivery_disabled'):
        deliveries = self._tables()[3]
        c.execute(deliveries.update().where(deliveries.c.id == row['id']).values(
            status='disabled', error=error, finished_at=now, owner=None, lease_until=0))
        self._event(c, row, 'disabled', now)

    def claim(self):
        automations, _, _, deliveries = self._tables()
        now = time.time()
        with self.db.tx() as c:
            due = select(deliveries).where(deliveries.c.available_at <= now, or_(
                deliveries.c.status == 'queued', and_(deliveries.c.status == 'running', deliveries.c.lease_until < now)))
            candidates = c.execute(due.order_by(deliveries.c.available_at, deliveries.c.created_at).limit(30)).mappings().all()
            for candidate in candidates:
                if not self._lock_sources(c, candidate, skip_locked=True):
                    continue
                automation = c.execute(select(automations).where(automations.c.id == candidate['automation_id'])
                                       .with_for_update(skip_locked=True)).mappings().first()
                # A locked row is not evidence that the automation was removed.
                if not automation:
                    continue
                row = c.execute(due.where(deliveries.c.id == candidate['id']).with_for_update(skip_locked=True)).mappings().first()
                if not row:
                    continue
                row = dict(row)
                if not self._eligible(c, row, automation):
                    self._disable(c, row, now)
                    continue
                if (row['attempts'] or 0) >= MAX_ATTEMPTS:
                    c.execute(deliveries.update().where(deliveries.c.id == row['id']).values(
                        status='failed', error='attempt_limit', finished_at=now, owner=None, lease_until=0))
                    self._event(c, row, 'failed', now)
                    continue
                generation = (row['generation'] or 0) + 1
                values = {'status': 'running', 'owner': self.worker_id, 'generation': generation,
                          'lease_until': now + self.lease_seconds, 'attempts': (row['attempts'] or 0) + 1}
                c.execute(deliveries.update().where(deliveries.c.id == row['id']).values(**values))
                return row | values
        return None

    def _locked(self, c, claim):
        automations, _, _, deliveries = self._tables()
        self._lock_sources(c, claim)
        automation = c.execute(select(automations).where(automations.c.id == claim['automation_id'])
                               .with_for_update()).mappings().first()
        row = c.execute(select(deliveries).where(deliveries.c.id == claim['id']).with_for_update()).mappings().first()
        if (not row or row['status'] != 'running' or row['owner'] != claim['owner']
                or row['generation'] != claim['generation'] or (row['lease_until'] or 0) < time.time()):
            raise ValueError('STALE_WORKER')
        return row, automation

    def renew(self, claim):
        with self.db.tx() as c:
            row, automation = self._locked(c, claim)
            if not self._eligible(c, row, automation):
                self._disable(c, row, time.time())
                return False
            deliveries = self._tables()[3]
            c.execute(deliveries.update().where(deliveries.c.id == claim['id']).values(lease_until=time.time() + self.lease_seconds))
            return True

    def deliver(self, claim):
        deliveries = self._tables()[3]
        # Lock automation before delivery, matching revision/pause publication.
        # The bounded POST stays under this lock: a pause committed before this
        # check prevents sending; a pause after an already-started POST cannot
        # retract it. The lease exceeds the full network deadline.
        with self.db.tx() as c:
            row, automation = self._locked(c, claim)
            now = time.time()
            if not self._eligible(c, row, automation):
                self._disable(c, row, now)
                return {'id': row['id'], 'status': 'disabled'}
            try:
                connection = self.store.get(row['connection_id'])
                if not connection or connection.get('enabled') is not True:
                    self._disable(c, row, now, 'connection_disabled')
                    return {'id': row['id'], 'status': 'disabled'}
                validate_url(connection['url'])
                payload = json.dumps(row['payload'], sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode('utf-8')
                if len(payload) > MAX_PAYLOAD:
                    raise NotificationError('payload_too_large')
                headers = {'Idempotency-Key': row['id']}
                if connection.get('secret'):
                    signature = hmac.new(connection['secret'].encode('utf-8'), payload, hashlib.sha256).hexdigest()
                    headers['X-Parity-Signature'] = 'sha256=' + signature
                c.execute(deliveries.update().where(deliveries.c.id == row['id']).values(lease_until=now + self.lease_seconds))
                result = self.transport(connection['url'], payload, headers, timeout=TIMEOUT)
                status = result.status
                if 200 <= status < 300:
                    values = {'status': 'succeeded', 'error': None, 'http_status': status, 'finished_at': time.time()}
                else:
                    transient = status in (408, 425, 429) or 500 <= status <= 599
                    error = 'redirect_blocked' if 300 <= status < 400 else 'http_error'
                    values = self._failure(row, error, transient, result.headers)
                    values['http_status'] = status
            except NotificationError as error:
                values = self._failure(row, error.code, error.transient, {})
            except (ValueError, KeyError, TypeError):
                values = self._failure(row, 'configuration_error', False, {})
            except Exception:
                # Never persist exception text: it can contain the URL/token or
                # an arbitrary response body supplied by an injected transport.
                values = self._failure(row, 'delivery_error', True, {})
            values.update(owner=None, lease_until=0)
            c.execute(deliveries.update().where(deliveries.c.id == row['id']).values(**values))
            self._event(c, row, values['status'], time.time())
            return {'id': row['id'], 'status': values['status'], 'error': values['error']}

    @staticmethod
    def _failure(row, error, transient, headers):
        now = time.time()
        retry = transient and row['attempts'] < MAX_ATTEMPTS
        return {'status': 'queued' if retry else 'failed', 'error': error, 'http_status': None,
                'available_at': now + max(min(86400, 5 * 2 ** row['attempts']), retry_after(headers, now)) if retry else now,
                'finished_at': None if retry else now}

    def once(self):
        claim = self.claim()
        return self.deliver(claim) if claim else None
