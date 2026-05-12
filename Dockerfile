FROM mcr.microsoft.com/playwright/python:v1.59.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY LetMeRent ./LetMeRent

WORKDIR /app/LetMeRent

ENTRYPOINT ["scrapy"]
CMD ["crawl", "housinganywhere"]
