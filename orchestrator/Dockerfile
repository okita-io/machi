FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY machi ./machi
COPY prompts ./prompts

# Main deps include cutlet, fugashi, and unidic-lite (furigana + romaji).
RUN pip install --no-cache-dir .

ENV SCENARIOS_PATH=/scenarios
ENV DB_PATH=/data/machi.sqlite
ENV ASSETS_PATH=/assets

EXPOSE 8100

CMD ["uvicorn", "machi.main:app", "--host", "0.0.0.0", "--port", "8100"]