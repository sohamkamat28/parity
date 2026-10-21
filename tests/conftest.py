"""Fresh SQLite files and opt-in PostgreSQL databases; never reset an installation."""
import os
import uuid
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


@pytest.fixture(params=['sqlite', 'postgresql'] if os.getenv('PARITY_TEST_DATABASE_URL') else ['sqlite'])
def database_url(request, tmp_path):
    if request.param == 'sqlite':
        yield 'sqlite:///'+str(tmp_path/'acceptance.sqlite')
        return
    base = make_url(os.environ['PARITY_TEST_DATABASE_URL'])
    assert base.drivername.startswith('postgresql'), 'PostgreSQL tests require a PostgreSQL URL'
    admin = create_engine(base, isolation_level='AUTOCOMMIT')
    name = 'parity_test_'+uuid.uuid4().hex
    with admin.connect() as c:c.execute(text(f'CREATE DATABASE {name}'))
    try:
        yield base.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as c:c.execute(text(f'DROP DATABASE {name} WITH (FORCE)'))
        admin.dispose()
