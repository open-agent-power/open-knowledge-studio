from pathlib import Path
from types import SimpleNamespace
import json
import tomllib

from typer.testing import CliRunner

from knowledge_studio import cli


runner = CliRunner()


def test_handler_install_hints_point_at_real_channels():
    """handlers.json ships to every user; a hint for a nonexistent package is a dead end.

    The old hints said `pip install 'oks-connector[watch]'`, but no such
    distribution exists on PyPI — agents following the routing table failed
    every install attempt.
    """
    handlers_path = Path(__file__).parents[2] / "assets" / "settings" / "handlers.json"
    handlers = json.loads(handlers_path.read_text(encoding="utf-8"))

    text = handlers_path.read_text(encoding="utf-8")
    assert "oks-connector[" not in text, "install_hint references a package that is not on PyPI"

    for handler in handlers:
        if handler.get("level") != 1:
            continue
        hint = handler["install_hint"]
        assert hint.startswith("oks capability install "), (
            f"{handler['name']}: L1 capabilities install via `oks capability install`, got {hint!r}"
        )
        capability = hint.split()[3]
        assert capability in cli._CAPABILITIES, (
            f"{handler['name']}: hint names unknown capability {capability!r}"
        )


def test_install_instructions_only_point_at_official_sources():
    """Install entry points must never route users to a non-org repository.

    This slipped in twice: a direct-URL dependency that PyPI rejects, and 17
    places (README, wheel metadata, runtime hints) pointing at a personal repo
    that lacked our security fixes and tracked a mutable @main ref.
    """
    repo_root = Path(__file__).parents[2]
    targets = [
        repo_root / "README.md",
        repo_root / "CLAUDE.md",
        repo_root / "AGENTS.md",
        repo_root / "cli" / "README.md",
        repo_root / "cli" / "pyproject.toml",
        repo_root / "cli" / "knowledge_studio" / "cli.py",
        *(repo_root / "docs").glob("*.md"),
    ]
    keywords = ("pipx install", "pipx upgrade", "pip install", "Homepage", "Repository")
    offenders: list[str] = []
    for path in targets:
        if not path.is_file() or "archive" in path.parts:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "github.com/" not in line or "github.com/open-agent-power/" in line:
                continue
            if any(word in line for word in keywords):
                offenders.append(f"{path.relative_to(repo_root)}:{lineno}: {line.strip()}")

    assert not offenders, "install entry points must stay on official sources:\n" + "\n".join(offenders)


def test_connect_skill_matches_install_and_review_boundaries():
    """The canonical Agent install contract must not drift from shipped behavior."""
    repo_root = Path(__file__).parents[2]
    text = (repo_root / "SKILL.md").read_text(encoding="utf-8")

    assert ".claude/skills/" in text
    assert ".agents/skills/" in text
    assert ".codex/" in text
    assert "including Codex discovery" in text
    assert "--editor <claude|qoder|codex|both>" in text

    assert "9 skills" not in text
    assert "materializes .claude/skills, .codex, .agents" not in text
    assert "oks wiki create" not in text
    assert "Do not immediately run `oks skills-install`" in text
    assert "`--force` only authorizes scaffolding" in text


def test_ingest_missing_connector_shows_explicit_action(monkeypatch):
    monkeypatch.setattr(cli, "_connector_command", lambda: None)

    result = runner.invoke(cli.app, ["ingest", "https://example.com/video"])

    assert result.exit_code == 2
    assert "Connector" in result.output  # appears in both zh/en
    assert result.exit_code == 2


def test_ingest_recommends_capability_install(monkeypatch):
    """Pre-flight check suggests capability install when extractor is missing."""
    monkeypatch.setattr(cli, "_connector_command", lambda: "built-in")
    monkeypatch.setattr(cli, "_capability_already_installed", lambda _name: False)

    result = runner.invoke(cli.app, ["ingest", "paper.pdf"])

    assert result.exit_code == 2
    assert "capability install" in result.output  # appears in both zh/en


