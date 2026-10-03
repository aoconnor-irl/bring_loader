FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bring_loader ./bring_loader
COPY run.py .
RUN useradd -r -u 10001 appuser && mkdir /app/data && chown appuser:appuser /app/data
USER appuser
ENV DATABASE_PATH=/app/data/bring_loader.sqlite3 APP_BIND=0.0.0.0 APP_PORT=8723 PYTHONUNBUFFERED=1
EXPOSE 8723
CMD ["python", "run.py"]
