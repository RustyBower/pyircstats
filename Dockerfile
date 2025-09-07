# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app
COPY . /app

ENTRYPOINT ["python", "/app/ircstats.py"]
CMD ["/logs"]
