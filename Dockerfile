FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

LABEL org.opencontainers.image.title="VeriReq" \
      org.opencontainers.image.source="https://github.com/intelligent-design-llc/verireq" \
      org.opencontainers.image.url="https://copilot.intelligent-design.us"

COPY --chown=10001:10001 verireq ./verireq
COPY --chown=10001:10001 profiles ./profiles
COPY --chown=10001:10001 library ./library
COPY --chown=10001:10001 LICENSE NOTICE ./

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app \
    && find /app -type d -exec chmod 755 {} \; \
    && find /app -type f -exec chmod 644 {} \;
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/config')" || exit 1
CMD ["python", "-m", "verireq"]
