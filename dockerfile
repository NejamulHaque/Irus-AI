# ---------- Build stage ----------
FROM python:3.11-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------- Runtime stage (smaller + safer) ----------
FROM python:3.11-slim
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder /install /usr/local
COPY . .

# Run as non-root user (least privilege)
RUN useradd -m -r appuser && \
    mkdir -p uploads app/static/avatars && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

CMD ["sh", "-c", "flask --app run db upgrade && gunicorn --worker-class gthread --threads 4 --workers 2 --timeout 120 -b 0.0.0.0:5000 run:app"]