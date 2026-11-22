FROM python:3.12-slim-bookworm

WORKDIR /app
COPY pyproject.toml ./
COPY speech_cpu ./speech_cpu
RUN pip install --no-cache-dir .

COPY docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8101 8102
ENTRYPOINT ["/entrypoint.sh"]