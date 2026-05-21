FROM mcr.microsoft.com/playwright/python:v1.59.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY api ./api
COPY LetMeRent ./LetMeRent
COPY scripts ./scripts
RUN chmod +x /app/scripts/run_all_spiders.sh

WORKDIR /app

EXPOSE 5000

CMD ["python3", "/app/app.py"]
