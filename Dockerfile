FROM python:3.11-slim
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY ./requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt
COPY autoChangelog /app/autoChangelog

ENV PYTHONPATH=/app
CMD ["python", "-m", "autoChangelog"]

LABEL org.opencontainers.image.description="A tool to generate changelog from GitHub issues"
LABEL org.opencontainers.image.source="https://github.com/PatrickPedersen/autoChangelog"
LABEL org.opencontainers.image.maintainer="Patrick Pedersen <https://github.com/PatrickPedersen>"