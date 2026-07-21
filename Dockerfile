FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir flask

COPY app.py .
COPY assets/ ./assets/

ENV FILE_SERVER_ROOT=/data/files

RUN mkdir -p /data/files

EXPOSE 8080

CMD ["python3", "app.py"]
