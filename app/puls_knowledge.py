"""
puls_knowledge.py — Wissensdatenbank-Anbindung für PULS.

Bringt eigene Tabellen mit (Präfix kb_), kollidiert also nicht mit dem
bestehenden PULS-Schema. Kann dieselbe SQLite-Datei benutzen.

Abhängigkeiten:
    pip install sqlite-vec fastembed          # schlank, ONNX
    pip install sqlite-vec sentence-transformers   # Alternative, zieht PyTorch

Embeddings laufen bewusst auf der CPU, damit Ollama die GPU exklusiv
für das Chat-Modell behalten kann (OLLAMA_MAX_LOADED_MODELS=1).

Welches Einbettungsmodell benutzt wird, entscheidet PULS_EMBED:

    minilm   paraphrase-multilingual-MiniLM-L12-v2 über fastembed (ONNX).
             220 MB, kein PyTorch. Vorgabe.
    e5       intfloat/multilingual-e5-small über sentence-transformers.
             470 MB Modell, ~2 GB Image durch PyTorch. Nutzt die
             query:/passage:-Präfixe, auf die e5 trainiert ist.
    stub     Deterministische Pseudovektoren ohne Modell. Nur für Tests:
             damit laesst sich die Verdrahtung pruefen, ohne 220 MB zu laden.

Beide echten Profile liefern 384 Dimensionen, die Tabelle kb_vec bleibt also
gleich. Welches besser trifft, sagt keine Theorie, sondern
tests/eval_knowledge.py. Ein Wechsel macht die gespeicherten Vektoren
allerdings unvergleichbar — deshalb merkt sich kb_meta, womit indexiert wurde,
und ingest() baut bei einem Wechsel von selbst neu auf.

Nutzung:
    # einmalig / bei Änderungen an den .md-Dateien
    python puls_knowledge.py ingest /pfad/zur/wissensdatenbank

    # im FastAPI-Code
    kb = KnowledgeBase("/data/puls.db")
    kontext = kb.build_context("Wie viele Sätze Rücken pro Woche?")
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
import struct
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("puls.knowledge")

EMBED_DIM = 384


def _vec():
    """sqlite-vec erst laden, wenn wirklich eine Datenbank geoeffnet wird.

    PROMPT_TEMPLATE und die Chunking-Funktionen sollen auch dann importierbar
    sein, wenn die Erweiterung fehlt — sonst startet PULS wegen eines
    Nachschlagewerks gar nicht.
    """
    import sqlite_vec
    return sqlite_vec

# Zielgröße eines Chunks in Zeichen. ~800 Zeichen ≈ 200–250 Token Deutsch.
CHUNK_TARGET = 900
CHUNK_MAX = 1400

# Datei 11 ist Verhaltenssteuerung und gehört in den System-Prompt,
# nicht in den Abrufindex.
SKIP_FILES = {"11_Coach_Playbook.md", "00_README.md"}

# Quellenverzeichnis wird indexiert, aber abgewertet – sonst gewinnen
# Literaturangaben gegen inhaltliche Chunks.
DEMOTE_FILES = {"12_Quellen.md"}
DEMOTE_FACTOR = 0.4


# --------------------------------------------------------------------------
# Einbettung
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class EmbedProfile:
    key: str
    model: str
    backend: str          # fastembed | sentence-transformers | stub
    query_prefix: str
    passage_prefix: str


PROFILES = {
    # e5 ist auf genau diese Praefixe trainiert; ohne sie verliert es Qualitaet.
    "e5": EmbedProfile("e5", "intfloat/multilingual-e5-small",
                       "sentence-transformers", "query: ", "passage: "),
    # MiniLM kennt keine Praefixe und will auch keine.
    "minilm": EmbedProfile("minilm",
                           "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                           "fastembed", "", ""),
    "stub": EmbedProfile("stub", "stub", "stub", "", ""),
}

DEFAULT_PROFILE = "minilm"


def active_profile() -> EmbedProfile:
    key = (os.environ.get("PULS_EMBED") or DEFAULT_PROFILE).strip().lower()
    if key not in PROFILES:
        log.warning("Unbekanntes Einbettungsprofil %r — nehme %s.",
                    key, DEFAULT_PROFILE)
        key = DEFAULT_PROFILE
    return PROFILES[key]


def _normalise(vector: list[float]) -> list[float]:
    length = sum(v * v for v in vector) ** 0.5
    return [v / length for v in vector] if length else vector


class Embedder:
    """Laedt das Modell erst beim ersten Gebrauch.

    Der FastAPI-Start soll nicht auf 220 MB warten, und wer PULS nur benutzt,
    ohne eine Frage zu stellen, braucht das Modell gar nicht.
    """

    def __init__(self, profile: EmbedProfile | None = None):
        self.profile = profile or active_profile()
        self._impl = None
        self._lock = threading.Lock()

    @property
    def key(self) -> str:
        return f"{self.profile.key}:{self.profile.model}"

    def _load(self):
        if self._impl is not None:
            return self._impl
        with self._lock:
            if self._impl is not None:
                return self._impl
            if self.profile.backend == "fastembed":
                from fastembed import TextEmbedding
                self._impl = TextEmbedding(model_name=self.profile.model)
            elif self.profile.backend == "sentence-transformers":
                from sentence_transformers import SentenceTransformer
                self._impl = SentenceTransformer(self.profile.model, device="cpu")
            else:
                self._impl = "stub"
            log.info("Einbettungsmodell geladen: %s", self.profile.model)
        return self._impl

    def encode(self, texts: list[str], kind: str = "passage") -> list[list[float]]:
        if not texts:
            return []
        prefix = (self.profile.query_prefix if kind == "query"
                  else self.profile.passage_prefix)
        prepared = [f"{prefix}{t}" for t in texts]
        impl = self._load()

        if self.profile.backend == "stub":
            return [_stub_vector(t) for t in prepared]
        if self.profile.backend == "fastembed":
            return [_normalise(list(map(float, v))) for v in impl.embed(prepared)]
        vectors = impl.encode(prepared, normalize_embeddings=True,
                              batch_size=8, show_progress_bar=False)
        return [list(map(float, v)) for v in vectors]

    def one(self, text: str, kind: str = "query") -> list[float]:
        return self.encode([text], kind=kind)[0]


def _stub_vector(text: str) -> list[float]:
    """Deterministische Pseudovektoren aus dem Hash des Textes.

    Sie sagen inhaltlich nichts aus. Sie erlauben aber, Ingest, Speicherung und
    Suche zu testen, ohne ein Modell zu laden — und sie sind reproduzierbar,
    was echte Einbettungen in einem Test nie waeren.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    raw = (digest * (EMBED_DIM // len(digest) + 1))[:EMBED_DIM]
    return _normalise([b / 255.0 - 0.5 for b in raw])


# --------------------------------------------------------------------------
# Chunking
# --------------------------------------------------------------------------

@dataclass
class Chunk:
    source: str       # Dateiname
    heading: str      # Überschriftenpfad, z.B. "Grundlagen Muskelaufbau > 1. Volumen"
    text: str


def _split_long(text: str) -> list[str]:
    """Zerlegt einen zu langen Abschnitt an Absatzgrenzen."""
    if len(text) <= CHUNK_MAX:
        return [text]

    parts, current = [], ""
    for para in text.split("\n\n"):
        if current and len(current) + len(para) + 2 > CHUNK_TARGET:
            parts.append(current.strip())
            # kleiner Overlap: letzte Zeile des vorigen Chunks mitnehmen
            tail = current.strip().split("\n")[-1]
            current = (tail + "\n\n" + para) if len(tail) < 200 else para
        else:
            current = (current + "\n\n" + para) if current else para
    if current.strip():
        parts.append(current.strip())
    return parts


def chunk_markdown(path: Path) -> list[Chunk]:
    """Teilt eine Markdown-Datei an ##-Überschriften."""
    raw = path.read_text(encoding="utf-8")

    # H1 als Dokumenttitel
    m = re.search(r"^#\s+(.+)$", raw, re.MULTILINE)
    doc_title = m.group(1).strip() if m else path.stem

    # an ## splitten, Überschrift behalten
    sections = re.split(r"^##\s+", raw, flags=re.MULTILINE)
    chunks: list[Chunk] = []

    for i, section in enumerate(sections):
        if i == 0:
            # Text vor dem ersten ## (Intro) – nur übernehmen wenn substanziell
            body = re.sub(r"^#\s+.+$", "", section, flags=re.MULTILINE).strip()
            if len(body) < 120:
                continue
            heading, text = doc_title, body
        else:
            lines = section.split("\n", 1)
            heading = f"{doc_title} > {lines[0].strip()}"
            text = lines[1].strip() if len(lines) > 1 else ""

        if not text:
            continue

        for part in _split_long(text):
            # Überschriftenpfad in den Chunk-Text hinein – hilft
            # Embedding und Keyword-Suche gleichermaßen
            chunks.append(Chunk(path.name, heading, f"{heading}\n\n{part}"))

    return chunks


# --------------------------------------------------------------------------
# Datenbank
# --------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_chunks (
    id       INTEGER PRIMARY KEY,
    source   TEXT NOT NULL,
    heading  TEXT NOT NULL,
    text     TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts
USING fts5(text, content='kb_chunks', content_rowid='id', tokenize='unicode61');

CREATE TABLE IF NOT EXISTS kb_files (
    name   TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL
);

-- Womit der Index gebaut wurde. Ein Wechsel des Einbettungsmodells macht
-- alle gespeicherten Vektoren unvergleichbar; ohne diesen Vermerk faende
-- die Suche danach stillschweigend Unsinn.
CREATE TABLE IF NOT EXISTS kb_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _connect(db_path: str) -> sqlite3.Connection:
    # check_same_thread=False, weil FastAPI die Endpunkte in einem Threadpool
    # ausfuehrt: Die Verbindung entsteht im Startup-Thread und wird spaeter aus
    # Arbeiter-Threads benutzt. Der Zugriff ist durch _db_lock serialisiert.
    vec = _vec()
    db = sqlite3.connect(db_path, check_same_thread=False)
    try:
        db.enable_load_extension(True)
        vec.load(db)
        db.enable_load_extension(False)
    except AttributeError as e:                                 # noqa: BLE001
        raise RuntimeError(
            "Dieses Python kann keine SQLite-Erweiterungen laden — "
            "sqlite-vec braucht das. Alpine-Images koennen das nicht, "
            "python:3.12-slim schon."
        ) from e
    # WAL: PULS schreibt aus seinen eigenen Verbindungen in dieselbe Datei.
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=5000")
    db.executescript(SCHEMA)
    db.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS kb_vec "
        f"USING vec0(embedding float[{EMBED_DIM}])"
    )
    return db


class KnowledgeBase:
    def __init__(self, db_path: str, profile: EmbedProfile | None = None):
        self.db = _connect(db_path)
        self.embedder = Embedder(profile)
        self._db_lock = threading.Lock()

    # -- Buchfuehrung ------------------------------------------------------

    def _meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM kb_meta WHERE key=?",
                              (key,)).fetchone()
        return row[0] if row else None

    def _set_meta(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO kb_meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def chunk_count(self) -> int:
        """Anzahl indexierter Abschnitte. Ohne eigene Sperre — die Aufrufer
        halten sie bereits, und die Sperre ist nicht reentrant."""
        return self.db.execute("SELECT COUNT(*) FROM kb_chunks").fetchone()[0]

    def size(self) -> int:
        with self._db_lock:
            return self.chunk_count()

    # -- Ingest ------------------------------------------------------------

    def ingest(self, folder: str, force: bool = False) -> dict[str, int]:      # noqa: C901
        """Liest alle .md-Dateien ein. Unveränderte Dateien werden übersprungen."""
        files = sorted(Path(folder).glob("*.md"))
        if not files:
            raise FileNotFoundError(f"Keine .md-Dateien in {folder}")

        # Wurde mit einem anderen Modell indexiert, sind die gespeicherten
        # Vektoren wertlos — dann wird komplett neu gebaut, nicht ergaenzt.
        self._db_lock.acquire()
        try:
            return self._ingest(files, force)
        finally:
            self._db_lock.release()

    def _ingest(self, files: list[Path], force: bool) -> dict[str, int]:
        stored = self._meta("embedder")
        if stored and stored != self.embedder.key:
            log.info("Einbettungsmodell gewechselt (%s → %s) — Index wird neu "
                     "gebaut.", stored, self.embedder.key)
            force = True
            self.db.execute("DELETE FROM kb_fts")
            self.db.execute("DELETE FROM kb_vec")
            self.db.execute("DELETE FROM kb_chunks")
            self.db.execute("DELETE FROM kb_files")
        self._set_meta("embedder", self.embedder.key)
        self.db.commit()

        stats = {"neu": 0, "unveraendert": 0, "uebersprungen": 0, "chunks": 0}
        for path in files:
            if path.name in SKIP_FILES:
                stats["uebersprungen"] += 1
                log.debug("übersprungen (System-Prompt): %s", path.name)
                continue

            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            row = self.db.execute(
                "SELECT sha256 FROM kb_files WHERE name = ?", (path.name,)
            ).fetchone()
            if row and row[0] == digest and not force:
                stats["unveraendert"] += 1
                continue

            self._delete_source(path.name)
            chunks = chunk_markdown(path)

            vectors = self.embedder.encode([c.text for c in chunks],
                                           kind="passage")

            for chunk, vec in zip(chunks, vectors):
                cur = self.db.execute(
                    "INSERT INTO kb_chunks (source, heading, text) VALUES (?, ?, ?)",
                    (chunk.source, chunk.heading, chunk.text),
                )
                rowid = cur.lastrowid
                self.db.execute(
                    "INSERT INTO kb_fts (rowid, text) VALUES (?, ?)",
                    (rowid, chunk.text),
                )
                self.db.execute(
                    "INSERT INTO kb_vec (rowid, embedding) VALUES (?, ?)",
                    (rowid, _vec().serialize_float32(vec)),
                )

            self.db.execute(
                "INSERT INTO kb_files (name, sha256) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET sha256 = excluded.sha256",
                (path.name, digest),
            )
            self.db.commit()
            stats["neu"] += 1
            stats["chunks"] += len(chunks)
            log.info("%s: %d Chunks", path.name, len(chunks))
        stats["gesamt"] = self.chunk_count()
        return stats

    def _delete_source(self, name: str) -> None:
        ids = [r[0] for r in self.db.execute(
            "SELECT id FROM kb_chunks WHERE source = ?", (name,)
        )]
        for i in ids:
            self.db.execute("DELETE FROM kb_fts WHERE rowid = ?", (i,))
            self.db.execute("DELETE FROM kb_vec WHERE rowid = ?", (i,))
        self.db.execute("DELETE FROM kb_chunks WHERE source = ?", (name,))

    # -- Retrieval ---------------------------------------------------------

    @staticmethod
    def _fts_query(text: str) -> str:
        """Baut eine tolerante FTS5-Query aus der Nutzerfrage."""
        words = re.findall(r"\w{3,}", text.lower())
        if not words:
            return ""
        return " OR ".join(f'"{w}"' for w in words[:12])

    def search(self, query: str, k: int = 5, pool: int = 20) -> list[dict]:
        """Hybride Suche: Vektor + FTS5, zusammengeführt per Reciprocal Rank Fusion."""
        # Erst rechnen, dann sperren: Die Einbettung dauert Millisekunden bis
        # Sekunden, und solange soll kein anderer Aufruf auf die Datenbank
        # warten muessen.
        vec = self.embedder.one(query, kind="query")
        with self._db_lock:
            return self._search_db(query, vec, k, pool)

    def _search_db(self, query: str, vec: list[float], k: int,
                   pool: int) -> list[dict]:
        dense = [r[0] for r in self.db.execute(
            "SELECT rowid FROM kb_vec "
            "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (_vec().serialize_float32(vec), pool),
        )]

        sparse: list[int] = []
        fts = self._fts_query(query)
        if fts:
            try:
                sparse = [r[0] for r in self.db.execute(
                    "SELECT rowid FROM kb_fts WHERE kb_fts MATCH ? "
                    "ORDER BY rank LIMIT ?",
                    (fts, pool),
                )]
            except sqlite3.OperationalError:
                sparse = []

        # Reciprocal Rank Fusion
        K = 60
        scores: dict[int, float] = {}
        for ranking in (dense, sparse):
            for rank, rowid in enumerate(ranking):
                scores[rowid] = scores.get(rowid, 0.0) + 1.0 / (K + rank + 1)

        results = []
        for rowid, score in scores.items():
            row = self.db.execute(
                "SELECT source, heading, text FROM kb_chunks WHERE id = ?", (rowid,)
            ).fetchone()
            if not row:
                continue
            source, heading, text = row
            if source in DEMOTE_FILES:
                score *= DEMOTE_FACTOR
            results.append(
                {"source": source, "heading": heading, "text": text, "score": score}
            )

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:k]

    # -- Prompt ------------------------------------------------------------

    def context_with_sources(self, query: str, k: int = 5,
                             max_chars: int = 4500) -> tuple[str, list[str]]:
        """Kontextblock und die Dateien, die wirklich hineingekommen sind.

        Die Quellenliste kommt aus dem Code, nicht aus der Antwort des Modells.
        Kleine Modelle erfinden Quellenangaben, und eine falsche Quelle ist
        schlimmer als keine: Sie sieht aus wie ein Beleg.

        Gezaehlt wird, was den Platz noch hergab — was wegen max_chars
        wegfaellt, hat die Antwort auch nicht beeinflusst.
        """
        blocks, sources, total = [], [], 0
        for h in self.search(query, k=k):
            block = f"[Quelle: {h['source']}]\n{h['text']}"
            if total + len(block) > max_chars:
                break
            blocks.append(block)
            total += len(block)
            if h["source"] not in sources:
                sources.append(h["source"])
        return "\n\n---\n\n".join(blocks), sources

    def build_context(self, query: str, k: int = 5, max_chars: int = 4500) -> str:
        """Fertiger Kontextblock für den Prompt. Leerer String = nichts gefunden."""
        return self.context_with_sources(query, k=k, max_chars=max_chars)[0]


