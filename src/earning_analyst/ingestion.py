"""Document ingestion: 10-Q/10-K and earnings-call transcripts.

Handles .pdf, .htm/.html and .txt. Produces cleaned text plus a light section
map so the engine can pass the most relevant slices to the model and keep
within context limits.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Document:
    path: str
    kind: str  # 'filing' or 'transcript'
    text: str
    sections: dict[str, str] = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        return len(self.text)

    def excerpt(self, max_chars: int = 60_000) -> str:
        """Return a trimmed version safe to send to the model."""
        if len(self.text) <= max_chars:
            return self.text
        head = self.text[: int(max_chars * 0.7)]
        tail = self.text[-int(max_chars * 0.3):]
        return f"{head}\n\n[... {len(self.text) - max_chars:,} chars omitted ...]\n\n{tail}"


# Section headers we care about in SEC filings (MD&A, risk factors, etc.)
_FILING_SECTIONS = {
    "mdna": r"management'?s discussion and analysis",
    "risk_factors": r"risk factors",
    "results_of_operations": r"results of operations",
    "liquidity": r"liquidity and capital resources",
}


def _read_raw(path: str) -> str:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return _read_pdf(p)
    if suffix in (".htm", ".html"):
        return _read_html(p)
    return p.read_text(encoding="utf-8", errors="ignore")


def _read_pdf(p: Path) -> str:
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pdfplumber is required to read PDF files") from exc
    parts: list[str] = []
    with pdfplumber.open(str(p)) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _read_html(p: Path) -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("beautifulsoup4 is required to read HTML files") from exc
    soup = BeautifulSoup(p.read_text(encoding="utf-8", errors="ignore"), "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text(separator="\n")


def _clean(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _find_sections(text: str) -> dict[str, str]:
    lower = text.lower()
    hits: list[tuple[int, str]] = []
    for key, pattern in _FILING_SECTIONS.items():
        m = re.search(pattern, lower)
        if m:
            hits.append((m.start(), key))
    hits.sort()
    sections: dict[str, str] = {}
    for i, (start, key) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else min(start + 40_000, len(text))
        sections[key] = text[start:end].strip()
    return sections


def load_document(path: str, kind: str | None = None) -> Document:
    """Load and clean a single document from disk."""
    raw = _clean(_read_raw(path))
    if kind is None:
        kind = _guess_kind(path, raw)
    sections = _find_sections(raw) if kind == "filing" else {}
    return Document(path=path, kind=kind, text=raw, sections=sections)


def load_text(text: str, kind: str = "filing", path: str = "<inline>") -> Document:
    """Build a Document from an in-memory string (used by the Streamlit app)."""
    raw = _clean(text)
    sections = _find_sections(raw) if kind == "filing" else {}
    return Document(path=path, kind=kind, text=raw, sections=sections)


def _guess_kind(path: str, text: str) -> str:
    name = Path(path).name.lower()
    if "transcript" in name or "call" in name:
        return "transcript"
    head = text[:4000].lower()
    if "operator" in head and ("q&a" in head or "prepared remarks" in head):
        return "transcript"
    if "form 10-q" in head or "form 10-k" in head or "securities and exchange" in head:
        return "filing"
    return "filing"
