import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.models import db, User


def make_client():
    app = create_app()
    app.config.update(
        TESTING=True,
        RATELIMIT_ENABLED=False,
        WTF_CSRF_ENABLED=False,
    )
    with app.app_context():
        db.create_all()
    return app


def test_health_endpoint():
    client = make_client().test_client()
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_security_headers_present():
    client = make_client().test_client()
    r = client.get("/auth")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_login_required_redirects():
    client = make_client().test_client()
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (200, 302)
    if r.status_code == 302:
        assert "/auth" in r.headers["Location"]


def test_register_and_login():
    app = make_client()
    with app.app_context():
        db.create_all()
        client = app.test_client()
        r = client.post("/auth", data={
            "action": "register",
            "username": "tester",
            "email": "tester@example.com",
            "password": "SuperSecret123",
        }, follow_redirects=True)
        assert r.status_code in (200, 302)
        client2 = app.test_client()
        r2 = client2.post("/auth", data={
            "action": "login",
            "username": "tester",
            "password": "SuperSecret123",
        }, follow_redirects=True)
        assert r2.status_code in (200, 302)
        db.session.remove()
        db.drop_all()


def test_weak_password_rejected():
    app = make_client()
    with app.app_context():
        db.create_all()
        client = app.test_client()
        r = client.post("/auth", data={
            "action": "register",
            "username": "weakuser",
            "email": "weak@example.com",
            "password": "short",
        })
        assert b"at least 8 characters" in r.data
        db.session.remove()
        db.drop_all()


def test_honeypot_blocks_bots():
    app = make_client()
    with app.app_context():
        db.create_all()
        client = app.test_client()
        r = client.post("/auth", data={
            "action": "register",
            "username": "botuser",
            "email": "bot@example.com",
            "password": "SuperSecret123",
            "website": "http://spam.com",   # honeypot filled = bot
        }, follow_redirects=True)
        assert r.status_code in (200, 302)
        assert User.query.filter_by(username="botuser").first() is None
        db.session.remove()
        db.drop_all()
