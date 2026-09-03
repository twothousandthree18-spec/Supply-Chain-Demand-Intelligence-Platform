# Supply Chain & Demand Intelligence Platform
# Web/API production image (serves the static SPA + /api data layer).
#
# Build:
#   docker build -t supply-chain-intelligence .
#
# The container is stateless: PostgreSQL is supplied externally (see
# docker-compose.yml) and configured via PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD.

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps required by psycopg2-binary / uvicorn are satisfied by the slim image.
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Application source + static assets.
COPY src/ ./src/

# Non-root launch user.
RUN adduser --disabled-password --gecos "" appuser
USER appuser

# Production start command. Behind a reverse proxy set --workers as appropriate.
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "src.web.main:app", "--host", "0.0.0.0", "--port", "8000"]