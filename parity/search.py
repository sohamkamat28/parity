"""Hybrid retrieval with strict version eligibility and a rebuildable projection."""
import math,time,os
from collections import Counter
from sqlalchemy import select,func,and_,or_,union,literal_column,delete
from .db import chunks,versions,pages,sources,cache,intervals
from .search_schema import projection
from .embedding import tokens,STOPWORDS,cosine

def project_version(service,version_id,connection=None):
    def publish(c):
        c.execute(delete(projection).where(projection.c.version_id==version_id))
        rows=c.execute(select(chunks.c.id.label('chunk_id'),pages.c.source_id,pages.c.id.label('page_id'),
            versions.c.id.label('version_id'),chunks.c.text,chunks.c.heading,chunks.c.locator,
            cache.c.signature.label('model_signature'),cache.c.vector).select_from(
                chunks.join(versions,chunks.c.version_id==versions.c.id).join(pages,versions.c.page_id==pages.c.id)
                .join(cache,chunks.c.cache_id==cache.c.id)).where(versions.c.id==version_id)).mappings().all()
        if rows:c.execute(projection.insert(),[dict(r) for r in rows])
        return len(rows)
    if connection is not None:return publish(connection)
    with service.db.tx() as c:return publish(c)

def pending_count(service,source_ids=None):
    stmt=select(func.count()).select_from(pages.join(versions,pages.c.current_id==versions.c.id)
        .join(sources,pages.c.source_id==sources.c.id)).where(versions.c.indexed_at.is_(None),
        pages.c.availability=='active',sources.c.enabled.is_(True))
    if source_ids is not None:stmt=stmt.where(sources.c.id.in_(source_ids))
    else:stmt=stmt.where(sources.c.config['demo'].as_boolean().is_not(True),
                         func.coalesce(sources.c.config['source_kind'].as_string(),'normal')=='normal')
    with service.db.engine.connect() as c:return c.execute(stmt).scalar_one()

