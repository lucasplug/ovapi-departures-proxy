FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Europe/Amsterdam

WORKDIR /srv/app

COPY requirements.txt .
# tzdata zit in requirements.txt (pip-pakket), zodat zoneinfo ook in dit slim
# image werkt zonder extra apt-installatie.
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN useradd --create-home --uid 1000 appuser
USER appuser

ENV PORT=8000
EXPOSE 8000

# Geen curl in een slim image: gebruik een python/urllib-oneliner.
# /ready geeft pas 200 nadat ten minste één OVapi-respons is opgehaald.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/ready' % os.environ.get('PORT', '8000'), timeout=4)"]

CMD ["python", "-m", "app"]
