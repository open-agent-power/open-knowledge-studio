"""Minimal bilingual (zh/en) strings for OKS CLI.

Language resolution:  $OKS_LANG  →  system locale  →  "zh"
"""

from __future__ import annotations

import locale
import os


_TEXTS: dict[str, dict[str, str]] = {
    "init_ready": {
        "zh": "知识库就绪。下一步：",
        "en": "Instance ready. Next steps:",
    },
    "init_step_install": {
        "zh": "  oks capability install watch --yes     # 安装视频/音频提取能力",
        "en": "  oks capability install watch --yes     # Install video/audio extraction",
    },
    "init_step_ingest": {
        "zh": '  oks ingest "<URL或文件>" --mode quick   # 采集第一条内容',
        "en": '  oks ingest "<URL or file>" --mode quick  # Ingest your first source',
    },
    "init_step_status": {
        "zh": "  oks status                              # 查看知识库状态",
        "en": "  oks status                              # Check knowledge base status",
    },
    "init_capabilities": {
        "zh": "可选能力（按需安装，不装不下载）：",
        "en": "Available capabilities (install on demand):",
    },
    "connector_missing": {
        "zh": "Connector 模块未找到",
        "en": "Connector module not found",
    },
    "connector_missing_hint": {
        "zh": "`scripts/raw_bundle_adapter.py` 模块导入失败。请确认 OKS 安装包含 scripts/ 目录。",
        "en": "The `scripts/raw_bundle_adapter.py` module could not be imported. Ensure the OKS installation includes the scripts/ directory.",
    },
    "action_required": {
        "zh": "需要操作",
        "en": "Action required",
    },
    "ingest_failed": {
        "zh": "提取失败",
        "en": "Ingest failed",
    },
    "capability_missing": {
        "zh": "缺少 {name} 能力",
        "en": "Missing {name} capability",
    },
    "capability_missing_hint": {
        "zh": "此来源需要 {name} 提取器。运行：\n  oks capability install {name} --yes\n\n或设置 {env} 环境变量指向已安装对应依赖的 Python 解释器。",
        "en": "This source requires the {name} extractor. Run:\n  oks capability install {name} --yes\n\nOr set the {env} environment variable to a Python interpreter with the required dependencies.",
    },
    "install_hint": {
        "zh": "安装提示",
        "en": "Install hint",
    },
    "ingest_done_hint": {
        "zh": "Raw Bundle 已生成。Agent 审核后可通过 `oks drafts promote` 晋升为 Wiki。",
        "en": "Raw Bundle generated. After Agent review, use `oks drafts promote` to promote to Wiki.",
    },
    "capability_installing": {
        "zh": "正在安装 {name} 能力...",
        "en": "Installing {name} capability...",
    },
    "capability_installed": {
        "zh": "{name} 安装完成。",
        "en": "{name} installed successfully.",
    },
    "capability_failed": {
        "zh": "{name} 安装失败（exit {code}）",
        "en": "{name} installation failed (exit {code})",
    },
    "capability_verify_failed": {
        "zh": "{name} 安装后仍不可用：目标 Python 无法导入所需模块。",
        "en": "{name} remains unavailable after installation: the target Python cannot import the required module.",
    },
    "capability_already": {
        "zh": "{name} 已安装，无需重复操作。",
        "en": "{name} is already installed.",
    },
    "feishu_private": {
        "zh": "飞书是私有部署扩展。\n\n安装你所在组织批准的 lark-cli。\nOKS 不捆绑任何租户密钥、权限或机器人身份。",
        "en": "Feishu is a private deployment extension.\n\nInstall your organization's approved lark-cli.\nNo tenant credentials, scopes, or bot identity are bundled into OKS.",
    },
    "user_managed_capability": {
        "zh": "用户自管理能力",
        "en": "User-managed capability",
    },
    "optional_install": {
        "zh": "可选能力安装",
        "en": "Optional capability install",
    },
    "capability_install_prompt": {
        "zh": "将安装 {n} 个依赖包（可能较大）。执行：\n{cmd}\n或重新运行并加 --yes 执行安装。",
        "en": "Will install {n} dependency packages (may be large). Run:\n{cmd}\nOr re-run with --yes to execute.",
    },
    "pipx_missing": {
        "zh": "pipx 未安装",
        "en": "pipx is not installed",
    },
}

# Simple lang detection
def _detect_lang() -> str:
    configured = os.environ.get("OKS_LANG", "").lower()
    if configured in ("zh", "en"):
        return configured
    try:
        sys_locale = locale.getlocale()[0] or ""
    except (ValueError, TypeError):
        sys_locale = ""
    if sys_locale.startswith("zh"):
        return "zh"
    return "en"


_LANG = _detect_lang()


def t(key: str, **kwargs: object) -> str:
    """Return the localized string for *key*.  Falls back to the key itself."""
    entry = _TEXTS.get(key, {})
    text = entry.get(_LANG) or entry.get("en") or key
    if kwargs:
        text = text.format(**{k: str(v) for k, v in kwargs.items()})
    return text
