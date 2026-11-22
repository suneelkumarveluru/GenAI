# Local document search (no cloud account required)

This project demonstrates the **retrieval** stage of retrieval-augmented generation (RAG). It does **not** call an LLM or generate an answer: the retriever ranks local files by a TF-IDF cosine-similarity score.

## Requirements

- Python 3.10 or newer
- No third-party packages, API keys, or network access

## Quick start

From the repository root:

```bash
mkdir -p demo_docs
echo "Snowflake warehouses and SQL models" > demo_docs/snowflake.txt
echo "Python orchestration and workflows" > demo_docs/python.md
python examples/rag_cli.py demo_docs "Snowflake SQL" --top-k 2
python -m unittest discover -s tests -v
```

Results show similarity scores followed by file paths. Search is case-insensitive and accepts `.txt` and `.md` files recursively. Empty files are ignored.

## Design and limitations

- Only tokenize letters and digits; no stemming, synonyms, chunking, or language-specific morphology.
- The entire file is the retrieval unit; very large files can dominate memory.
- The tool reads the specified directory: do not point it at private or sensitive files without understanding that returned file names may be logged.
- The lexical ranker is not a production semantic/vector search engine; add embedding models and vector search separately if needed.
- No external calls or telemetry.

## Potential next steps

Add text chunking, BM25, vector embeddings, a reranker, citations from document offsets, and an optional LLM generator.
