FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /monitor

COPY monitor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY monitor/ .

# The monitor needs access to the Docker socket, so it runs as root inside the
# container (the socket is mounted by docker-compose.yml).
EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"]

CMD ["python", "monitor.py"]
