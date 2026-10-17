import json,socket,sys,time
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from parity import config
from parity.db import DB,chat_messages
from parity.embedding import Embedder
from parity.chat import ChatService,ChatError,GroundedAnswer,AnswerBlock,SearchQuestion,EvidenceSelection
from run import ensure_ports_available,portal_port,LaunchError,OwnedProcesses

class EvidenceService:
    def __init__(self,tmp_path):
        self.db=DB('sqlite:///'+str(tmp_path/'chat.db'));self.queries=[]
        self.evidence=[{'chunk_id':'chunk','page_id':'page','version_id':'immutable-version','number':2,'title':'Honours',
            'url':'https://example.org/honours','text':'Registration closes on 28 August 2026.','locator':'Deadline','last_verified_at':100,'warnings':['Verification is older than the polling interval']}]
    def model(self):return Embedder('lexical')
    def search(self,question,**kwargs):self.queries.append((question,kwargs));return {'results':self.evidence}

def provider(*outputs):
    calls=[];queue=list(outputs)
    def parse(**kwargs):
        calls.append(kwargs);item=queue.pop(0)
        if isinstance(item,Exception):raise item
        return SimpleNamespace(output_parsed=item)
    return SimpleNamespace(responses=SimpleNamespace(parse=parse),calls=calls)

def answer(ids=[1]):return GroundedAnswer(blocks=[AnswerBlock(text='The deadline is 28 August.',citation_ids=ids)],insufficient_evidence=False)

def test_citations_and_context_persist_as_immutable_snapshots(tmp_path):
    service=EvidenceService(tmp_path);client=provider(answer(),SearchQuestion(question='What is the honours deadline?'),answer())
    chat=ChatService(service,client);first=chat.ask('Honours deadline?',source_ids=['a'])
    assert first['citations'][0]['version_id']=='immutable-version' and first['warnings']
    service.evidence[0]={**service.evidence[0],'text':'Changed after answer','version_id':'next-version','number':3}
    saved=chat.conversation(first['conversation_id'])['messages'][-1]
    assert saved['citations'][0]['text']=='Registration closes on 28 August 2026.'
    second=chat.ask('And now?',conversation_id=first['conversation_id'],source_ids=['b'],mode='as_of',as_of=25)
    assert service.queries[-1]==('What is the honours deadline?',{'source_ids':['b'],'limit':8,'mode':'as_of','as_of':25})
    assert len(chat.conversation(first['conversation_id'])['messages'])==4
    assert client.calls[0]['store'] is False

@pytest.mark.parametrize('ids',[[99],[],[1,99]])
def test_outside_or_missing_citations_are_rejected_without_persistence(tmp_path,ids):
    service=EvidenceService(tmp_path);chat=ChatService(service,provider(answer(ids)))
    with pytest.raises(ChatError,match='citation validation'):chat.ask('deadline')
    assert service.db.all(select(chat_messages))==[]

def test_provider_failure_is_actionable_and_search_remains_usable(tmp_path):
    service=EvidenceService(tmp_path);error=RuntimeError('secret provider response');error.status_code=429
    chat=ChatService(service,provider(error))
    with pytest.raises(ChatError,match='quota') as captured:chat.ask('deadline')
    assert 'secret' not in str(captured.value)
    assert service.search('deadline')['results'] and not service.db.all(select(chat_messages))

def test_no_evidence_does_not_contact_provider(tmp_path):
    service=EvidenceService(tmp_path);service.evidence=[];client=provider();chat=ChatService(service,client)
    result=chat.ask('An unknown topic')
    assert result['status']=='no_evidence' and result['citations']==[] and client.calls==[]

def test_local_answers_quote_only_server_owned_evidence(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'CHAT_PROVIDER','local');service=EvidenceService(tmp_path);chat=ChatService(service)
    monkeypatch.setattr(chat,'_local_call',lambda **kwargs:EvidenceSelection(citation_ids=[1],insufficient_evidence=False))
    result=chat.ask('deadline')
    assert result['answer']=='Registration closes on 28 August 2026. [1]'

def test_local_invalid_ids_are_rejected(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'CHAT_PROVIDER','local');service=EvidenceService(tmp_path);chat=ChatService(service)
    monkeypatch.setattr(chat,'_local_call',lambda **kwargs:EvidenceSelection(citation_ids=[9],insufficient_evidence=False))
    with pytest.raises(ChatError,match='citation validation'):chat.ask('deadline')

def test_local_topic_filter_does_not_mix_unrelated_deadlines(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'CHAT_PROVIDER','local');service=EvidenceService(tmp_path)
    service.evidence.append({**service.evidence[0],'page_id':'scholarship','title':'Scholarship','text':'Renewal closes on 30 August.'})
    chat=ChatService(service)
    def choose(**kwargs):
        supplied=json.loads(kwargs['input'][-1]['content'])['EVIDENCE']
        assert len(supplied)==1 and supplied[0]['title']=='Honours'
        assert kwargs['max_citations']==1
        return EvidenceSelection(citation_ids=[1],insufficient_evidence=False)
    monkeypatch.setattr(chat,'_local_call',choose)
    assert '30 August' not in chat.ask('What is the honours deadline?')['answer']

def test_cli_contract_imports_and_reads_status(tmp_path):
    import subprocess,os
    env={**os.environ,'PARITY_DATA_DIR':str(tmp_path),'DATABASE_URL':'sqlite:///'+str(tmp_path/'cli.db'),'PARITY_EMBEDDER':'lexical'}
    result=subprocess.run([sys.executable,'cli.py','status'],env=env,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['embedding_mode']=='lexical'

def test_launcher_detects_conflict_and_invalid_origins():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));sock.listen()
        with pytest.raises(LaunchError,match='occupied'):ensure_ports_available([('test',sock.getsockname()[1])])
    with pytest.raises(LaunchError,match='more than one'):ensure_ports_available([('a',19001),('b',19001)])
    assert portal_port('http://localhost:8080')==8080
    for bad in ['https://localhost:8080','http://example.com','http://127.0.0.1/admin']:
        with pytest.raises(LaunchError):portal_port(bad)

def test_launcher_reports_failed_subprocess_and_cleans_owned_children(tmp_path):
    owned=OwnedProcesses(tmp_path)
    try:
        import os
        child=owned.start('fail',[sys.executable,'-c','raise SystemExit(7)'],tmp_path,os.environ.copy())
        child.wait(timeout=10)
        with pytest.raises(LaunchError,match='code 7'):owned.check()
        sleeper=owned.start('sleep',[sys.executable,'-c','import time; time.sleep(60)'],tmp_path,os.environ.copy())
    finally:owned.close()
    assert sleeper.poll() is not None
