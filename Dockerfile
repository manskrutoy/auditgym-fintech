# AuditGym official check container: offline, CPU only, standard library only.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=0

WORKDIR /app
COPY . /app
# The evaluator runs as root; every policy process is started as `nobody` from a temp directory
# that contains only policy code, so it cannot read closed files (mode 700) or write the project.
RUN find /app/episodes -type d -name private -exec chmod 700 {} + && chmod -R go-w /app

# Single verification command (writes reports/check_report.{md,json}; non-zero exit on failure)
CMD ["python", "-m", "auditgym", "check"]
