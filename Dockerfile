# syntax=docker/dockerfile:1
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
# Optional extra CA (only needed behind a TLS-intercepting proxy): build secret "extra_ca".
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install --no-cache-dir ".[test]"
COPY tests ./tests
COPY scripts ./scripts
# data/ is mounted at runtime (see docker-compose.yml), never baked into the image
ENTRYPOINT ["itb"]
CMD ["--help"]
