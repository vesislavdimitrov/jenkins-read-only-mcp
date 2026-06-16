# Mirrors setup.sh: install uv, uv sync, run server.py --http.
FROM python:3.12-slim-bookworm

WORKDIR /app

# uv (same installer setup.sh uses).
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
 && curl -LsSf https://astral.sh/uv/install.sh | sh \
 && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
ENV PATH="/root/.local/bin:$PATH"

COPY pyproject.toml ./
RUN uv sync --python 3.12

COPY config.py jenkins_client.py jenkins_utils.py server.py ./

ENV HTTP_HOST=0.0.0.0 PORT=8000
EXPOSE 8000

CMD ["uv", "run", "--python", "3.12", "python", "server.py", "--http"]
