import importlib.util
from argparse import Namespace
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "multimodal_feedback.py"
SPEC = importlib.util.spec_from_file_location("multimodal_feedback", MODULE_PATH)
assert SPEC and SPEC.loader
feedback = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(feedback)


def test_feedback_loop_records_gap_fix_and_verification(tmp_path):
    path = tmp_path / "feedback.jsonl"
    base = {
        "cycle": "ppt-image-map",
        "sample": "deck.pptx",
        "capability": "PPT图片关系映射",
        "evidence": None,
        "next_action": None,
        "commit": None,
    }
    for status, observation in (
        ("gap", "图片引用未映射"),
        ("fix", "读取OOXML关系"),
        ("verified", "同一样本复跑通过"),
    ):
        args = Namespace(**base, status=status, observation=observation)
        feedback.append_record(path, feedback.make_record(args))

    records = feedback.load_records(path)
    report = feedback.render_report(records)

    assert [item["status"] for item in records] == ["gap", "fix", "verified"]
    assert "当前状态：verified" in report
    assert "图片引用未映射" in report
    assert "同一样本复跑通过" in report


def test_empty_feedback_report_is_explicit():
    assert "暂无反馈记录" in feedback.render_report([])
