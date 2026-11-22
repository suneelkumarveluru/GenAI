"""Search your own UTF-8 text/Markdown files with a local lexical retriever.

Run: python examples/rag_cli.py ./docs "data governance" --top-k 5
No API keys, external services, or network requests required.
"""
import argparse
from pathlib import Path
from rag_retriever import retrieve


def load_documents(root: Path) -> tuple[list[Path], list[str]]:
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")
    paths = sorted(p for p in root.rglob("*")
                   if p.is_file() and p.suffix.lower() in {".txt", ".md"}
                   and not p.is_symlink())
    readable_paths, documents = [], []
    for path in paths:
        try:
            contents = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if contents.strip():
            readable_paths.append(path)
            documents.append(contents)
    return readable_paths, documents


def search_directory(root: Path, query: str, top_k: int = 5) -> list[tuple[Path, float]]:
    paths, documents = load_documents(root)
    return [(paths[index], score) for index, score in retrieve(query, documents, top_k)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Folder containing .txt and .md files")
    parser.add_argument("query", help="Search keywords")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("--top-k must be at least 1")
    try:
        results = search_directory(args.directory, args.query, args.top_k)
    except (NotADirectoryError, OSError) as exc:
        parser.error(str(exc))
    if not results:
        print("No matching documents found.")
    for path, score in results:
        print(f"{score:.3f}\t{path}")


if __name__ == "__main__":
    main()
