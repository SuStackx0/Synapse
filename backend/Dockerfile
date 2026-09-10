FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    git curl build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Production-safe default: no auto-reload. Set RELOAD=true (docker-compose does
# this for local dev) to enable uvicorn's file-watching reloader.
CMD ["sh", "-c", "if [ \"$RELOAD\" = \"true\" ]; then exec uvicorn main:app --host 0.0.0.0 --port 8000 --reload; else exec uvicorn main:app --host 0.0.0.0 --port 8000; fi"]