# --------------------------------------------------------------------------
# Prompt-Vorlage
# --------------------------------------------------------------------------

PROMPT_TEMPLATE = """{playbook}

## Wissensauszüge

{kontext}

## Berechnete Werte (bereits geprüft, nicht nachrechnen)

{berechnet}

## Frage

{frage}

## Regeln für diese Antwort

- Nutze die Wissensauszüge als Grundlage. Widersprich ihnen nicht.
- Übernimm die berechneten Werte unverändert. Rechne selbst nichts aus.
- Steht die Antwort nicht in den Auszügen: sag das, statt zu raten.
- Widersprechen die Auszüge deiner eigenen Einschätzung, gelten die Auszüge.
- Betrifft die Frage konkret meine Person (Schmerzen, aktuelle Werte, Termine),
  haben meine Angaben Vorrang vor den allgemeinen Auszügen.
- Nenne die Dateiquelle, wenn du eine konkrete Zahl oder Empfehlung nutzt.
- Antworte auf Deutsch, knapp und direkt. Keine Motivationsfloskeln."""


def build_prompt(kb: KnowledgeBase, frage: str, playbook: str,
                 berechnet: str = "—") -> str:
    kontext = kb.build_context(frage)
    if not kontext:
        kontext = "(Keine passenden Auszüge gefunden.)"
    return PROMPT_TEMPLATE.format(
        playbook=playbook.strip(),
        kontext=kontext,
        berechnet=berechnet.strip() or "—",
        frage=frage.strip(),
    )


# --------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="  %(message)s")
    if len(sys.argv) < 3 or sys.argv[1] != "ingest":
        print("Aufruf: python -m app.puls_knowledge ingest <ordner> [--force]")
        raise SystemExit(1)

    db_path = os.environ.get("PULS_DB", "puls.db")
    base = KnowledgeBase(db_path)
    print(f"Datenbank: {db_path}")
    print(f"Modell:    {base.embedder.profile.model} "
          f"({base.embedder.profile.backend})")
    result = base.ingest(sys.argv[2], force="--force" in sys.argv)
    print(f"\nFertig. {result['neu']} Datei(en) neu gelesen, "
          f"{result['unveraendert']} unverändert, "
          f"{result['uebersprungen']} übersprungen — "
          f"{result['gesamt']} Chunks im Index.")
