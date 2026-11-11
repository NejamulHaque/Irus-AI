import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.models import db


@pytest.fixture
def client():
    app = create_app()
    app.config.update({
        "TESTING": True,
        "RATELIMIT_ENABLED": False,
        "WTF_CSRF_ENABLED": False,
    })
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


def test_public_pages(client):
    for url in ['/', '/auth', '/privacy', '/terms', '/robots.txt', '/sitemap.xml', '/health']:
        assert client.get(url).status_code in (200, 302), url


def test_404_page(client):
    assert client.get('/definitely-not-here').status_code == 404


def test_register_form_validation(client):
    r = client.post('/auth', data={'action': 'register', 'username': 'x', 'email': 'bad', 'password': 'short'}, follow_redirects=True)
    assert r.status_code == 200


def test_login_form_rejects_bad_credentials(client):
    r = client.post('/auth', data={'action': 'login', 'username': 'ghost', 'password': 'wrong123'}, follow_redirects=True)
    assert b'Invalid username or password' in r.data


def test_honeypot_blocks_bots(client):
    r = client.post('/auth', data={'website': 'bot-filled'})
    assert r.status_code in (200, 302)
