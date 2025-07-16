import os
from dotenv import load_dotenv

load_dotenv()

# Groq AI
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama3-70b-8192")

# MySQL DB
HOST = os.getenv("DB_HOST")
USER = os.getenv("DB_USER")
PASSWORD = os.getenv("DB_PASSWORD")
DATABASE = os.getenv("DB_NAME")

# Flask
FLASK_SECRET_KEY = os.getenv("SECRET_KEY")