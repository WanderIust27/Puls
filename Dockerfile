FROM python:3.12-slim

WORKDIR /puls

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
# Faellt die Wissensdatenbank im Container aus, liegt hier wenigstens eine
# Kopie der Quellen — der Ordner /knowledge wird normalerweise gemountet.
COPY knowledge ./knowledge
# Die Testsuite gehoert mit ins Image. Nicht, um sie im Betrieb laufen zu
# lassen, sondern weil die Wissensdatenbank nur dort messbar ist, wo sie steht:
# tests/eval_knowledge.py braucht dieselbe Datenbank und dasselbe
# Einbettungsmodell wie die laufende Anwendung. Kostet ein paar hundert
# Kilobyte.
COPY tests ./tests

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
