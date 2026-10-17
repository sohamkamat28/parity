"""Local database prerequisites and startup. No administrator actions are taken."""
import os,secrets,shutil,subprocess,time
from pathlib import Path
from urllib.parse import quote
from . import config

def docker_path():
    found=shutil.which('docker')
    if found:return found
    candidate=Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Docker/Docker/resources/bin/docker.exe'
    return str(candidate) if candidate.is_file() else None

def docker_status():
    executable=docker_path()
    if not executable:return {'status':'not_installed','error':'Install Docker Desktop for Windows, enable its WSL 2 backend, restart Windows if requested, then open Docker Desktop. https://docs.docker.com/desktop/setup/install/windows-install/'}
    try:
        result=subprocess.run([executable,'info','--format','{{.OSType}}'],capture_output=True,text=True,timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    except (OSError,subprocess.TimeoutExpired):return {'status':'unavailable','error':'Docker Desktop did not respond. Open it and wait for the engine to start.'}
    if result.returncode or result.stdout.strip()!='linux':
        return {'status':'stopped','error':'Open Docker Desktop, select Linux containers with the WSL 2 backend, and wait until the engine is running. Windows may need a restart after enabling WSL or virtualization.'}
    return {'status':'ready','executable':executable}

def configure_database(profile='postgresql',start=True):
    if profile=='sqlite':return 'sqlite:///'+str(config.DATA/'parity.db')
    explicit=os.getenv('DATABASE_URL','')
    if explicit:
        if not explicit.startswith('postgresql'):raise ValueError('DATABASE_URL must use PostgreSQL for this profile. Select --profile sqlite explicitly to use compatibility mode.')
        return explicit
    status=docker_status()
    if status['status']!='ready':raise ValueError(status['error'])
    password=os.getenv('PARITY_DB_PASSWORD','').strip()
    if not password:
        password=secrets.token_urlsafe(32)
        with (config.ROOT/'.env').open('a',encoding='utf-8') as f:
            f.write('\nPARITY_DB_PASSWORD='+password+'\n')
        os.environ['PARITY_DB_PASSWORD']=password
    port=int(os.getenv('PARITY_DB_PORT','5432'))
    if not 1<=port<=65535:raise ValueError('PARITY_DB_PORT must be between 1 and 65535')
    if start:
        result=subprocess.run([status['executable'],'compose','--project-name','parity2','-f',str(config.ROOT/'docker-compose.yml'),
            'up','-d','--wait','--wait-timeout','120'],cwd=config.ROOT,capture_output=True,text=True,timeout=240,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        if result.returncode:raise ValueError('PostgreSQL could not start. Check Docker Desktop, available disk space and port '+str(port)+'. Run docker compose --project-name parity2 up -d --wait in this folder for details.')
    return f'postgresql+psycopg://parity:{quote(password,safe="")}@127.0.0.1:{port}/parity'
