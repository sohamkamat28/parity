"""Inject test transport only into isolated API/worker verification processes."""
import os,runpy,sys
from parity.fetch import Fetcher
from parity import service
class FixtureFetcher(Fetcher):
    def __init__(self):super().__init__(os.environ['PARITY_FIXTURE_ORIGIN'])
service.Fetcher=FixtureFetcher
role=sys.argv[1]
if role=='api':
    import uvicorn
    uvicorn.run('parity.api:app',host='127.0.0.1',port=int(os.environ['PARITY_PORT']),access_log=False)
else:
    sys.argv=['parity.worker','--role',role]
    runpy.run_module('parity.worker',run_name='__main__')
