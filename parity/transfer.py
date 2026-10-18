"""Verified portable backups and SQLite-to-PostgreSQL migration.

The archive contains data and evidence, never connection credentials. Restore
requires an empty target and verifies every table before resetting worker leases.
"""
import hashlib
import json
import math
import os
from pathlib import Path,PurePosixPath
import sqlite3
import struct
import tempfile
import time
import zipfile
from contextlib import closing
from sqlalchemy import create_engine,select,func,inspect,text
from sqlalchemy.pool import NullPool
from .db import DB,meta,SCHEMA_VERSION

FORMAT=1


def resolve_sqlite(source):
    path=Path(source).expanduser().resolve()
    if path.is_file():return path,path.parent
    if path.is_dir():
        candidates=[path/'parity.db',path/'data'/'parity.db']
        found=[candidate for candidate in candidates if candidate.is_file()]
        if len(found)==1:return found[0],found[0].parent
    raise ValueError('Choose the existing parity.db file, its data folder, or its installation folder.')


def _sqlite_snapshot(source,destination):
    # SQLite backup includes the WAL without changing the original database.
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=30)) as original:
        with closing(sqlite3.connect(destination)) as copied:
            with copied:original.backup(copied)


def _plain(value):
    if hasattr(value,'tolist'):return _plain(value.tolist())
    if isinstance(value,dict):return {str(key):_plain(item) for key,item in value.items()}
    if isinstance(value,(tuple,list)):return [_plain(item) for item in value]
    if isinstance(value,float) and not math.isfinite(value):raise ValueError('Non-finite database value cannot be backed up')
    return value


def _row(row):
    result=_plain(dict(row))
    # pgvector stores float32. Normalize only vectors so cross-database hashes
    # compare the representation PostgreSQL can preserve exactly.
    if result.get('vector') is not None:
        result['vector']=[struct.unpack('!f',struct.pack('!f',float(item)))[0] for item in result['vector']]
    return result


