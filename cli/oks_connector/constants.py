"""Module-level constants shared across the extraction pipeline."""

from __future__ import annotations

import threading

SCHEMA_VERSION = "raw-multimodal/v0.1"
FETCH_RECEIPT_VERSION = "oks-fetch-receipt/v0.1"
RAW_V2_VERSION = "raw-multimodal/v0.2"
PLUGIN_VERSION = "0.1.0"
_WATCH_OVERRIDE_LOCK = threading.Lock()