def test_connector_command_reports_builtin_when_module_available(monkeypatch):
    """After repo merge, _connector_command returns 'built-in' when the module is importable."""
    monkeypatch.setattr(cli, "_connector_available", True)

    assert cli._connector_command() == "built-in"


def test_ingest_forwards_mode_timeout_and_progress(monkeypatch):
    received = {}

    def fake_run_ingest(parsed):
        received["mode"] = parsed.mode
        received["timeout"] = getattr(parsed, "timeout_seconds", None)
        received["progress"] = getattr(parsed, "progress", False)
        received["source"] = parsed.source
        return 0

    monkeypatch.setattr(cli, "_connector_command", lambda: "built-in")
    monkeypatch.setattr(cli, "_capability_already_installed", lambda _name: True)
    monkeypatch.setattr(cli, "_connector_run_ingest", fake_run_ingest)

    result = runner.invoke(
        cli.app,
        ["ingest", "https://example.com/video", "--mode", "forensic", "--timeout-seconds", "30"],
    )

    assert result.exit_code == 0, result.output
    assert received["mode"] == "forensic"
    assert received["timeout"] == 30.0
    assert received["progress"] is True


def test_ingest_forwards_formula_secondary_for_pdf(monkeypatch):
    received = {}

    def fake_run_ingest(parsed):
        received["formula_secondary"] = parsed.formula_secondary
        received["formula_max_regions"] = parsed.formula_max_regions
        return 0

    monkeypatch.setattr(cli, "_connector_command", lambda: "built-in")
    monkeypatch.setattr(cli, "_capability_already_installed", lambda _name: True)
    monkeypatch.setattr(cli, "_connector_run_ingest", fake_run_ingest)

    result = runner.invoke(
        cli.app,
        ["ingest", "paper.pdf", "--formula-secondary", "--formula-max-regions", "7"],
    )

    assert result.exit_code == 0, result.output
    assert received == {"formula_secondary": True, "formula_max_regions": 7}


def test_capability_install_is_explicit_by_default():
    result = runner.invoke(cli.app, ["capability", "install", "watch"])

    assert result.exit_code == 0, result.output
    assert "pip" in result.output  # pip install command shown (may wrap in panel)
    assert "--yes" in result.output


def test_formula_capability_pins_mineru_compatible_tokenizers():
    """Keep the optional formula install compatible with MinerU's worker."""
    assert "tokenizers==0.22.1" in cli._CAPABILITIES["formula"]["deps"]
def test_no_direct_url_dependencies_block_pypi_upload():
    """PyPI rejects any Requires-Dist with a direct URL — that breaks releases.

    Runtime-only installs (git checkouts, private forks) belong in
    cli._CAPABILITIES, which is passed to `pip install` and never becomes
    package metadata.
    """
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = config["project"]

    declared = list(project.get("dependencies", []))
    for extra_deps in project.get("optional-dependencies", {}).values():
        declared.extend(extra_deps)

    offenders = [dep for dep in declared if "@ git+" in dep or "@ http" in dep]
    assert not offenders, f"direct URL dependencies make the release unpublishable: {offenders}"


def test_connector_packages_are_declared_for_wheel_builds():
    """One distribution ships extraction/search, retaining the old command namespace."""
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    packages = config["tool"]["setuptools"]["packages"]

    assert "oks_connector" in packages
    assert "oks_connector.extractors" in packages
    deps = config["project"]["dependencies"]
    assert not any("oks-connector" in d for d in deps)
    assert config["project"]["scripts"]["oks-connector"] == "oks_connector.raw_bundle_adapter:main"


def test_wheel_never_installs_generic_top_level_names():
    """Generic names in site-packages would collide with unrelated user packages."""
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    setuptools_config = config["tool"]["setuptools"]

    installed_tops = {name.split(".")[0] for name in setuptools_config["packages"]}
    installed_tops |= {
        name.split(".")[0] for name in setuptools_config.get("py-modules", [])
    }
    assert installed_tops == {"knowledge_studio", "oks_connector"}
    for reserved in ("i18n", "constants", "digest", "network", "route", "validator"):
        assert reserved not in installed_tops
