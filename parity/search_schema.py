"""Rebuildable denormalized retrieval projection, independent of evidence."""
from sqlalchemy import Table,Column,String,Text,Integer,Float,JSON,ForeignKey
from pgvector.sqlalchemy import Vector

def register(meta):
    if 'search_projection' not in meta.tables:
        Table('search_projection',meta,
            Column('chunk_id',ForeignKey('chunks.id'),primary_key=True),
            Column('source_id',ForeignKey('sources.id'),nullable=False,index=True),
            Column('page_id',ForeignKey('pages.id'),nullable=False,index=True),
            Column('version_id',ForeignKey('versions.id'),nullable=False,index=True),
            Column('text',Text,nullable=False),Column('heading',Text),Column('locator',Text),
            Column('model_signature',String,nullable=False,index=True),
            Column('vector',Vector(384).with_variant(JSON,'sqlite'),nullable=False))
    globals()['projection']=meta.tables['search_projection']
    return {'search_projection':projection}
