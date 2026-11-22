# GenAI: Practical RAG retrieval examples

A beginner-friendly, dependency-free Python project demonstrating the retrieval step of retrieval-augmented generation (RAG).

## What it does

- Indexes local Markdown (`.md`) and plain-text (`.txt`) documents on demand
- Ranks relevant files using TF-IDF cosine similarity
- Provides a command-line interface
- Includes unit tests and a GitHub Actions test workflow

It does **not** call an LLM, create embeddings, or generate answers. This keeps the project safe to run offline and makes the retrieval behavior easy to understand.

## Quick start

Requires Python 3.10 or later:

```bash
git clone https://github.com/suneelkumarveluru/GenAI.git
cd GenAI
mkdir -p demo_docs
echo "Snowflake and data governance" > demo_docs/warehouse.txt
echo "Python data pipeline orchestration" > demo_docs/pipeline.txt
python examples/rag_cli.py demo_docs "data governance" --top-k 3
python -m unittest discover -s tests -v
```

See [full documentation](docs/LOCAL_SEARCH.md) for behavior, limitations, and extension ideas.

## Repository contents

| Path | Purpose |
|---|---|
| `examples/rag_retriever.py` | TF-IDF cosine retrieval logic |
| `examples/rag_cli.py` | Local document search CLI |
| `tests/test_retriever.py` | Standard-library unit tests |
| `docs/LOCAL_SEARCH.md` | Setup and technical notes |
| `.github/workflows/python-tests.yml` | Tests on pushes and pull requests |

## Contributing

Open an issue for a bug or feature proposal and submit a focused pull request with tests. Do not commit real company data, API tokens, or private documents.

Licensed under the MIT License.
