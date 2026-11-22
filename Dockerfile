# AuditGym official check container: offline, CPU only, standard library only.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=0

WORKDIR /app
COPY . /app
RUN useradd --create-home auditor && chown -R auditor:auditor /app
USER auditor

# Single verification command (writes reports/check_report.{md,json}; non-zero exit on failure)
CMD ["python", "-m", "auditgym", "check"]
