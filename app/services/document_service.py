import os
import io
import json

import requests
import numpy as np
from werkzeug.utils import secure_filename
from PyPDF2 import PdfReader
from docx import Document as DocxDocument

from app.models import db, Document, DocumentChunk

ALLOWED_EXTENSIONS = {'txt', 'pdf', 'docx'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_text(stream, filename):
    """Extract text from an in-memory file stream."""
    ext = filename.rsplit('.', 1)[1].lower()
    text = ""
    try:
        if ext == 'pdf':
            reader = PdfReader(stream)
            for page in reader.pages:
                text += (page.extract_text() or "") + "\n"
        elif ext == 'docx':
            doc = DocxDocument(stream)
            for para in doc.paragraphs:
                text += para.text + "\n"
        elif ext == 'txt':
            text = stream.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"Error extracting text: {e}")
        return ""
    return text.strip()


def chunk_text(text, chunk_size=1000, overlap=200):
    chunks = []
    start = 0
    while start < len(text):
        chunks.append(text[start:start + chunk_size])
        start += (chunk_size - overlap)
    return [c for c in chunks if c.strip()]


# ---------- Semantic embeddings (free local Ollama) ----------

def _embedding_enabled():
    return os.getenv('EMBEDDING_PROVIDER', 'ollama').lower() != 'off'


def get_embeddings(texts):
    if not _embedding_enabled() or not texts:
        return None
    base = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434').rstrip('/')
    if base.endswith('/v1'):
        base = base[:-3]
    model = os.getenv('EMBEDDING_MODEL', 'nomic-embed-text')
    try:
        r = requests.post(f"{base}/api/embed", json={"model": model, "input": texts}, timeout=180)
        if r.ok:
            return r.json().get('embeddings')
        vecs = []
        for t in texts:
            r2 = requests.post(f"{base}/api/embeddings", json={"model": model, "prompt": t}, timeout=60)
            if not r2.ok:
                return None
            vecs.append(r2.json().get('embedding'))
        return vecs
    except Exception as e:
        print(f"--- DEBUG: embeddings unavailable ({e}). Using TF-IDF fallback. ---")
        return None


def cosine_similarity(a, b):
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom else 0.0


# ---------- Cloud-safe processing (NO disk writes) ----------

def process_and_save_document(file, user_id):
    if not allowed_file(file.filename):
        raise ValueError("File type not allowed.")

    filename = secure_filename(file.filename)
    stream = io.BytesIO(file.read())

    text = extract_text(stream, filename)
    if not text:
        raise ValueError("Could not extract text from file (it might be empty or a scanned image).")

    doc = Document(
        user_id=user_id,
        filename=filename,
        original_name=file.filename,
        file_path=''  # cloud-safe: knowledge lives in DB chunks, not on disk
    )
    db.session.add(doc)
    db.session.commit()

    chunks = chunk_text(text)
    vectors = get_embeddings(chunks)

    for i, chunk_content in enumerate(chunks):
        vec_json = None
        if vectors and i < len(vectors) and vectors[i]:
            vec_json = json.dumps(vectors[i])
        db.session.add(DocumentChunk(
            document_id=doc.id,
            content=chunk_content,
            chunk_index=i,
            embedding=vec_json
        ))

    db.session.commit()
    return doc


def get_relevant_context(query, document_id, top_k=3):
    chunks = DocumentChunk.query.filter_by(
        document_id=document_id
    ).order_by(DocumentChunk.chunk_index).all()

    if not chunks:
        return ""

    if len(chunks) <= top_k:
        return "\n\n---\n\n".join([c.content for c in chunks])

    vecs = [json.loads(c.embedding) if c.embedding else None for c in chunks]

    # Lazy re-index older documents
    if _embedding_enabled() and any(v is None for v in vecs):
        missing_idx = [i for i, v in enumerate(vecs) if v is None]
        new_vecs = get_embeddings([chunks[i].content for i in missing_idx])
        if new_vecs:
            for j, idx in enumerate(missing_idx):
                vecs[idx] = new_vecs[j]
                chunks[idx].embedding = json.dumps(new_vecs[j])
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

    # SEMANTIC SEARCH
    if all(v is not None for v in vecs):
        qvec = get_embeddings([query])
        if qvec and qvec[0]:
            scored = sorted(
                range(len(chunks)),
                key=lambda i: cosine_similarity(qvec[0], vecs[i]),
                reverse=True
            )
            top = sorted(scored[:top_k])
            return "\n\n---\n\n".join([chunks[i].content for i in top])

    # TF-IDF FALLBACK
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity as tfidf_cosine

    chunk_texts = [c.content for c in chunks]
    vectorizer = TfidfVectorizer().fit(chunk_texts + [query])
    chunk_vectors = vectorizer.transform(chunk_texts)
    query_vector = vectorizer.transform([query])
    similarities = tfidf_cosine(query_vector, chunk_vectors).flatten()
    top_indices = similarities.argsort()[-top_k:][::-1]
    return "\n\n---\n\n".join([chunks[i].content for i in sorted(top_indices)])