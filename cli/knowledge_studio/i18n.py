"""Minimal bilingual (zh/en) strings for OKS CLI.

Language resolution:  $OKS_LANG  →  system locale  →  "zh"
"""

from __future__ import annotations

import locale
import os


_TEXTS: dict[str, dict[str, str]] = {
    "init_ready": {
        "zh": "OKS 已准备完成。",
        "en": "OKS is ready.",
    },
    "init_first_prompt": {
        "zh": "现在可对 Agent 说：",
        "en": "Now you can say to your Agent:",
    },
    "init_local_capabilities": {
        "zh": "本地能力：",
        "en": "Local capabilities:",
    },
    "init_remote_capabilities": {
        "zh": "远程能力：",
        "en": "Remote capabilities:",
    },
    "status_configured": {
        "zh": "已配置",
        "en": "Configured",
    },
    "status_not_configured": {
        "zh": "未配置",
        "en": "Not configured",
    },
    "status_not_installed": {
        "zh": "未安装",
        "en": "Not installed",
    },
    "status_runtime_only": {
        "zh": "需要 Agent 运行时验证",
        "en": "Requires Agent runtime verification",
    },
    "status_blocked": {
        "zh": "当前不可用",
        "en": "Currently unavailable",
    },
    "status_experimental": {
        "zh": "实验性",
        "en": "Experimental",
    },
    "firecrawl_setup_hint": {
        "zh": "设置环境变量 FIRECRAWL_API_KEY=<你的密钥>",
        "en": "Set FIRECRAWL_API_KEY=<your key> as environment variable",
    },
    "agentkey_setup_hint": {
        "zh": "在 Claude Code 中配置 AgentKey MCP 服务器。本地无法验证 AgentKey 可用性。",
        "en": "Configure AgentKey MCP server in Claude Code. Local verification not available.",
    },
    "mediacrawler_setup_hint": {
        "zh": "需自行安装 MediaCrawler。不捆绑进 OKS。",
        "en": "Install MediaCrawler separately. Not bundled with OKS.",
    },
    "init_remote_note": {
        "zh": "Firecrawl 用于普通网页；AgentKey 用于受限平台。两者独立配置，都不影响本地文件摄入。",
        "en": "Firecrawl for public web; AgentKey for restricted platforms. Both are optional — local file ingest always works.",
    },
    "init_no_remote": {
        "zh": "当前仅本地文本能力可用。配置 Firecrawl 后可摄入网页。AgentKey 用于受限平台（独立配置）。",
        "en": "Only local text capability available. Configure Firecrawl for web content. AgentKey for restricted platforms (separate config).",
    },
    "init_prompt_local_only": {
        "zh": "把这份文档收录进 OKS。",
        "en": "Ingest this document into OKS.",
    },
    "init_prompt_with_pdf": {
        "zh": "把这个 PDF 收录进 OKS，并生成待审核知识。",
        "en": "Ingest this PDF into OKS and generate a reviewable candidate.",
    },
    "init_prompt_with_web": {
        "zh": "把这个网页收录进 OKS。",
        "en": "Ingest this web page into OKS.",
    },
    "init_step_install": {
        "zh": "  oks capability install watch --yes     # 安装视频/音频提取能力",
        "en": "  oks capability install watch --yes     # Install video/audio extraction",
    },
    "init_step_ingest": {
        "zh": '  oks ingest prepare "<URL或文件>"   # 准备第一条资料',
        "en": '  oks ingest prepare "<URL or file>"  # Prepare your first source',
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
        "zh": "oks ingest 在纯终端中需 Agent 接管。请使用支持的 Agent Host (Claude Code / Codex) 并运行 /ingest 技能。",
        "en": "oks ingest in a pure terminal requires an Agent. Use a supported Agent Host (Claude Code / Codex) and run the /ingest skill.",
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
    "init_always_available": {
        "zh": "始终可用：",
        "en": "Always available:",
    },
    "cap_markdown_text": {
        "zh": "收录 Markdown / 文本",
        "en": "Ingest Markdown / text",
    },
    "cap_agent_multimodal": {
        "zh": "使用 Agent 理解图片和网页（需要支持多模态的模型）",
        "en": "Agent multimodal understanding — images and web pages (requires multimodal model)",
    },
    "init_can_do_now": {
        "zh": "现在可以直接：",
        "en": "Available now:",
    },
    "init_can_enable": {
        "zh": "按需可以启用：",
        "en": "Available on demand:",
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