def postgres_search(service,query,qvec,model,source_ids,limit,mode,as_of,include_unavailable):
    base=projection.join(versions,projection.c.version_id==versions.c.id).join(pages,projection.c.page_id==pages.c.id).join(sources,projection.c.source_id==sources.c.id)
    stmt=select(projection.c.chunk_id,projection.c.text,projection.c.heading,projection.c.locator,
        projection.c.version_id,versions.c.number,versions.c.title,versions.c.observed_at,versions.c.indexed_at,
        projection.c.page_id,pages.c.url,pages.c.availability,pages.c.health,pages.c.verified_at,pages.c.checked_at,
        pages.c.last_error,projection.c.source_id,sources.c.name.label('source_name'),sources.c.config,
        projection.c.vector).select_from(base).where(or_(sources.c.enabled.is_(True),and_(sources.c.removed_at.is_not(None),mode=='as_of')),pages.c.health!='blocked',
            versions.c.indexed_at.is_not(None),projection.c.model_signature==model.signature)
    if source_ids is not None:stmt=stmt.where(sources.c.id.in_(source_ids))
    else:stmt=stmt.where(sources.c.config['demo'].as_boolean().is_not(True),
                         func.coalesce(sources.c.config['source_kind'].as_string(),'normal')=='normal')
    if mode=='current':
        stmt=stmt.where(sources.c.removed_at.is_(None),versions.c.id==pages.c.current_id)
        if not include_unavailable:stmt=stmt.where(pages.c.availability=='active')
    else:
        stmt=stmt.where(select(intervals.c.id).where(intervals.c.version_id==versions.c.id,
            intervals.c.start<=as_of,or_(intervals.c.end.is_(None),intervals.c.end>as_of)).exists())
    # Approximation is opt-in until a deployment's exact-vs-ANN benchmark passes.
    approximate=os.getenv('PARITY_ANN_ENABLED','0')=='1' and not source_ids and mode=='current'
    distance=projection.c.vector.cosine_distance(qvec)
    # Adding zero forces an exact sort over eligible rows; HNSW cannot trim this set.
    ids=stmt.with_only_columns(projection.c.chunk_id,maintain_column_froms=True)
    if approximate:
        pool=select(projection.c.chunk_id).where(projection.c.model_signature==model.signature).order_by(distance).limit(max(200,limit*20)).cte('ann_pool').prefix_with('MATERIALIZED')
        eligible_ann=ids.where(projection.c.chunk_id.in_(select(pool.c.chunk_id))).order_by(distance).limit(100).cte('eligible_ann').prefix_with('MATERIALIZED')
        # A history-heavy projection can exhaust the ANN pool. Recover with exact
        # eligible retrieval rather than returning an empty or outdated answer.
        fallback=ids.where(select(func.count()).select_from(eligible_ann).scalar_subquery()<limit).order_by(distance+0.0).limit(100).cte('dense_fallback')
        dense=union(select(eligible_ann.c.chunk_id),select(fallback.c.chunk_id)).cte('dense')
    else:dense=ids.order_by(distance+0.0).limit(100).cte('dense')
    query_terms=' '.join(word for word in tokens(query) if word not in STOPWORDS) or query
    lexq=func.plainto_tsquery(literal_column("'simple'::regconfig"),query_terms)
    lexdoc=func.to_tsvector(literal_column("'simple'::regconfig"),projection.c.text)
    title_doc=func.to_tsvector(literal_column("'simple'::regconfig"),func.coalesce(versions.c.title,'')+' '+func.coalesce(projection.c.heading,''))
    fts_score=func.ts_rank_cd(lexdoc,lexq)+func.ts_rank_cd(title_doc,lexq)
    lexical=ids.where(or_(lexdoc.op('@@')(lexq),title_doc.op('@@')(lexq))).order_by(fts_score.desc(),projection.c.chunk_id).limit(100).cte('lexical')
    selected=union(select(dense.c.chunk_id),select(lexical.c.chunk_id))
    with service.db.engine.connect() as c:
        if approximate:
            c.exec_driver_sql("SET LOCAL hnsw.ef_search = 160")
            c.exec_driver_sql("SET LOCAL hnsw.iterative_scan = 'strict_order'")
        ranked_stmt=stmt.add_columns(projection.c.chunk_id.in_(select(dense.c.chunk_id)).label('_dense'),
            projection.c.chunk_id.in_(select(lexical.c.chunk_id)).label('_lexical'),fts_score.label('_fts_score'))
        rows=[dict(r) for r in c.execute(ranked_stmt.where(projection.c.chunk_id.in_(selected))).mappings()]
    qt=set(tokens(query))-STOPWORDS
    for row in rows:
        row['_sim']=cosine(qvec,row['vector'])
        row['_lex']=len(qt.intersection(tokens((row['title'] or '')+' '+row['text'])))
        row['_score']=0
    dense_rows=sorted([r for r in rows if r['_dense']],key=lambda r:(-r['_sim'],r['chunk_id']))
    lexical_rows=sorted([r for r in rows if r['_lexical']],key=lambda r:(-r['_fts_score'],r['chunk_id']))
    for ranked in (dense_rows if model.mode=='minilm' else [],lexical_rows):
        for rank,row in enumerate(ranked,1):row['_score']+=1/(60+rank)
    results=[]
    for row in sorted(rows,key=lambda r:(-r['_score'],r['chunk_id'])):
        if not row['_score'] or not (row['_lex'] or row['_sim']>=.40):continue
        verified=row['verified_at'] if mode=='current' else row['observed_at']
        stale=verified is None or time.time()-verified>row['config'].get('interval',900)
        warnings=[]
        if mode=='as_of':warnings.append('Historical indexed snapshot')
        elif stale:warnings.append('Verification is older than the polling interval')
        if row['health']!='healthy':warnings.append(row['last_error'] or row['health'])
        if row['availability']!='active':warnings.append('Source page is currently unavailable')
        result={k:v for k,v in row.items() if not k.startswith('_') and k not in ('vector','config','verified_at')}
        result.update(score=row['_score'],cosine=row['_sim'],lexical_score=row['_lex'],score_type='RRF',
            last_verified_at=verified,freshness_status='historical' if mode=='as_of' else ('stale' if stale else 'within_interval'),
            is_demo=row['config'].get('demo',False),warnings=warnings)
        results.append(result)
        if len(results)==limit:break
    pending=pending_count(service,source_ids)
    return {'query':query,'mode':mode,'as_of':as_of,'embedding_mode':model.mode,'results':results,
        'retrieval':'hnsw_hybrid' if approximate else 'exact_hybrid','index_pending':pending,
        'message':'Search index updating' if pending else ('' if results else 'No sufficiently relevant evidence found.')}