def _command_children() -> dict[str, set[str]]:
    """Map each command path to its direct children, from the Typer app itself.

    Duck-typed on ``.commands`` rather than ``isinstance(x, click.Group)``:
    ``click`` is not guaranteed to be importable as a top-level module
    alongside Typer, and CI proved it is not.
    """
    import typer

    children: dict[str, set[str]] = {}

    def index(command, prefix: tuple[str, ...] = ()) -> None:
        kids = getattr(command, "commands", None) or {}
        children[" ".join(prefix)] = set(kids)
        for name, sub in kids.items():
            index(sub, prefix + (name,))

    index(typer.main.get_command(cli.app))
    return children


def _names_a_missing_command(cited: str, children: dict[str, set[str]]) -> bool:
    """True when *cited* walks into a subcommand the CLI does not define."""
    import re

    plain_word = re.compile(r"[a-z][a-z0-9-]*\Z")
    path: list[str] = []
    for word in cited.split():
        if not plain_word.fullmatch(word):
            break  # a flag, placeholder or value — not a subcommand
        key = " ".join(path)
        if not children.get(key):
            break  # reached a leaf; everything after is an argument
        if word not in children[key]:
            return True
        path.append(word)
    return not path


def test_documented_commands_all_exist():
    """Citing a missing command sends the reader or the Agent down a dead end.

    Both halves failed silently before: the ingest skill named six commands that
    never existed, and README's Quick Start told every new user to run
    `oks skills-install`, which was never a command — hidden inside a fenced
    bash block where an inline-backtick scan could not see it.
    """
    import re

    children = _command_children()
    repo = Path(__file__).parents[2]
    targets = [repo / "README.md", repo / "cli" / "README.md"]
    targets += sorted((repo / "assets" / "skills").rglob("SKILL.md"))
    # research/ and acceptance/ discuss designs and past runs on purpose,
    # including commands that do not exist yet.
    targets += [
        doc for doc in sorted((repo / "docs").rglob("*.md"))
        if not {"research", "acceptance", "archive"} & set(doc.parts)
    ]

    unknown: list[str] = []
    for doc in targets:
        text = doc.read_text(encoding="utf-8")
        cited = set(re.findall(r"`oks ([a-z][^`\n]*)`", text))
        cited |= set(re.findall(r"^\s*oks ([a-z][^\n|#]*)", text, re.MULTILINE))
        for citation in cited:
            citation = citation.strip().strip("`\"'")
            if citation and _names_a_missing_command(citation, children):
                unknown.append(f"{doc.relative_to(repo)}: oks {citation[:60]}")

    assert not unknown, "documented commands the CLI does not have:\n" + "\n".join(
        sorted(unknown)
    )


def test_bundled_schema_examples_validate_against_their_schema():
    """`oks schema show` teaches Agents the shape — it must be a valid shape."""
    from jsonschema import Draft202012Validator

    from knowledge_studio import schema_examples
    from knowledge_studio.raw_commit import _build_registry, _load_schema

    schema_files = {
        "source-envelope": "source-envelope-v0.1.schema.json",
        "evidence-manifest": "evidence-manifest-v0.1.schema.json",
        "evidence-fragment": "evidence-fragment-v0.1.schema.json",
        "locator": "locator-v0.1.schema.json",
        "raw-bundle": "raw-bundle-v0.2.schema.json",
    }
    assert set(schema_examples.list_schema_names()) == set(schema_files), (
        "every bundled example needs a schema to check it against"
    )

    registry = _build_registry()
    kwargs = {"registry": registry} if registry is not None else {}
    problems: list[str] = []
    for name, schema_file in schema_files.items():
        validator = Draft202012Validator(_load_schema(schema_file), **kwargs)
        for error in validator.iter_errors(schema_examples.get_example(name)):
            problems.append(f"{name}{error.json_path[1:]}: {error.message}")

    assert not problems, "invalid protocol examples:\n" + "\n".join(problems)
