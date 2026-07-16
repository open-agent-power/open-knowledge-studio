import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "formula_candidates.py"
SPEC = importlib.util.spec_from_file_location("formula_candidates", MODULE_PATH)
assert SPEC and SPEC.loader
formula = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(formula)


def test_candidate_regions_only_keeps_existing_equation_images(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "formula.png").write_bytes(b"png")
    (tmp_path / "sample_content_list.json").write_text(
        json.dumps(
            [
                {"type": "text", "text": "正文", "page_idx": 0},
                {
                    "type": "equation",
                    "text": "x+y",
                    "page_idx": 1,
                    "bbox": [1, 2, 3, 4],
                    "img_path": "images/formula.png",
                },
                {
                    "type": "equation",
                    "text": "missing",
                    "page_idx": 2,
                    "img_path": "images/missing.png",
                },
            ]
        ),
        encoding="utf-8",
    )

    regions = formula.candidate_regions(tmp_path, 20)

    assert len(regions) == 1
    assert regions[0]["page"] == 2
    assert regions[0]["bbox"] == [1, 2, 3, 4]
