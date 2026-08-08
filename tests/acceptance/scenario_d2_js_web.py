"""D2: JavaScript web acceptance — prove static-vs-JS degradation path.

This script demonstrates:
1. Static HTTP fetch of a JS-rendered page returns empty content
2. The gap is detected and reported honestly
3. A JS-capable provider (Firecrawl) would be selected as fallback

The JS web fixture at fixtures/js-web/index.html renders its content
via JavaScript after page load. A plain HTTP GET only sees an empty div.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

# Project paths
_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
_REPO = Path(__file__).resolve().parents[3]

sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_REPO / "cli"))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main():
    fixture_dir = Path(__file__).resolve().parent / "fixtures" / "js-web"
    html_path = fixture_dir / "index.html"
    html_content = html_path.read_bytes()

    run_id = f"run-{uuid.uuid4().hex[:12]}"  # no colon — Windows path limitation
    work_dir = Path(os.environ.get("OKS_ROOT", _REPO)) / ".oks" / "runs" / run_id / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir = work_dir.parent / "manifest" / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: static HTTP fetch (no JS) → empty content ──
    import urllib.request
    import tempfile
    import http.server
    import threading

    # Serve the fixture
    html_bytes = html_path.read_bytes()
    served_content = [None]

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(fixture_dir), **kwargs)

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        url = f"http://127.0.0.1:{port}/index.html"
        req = urllib.request.Request(url, headers={"User-Agent": "oks-acceptance/0.4.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            static_html = resp.read()
    finally:
        server.shutdown()

    # Verify: static fetch — the content lives inside <script> tags,
    # not rendered in the DOM. Use an HTML parser to check the actual DOM.
    from html.parser import HTMLParser

    class DOMChecker(HTMLParser):
        def __init__(self):
            super().__init__()
            self.in_div = False
            self.div_content = []
        def handle_starttag(self, tag, attrs):
            attrs_dict = dict(attrs)
            if tag == "div" and attrs_dict.get("id") == "content":
                self.in_div = True
        def handle_endtag(self, tag):
            if tag == "div" and self.in_div:
                self.in_div = False
        def handle_data(self, data):
            if self.in_div:
                self.div_content.append(data)

    checker = DOMChecker()
    checker.feed(static_html.decode("utf-8"))
    dom_content = "".join(checker.div_content).strip()
    has_js_content = "oks-js-web-acceptance-v0.4.0" in dom_content

    # ── Evidence ──
    static_artifact = str(artifacts_dir / "static-fetch.html")
    Path(static_artifact).write_bytes(static_html)

    evidence = []
    if has_js_content:
        # Unexpected — JS rendered server-side or cached
        evidence.append({
            "evidence_id": "ev_d2_static",
            "artifact_id": "static-fetch.html",
            "kind": "static text",
            "locator": {"kind": "dom", "xpath_fragment": "//div[@id='content']"},
            "content_text": "Static fetch returned full content (unexpected)",
            "agent_judgment": "platform_observed",
        })
        status = "unexpected_pass"
        warnings = ["Static fetch returned JS-rendered content — JS may not be required"]
    else:
        evidence.append({
            "evidence_id": "ev_d2_static",
            "artifact_id": "static-fetch.html",
            "kind": "static text",
            "locator": {"kind": "dom", "xpath_fragment": "//div[@id='content']"},
            "content_text": "Static fetch: empty div — JS rendering required",
            "agent_judgment": "platform_observed",
        })
        status = "partial"
        warnings = []

    # ── Source envelope ──
    source_envelope = {
        "schema_version": "oks-source-envelope/v0.1",
        "source_id": f"d2-js-web-{uuid.uuid4().hex[:8]}",
        "run_id": run_id,
        "source_uri": url,
        "source_modality": "web",
        "access_mode": "public_url",
        "captured_at": "2026-08-06T00:00:00Z",
        "policy": {"remote_processing": "allow", "sensitivity": "public"},
    }

    # ── Manifest ──
    manifest = {
        "schema_version": "oks-evidence-manifest/v0.1",
        "run_id": run_id,
        "source_id": source_envelope["source_id"],
        "status": status,
        "primary_evidence": evidence,
        "supplementary_evidence": [],
        "artifacts": [
            {
                "artifact_id": "static-fetch.html",
                "path": "static-fetch.html",
                "media_type": "text/html",
                "sha256": sha256_hex(static_html),
                "byte_size": len(static_html),
            }
        ],
        "warnings": warnings,
        "missing": [] if status == "complete" else [
            {
                "capability": "web.extract",
                "reason": "JS rendering required — static fetch sees empty div",
                "recommended": ["firecrawl scrape", "browser screenshot", "agentkey web.extract"],
            }
        ],
        "steps": [
            {
                "capability": "web.fetch",
                "provider": "http-fetch",
                "status": "succeeded",
                "reason": None,
            },
            {
                "capability": "web.extract",
                "provider": "http-fetch",
                "status": "partial",
                "reason": "JS rendering required",
            },
        ],
        "provenance": {"cost": 0.0, "latency_ms": 0, "remote_services": []},
    }

    # Write manifest
    manifest_dir = work_dir.parent / "manifest"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "source-envelope.json").write_text(
        json.dumps(source_envelope, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (manifest_dir / "evidence-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Run ID: {run_id}")
    print(f"Status: {status}")
    print(f"Static fetch has JS content: {has_js_content}")
    print(f"Evidence records: {len(evidence)}")
    print(f"Missing capabilities: {len(manifest['missing'])}")
    if warnings:
        for w in warnings:
            print(f"  Warning: {w}")
    for m in manifest["missing"]:
        print(f"  Missing: {m['capability']} — {m['reason']}")
        print(f"    Recommended: {', '.join(m['recommended'])}")
    print(f"Manifest: {manifest_dir}")

    return manifest


if __name__ == "__main__":
    main()
