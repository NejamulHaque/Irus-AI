from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()


class User(db.Model, UserMixin):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(30), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    bio = db.Column(db.String(500), default='')
    avatar = db.Column(db.String(2_000_000), default='')  # base64 data URL
    preferred_model = db.Column(db.String(100), default='llama-3.3-70b-versatile')
    is_admin = db.Column(db.Boolean, default=False)
    is_banned = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    conversations = db.relationship('Conversation', backref='user', cascade='all, delete-orphan')
    memories = db.relationship('Memory', backref='user', cascade='all, delete-orphan')
    documents = db.relationship('Document', backref='user', cascade='all, delete-orphan')
    error_logs = db.relationship('ErrorLog', backref='user', cascade='all, delete-orphan')
    api_keys = db.relationship('APIKey', backref='user', cascade='all, delete-orphan')
    login_audits = db.relationship('LoginAudit', backref='user', cascade='all, delete-orphan')

    @property
    def active_subscription(self):
        """Return the current active, non-expired subscription (if any)."""
        now = datetime.utcnow()
        return Subscription.query.filter_by(user_id=self.id, status='active').filter(
            (Subscription.expires_at == None) | (Subscription.expires_at > now)
        ).order_by(Subscription.expires_at.desc()).first()

    @property
    def is_pro(self):
        return self.active_subscription is not None


class Conversation(db.Model):
    __tablename__ = 'conversation'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    title = db.Column(db.String(120), default='New Chat')
    folder = db.Column(db.String(40), nullable=True, index=True)
    share_token = db.Column(db.String(24), unique=True, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = db.relationship('Message', backref='conversation', cascade='all, delete-orphan',
                               order_by='Message.created_at')


class Message(db.Model):
    __tablename__ = 'message'
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversation.id'), nullable=False, index=True)
    role = db.Column(db.String(16), nullable=False)  # user | assistant
    content = db.Column(db.Text, nullable=False)
    document_id = db.Column(db.Integer, db.ForeignKey('document.id'), nullable=True)
    image_data = db.Column(db.Text, nullable=True)  # base64 data URL for attached images
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Document(db.Model):
    __tablename__ = 'document'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    original_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    chunks = db.relationship('DocumentChunk', backref='document', cascade='all, delete-orphan')
    messages = db.relationship('Message', backref='document')


class DocumentChunk(db.Model):
    __tablename__ = 'document_chunk'
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey('document.id'), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    chunk_index = db.Column(db.Integer, nullable=False)
    embedding = db.Column(db.Text, nullable=True)  # serialized embedding


class Memory(db.Model):
    __tablename__ = 'memory'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    content = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ErrorLog(db.Model):
    __tablename__ = 'error_log'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    error_type = db.Column(db.String(100), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class APIKey(db.Model):
    __tablename__ = 'api_key'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    prefix = db.Column(db.String(10), nullable=False)
    key_hash = db.Column(db.String(64), unique=True, nullable=False)
    last_used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    logs = db.relationship('APIRequestLog', backref='api_key', cascade='all, delete-orphan')


class APIRequestLog(db.Model):
    __tablename__ = 'api_request_log'
    id = db.Column(db.Integer, primary_key=True)
    api_key_id = db.Column(db.Integer, db.ForeignKey('api_key.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    endpoint = db.Column(db.String(100), nullable=False)
    method = db.Column(db.String(10), nullable=False)
    status_code = db.Column(db.Integer, nullable=False)
    latency_ms = db.Column(db.Integer, nullable=True)
    ip = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class LoginAudit(db.Model):
    __tablename__ = 'login_audit'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ip = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Broadcast(db.Model):
    __tablename__ = 'broadcast'
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(200), nullable=False)
    is_active = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Subscription(db.Model):
    __tablename__ = 'subscription'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    plan = db.Column(db.String(20), nullable=False)     # pro_monthly | pro_yearly
    amount = db.Column(db.Integer, nullable=False)      # rupees paid
    utr = db.Column(db.String(64), nullable=True)       # UPI transaction reference
    status = db.Column(db.String(12), default='pending')  # pending | active | rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    activated_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref='subscriptions')