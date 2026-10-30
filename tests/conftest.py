import os

import pytest

# The app-wide Host guard (app/local_guard.py) allows only 127.0.0.1 / localhost / [::1] in production.
# Starlette's TestClient sends "Host: testserver", so the tests add that one name through the config allow-list.
os.environ.setdefault("OPENSOUL_ALLOWED_HOSTS", "testserver")



@pytest.fixture
def demo():
    """The bundled demo character (name, pack, poster, sheet, a non-demo name): see tests/demo_character.py."""
    import demo_character

    return demo_character
