import os, pytest
from importlib import import_module
@pytest.fixture(scope='session')
def app():
    os.environ.setdefault('FLASK_ENV','testing')
    os.environ.setdefault('TESTING','1')
    mod = import_module('server')
    app = getattr(mod, 'app')
    app.config.update(TESTING=True)
    return app
@pytest.fixture() def client(app): return app.test_client()
