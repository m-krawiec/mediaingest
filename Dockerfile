FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends rsync \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first (better layer caching)
COPY pyproject.toml .
RUN pip install --no-cache-dir PyYAML

# Copy source and install the package
COPY photo_ingest/ ./photo_ingest/
RUN pip install --no-cache-dir --no-deps -e .

ENTRYPOINT ["photo-ingest"]
CMD ["--help"]
