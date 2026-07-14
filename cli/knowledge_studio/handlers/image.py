"""Image handler — vision model / OCR for images and screenshots.

Pipeline: Image → Vision model (or OCR fallback) → structured description → Markdown
Dependencies: OpenAI Vision API or Claude Vision (needs API key)

Config (from ~/.oks/config.json → handlers.image):
    vision_api_key: API key for vision model
    vision_model: model name (default: "gpt-4o")
    max_tokens: max response tokens (default: 1000)
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from knowledge_studio.handlers.base import BaseHandler, HandlerResult, HandlerError
from knowledge_studio.handlers.detect import IMAGE_EXTENSIONS


class ImageHandler(BaseHandler):
    name = "image"
    modalities = ["png", "jpg", "jpeg", "webp", "gif", "bmp"]
    description = "Image: Vision model / OCR → structured description"

    def detect(self, input_path: str) -> bool:
        return Path(input_path).suffix.lower() in IMAGE_EXTENSIONS

    def is_available(self) -> bool:
        return False

    def process(self, input_path: str, config: dict[str, Any] | None = None) -> HandlerResult:
        cfg = config or {}
        api_key = cfg.get("vision_api_key") or cfg.get("openai_api_key")
        if not api_key:
            raise HandlerError(
                self.name, "No vision API key configured",
                hint="Set in ~/.oks/config.json → handlers.image.vision_api_key",
            )

        path = Path(input_path)
        if not path.exists():
            raise HandlerError(self.name, f"File not found: {input_path}")

        image_data = base64.b64encode(path.read_bytes()).decode("utf-8")
        description = self._vision_describe(image_data, path.suffix, api_key, cfg)

        return HandlerResult(
            markdown=f"## Image Description\n\n{description}",
            title=path.stem,
            source=str(path),
            modality="image",
            handler_name=self.name,
            metadata={
                "original_file": path.name,
                "file_size": path.stat().st_size,
                "vision_model": cfg.get("vision_model", "gpt-4o"),
            },
        )

    def _vision_describe(self, image_b64: str, ext: str, api_key: str, cfg: dict) -> str:
        model = cfg.get("vision_model", "gpt-4o")
        max_tokens = cfg.get("max_tokens", 1000)

        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp"}
        mime_type = mime.get(ext.lower(), "image/png")

        try:
            import httpx
        except ImportError:
            from urllib.request import Request, urlopen

            body = _build_openai_vision_body(image_b64, mime_type, model, max_tokens)
            req = Request(
                "https://api.openai.com/v1/chat/completions",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
            )
            with urlopen(req, timeout=60) as resp:
                import json
                result = json.loads(resp.read())
                return result["choices"][0]["message"]["content"]

        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            json=_build_openai_vision_body(image_b64, mime_type, model, max_tokens),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60,
        )
        result = response.json()
        return result["choices"][0]["message"]["content"]


def _build_openai_vision_body(image_b64: str, mime_type: str, model: str, max_tokens: int) -> dict:
    return {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this image in detail. Capture all text, diagrams, UI elements, and technical content. Preserve maximum information fidelity."},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_b64}"}},
            ],
        }],
    }
