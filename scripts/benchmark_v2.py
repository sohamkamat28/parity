"""Reproducible PostgreSQL projection benchmark with real or explicit lexical vectors.

Creates and removes only a unique parity_bench_* database. Measures embedding +
projection ingestion, exact/hybrid vs ANN quality, first-client and warm requests.
It does not flush OS/PostgreSQL caches or claim capture-worker throughput.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
try:import resource
except ImportError:resource=None
import statistics
import re
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sqlalchemy import create_engine, select, text, func, event
from sqlalchemy.engine import make_url
from parity import config
from parity.db import DB,sources,pages,versions,cache,chunks,intervals
from parity.search_schema import projection
from parity.embedding import Embedder
from parity.service import Service
from parity.extract import digest


@contextmanager
def fresh_database(base):
    url=make_url(base);assert url.drivername.startswith('postgresql')
    admin=create_engine(url,isolation_level='AUTOCOMMIT');name='parity_bench_'+uuid.uuid4().hex
    with admin.connect() as c:c.execute(text(f'CREATE DATABASE {name}'))
    try:yield url.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as c:c.execute(text(f'DROP DATABASE {name} WITH (FORCE)'))
        admin.dispose()


def percentile(values,p):return sorted(values)[min(len(values)-1,int((len(values)-1)*p))]

def corpus_text(i):
    if i%10==0:return 'Shared reporting policy: measurements are verified at scheduled checks and require source evidence.'
    return f'Project Aster{i//10:05d} observation {i%10}. The verified capacity is {100+i%997} MW for reporting period 2026. Region {i%31} uses resource class {i%17}. This record describes collected evidence.'


def ingest(db,model,n):
    now=time.time();docs=(n+9)//10
    with db.tx() as c:
        c.execute(sources.insert().values(id='benchmark',name='Benchmark corpus',root_url='https://benchmark.invalid/',config={'interval':900,'demo':False,'source_kind':'normal'},enabled=True))
        for start in range(0,docs,500):
            batch=range(start,min(docs,start+500))
            c.execute(pages.insert(),[{'id':f'p{i}','source_id':'benchmark','url':f'https://benchmark.invalid/{i}','title':f'Project Aster{i:05d}','availability':'active','health':'healthy','current_id':f'v{i}','last_version_id':f'v{i}','checked_at':now,'verified_at':now} for i in batch])
            c.execute(versions.insert(),[{'id':f'v{i}','page_id':f'p{i}','number':1,'title':f'Project Aster{i:05d}','content':'Benchmark corpus','hash':str(i),'observed_at':now,'indexed_at':now,'sections':[]} for i in batch])
            c.execute(intervals.insert(),[{'id':f'i{i}','page_id':f'p{i}','version_id':f'v{i}','start':now} for i in batch])
    seen={};embedding_seconds=0;started=time.perf_counter()
    for start in range(0,n,512):
        batch=list(range(start,min(n,start+512)));texts={digest(model.signature+'\0'+corpus_text(i)):corpus_text(i) for i in batch}
        missing={k:t for k,t in texts.items() if k not in seen}
        tick=time.perf_counter();vectors=model.encode_many(list(missing.values()));embedding_seconds+=time.perf_counter()-tick
        new=[]
        for (key,content),vector in zip(missing.items(),vectors):
            seen[key]=key
            new.append({'id':key,'key':key,'signature':model.signature,'input':content,'vector':vector})
        # Keep only the current batch of vectors in memory; evidence references the
        # immutable cache rows, whose keys identify exact embedding reuse.
        with db.tx() as c:
            if new:c.execute(cache.insert(),new)
            c.execute(chunks.insert(),[{'id':f'c{i}','version_id':f'v{i//10}','ordinal':i%10,'heading':'Capacity','locator':f'Observation {i%10}','text':corpus_text(i),'cache_id':digest(model.signature+'\0'+corpus_text(i))} for i in batch])
            c.execute(text('''INSERT INTO search_projection (chunk_id,source_id,page_id,version_id,text,heading,locator,model_signature,vector)
                SELECT ch.id,p.source_id,p.id,v.id,ch.text,ch.heading,ch.locator,ec.signature,ec.vector
                FROM chunks ch JOIN versions v ON ch.version_id=v.id JOIN pages p ON v.page_id=p.id
                JOIN embedding_cache ec ON ch.cache_id=ec.id WHERE ch.id = ANY(:ids)'''),{'ids':[f'c{i}' for i in batch]})
    elapsed=time.perf_counter()-started
    with db.engine.begin() as c:
        c.execute(text('ANALYZE'))
        bytes_used=c.execute(text('SELECT pg_database_size(current_database())')).scalar_one()
        distinct_vectors=c.execute(select(func.count(func.distinct(cache.c.vector)))).scalar_one()
    return {'documents':docs,'chunks':n,'unique_vectors':distinct_vectors,'unique_embedding_inputs':len(seen),'reused_embeddings':n-len(seen),'embedding_seconds':embedding_seconds,'ingestion_seconds':elapsed,'ingestion_chunks_per_second':n/elapsed,'database_bytes':bytes_used}


def measure(service,queries,concurrency):
    def one(query):
        started=time.perf_counter();r=service.search(query,limit=10)
        target='p'+str(int(re.search(r'Aster(\d+)',query).group(1)))
        return {'ms':(time.perf_counter()-started)*1000,'ids':[x['chunk_id'] for x in r['results']],'target_hit':any(x['page_id']==target for x in r['results'])}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:rows=list(pool.map(one,queries))
    values=[r['ms'] for r in rows]
    return {'clients':concurrency,'queries':len(rows),'p50_ms':statistics.median(values),'p95_ms':percentile(values,.95),'max_ms':max(values),'target_document_hit_at_10':statistics.mean(r['target_hit'] for r in rows)},rows


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sizes',nargs='+',type=int,default=[1000,10000,50000]);p.add_argument('--embedder',choices=['minilm','lexical'],default='minilm')
    p.add_argument('--output',default='docs/verification/benchmark.json');p.add_argument('--queries',type=int,default=20)
    args=p.parse_args();base=os.getenv('PARITY_TEST_DATABASE_URL') or config.DATABASE_URL
    model=Embedder(args.embedder);report={'profile':'postgresql','embedding':args.embedder,'model_signature':model.signature,'cache_definition':'First client = first retrieval after ingestion; warm = repeated queries. OS/database cache flushing was not performed.','throughput_scope':'Batch embeddings and projection insertion, including HNSW maintenance; excludes fetching and document extraction.','results':[]}
    for size in args.sizes:
        print(f'Benchmark: {size} chunks',flush=True)
        with fresh_database(base) as url:
            db=DB(url);service=Service(db,model,inline_index=False)
            try:
                result=ingest(db,model,size)
                queries=[f'Project Aster{((i*7919)%(size//10)):05d} verified capacity MW' for i in range(args.queries)]
                os.environ['PARITY_ANN_ENABLED']='0';cold,exact=measure(service,queries[:1],1)
                result['first_client']=cold;result['warm']=[]
                captured={}
                def capture_sql(conn,cursor,statement,parameters,context,executemany):
                    if statement.startswith('WITH ') and 'search_projection' in statement:
                        captured.update(statement=statement,parameters=parameters)
                event.listen(db.engine,'before_cursor_execute',capture_sql)
                os.environ['PARITY_ANN_ENABLED']='1';service.search(queries[0],limit=10)
                event.remove(db.engine,'before_cursor_execute',capture_sql)
                if captured:
                    with db.engine.connect() as c:
                        c.exec_driver_sql('SET LOCAL hnsw.ef_search = 160')
                        c.exec_driver_sql("SET LOCAL hnsw.iterative_scan = 'strict_order'")
                        plan=c.exec_driver_sql('EXPLAIN (FORMAT JSON) '+captured['statement'],captured['parameters']).scalar_one()
                    result['ann_plan_uses_hnsw']='ix_projection_hnsw' in json.dumps(plan)
                    def compact(node):
                        if isinstance(node,list):return [compact(x) for x in node]
                        if isinstance(node,dict):return {k:compact(v) for k,v in node.items() if k in ('Plan','Node Type','Index Name','Relation Name','Plans')}
                        return node
                    result['ann_plan']=compact(plan)
                os.environ['PARITY_ANN_ENABLED']='0'
                for concurrency in (1,5):
                    exact_stats,exact_rows=measure(service,queries,concurrency)
                    os.environ['PARITY_ANN_ENABLED']='1';ann_stats,ann_rows=measure(service,queries,concurrency)
                    os.environ['PARITY_ANN_ENABLED']='0'
                    recall=statistics.mean(len(set(a['ids'])&set(b['ids']))/max(1,len(a['ids'])) for a,b in zip(exact_rows,ann_rows))
                    exact_stats['mode']='exact_hybrid';ann_stats.update(mode='hnsw_hybrid',recall_at_10_vs_exact=recall)
                    result['warm'].extend([exact_stats,ann_stats])
                result['process_peak_rss_bytes']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024) if resource else None
                report['results'].append(result)
                destination=ROOT/args.output;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(json.dumps(report,indent=2)+'\n')
                print(json.dumps({k:v for k,v in result.items() if k!='ann_plan'}),flush=True)
            finally:db.engine.dispose()
    return 0


if __name__=='__main__':raise SystemExit(main())
