"""PDF handler — parse PDF files into structured markdown.

Pipeline: PDF → text extraction → structure preservation → Markdown
Dependencies: pypdf (pure Python) or pdfplumber (more accurate, needs C libs)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from knowledge_studio.handlers.base import BaseHandler, HandlerResult, HandlerError


class PDFHandler(BaseHandler):
    name = "pdf"
    modalities = ["pdf"]
    description = "PDF parse → text + structure"

    def detect(self, input_path: str) -> bool:
        if input_path.startswith(("http://", "https://")):
            return input_path.lower().endswith(".pdf")
        return Path(input_path).suffix.lower() == ".pdf"

    def is_available(self) -> bool:
        try:
            import pypdf  # noqa: F401
            return True
        except ImportError:
            return False

    def process(self, input_path: str, config: dict[str, Any] | None = None) -> HandlerResult:
        if not self.is_available():
            raise HandlerError(
                self.name, "pypdf not installed",
                hint="pip install pypdf",
            )

        import pypdf

        path = Path(input_path)
        if not path.exists():
            raise HandlerError(self.name, f"File not found: {input_path}")

        reader = pypdf.PdfReader(str(path))
        pages = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            pages.append(f"## Page {i + 1}\n\n{text}")

        title = path.stem
        meta = reader.metadata
        if meta and meta.title:
            title = meta.title

        return HandlerResult(
            markdown="\n\n".join(pages),
            title=title,
            source=str(path),
            modality="paper",
            handler_name=self.name,
            metadata={
                "page_count": len(reader.pages),
                "original_file": path.name,
            },
        )
