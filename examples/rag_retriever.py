"""Dependency-free toy document retriever for learning RAG concepts.

This is lexical retrieval, not a production vector embedding implementation.
Run: python examples/rag_retriever.py
"""
from collections import Counter
from math import log, sqrt
import re


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def retrieve(query: str, documents: list[str], top_k: int = 3) -> list[tuple[int, float]]:
    """Return document indices ordered by cosine TF-IDF similarity."""
    if top_k < 1:
        return []
    corpus = [Counter(tokens(d)) for d in documents]
    query_counts = Counter(tokens(query))
    if not query_counts or not corpus:
        return []
    df = Counter(term for doc in corpus for term in doc)
    n = len(corpus)
    def weight(counts: Counter) -> dict[str, float]:
        return {term: freq * (log((n + 1) / (df[term] + 1)) + 1)
                for term, freq in counts.items()}
    q = weight(query_counts)
    q_norm = sqrt(sum(v * v for v in q.values()))
    scored = []
    for index, doc in enumerate(corpus):
        d = weight(doc)
        d_norm = sqrt(sum(v * v for v in d.values()))
        score = sum(q[t] * d.get(t, 0) for t in q) / (q_norm * d_norm) if q_norm and d_norm else 0.0
        if score > 0:
            scored.append((index, round(score, 6)))
    return sorted(scored, key=lambda item: (-item[1], item[0]))[:top_k]


if __name__ == "__main__":
    docs = ["Snowflake manages cloud data warehouses.",
            "Retrieval augmented generation grounds LLM answers in documents.",
            "Python helps build data pipelines."]
    for doc_index, similarity in retrieve("LLM retrieval documents", docs):
        print(f"{similarity:.3f} {docs[doc_index]}")
