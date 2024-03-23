FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY ./requirements.txt /app/requirements.txt

RUN pip install -r /app/requirements.txt

COPY autoChangelog /app/autoChangelog
COPY CHANGELOG.md /app/CHANGELOG.md

ENV PYTHONPATH=/app

CMD ["python", "-m", "autoChangelog"]