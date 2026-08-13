from flask import Flask, jsonify
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config import Config
from app.models import db, User

login_manager = LoginManager()
login_manager.login_view = 'main.auth'

migrate = Migrate()


def _rate_limit_key():
    """Rate-limit per logged-in user, fallback to IP."""
    try:
        if current_user.is_authenticated:
            return f"user-{current_user.id}"
    except Exception:
        pass
    return get_remote_address()


limiter = Limiter(
    key_func=_rate_limit_key,
    default_limits=["300 per hour"],
    storage_uri="memory://",
)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)

    from app.routes import main
    app.register_blueprint(main)

    @app.errorhandler(429)
    def too_many_requests(e):
        return jsonify({'error': 'Too many requests. Please slow down a bit.'}), 429

    # ---- Security headers (MUST be inside create_app, before return) ----
    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'camera=(), geolocation=()'
        return response

    return app