"""Release guards must fail when an evaluator or schema is missing."""
import importlib.util
from pathlib import Path

import pytest


def load_script(name):
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def checker(tmp_path, monkeypatch):
    module = load_script("check_dist")
    assets = tmp_path / "assets"
    (assets / "_meta").mkdir(parents=True)
    (assets / "skills").mkdir()
    (assets / "_meta/recall-case-v2.schema.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module, "_ASSETS", assets)
    monkeypatch.setattr(module, "_MAINTAINER_SKILLS", tmp_path / "maintainer-skills")
    return module


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
@pytest.mark.parametrize("missing", ["schema", "module"])
def test_distribution_missing_evaluation_contract_fails(checker, kind, missing):
    schema = "knowledge_studio/_assets/_meta/recall-case-v2.schema.json"
    names = list(checker._REQUIRED_MODULES) + [schema]
    check = getattr(checker, f"check_{kind}")
    assert check(names) == []
    omitted = schema if missing == "schema" else "knowledge_studio/evaluation_dataset.py"
    names.remove(omitted)
    assert any(omitted in problem for problem in check(names))


def test_smoke_removes_ambient_source_and_recall_overrides(monkeypatch):
    smoke = load_script("smoke_installed")
    monkeypatch.setenv("OKS_ROOT", "personal-kb")
    monkeypatch.setenv("OKS_SEARCH_BACKEND", "unexpected")
    monkeypatch.setenv("PYTHONPATH", "source-checkout")
    monkeypatch.setenv("PYTHONHOME", "source-python")
    env = smoke.clean_env()
    assert not any(k.upper().startswith("OKS_") for k in env)
    assert "PYTHONPATH" not in env and "PYTHONHOME" not in env
    assert env["PYTHONUTF8"] == "1"
    # Building the child environment must not mutate the parent's settings.
    import os
    assert os.environ["OKS_ROOT"] == "personal-kb"
