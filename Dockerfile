FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir .

CMD ["kopf", "run", \
     "--liveness=http://0.0.0.0:8080/healthz", \
     "--namespace=calunga-tenant", \
     "--namespace=rhtap-releng-tenant", \
     "-m", "calunga_release_watcher.handlers"]
