# MARINER_2 — HuggingFace Docker Space
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/
COPY main.py .

# HF Spaces routes traffic to this port by default (override with app_port
# in the README frontmatter if you change it).
EXPOSE 7860

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
