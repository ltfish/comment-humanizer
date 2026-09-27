from __future__ import annotations

from ..models import Comment
from .python import extract_python
from .rust import extract_rust

LANGUAGES = {".py": "python", ".pyi": "python", ".rs": "rust"}


def language_of(path: str) -> str | None:
    for ext, lang in LANGUAGES.items():
        if path.endswith(ext):
            return lang
    return None


def extract(source: str, path: str) -> list[Comment]:
    lang = language_of(path)
    if lang == "python":
        return extract_python(source, path)
    if lang == "rust":
        return extract_rust(source, path)
    return []


__all__ = ["LANGUAGES", "extract", "extract_python", "extract_rust", "language_of"]
