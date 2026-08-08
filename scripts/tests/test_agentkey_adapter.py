from __future__ import annotations

import json
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from capture_adapters.agentkey import (
    AgentKeyBilibiliAdapter,
    ascii_summary,
    classify_bilibili,
    write_utf8_json,
)
from capture_contract import CaptureContext, CaptureRequest
from raw_assembler import assemble_raw_bundle


ANCHORS = (
    "就这种大半夜起来接他呕吐物的事情",
    "都是用支付宝的阿宝AI自动生成的呢",
)


def test_agentkey_utf8_response_survives_and_generates_raw(tmp_path):
    original_subtitle = "就这种大半夜起来接他\u200b呕吐物的事情 😀"
    payload = {
        "result": {
            "data": {
                "bvid": "BV1Lg3R65EZn",
                "title": "卷卷宝 ＡＩ 日记 😀",
                "subtitle": {"body": [{"content": original_subtitle}]},
            }
        }
    }
    raw = write_utf8_json(tmp_path / "agentkey-response.json", payload)
    adapter = AgentKeyBilibiliAdapter(
        raw,
        anchors=ANCHORS,
        provider="TikHub",
        provider_version="test",
        credits=0.2,
        latency_ms=321,
    )

    result = adapter.capture(CaptureRequest(
        "https://www.bilibili.com/video/BV1Lg3R65EZn", ("subtitle",)
    ))

    assert result.status == "complete"
    assert original_subtitle in result.content_markdown
    assert raw.read_text(encoding="utf-8").count("😀") == 2
    assert not list(tmp_path.glob(".agentkey-response.json.*.tmp"))
    assert ascii_summary(result).isascii()

    output = tmp_path / "raw"
    report = assemble_raw_bundle(
        result,
        output,
        CaptureContext(
            capture_id="agentkey-bili-fixture",
            run_id="agentkey-bili-fixture-run",
            source_type="remote_api",
        ),
    )
    assert report["valid"] is True
    capture = json.loads((output / "derived" / "capture-result.json").read_text(encoding="utf-8"))
    assert capture["cost"]["amount"] == 0.2


def test_agentkey_metadata_is_not_misclassified_as_subtitle(tmp_path):
    payload = {"data": {"bvid": "BV1Lg3R65EZn", "title": "只有元数据"}}
    raw = write_utf8_json(tmp_path / "metadata.json", payload)
    result = AgentKeyBilibiliAdapter(
        raw,
        anchors=ANCHORS,
        provider="TikHub",
        provider_version="test",
    ).capture(CaptureRequest("https://www.bilibili.com/video/BV1Lg3R65EZn"))

    assert result.status == "partial"
    assert result.failure_disposition == "needs_user_action"
    assert "agentkey_classification=metadata_only" in result.warnings


def test_agentkey_login_challenge_is_preserved():
    extraction = classify_bilibili(
        {"error": "需要登录后查看字幕", "bvid": "BV1Lg3R65EZn"},
        anchors=ANCHORS,
    )

    assert extraction.classification == "needs_user_auth"
