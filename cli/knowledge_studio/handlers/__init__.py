"""Multi-modal handler framework for raw material intake.

Each handler processes a specific input modality (web, PDF, video, audio, image, repo)
and outputs structured markdown with maximum fidelity preservation.

Architecture:
    /ingest (orchestrator) → detect modality → dispatch to handler → unified markdown → raw/

Handlers are registered in settings/handlers.json and can be:
    - Built-in Python handlers (this package)
    - External CLI commands (registered via config)
"""
from knowledge_studio.handlers.base import BaseHandler, HandlerResult
from knowledge_studio.handlers.registry import HandlerRegistry
from knowledge_studio.handlers.detect import detect_modality

__all__ = ["BaseHandler", "HandlerResult", "HandlerRegistry", "detect_modality"]
