# ✅ Use official lightweight Python image
FROM python:3.12-slim

# 🧱 Set environment
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 🧰 Create working directory
WORKDIR /app

# 🧩 Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 📁 Copy project files
COPY . .

# ✅ Expose port (Railway will auto bind to PORT env)
EXPOSE 5000

# 🚀 Start app
CMD ["python", "app.py"]