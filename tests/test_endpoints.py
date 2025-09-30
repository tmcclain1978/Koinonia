import os, pytest

pytestmark = pytest.mark.skipif("FLASK_ENV" not in os.environ, reason="skip if Flask app not configured in tests")

def test_dummy():
    assert 2 + 2 == 4
