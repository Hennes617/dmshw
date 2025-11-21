# Basis-Image
FROM python:3.12-slim

# Arbeitsverzeichnis im Container
WORKDIR /app

# Nur die Python-Datei kopieren (ohne führendes /)
COPY prox.py .

# Port, auf dem der Server läuft
EXPOSE 80

# Container-Startbefehl
CMD ["python3", "prox.py"]