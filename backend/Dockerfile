FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY data ./data
COPY scripts ./scripts
COPY evaluate.py .
# Словарь CC-CEDICT (необязательно): скачивается при сборке, если есть интернет
ARG WITH_CEDICT=1
RUN if [ "$WITH_CEDICT" = "1" ]; then python scripts/download_cedict.py || echo "CC-CEDICT не скачан — работаем на мини-словаре"; fi
RUN useradd -m benshu && mkdir -p /data && chown -R benshu /app /data
USER benshu
ENV BENSHU_DB=/data/benshu.db
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers"]
