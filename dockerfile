FROM python:3.11-slim

# Build tools needed for C-extension packages (grpcio, tokenizers, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONPATH=/app
# Install uv — faster resolver, handles crewai's complex dep tree without choking
RUN pip install --no-cache-dir uv

# Install all dependencies via uv
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# Copy application code
COPY . .

# Temp directory for uploaded PDFs (shared volume between api + worker)
RUN mkdir -p /app/data

# Run as non-root
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000