def _line(row):
    return (json.dumps(_row(row),ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode('utf-8')


def _hash_file(path):
    value=hashlib.sha256()
    with path.open('rb') as handle:
        while block:=handle.read(1024*1024):value.update(block)
    return value.hexdigest()


def _safe_relative(value):
    path=PurePosixPath(str(value).replace('\\','/'))
    if path.is_absolute() or not path.parts or '..' in path.parts or ':' in str(path):raise ValueError('Unsafe evidence path in backup')
    return path.as_posix()


def _references(table,row):
    if table=='versions' and row.get('raw_key'):
        return ['artifacts/'+_safe_relative(row['raw_key'])]
    if table=='monitor_captures' and row.get('raw_key'):
        return [_safe_relative(row['raw_key'])]
    if table=='url_jobs':
        capture=(row.get('metrics') or {}).get('_capture')
        if capture:return ['artifacts/'+_safe_relative(capture['raw_key'])]
    return []


def backup_database(database_url,data_dir,destination):
    """Create a verified ZIP from a consistent SQL snapshot and immutable captures."""
    data=Path(data_dir).resolve();destination=Path(destination).resolve()
    if destination.exists():raise ValueError('Backup destination already exists; choose a new filename')
    destination.parent.mkdir(parents=True,exist_ok=True)
    engine=create_engine(database_url,poolclass=NullPool)
    archive_temp=None
    try:
        with tempfile.TemporaryDirectory(prefix='parity-backup-',dir=destination.parent) as temporary:
            temporary=Path(temporary)
            if engine.dialect.name=='sqlite':
                source=Path(engine.url.database).resolve()
                engine.dispose();snapshot=temporary/'snapshot.sqlite'
                _sqlite_snapshot(source,snapshot)
                engine=create_engine('sqlite:///'+str(snapshot),poolclass=NullPool)
            manifest={'format':FORMAT,'created_at':time.time(),'schema_version':None,
                'database':engine.dialect.name,'vector_representation':'float32','tables':{},'files':{}}
            archive_temp=temporary/'backup.zip';references=set()
            with zipfile.ZipFile(archive_temp,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as archive:
                with engine.connect() as connection:
                    if engine.dialect.name=='postgresql':
                        connection=connection.execution_options(isolation_level='REPEATABLE READ')
                        connection.exec_driver_sql('SET TRANSACTION READ ONLY')
                    available=set(inspect(connection).get_table_names())
                    unknown=available-set(meta.tables)
                    if unknown:raise ValueError('Database contains unsupported tables: '+', '.join(sorted(unknown)))
                    if 'schema_version' not in available:raise ValueError('This database is not a Parity database')
                    manifest['schema_version']=connection.execute(select(func.max(meta.tables['schema_version'].c.number))).scalar()
                    if not manifest['schema_version'] or manifest['schema_version']>SCHEMA_VERSION:
                        raise ValueError('Unsupported database schema version')
                    for table in meta.sorted_tables:
                        if table.name not in available:continue
                        checksum=hashlib.sha256();count=0
                        columns=list(table.columns.keys())
                        statement=select(table).order_by(*table.primary_key.columns)
                        with archive.open('tables/'+table.name+'.jsonl','w',force_zip64=True) as output:
                            rows=connection.execution_options(stream_results=True).execute(statement).mappings()
                            for row in rows:
                                row=_row(row);encoded=_line(row);output.write(encoded);checksum.update(encoded);count+=1
                                references.update(_references(table.name,row))
                        manifest['tables'][table.name]={'count':count,'sha256':checksum.hexdigest(),'columns':columns}
                # Portal fixture state is a separate SQLite database; snapshot its WAL too.
                portal=data/'portal.sqlite'
                if portal.is_file():
                    portal_copy=temporary/'portal.sqlite';_sqlite_snapshot(portal,portal_copy)
                    archive.write(portal_copy,'data/portal.sqlite')
                    manifest['files']['portal.sqlite']={'sha256':_hash_file(portal_copy),'bytes':portal_copy.stat().st_size}
                for relative in sorted(references):
                    source=(data/relative).resolve()
                    if not source.is_relative_to(data) or not source.is_file():raise ValueError('Referenced evidence is missing or outside the data folder: '+relative)
                    checksum=_hash_file(source)
                    archive.write(source,'data/'+relative)
                    manifest['files'][relative]={'sha256':checksum,'bytes':source.stat().st_size}
                archive.writestr('manifest.json',json.dumps(manifest,indent=2,sort_keys=True))
            verify_backup(archive_temp)
            os.replace(archive_temp,destination)
            return {'backup':str(destination),'sha256':_hash_file(destination),'tables':{
                name:details['count'] for name,details in manifest['tables'].items()},'files':len(manifest['files'])}
    finally:engine.dispose()


def verify_backup(path):
    with zipfile.ZipFile(path) as archive:
        names=archive.namelist()
        if len(names)!=len(set(names)):raise ValueError('Backup contains duplicate entries')
        manifest=json.loads(archive.read('manifest.json'))
        if manifest.get('format')!=FORMAT or manifest.get('schema_version',SCHEMA_VERSION+1)>SCHEMA_VERSION:
            raise ValueError('Unsupported backup format or schema version')
        expected={'manifest.json'}
        for name,details in manifest['tables'].items():
            if name not in meta.tables:raise ValueError('Unknown table in backup')
            member='tables/'+name+'.jsonl';expected.add(member)
            digest=hashlib.sha256();count=0
            with archive.open(member) as handle:
                for line in handle:
                    digest.update(line);json.loads(line);count+=1
            if digest.hexdigest()!=details['sha256'] or count!=details['count']:raise ValueError('Table integrity check failed: '+name)
        for relative,details in manifest['files'].items():
            relative=_safe_relative(relative);member='data/'+relative;expected.add(member)
            digest=hashlib.sha256();length=0
            with archive.open(member) as handle:
                while block:=handle.read(1024*1024):digest.update(block);length+=len(block)
            if digest.hexdigest()!=details['sha256'] or length!=details['bytes']:raise ValueError('Evidence integrity check failed: '+relative)
        if set(names)!=expected:raise ValueError('Backup contains unexpected files')
        return manifest


def _verify_table(connection,table,expected):
    checksum=hashlib.sha256();count=0
    for row in connection.execute(select(table).order_by(*table.primary_key.columns)).mappings():
        checksum.update(_line(row));count+=1
    if count!=expected['count'] or checksum.hexdigest()!=expected['sha256']:
        raise ValueError('Restored table verification failed: '+table.name)


def restore_database(archive_path,target_url,target_data):
    """Restore into an empty database/data destination; rollback on any mismatch."""
    manifest=verify_backup(archive_path)
    data=Path(target_data).resolve()
    if data.exists() and any(data.iterdir()):raise ValueError('Target data folder must be empty')
    data.mkdir(parents=True,exist_ok=True)
    database=DB(target_url);copied=[]
    try:
        with database.tx() as connection:
            if database.engine.dialect.name=='postgresql':connection.exec_driver_sql('SELECT pg_advisory_xact_lock(1936745082)')
            for table in meta.sorted_tables:
                if table.name=='schema_version':continue
                if connection.execute(select(table).limit(1)).first():raise ValueError('Target database must be empty: '+table.name)
            with zipfile.ZipFile(archive_path) as archive:
                for table in meta.sorted_tables:
                    if table.name=='schema_version' or table.name not in manifest['tables']:continue
                    batch=[]
                    with archive.open('tables/'+table.name+'.jsonl') as handle:
                        for line in handle:
                            batch.append(json.loads(line))
                            if len(batch)>=100:
                                connection.execute(table.insert(),batch);batch=[]
                        if batch:connection.execute(table.insert(),batch)
                    _verify_table(connection,table,manifest['tables'][table.name])
                for relative,details in manifest['files'].items():
                    target=(data/_safe_relative(relative)).resolve()
                    if not target.is_relative_to(data):raise ValueError('Unsafe restore path')
                    target.parent.mkdir(parents=True,exist_ok=True)
                    with archive.open('data/'+relative) as original,target.open('xb') as output:
                        copied.append(target)
                        while block:=original.read(1024*1024):output.write(block)
                    if _hash_file(target)!=details['sha256']:raise ValueError('Restored evidence verification failed: '+relative)
                # Legacy archives have no projection; rebuild using their stored vectors.
                if 'search_projection' not in manifest['tables']:
                    connection.exec_driver_sql('''INSERT INTO search_projection
                        (chunk_id,source_id,page_id,version_id,text,heading,locator,model_signature,vector)
                        SELECT ch.id,p.source_id,p.id,v.id,ch.text,ch.heading,ch.locator,ec.signature,ec.vector
                        FROM chunks ch JOIN versions v ON ch.version_id=v.id JOIN pages p ON v.page_id=p.id
                        JOIN embedding_cache ec ON ch.cache_id=ec.id WHERE v.indexed_at IS NOT NULL''')
                _reset_runtime(connection)
                if database.engine.dialect.name=='postgresql':
                    # Restore explicitly supplied event IDs before repairing SERIAL sequences.
                    for table in meta.sorted_tables:
                        for column in table.primary_key:
                            if column.type.python_type is int:
                                sequence=connection.execute(text('SELECT pg_get_serial_sequence(:table_name,:column_name)'),
                                    {'table_name':table.name,'column_name':column.name}).scalar()
                                if sequence:
                                    maximum=connection.execute(select(func.max(column))).scalar()
                                    connection.execute(text('SELECT setval(CAST(:sequence AS regclass),:value,:called)'),
                                        {'sequence':sequence,'value':maximum or 1,'called':maximum is not None})
        return {'tables':{name:value['count'] for name,value in manifest['tables'].items()},
            'files':len(manifest['files']),'verified':True,'schema_version':SCHEMA_VERSION,
            'runtime_reset':'Worker leases cleared; durable URL and indexing jobs resume from saved progress.'}
    except Exception:
        for path in copied:
            if path.is_relative_to(data) and path.is_file():path.unlink()
        raise
    finally:database.engine.dispose()


def _reset_runtime(connection):
    # Keep frozen configurations, progress and evidence. Only process ownership is obsolete.
    from .job_schema import url_jobs,index_jobs,origin_locks,resource_locks,worker_status,run_state
    from .db import sources,runs
    connection.execute(worker_status.delete())
    for table in (url_jobs,index_jobs):
        connection.execute(table.update().where(table.c.status=='running').values(status='queued',owner=None,lease_until=0))
    connection.execute(origin_locks.update().values(owner=None,lease_until=0))
    connection.execute(resource_locks.update().values(owner=None,lease_until=0))
    connection.execute(sources.update().values(lease_until=0))
    legacy=select(runs.c.id).where(runs.c.status.in_(['queued','running']),
        ~select(run_state.c.run_id).where(run_state.c.run_id==runs.c.id).exists())
    legacy_ids=list(connection.execute(legacy).scalars())
    if legacy_ids:
        connection.execute(runs.update().where(runs.c.id.in_(legacy_ids)).values(status='failed',finished_at=time.time(),
            error='Monitoring was interrupted during migration. Start a new check.'))
        connection.execute(sources.update().where(sources.c.lease_run.in_(legacy_ids)).values(lease_run=None,next_due=0))


def migrate_sqlite(source,target_url,target_data,backup_path=None):
    original,data=resolve_sqlite(source)
    if not target_url.startswith('postgresql'):raise ValueError('Migration target must be PostgreSQL')
    target_data=Path(target_data).resolve()
    if target_data==data or target_data.is_relative_to(data):raise ValueError('Use a separate destination data folder')
    backup=Path(backup_path).resolve() if backup_path else target_data.parent/('parity-before-migration-'+time.strftime('%Y%m%d-%H%M%S')+'.zip')
    saved=backup_database('sqlite:///'+str(original),data,backup)
    restored=restore_database(backup,target_url,target_data)
    return {'backup':saved,'restore':restored,'original_preserved':True}
