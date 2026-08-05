FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    dnsmasq \
    iproute2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir flask

COPY app.py .
COPY assets/ ./assets/

ENV FILE_SERVER_ROOT=/data/files

RUN mkdir -p /data/files /var/lib/dnsmasq /etc/dnsmasq.d

EXPOSE 8080

CMD ["python3", "app.py"]
