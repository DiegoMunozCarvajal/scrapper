FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir scrapy scrapy-playwright supabase python-dotenv loguru tenacity
RUN playwright install-deps chromium
RUN playwright install chromium

COPY src/ /app/src/
COPY scrapy.cfg /app/

ENV PYTHONPATH=/app/src
CMD ["scrapy"]