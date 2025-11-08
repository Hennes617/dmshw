# Basis-Image
FROM python:3.12-slim

# Arbeitsverzeichnis im Container
WORKDIR /app

# Nur die Python-Datei kopieren
COPY prox.py .

# Port, auf dem der Server läuft
EXPOSE 8080

# Container-Startbefehl
CMD ["python3", "prox.py"]