def search(service,query,source_ids=None,limit=5,mode="current",as_of=None,include_unavailable=False):
    if not query.strip() or len(query)>2000:raise ValueError("Query must contain 1–2000 characters")
    if not 1<=limit<=20:raise ValueError("Limit must be 1–20")
    if mode not in ("current","as_of") or (mode=="as_of" and as_of is None):
        raise ValueError("Historical search needs an as_of timestamp")
    model=service.model();qvec=model.encode(query)
    if service.db.engine.dialect.name=='postgresql':
        return postgres_search(service,query,qvec,model,source_ids,limit,mode,as_of,include_unavailable)
    base=(chunks.join(versions,chunks.c.version_id==versions.c.id)
          .join(pages,versions.c.page_id==pages.c.id).join(sources,pages.c.source_id==sources.c.id)
          .join(cache,chunks.c.cache_id==cache.c.id))
    stmt=select(chunks.c.id.label("chunk_id"),chunks.c.text,chunks.c.heading,chunks.c.locator,
        versions.c.id.label("version_id"),versions.c.number,versions.c.title,versions.c.observed_at,
        versions.c.indexed_at,pages.c.id.label("page_id"),pages.c.url,pages.c.availability,pages.c.health,
        pages.c.verified_at,pages.c.checked_at,pages.c.last_error,sources.c.id.label("source_id"),
        sources.c.name.label("source_name"),sources.c.config,cache.c.vector).select_from(base).where(
            or_(sources.c.enabled.is_(True),and_(sources.c.removed_at.is_not(None),mode=='as_of')),cache.c.signature==model.signature,pages.c.health!="blocked")
    if source_ids is not None:stmt=stmt.where(sources.c.id.in_(source_ids))
    else:stmt=stmt.where(sources.c.config['demo'].as_boolean().is_not(True),
                         func.coalesce(sources.c.config['source_kind'].as_string(),'normal')=='normal')
    stmt=stmt.where(versions.c.indexed_at.is_not(None))
    if mode=="current":
        stmt=stmt.where(sources.c.removed_at.is_(None),versions.c.id==pages.c.current_id)
        if not include_unavailable:stmt=stmt.where(pages.c.availability=="active")
    else:
        stmt=stmt.join(intervals,and_(intervals.c.version_id==versions.c.id,intervals.c.page_id==pages.c.id))
        stmt=stmt.where(intervals.c.start<=as_of,or_(intervals.c.end.is_(None),intervals.c.end>as_of))
    # One joined SELECT gives the local profile a consistent eligibility snapshot.
    if service.db.engine.dialect.name=="postgresql":
        # Filter before selecting candidates; one statement retains a consistent snapshot.
        ids=stmt.with_only_columns(chunks.c.id.label("chunk_id"),maintain_column_froms=True)
        semantic=ids.order_by(cache.c.vector.cosine_distance(qvec)).limit(100).cte("dense_candidates")
        lex_query=func.plainto_tsquery(literal_column("'simple'::regconfig"),query)
        lex_document=func.to_tsvector(literal_column("'simple'::regconfig"),chunks.c.text)
        lexical_ids=ids.where(lex_document.op("@@")(lex_query)).order_by(
            func.ts_rank_cd(lex_document,lex_query).desc()).limit(100).cte("lexical_candidates")
        candidates=union(select(semantic.c.chunk_id),select(lexical_ids.c.chunk_id))
        stmt=stmt.where(chunks.c.id.in_(candidates))
    else:
        stmt=stmt.limit(20001)
    rows=service.db.all(stmt)
    if len(rows)>20000:raise ValueError("Local retrieval limit reached; use the scalable database search extension")
    qt=set(tokens(query))-STOPWORDS;N=len(rows);df=Counter()
    for row in rows:
        row["_tokens"]=tokens(row["title"]+" "+row["heading"]+" "+row["text"])
        df.update(set(row["_tokens"]))
    avg=sum(len(r["_tokens"]) for r in rows)/max(1,N)
    for row in rows:
        tf=Counter(row["_tokens"]);L=len(row["_tokens"])
        row["_lex"]=sum(math.log(1+(N-df[t]+.5)/(df[t]+.5))*tf[t]*2.2/
            (tf[t]+1.2*(.25+.75*L/max(1,avg))) for t in qt if tf[t])
        row["_sim"]=cosine(qvec,row["vector"])
        row["_score"]=0
    dense=sorted(rows,key=lambda r:(-r["_sim"],r["chunk_id"]))[:50]
    lexical=sorted([r for r in rows if r["_lex"]>0],key=lambda r:(-r["_lex"],r["chunk_id"]))[:50]
    for ranked in (dense if model.mode=="minilm" else [],lexical):
        for rank,row in enumerate(ranked,1):row["_score"]+=1/(60+rank)
    chosen=sorted([r for r in rows if r["_score"]>0 and (r["_lex"]>0 or r["_sim"]>=0.40)],
                  key=lambda r:(-r["_score"],r["chunk_id"]))[:limit]
    results=[]
    for row in chosen:
        verified=row["verified_at"] if mode=="current" else row["observed_at"]
        stale=verified is None or time.time()-verified>row["config"]["interval"]
        warnings=[]
        if mode=="as_of":warnings.append("Historical indexed snapshot")
        elif stale:warnings.append("Verification is older than the polling interval")
        if row["health"]!="healthy":warnings.append(row["last_error"] or row["health"])
        if row["availability"]!="active":warnings.append("Source page is currently unavailable")
        results.append({k:v for k,v in row.items() if not k.startswith("_") and k not in ("vector","config","verified_at")})
        results[-1].update(score=row["_score"],cosine=row["_sim"],lexical_score=row["_lex"],
            score_type="RRF" if model.mode=="minilm" else "lexical_rank",last_verified_at=verified,
            freshness_status="historical" if mode=="as_of" else ("source_unavailable" if row["health"]!="healthy" else ("stale" if stale else "within_interval")),
            is_demo=row["config"].get("demo",False),warnings=warnings)
    pending=pending_count(service,source_ids)
    return {"query":query,"mode":mode,"as_of":as_of,"embedding_mode":model.mode,"results":results,
            "index_pending":pending,"message":"Search index updating" if pending else ("" if results else "No sufficiently relevant evidence found. This does not prove the source has no update.")}
