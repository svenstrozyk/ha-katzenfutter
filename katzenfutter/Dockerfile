FROM python:3.12-alpine

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ /app/

EXPOSE 8099
# Ein Prozess mit Threads: genau eine MQTT-Verbindung, keine doppelten Sensormeldungen
CMD ["gunicorn", "-b", "0.0.0.0:8099", "-w", "1", "--threads", "4", "--access-logfile", "-", "app:app"]
