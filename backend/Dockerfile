FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
COPY backend/requirements-rag.txt /app/backend/requirements-rag.txt
COPY backend/requirements-optional.txt /app/backend/requirements-optional.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements-rag.txt

COPY backend /app/backend
COPY data /app/data

WORKDIR /app/backend
EXPOSE 8010

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
