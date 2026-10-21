"""Additive APIs for automatic calculations and their immutable evidence."""
from fastapi import APIRouter, Query
from sqlalchemy import select
from .automation import Automations
from . import automation_schema as a


def create_automation_router(service):
    router=APIRouter();automation=Automations(service)

    @router.post('/api/automations/preview')
    def preview(body:dict):return automation.preview(body)

    @router.post('/api/automations')
    def activate(body:dict):return automation.activate(body)

    @router.get('/api/automations')
    def listing(source_id:str|None=None,limit:int=Query(50,ge=1,le=100),cursor:str|None=None,archived:bool=False):
        return automation.listing(source_id,limit,cursor,archived)

    @router.get('/api/automations/{identity}')
    def detail(identity:str):return automation.get(identity)

    @router.patch('/api/automations/{identity}')
    def patch(identity:str,body:dict):return automation.patch(identity,body)

    @router.delete('/api/automations/{identity}')
    def archive(identity:str):return automation.archive(identity)

    @router.get('/api/automations/{identity}/history')
    def history(identity:str,limit:int=Query(50,ge=1,le=200),cursor:str|None=None):return automation.history(identity,limit,cursor)

    @router.get('/api/calculations/{identity}')
    def evidence(identity:str):return automation.evidence(identity)

    @router.get('/api/automation-alerts')
    def alerts(limit:int=Query(50,ge=1,le=200),cursor:str|None=None):return automation.alerts(limit,cursor)

    @router.patch('/api/automation-alerts/{identity}')
    def acknowledge(identity:str,body:dict):
        if body!={'acknowledged':True}:raise ValueError('Use acknowledged: true to acknowledge an alert.')
        return automation.acknowledge(identity)

    @router.get('/api/automation-connections')
    def connections():
        from .automation_notifications import ConnectionStore
        return {'items':ConnectionStore().list()}

    @router.post('/api/automation-connections')
    def create_connection(body:dict):
        from .automation_notifications import ConnectionStore
        return ConnectionStore().save(body)

    @router.patch('/api/automation-connections/{identity}')
    def edit_connection(identity:str,body:dict):
        from .automation_notifications import ConnectionStore
        return ConnectionStore().save(body,identity)

    @router.delete('/api/automation-connections/{identity}')
    def remove_connection(identity:str):
        from .automation_notifications import ConnectionStore
        ConnectionStore().delete(identity)
        return {'id':identity,'deleted':True}

    @router.get('/api/automation-deliveries')
    def deliveries(limit:int=Query(50,ge=1,le=200),cursor:str|None=None):
        from .v2_api import paginate
        table=a.automation_deliveries
        # Outbound payload is immutable but may contain user-supplied quantities;
        # list only delivery status. Exact evidence is resolved through the alert.
        stmt=select(*(table.c[k] for k in ('id','alert_id','automation_id','connection_id','status','attempts','created_at','finished_at','error','http_status'))).add_columns(table.c.created_at.label('_cursor_at'),table.c.id.label('_cursor_id'))
        return paginate(service.db,stmt,table.c.created_at,table.c.id,limit,cursor)

    return router
