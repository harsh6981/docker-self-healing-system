FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000

WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

# Run as a non-root user
RUN useradd --create-home appuser
USER appuser

EXPOSE 5000

# --interval    : run the check every 5 s
# --timeout     : a check taking longer than 3 s counts as a failure
# --start-period: failures during the first 5 s are not counted (app booting)
# --retries     : 2 consecutive failures => container becomes "unhealthy"
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=2 \
  CMD ["python", "healthcheck.py"]

CMD ["python", "app.py"]
