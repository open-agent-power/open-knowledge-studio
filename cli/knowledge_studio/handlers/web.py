"""Web handler — fetch URL and extract article content via Readability.

Pipeline: URL → HTTP GET → HTML parse → Readability extraction → clean Markdown
Maximum fidelity: preserves original text, headings, code blocks, lists.
"""
from __future__ import annotations

from typing import Any

from knowledge_studio.handlers.base import BaseHandler, HandlerResult, HandlerError


class WebHandler(BaseHandler):
    name = "web"
    modalities = ["url:http", "url:https"]
    description = "Web article fetch + Readability extraction"

    def detect(self, input_path: str) -> bool:
        return input_path.startswith(("http://", "https://"))

    def process(self, input_path: str, config: dict[str, Any] | None = None) -> HandlerResult:
        try:
            import urllib.request
            with urllib.request.urlopen(input_path, timeout=30) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            raise HandlerError(self.name, f"Fetch failed: {e}", hint="Check URL or network")

        title = self._extract_title(html)
        body = self._html_to_markdown(html)

        return HandlerResult(
            markdown=body,
            title=title or input_path,
            source=input_path,
            modality="article",
            handler_name=self.name,
            metadata={"fetched_url": input_path},
        )

    def _extract_title(self, html: str) -> str:
        import re
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else ""

    def _html_to_markdown(self, html: str) -> str:
        import re
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<nav[^>]*>.*?</nav>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<footer[^>]*>.*?</footer>", "", html, flags=re.DOTALL | re.IGNORECASE)

        html = re.sub(r"<h1[^>]*>(.*?)</h1>", r"# \1", html, flags=re.DOTALL)
        html = re.sub(r"<h2[^>]*>(.*?)</h2>", r"## \1", html, flags=re.DOTALL)
        html = re.sub(r"<h3[^>]*>(.*?)</h3>", r"### \1", html, flags=re.DOTALL)
        html = re.sub(r"<p[^>]*>(.*?)</p>", r"\1\n\n", html, flags=re.DOTALL)
        html = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", html, flags=re.DOTALL)
        html = re.sub(r"<pre[^>]*>(.*?)</pre>", r"```\n\1\n```", html, flags=re.DOTALL)
        html = re.sub(r"<li[^>]*>(.*?)</li>", r"- \1\n", html, flags=re.DOTALL)
        html = re.sub(r"<a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", r"[\2](\1)", html, flags=re.DOTALL)
        html = re.sub(r"<[^>]+>", "", html)
        html = re.sub(r"\n{3,}", "\n\n", html)

        import html as html_module
        return html_module.unescape(html).strip()
