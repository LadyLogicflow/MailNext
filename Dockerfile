FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /data && useradd -u 1000 -m mailnext && chown -R 1000:1000 /app /data
USER 1000

EXPOSE 8000
# Ein Worker: SQLite und der spätere Versandlauf (Planer) laufen im selben Prozess.
CMD ["gunicorn", "--workers", "1", "--threads", "4", "--bind", "0.0.0.0:8000", "--timeout", "60", "wsgi:app"]
