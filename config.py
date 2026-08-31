import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-change-me')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///irus.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True}

    GROQ_API_KEY = os.getenv('GROQ_API_KEY')
    AI_PROVIDER = os.getenv('AI_PROVIDER', 'groq')
    FALLBACK_PROVIDER = os.getenv('FALLBACK_PROVIDER', '')
    GROQ_MODEL = os.getenv('GROQ_MODEL', 'qwen/qwen3.8-27b')
    OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'llama3.2')
    
        # Hardened session cookies
    SESSION_COOKIE_HTTPONLY = True      # JS cannot read the session cookie
    SESSION_COOKIE_SAMESITE = 'Lax'     # CSRF mitigation
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'false').lower() == 'true'  # enable in production HTTPS