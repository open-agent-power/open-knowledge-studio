"""Locate the shared instance assets in a checkout or installed package."""
from pathlib import Path


def asset_source() -> Path | None:
    """Prefer checkout assets over generated copies; installed packages use _assets."""
    package = Path(__file__).resolve().parent
    checkout = package.parent.parent
    if (
        package == checkout / "cli" / "knowledge_studio"
        and (checkout / ".git").exists()
        and (checkout / "assets").is_dir()
    ):
        return checkout / "assets"
    packaged = package / "_assets"
    if packaged.is_dir() and any(packaged.iterdir()):
        return packaged
    return None


def asset_root() -> Path:
    """Return required assets or report an incomplete installation."""
    source = asset_source()
    if source is None:
        raise FileNotFoundError("Bundled OKS assets are unavailable; reinstall open-knowledge-studio")
    return source
