#!/usr/bin/env sh
set -eu

cd /app/LetMeRent

SPIDERS="${SPIDERS:-funda housinganywhere huurwoningen irentalize kamernet}"

for spider in $SPIDERS; do
    echo "Running spider: $spider"
    scrapy crawl "$spider" "$@"
done
