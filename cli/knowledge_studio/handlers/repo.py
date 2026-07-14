"""Repo handler — scan code repository structure and extract key patterns.

Pipeline: Directory → structure scan → README extraction → key files summary → Markdown
No external dependencies — pure Python filesystem operations.

Output preserves: directory tree, README content, key configuration files,
and detected tech stack.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from knowledge_studio.handlers.base import BaseHandler, HandlerResult, HandlerError


class RepoHandler(BaseHandler):
    name = "repo"
    modalities = ["directory"]
    description = "Code repo: structure scan + README + key patterns"

    def detect(self, input_path: str) -> bool:
        if input_path.startswith(("http://", "https://")):
            return False
        p = Path(input_path)
        return p.is_dir() and (
            (p / ".git").exists()
            or (p / "package.json").exists()
            or (p / "pyproject.toml").exists()
            or (p / "Cargo.toml").exists()
            or (p / "go.mod").exists()
        )

    def process(self, input_path: str, config: dict[str, Any] | None = None) -> HandlerResult:
        repo_path = Path(input_path)
        if not repo_path.is_dir():
            raise HandlerError(self.name, f"Not a directory: {input_path}")

        cfg = config or {}
        max_depth = cfg.get("max_depth", 3)
        max_files = cfg.get("max_files", 100)

        tree = self._scan_tree(repo_path, max_depth, max_files)
        readme = self._extract_readme(repo_path)
        key_files = self._extract_key_files(repo_path)
        tech_stack = self._detect_tech_stack(repo_path)

        sections = [f"# Repository: {repo_path.name}\n"]

        if tech_stack:
            sections.append("## Tech Stack\n")
            for tech in tech_stack:
                sections.append(f"- {tech}")
            sections.append("")

        if readme:
            sections.append("## README\n")
            sections.append(readme[:5000])
            sections.append("")

        sections.append("## Directory Structure\n")
        sections.append(f"```\n{tree}\n```")

        if key_files:
            sections.append("\n## Key Files\n")
            for name, content in key_files:
                sections.append(f"### {name}\n")
                sections.append(f"```\n{content[:2000]}\n```\n")

        return HandlerResult(
            markdown="\n".join(sections),
            title=repo_path.name,
            source=str(repo_path),
            modality="repo",
            handler_name=self.name,
            metadata={
                "tech_stack": tech_stack,
                "has_readme": bool(readme),
                "max_depth": max_depth,
            },
        )

    def _scan_tree(self, path: Path, max_depth: int, max_files: int) -> str:
        lines = []
        count = 0

        def walk(p: Path, prefix: str, depth: int):
            nonlocal count
            if depth > max_depth or count > max_files:
                return
            for item in sorted(p.iterdir()):
                if item.name.startswith("."):
                    if item.name not in (".gitignore", ".env.example"):
                        continue
                if item.is_dir():
                    lines.append(f"{prefix}{item.name}/")
                    count += 1
                    walk(item, prefix + "  ", depth + 1)
                else:
                    lines.append(f"{prefix}{item.name}")
                    count += 1

        walk(path, "", 0)
        return "\n".join(lines[:max_files])

    def _extract_readme(self, repo_path: Path) -> str:
        for name in ["README.md", "README.rst", "README.txt", "README", "readme.md"]:
            readme = repo_path / name
            if readme.exists():
                return readme.read_text(encoding="utf-8", errors="replace")
        return ""

    def _extract_key_files(self, repo_path: Path) -> list[tuple[str, str]]:
        key_names = [
            "package.json", "pyproject.toml", "Cargo.toml", "go.mod",
            "docker-compose.yml", "Dockerfile", "Makefile",
            ".env.example", "CLAUDE.md", "CONSTITUTION.md",
        ]
        results = []
        for name in key_names:
            f = repo_path / name
            if f.exists():
                results.append((name, f.read_text(encoding="utf-8", errors="replace")))
        return results

    def _detect_tech_stack(self, repo_path: Path) -> list[str]:
        stack = []
        if (repo_path / "package.json").exists():
            stack.append("Node.js")
        if (repo_path / "pyproject.toml").exists() or (repo_path / "setup.py").exists():
            stack.append("Python")
        if (repo_path / "Cargo.toml").exists():
            stack.append("Rust")
        if (repo_path / "go.mod").exists():
            stack.append("Go")
        if (repo_path / "pom.xml").exists():
            stack.append("Java/Maven")
        if (repo_path / "build.gradle").exists() or (repo_path / "build.gradle.kts").exists():
            stack.append("Java/Gradle")
        if (repo_path / "Gemfile").exists():
            stack.append("Ruby")
        if (repo_path / "docker-compose.yml").exists() or (repo_path / "Dockerfile").exists():
            stack.append("Docker")
        return stack
