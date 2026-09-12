FROM python:3.12-slim

WORKDIR /puls

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
# Faellt die Wissensdatenbank im Container aus, liegt hier wenigstens eine
# Kopie der Quellen — der Ordner /knowledge wird normalerweise gemountet.
COPY knowledge ./knowledge

ENV PULS_DATA_DIR=/data
# Die Wissensdatenbank teilt sich die Datei mit PULS.
ENV PULS_DB=/data/puls.db
ENV PULS_KB=/knowledge
# Modell-Cache. Ohne ein Volume darauf laedt der Container bei jedem Neustart
# das Einbettungsmodell neu.
ENV HF_HOME=/models
ENV FASTEMBED_CACHE_PATH=/models/fastembed
VOLUME /data

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
