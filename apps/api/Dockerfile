FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY apps/api/requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt
COPY apps/api/orca /srv/apps/api/orca
COPY data/reference /srv/data/reference
COPY data/replay /srv/data/replay
ENV ORCA_DATA_DIR=/srv/data ORCA_DB_PATH=/srv/state/orca.db
RUN useradd -m orca && mkdir -p /srv/state && chown -R orca /srv/state
USER orca
EXPOSE 8000
CMD ["uvicorn", "orca.main:app", "--app-dir", "/srv/apps/api", "--host", "0.0.0.0", "--port", "8000"]
