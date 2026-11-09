"""Packaged loopback Mail workspace; all persistence uses Mail Core."""
import html
import json
import hashlib
import re
from datetime import date, datetime, time, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer
from threading import RLock
from time import monotonic
from urllib.parse import parse_qs, urlsplit

from knowledge_studio import identity, mail, mail_media, store
from knowledge_studio import mail_knowledge, mail_timeline, mail_observation, team_sync
from knowledge_studio.mail_activity import activity_data, delivery_records
from knowledge_studio.mail_setup import asset_root, validate_root, agent_id

ROOT = asset_root() / "mail-web"
FILES = {"/": ("index.html", "text/html"), "/style.css": ("style.css", "text/css"), "/app.js": ("app.js", "text/javascript"), "/favicon.svg": ("favicon.svg", "image/svg+xml")}
FILES["/layout.css"] = ("layout.css", "text/css")
FILES["/wiki-page.css"] = ("wiki-page.css", "text/css")
for _asset in ("force-layout.js", "graph-labels.js", "tag-graph.js", "mail-view-model.js", "knowledge-browser.js", "knowledge-navigation.js"):
    FILES["/" + _asset] = (_asset, "text/javascript")
for _asset in ("tag-graph.css", "knowledge-browser.css", "knowledge-reading.css", "knowledge-workspace.css"):
    FILES["/" + _asset] = (_asset, "text/css")
FILES["/debug"] = ("debug.html", "text/html")
FILES["/debug.js"] = ("debug.js", "text/javascript")
FILES["/debug.css"] = ("debug.css", "text/css")
FILES["/tasks"] = ("tasks.html", "text/html")
FILES["/tasks.js"] = ("tasks.js", "text/javascript")
FILES["/tasks.css"] = ("tasks.css", "text/css")
for _page in ('start', 'review', 'versions'):
    FILES['/' + _page] = (_page + '.html', 'text/html')
    if _page == 'review':
        FILES['/' + _page + '.js'] = (_page + '.js', 'text/javascript')
        FILES['/' + _page + '.css'] = (_page + '.css', 'text/css')
FILES['/workspace-ui.js'] = ('workspace-ui.js', 'text/javascript')
FILES['/workspace-shell.js'] = ('workspace-shell.js', 'text/javascript')
FILES['/workspace-shell.css'] = ('workspace-shell.css', 'text/css')
FILES['/knowledge-heatmap.js'] = ('knowledge-heatmap.js', 'text/javascript')
for _asset in ('studio.html', 'studio.js', 'studio-model.js', 'studio.css'):
    FILES['/' + _asset] = (_asset, 'text/html' if _asset.endswith('.html') else 'text/css' if _asset.endswith('.css') else 'text/javascript')
for _module in ('api', 'dom', 'state', 'discussion', 'graph', 'goals', 'learning', 'settings', 'formulas', 'knowledge', 'knowledge-model', 'workflow', 'evaluation', 'evaluation-charts', 'files', 'evaluation-review', 'call-trace', 'timeline', 'mindmap', 'onboarding', 'libraries'):
    FILES[f'/studio/{_module}.js'] = (f'studio/{_module}.js', 'text/javascript')
for _module in ('graph-pixi', 'graph-camera', 'graph-controls', 'graph-layout', 'graph-renderer'):
    FILES[f'/studio/{_module}.js'] = (f'studio/{_module}.js', 'text/javascript')
for _asset in ('pixi.min.js', 'layout.worker.js', 'edge-mesh.js', 'position-smoothing.js'):
    FILES[f'/vendor/graph-engine/{_asset}'] = (f'vendor/graph-engine/{_asset}', 'text/javascript')
for _style in ('graph', 'goals', 'learning', 'evaluation'):
    FILES[f'/studio/{_style}.css'] = (f'studio/{_style}.css', 'text/css')
FILES['/studio-theme.css'] = ('studio-theme.css', 'text/css')
FILES['/studio-redirect.js'] = ('studio-redirect.js', 'text/javascript')
for _asset in ('katex.min.js', 'katex.min.css'):
    FILES['/vendor/katex/' + _asset] = ('vendor/katex/' + _asset, 'text/javascript' if _asset.endswith('.js') else 'text/css')
for _font in (ROOT / 'vendor/katex/fonts').glob('*.woff2'):
    FILES['/vendor/katex/fonts/' + _font.name] = ('vendor/katex/fonts/' + _font.name, 'font/woff2')

UI_AGENT = "human"

#: Self-contained page shown for "在完整 Wiki 中打开" (new tab) and embedded in
#: the detail drawer. No scripts at all, so the strict CSP below is enough.
WIKI_PAGE_CSP = (
    "default-src 'none'; style-src 'self'; img-src 'self' data:; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
)


def connection_guide(kb_root: Path) -> str:
    """Text the page copies so the user can hand onboarding to a host Agent.

    Mirrors ``assets/skills/oks-mail/references/connection.md``. The page only
    copies it (移交而非代办): it never installs a Skill, edits host config, or
    claims the Agent is connected.
    """
    reference = asset_root() / "skills" / "oks-mail" / "references" / "connection.md"
    try:
        body = reference.read_text(encoding="utf-8").strip()
    except OSError:
        body = ""
    header = (
        "OKS Mail 接入说明\n"
        f"知识库：{kb_root}\n"
        "把上面的知识库路径交给宿主对话区里的 Agent，让它在对话区完成接入；"
        "本面板只复制说明，不安装 Skill、不改宿主配置、不宣称已连接。\n"
    )
    return header + ("\n---\n\n" + body if body else "")


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def visible_message(root, message_id):
    return next(
        (item for item in mail.iter_messages(root, UI_AGENT)
         if str(item["meta"].get("message_id", "")) == str(message_id)),
        None,
    )


def reply_recipients(root, thread_id):
    messages = mail.thread_messages(root, thread_id, UI_AGENT)
    if not messages:
        raise ValueError("thread not found")
    latest = messages[-1]
    recipients = sorted(
        {
            value for value in ({str(latest["meta"].get("from", ""))} | set(latest["meta"].get("to", [])))
            if value not in {"@human", "@all", "human", "all", ""}
        }
    )
    if not recipients:
        raise ValueError("thread has no reply recipient")
    return recipients, latest


def _mail_verification(root, viewer=None):
    """Derive Mail verification only from an observed lifecycle, never a heartbeat.

    Evidence is restricted to the viewer when supplied. Acknowledgement or an
    explicit reply proves an observed lifecycle, never online availability or
    task acceptance. Internal callers may omit the viewer for KB-wide evidence.
    """
    messages = list(mail.iter_messages(root, viewer))
    by_id = {str(row["meta"]["message_id"]): row for row in messages}
    deliveries = delivery_records(root, messages)
    verified = {}
    for row in messages:
        meta = row["meta"]
        message_id = str(meta.get("message_id", ""))
        sender = mail._normalise_agent(str(meta.get("from", "")))
        # Require the actual visible parent; a dangling/private/cross-Thread
        # reply_to string cannot establish an observed communication lifecycle.
        if mail.visible_reply_parent(row, by_id) and sender not in {"@human", "@unknown"}:
            verified.setdefault(sender, {"message_id": message_id, "thread_id": meta.get("thread_id") or message_id, "evidence": "reply"})
        for recipient in meta.get("to", []):
            agent = mail._normalise_agent(str(recipient))
            if agent in {"@human", "@all", "@unknown"}:
                continue
            recipient_delivery = next((item for item in deliveries.get(message_id, []) if item.get("agent_id") == agent), None)
            sessions = recipient_delivery.get("sessions", []) if recipient_delivery else []
            ack = next((session for session in sessions if session.get("acknowledged_at")), None)
            if ack:
                verified[agent] = {"message_id": message_id, "thread_id": meta.get("thread_id") or message_id, "session_id": ack.get("session_id"), "evidence": "acknowledged"}
    return verified


def _verification_state(agent, verification, traced):
    """三态：有回执证据 → 已验证；只有消息痕迹 → 已观察到；只剩档案 → 未验证。

    面板不显示在线状态（文件系统推不出来）。这三态说的都是「本机能查到
    什么证据」，不是对方此刻在不在。缺了第三态，一份没跟任何消息发生过
    关系的档案会被说成「已观察到」——那是在无证据地承认对方参与过。
    """
    if agent in verification:
        return "verified"
    return "observed" if agent in traced else "unverified"


def connection_status(root, viewer=None):
    """Return observed provenance plus explicit Mail lifecycle verification."""
    sessions = []
    agents = {}
    machines = set()
    verification = _mail_verification(root, viewer)
    visible_rows = list(mail.iter_messages(root, viewer))
    visible_sessions = set()
    visible_times = {}
    visible_machines = {}
    if viewer is not None:
        for row in visible_rows:
            meta = row["meta"]
            session_id = str(meta.get("origin_session_id") or "")
            if session_id:
                pair = (mail._normalise_agent(str(meta.get("from") or "")), session_id)
                visible_sessions.add(pair)
                visible_times[pair] = max(visible_times.get(pair, ""), str(meta.get("timestamp") or ""))
                machine = str(meta.get("origin_machine_id") or "")
                if machine and machine != "unknown":
                    visible_machines[pair] = machine
        for deliveries in delivery_records(root, visible_rows).values():
            for delivery in deliveries:
                for receipt in delivery["sessions"]:
                    session_id = str(receipt.get("session_id") or "")
                    pair = (delivery["agent_id"], session_id)
                    visible_sessions.add(pair)
                    visible_times[pair] = max(
                        visible_times.get(pair, ""),
                        *(str(receipt.get(key) or "") for key in ("injected_at", "delivered_at", "acknowledged_at")),
                    )
                    machine = str(receipt.get("machine_id") or "")
                    if machine and machine != "unknown":
                        visible_machines[pair] = machine
                        machines.add(machine)
    # 「有投递痕迹」：这个身份在某条消息里发过言、或被人投递过。
    # 它与「有回执证据」是两件事——痕迹只说明双方通过消息接触过，
    # 不说明对方确认读到了。所以得先把全库的消息扫完，再统一判状态。
    traced: set[str] = set()

    # 消息先扫：它同时提供「这个身份存在过」和「有过投递痕迹」两份信息，
    # 而 Session 档案只提供前者。顺序反过来就算不出未验证。
    # Verification, provenance and Session summaries use the same viewer scope.
    # A private conversation must not leak through counts or the member roster.
    for message in visible_rows:
        sender = mail._normalise_agent(str(message["meta"].get("from", "")))
        if sender not in {"@human", "@unknown"}:
            traced.add(sender)
            summary = agents.setdefault(sender, {
                "agent_id": sender,
                "session_count": 0,
                "machine_ids": set(),
                "last_observed_at": "",
            })
            timestamp = str(message["meta"].get("timestamp", "") or "")
            if timestamp > summary["last_observed_at"]:
                summary["last_observed_at"] = timestamp
        for recipient in message["meta"].get("to", []) or []:
            peer = mail._normalise_agent(str(recipient))
            if peer not in {"@human", "@all", "@unknown"}:
                traced.add(peer)
                if viewer is not None:
                    agents.setdefault(peer, {
                        "agent_id": peer, "session_count": 0,
                        "machine_ids": set(), "last_observed_at": "",
                    })
        machine = str(message["meta"].get("origin_machine_id", "") or "")
        if machine and machine != "unknown":
            machines.add(machine)

    if viewer is not None:
        # Session summaries may be backed by a registry row, but their machine
        # identity must come from the visible snapshot rather than that row.
        for (agent, _session_id), machine in visible_machines.items():
            summary = agents.get(agent)
            if summary:
                summary["machine_ids"].add(machine)

    directory = mail.sessions_dir(root)
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(record, dict):
                continue
            agent = mail._normalise_agent(str(record.get("agent_id", "@unknown")))
            session_id = str(record.get("session_id", path.stem))
            if viewer is not None and (agent, session_id) not in visible_sessions:
                continue
            machine = str(record.get("machine_id", "unknown") or "unknown")
            last_seen = str(record.get("last_seen_at", "") or "")
            if viewer is not None:
                last_seen = visible_times.get((agent, session_id), "")
                machine = visible_machines.get((agent, session_id), "unknown")
            item = {
                "session_id": session_id,
                "agent_id": agent,
                "machine_id": machine,
                "verification_status": _verification_state(agent, verification, traced),
                "last_observed_at": last_seen,
                "scope": "" if viewer is not None else str(record.get("scope", "") or ""),
            }
            if agent in verification:
                item["verification_evidence"] = verification[agent]
            sessions.append(item)
            # A Session with no machine on record contributes no machine. The
            # provenance loop below already filters it; counting the literal
            # "unknown" here inflated machine_count with a non-machine.
            if machine != "unknown":
                machines.add(machine)
            if agent != "@human":
                summary = agents.setdefault(agent, {
                    "agent_id": agent,
                    "session_count": 0,
                    "machine_ids": set(),
                    "last_observed_at": "",
                })
                summary["session_count"] += 1
                summary["machine_ids"].add(machine)
                if last_seen > summary["last_observed_at"]:
                    summary["last_observed_at"] = last_seen

    serialised_agents = []
    for summary in sorted(agents.values(), key=lambda item: item["agent_id"]):
        summary = dict(summary)
        summary["machine_ids"] = sorted(summary["machine_ids"])
        summary["verification_status"] = _verification_state(summary["agent_id"], verification, traced)
        if summary["agent_id"] in verification:
            summary["verification_evidence"] = verification[summary["agent_id"]]
        serialised_agents.append(summary)
    return {
        "schema": "mail.connection-status.v1",
        "knowledge_base": str(root),
        "current_machine_id": identity.normalise_machine_id(),
        "sessions": sessions,
        "agents": serialised_agents,
        "machines": sorted(machines),
        "machine_count": len(machines),
        "sync": {
            "transport": "git",
            "state": "local-files",
            "message": "Mail 文件通过团队 Git 流程交换；观察面板不执行同步。",
        },
    }


def memory_status(root):
    """Return a read-only, bounded projection of the knowledge lifecycle."""
    def files_under(relative, *, exclude=()):
        base = root / relative
        if not base.is_dir():
            return []
        return [
            path for path in base.rglob("*")
            if path.is_file() and path.suffix.lower() == ".md"
            and not any(part in exclude for part in path.relative_to(base).parts)
        ]

    raw = files_under("raw", exclude={"executions", ".logs"})
    drafts = files_under("drafts")
    from .task_workflow import candidate_disposition, _promotions, _rejections
    promotions, rejections = _promotions(root), _rejections(root)
    drafts = [path for path in drafts if not candidate_disposition(root, path.relative_to(root).as_posix(), promotions=promotions, rejections=rejections)]
    from .draft_review import disposition as ordinary_review
    drafts = [path for path in drafts if not ordinary_review(root, path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest())]
    wiki = files_under("wiki")
    knowledge = wiki + drafts
    visible = []
    excluded = 0
    for path in knowledge:
        meta, _body = _memory_meta(path)
        if _memory_is_visible(meta):
            visible.append(path)
        else:
            excluded += 1
    latest = sorted(visible, key=lambda path: _memory_event_time(_memory_meta(path)[0], path)[0], reverse=True)[:12]
    recent = []
    facets = {"areas": {}, "types": {}}
    for path in visible:
        meta, body = _memory_meta(path)
        item = _memory_summary(meta, body, path)
        for facet_name, value in (("areas", item["area"]), ("types", item["type"])):
            facets[facet_name][value] = facets[facet_name].get(value, 0) + 1
        if path in latest:
            item["path"] = path.relative_to(root).as_posix()
            recent.append(item)
    recent.sort(key=lambda item: item["updated_at"], reverse=True)
    return {
        "schema": "memory.snapshot.v1",
        "counts": {
            "raw": len(raw),
            "drafts": sum(1 for path in drafts if path in visible),
            "wiki": sum(1 for path in wiki if path in visible),
            "drafts_total": len(drafts),
            "wiki_total": len(wiki),
            "excluded": excluded,
        },
        "lifecycle": ["raw", "candidate", "human_review", "wiki", "recall", "explicit_feedback"],
        "recent": recent,
        "facets": facets,
    }


def _memory_plain(value: str, limit: int = 240) -> str:
    """Make a small, safe human-facing summary without pretending to render Markdown."""
    value = re.sub(r"`([^`]*)`", r"\1", str(value or ""))
    value = re.sub(r"!?(?:\[([^\]]+)\]\([^)]*\))", r"\1", value)
    value = re.sub(r"[*_~]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


_MEMORY_TIME_KEYS = (
    "updated_at",
    "updated",
    "modified_at",
    "ingested_at",
    "human_reviewed_at",
    "created",
)


def _parse_memory_time(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    elif isinstance(value, str) and value.strip():
        raw = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            try:
                parsed = datetime.combine(date.fromisoformat(raw), time.min)
            except ValueError:
                return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _memory_event_time(meta: dict, path: Path) -> tuple[datetime, str]:
    """Prefer durable knowledge timestamps; use mtime only as a compatibility fallback."""
    for key in _MEMORY_TIME_KEYS:
        parsed = _parse_memory_time(meta.get(key))
        if parsed is not None:
            return parsed, key
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc), "file_mtime"


def _memory_is_visible(meta: dict) -> bool:
    status = str(meta.get("status") or "active").strip().lower()
    archived = meta.get("archived") is True or str(meta.get("archived") or "").strip().lower() in {"1", "true", "yes"}
    return not archived and status not in {"dropped", "superseded", "retired", "archived"}


def _memory_meta(path: Path) -> tuple[dict, str]:
    parsed = store.parse_wiki_file(path) or {}
    body = str(parsed.pop("body", "") or "")
    return parsed, body


def _memory_title(meta: dict, body: str, path: Path) -> str:
    for key in ("title", "name"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return _memory_plain(value.strip(), 140)
    for line in body.splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match and match.group(1).strip():
            return _memory_plain(match.group(1), 140)
    return _memory_plain(path.stem.replace("-", " ").replace("_", " "), 140) or "未命名知识"


def _memory_summary(meta: dict, body: str, path: Path) -> dict:
    summary = ""
    for key in ("summary", "description", "abstract"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            summary = _memory_plain(value)
            break
    if not summary:
        paragraph = []
        for line in body.splitlines():
            clean = line.strip()
            if not clean:
                if paragraph:
                    break
                continue
            if clean.startswith("#") or clean.startswith("---"):
                continue
            paragraph.append(clean)
        summary = _memory_plain(" ".join(paragraph))
    if not summary:
        summary = "这份知识还没有可显示的摘要，打开详情查看原文。"
    kind = "wiki" if "wiki" in path.parts else "candidate"
    area = str(meta.get("area") or meta.get("domain") or meta.get("draft_area") or "未分类").strip() or "未分类"
    memory_type = str(meta.get("type") or ("wiki" if kind == "wiki" else "candidate")).strip() or ("wiki" if kind == "wiki" else "candidate")
    tags = meta.get("tags", [])
    if isinstance(tags, str):
        tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
    elif not isinstance(tags, list):
        tags = []
    event_time, event_source = _memory_event_time(meta, path)
    status = str(meta.get("status", "active" if kind == "wiki" else "pending")).strip() or ("active" if kind == "wiki" else "pending")
    status_label = {
        "active": "当前条目",
        "pending": "待审核",
        "provisional": "待确认",
        "stale": "需要更新",
    }.get(status, status)
    # 页面上要显示人话，不要显示 frontmatter 的原始值（"collaboration" / "strategy"）。
    # 标签表跟知识图共用同一份 DOMAIN_LABELS / GOVERNANCE_TYPES，避免两处口径漂移。
    area_label = mail_knowledge.DOMAIN_LABELS.get(area)
    governance = mail_knowledge.GOVERNANCE_TYPES.get(memory_type)
    return {
        "path": str(path),
        "kind": kind,
        "kind_label": mail_knowledge.review_summary(meta, kind)["kind_label"],
        "review": mail_knowledge.review_summary(meta, kind),
        "title": _memory_title(meta, body, path),
        "summary": summary,
        "area": area,
        "area_label": area_label or area,
        "type": memory_type,
        # 只有真的声明了治理类型才有标签；普通 Wiki 条目不冒充治理位。
        "type_label": governance[0] if governance else "",
        "tags": [str(tag) for tag in tags[:12]],
        # 给读者看的标签沿用同一套人话口径；翻不出来的英文机器键在这里就被挡掉，
        # 页面拿到的是可以直接显示的清单，不用再判断。
        "tag_labels": [label for label in (mail_knowledge.tag_label(tag) for tag in tags[:12]) if label],
        "status": status,
        "status_label": status_label,
        "updated_at": event_time.isoformat(),
        "timestamp_source": event_source,
    }


def _memory_item(root: Path, relative: str, *, full: bool = False) -> dict:
    """Read one Markdown knowledge item, refusing paths outside wiki/drafts."""
    if not relative or Path(relative).is_absolute():
        raise ValueError("memory path must be a relative wiki/ or drafts/ path")
    candidate = (root / relative).resolve()
    allowed = [(root / "wiki").resolve(), (root / "drafts").resolve()]
    if relative.startswith('drafts/') and candidate.is_file():
        from . import draft_review
        from .ingest_workflow import _inside
        bounded = _inside(root.resolve(), relative, 'drafts')
        ordinary = draft_review.disposition(root, relative, hashlib.sha256(bounded.read_bytes()).hexdigest())
        if ordinary and ordinary['decision'] == 'promoted':
            wiki = _inside(root.resolve(), ordinary['wiki_path'], 'wiki')
            reviewed_meta = store.parse_wiki_file(wiki) if wiki.is_file() else None
            if (not reviewed_meta or reviewed_meta.get('status') != 'active'
                    or not reviewed_meta.get('human_reviewed_at') or reviewed_meta.get('archived')
                    or not isinstance(reviewed_meta.get('source_candidates'), list)
                    or relative not in reviewed_meta['source_candidates']):
                raise FileNotFoundError('Reviewed knowledge is unavailable')
            candidate = wiki
    from .task_workflow import candidate_disposition
    retained = relative.startswith('drafts/') and candidate.exists() and candidate_disposition(root, relative) == 'promoted'
    if retained:
        from .task_workflow import reviewed_candidate
        exact = reviewed_candidate(root, relative, sha256=hashlib.sha256(candidate.read_bytes()).hexdigest())
        if exact:
            candidate = (root / exact['wiki_path']).resolve()
            retained = False
    if (not candidate.exists() or retained) and relative.startswith("drafts/"):
        from knowledge_studio.ingest_workflow import _inside
        import os
        _inside(root.resolve(), relative, "drafts")
        matches = []
        for parent, dirs, names in os.walk(root / "wiki", followlinks=False):
            dirs[:] = [name for name in dirs if not (Path(parent) / name).is_symlink()
                       and not (Path(parent) / name).is_junction()]
            for name in names:
                if not name.endswith(".md"):
                    continue
                path = Path(parent) / name
                if path.is_symlink() or path.is_junction():
                    continue
                try:
                    _inside(root.resolve(), path.relative_to(root).as_posix(), "wiki")
                except ValueError:
                    continue
                meta = store.parse_wiki_file(path) or {}
                origins = meta.get("source_candidates", [])
                if (isinstance(origins, list) and relative in origins
                        and meta.get("human_reviewed_at") and meta.get("status") == "active"
                        and not meta.get("archived")):
                    matches.append(path.resolve())
        if len(matches) == 1:
            candidate = matches[0]
    if (not candidate.is_relative_to(root.resolve()) or candidate.suffix.lower() != ".md"
            or not candidate.is_file() or not any(candidate.is_relative_to(base) for base in allowed)):
        raise FileNotFoundError("memory item not found")
    meta, body = _memory_meta(candidate)
    summary = _memory_summary(meta, body, candidate)
    summary["path"] = candidate.relative_to(root).as_posix()
    from knowledge_studio.knowledge_policy import is_source_material
    summary["content_role"] = "source_material" if is_source_material(meta) else "knowledge"
    if is_source_material(meta):
        summary["kind_label"] = "来源资料 · 机器提取"
    body_limit = 1_000_000 if full else 12000
    summary["body"] = body[:body_limit]
    summary["body_html"] = mail_media.render_body(root, summary["path"], meta, summary["body"], md_to_html)
    origins = meta.get('source_candidates')
    if meta.get('human_reviewed_at') and isinstance(origins, list):
        managed = next((value for value in origins if isinstance(value, str) and re.fullmatch(r'drafts/task-learning-[0-9a-f]{28}\.md', value)), None)
        if managed:
            from .task_workflow import reviewed_candidate
            revision = (meta.get('reviewed_source') or {}).get('sha256') if isinstance(meta.get('reviewed_source'), dict) else None
            reviewed = reviewed_candidate(root, managed, sha256=revision)
            if reviewed:
                summary['learning_review'] = {key: reviewed.get(key) for key in ('review_status', 'reviewed_at', 'original_available', 'snapshot_status')}
                summary['learning_review']['candidate_path'] = managed
                summary['learning_review']['revision'] = revision
                source = reviewed.get('workflow_source')
                summary['learning_review']['task_id'] = source.get('task_id') if isinstance(source, dict) else None
    original = candidate.read_text(encoding="utf-8")
    summary["markdown"] = original[:body_limit]
    summary["markdown_truncated"] = len(original) > body_limit
    summary["truncated"] = len(body) > body_limit
    summary["metadata"] = {
        key: _json_safe(value)
        for key, value in meta.items()
        if key not in {"file_path", "slug"}
    }
    summary["id"] = summary["path"]
    mail_knowledge.worker_knowledge.project(root, [summary], {summary["id"]: meta})
    return summary


def member_profiles(root: Path) -> dict:
    """Project shared Agent role profiles without exposing private user files.

    A profile is descriptive shared context. It is not a runtime connection,
    installation record, or proof that an Agent is currently available.
    """
    base = root / "profiles"
    paths = []
    team_path = base / "team.md"
    if team_path.is_file():
        paths.append((team_path, "team"))
    agents_dir = base / "agents"
    if agents_dir.is_dir():
        paths.extend(
            (path, "assistant")
            for path in sorted(agents_dir.glob("*.md"))
            if not path.name.startswith("_")
        )
    profiles = []
    for path, kind in paths:
        try:
            meta, body = _memory_meta(path)
            stat = path.stat()
        except (OSError, ValueError):
            continue
        title = _memory_title(meta, body, path)
        summary = _memory_summary(meta, body, path)["summary"]
        role = meta.get("role") or meta.get("responsibility") or meta.get("responsibilities") or ""
        scope = meta.get("scope") or meta.get("areas") or meta.get("area") or ""
        if isinstance(scope, (list, tuple)):
            scope = "、".join(str(item) for item in scope)
        profiles.append({
            "id": str(meta.get("id") or path.stem),
            "kind": kind,
            "title": title,
            "summary": summary,
            "role": str(role),
            "scope": str(scope),
            "status": str(meta.get("status") or "active"),
            "profile_kind": str(meta.get("profile_kind") or ("agent" if kind == "assistant" else "team")),
            "path": path.relative_to(root).as_posix(),
            "updated_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        })
    return {"schema": "oks.members.v1", "profiles": profiles}


def _json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


# ── Wiki 原文页：把一篇 Markdown 知识渲染成可独立打开的只读页面 ──────────
#
# 「在完整 Wiki 中打开」必须真的打开这篇知识，而不是只把路径复制到剪贴板。
# 渲染在服务端完成，页面零脚本，因此可以用很严的 CSP（default-src 'none'）。
# 正文一律先转义再套用一小撮 Markdown 规则 —— 知识正文是数据，不是可执行内容。

_MD_INLINE_CODE = re.compile(r"`([^`]+)`")
_MD_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_MD_EM = re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])")
_MD_LINK = re.compile(r"!?\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_MD_UL = re.compile(r"^[-*+]\s+(.*)$")
_MD_OL = re.compile(r"^\d+[.)]\s+(.*)$")
_MD_TABLE_RULE = re.compile(r"^\s*\|?[\s:\-|]*-[\s:\-|]*\|?\s*$")


def _md_link(match):
    label = match.group(1) or match.group(2)
    target = match.group(2)
    if target.startswith(("http://", "https://")):
        return f'<a href="{target}" rel="noreferrer noopener" target="_blank">{label}</a>'
    if re.fullmatch(r'/#collaboration&amp;entry=capture-[0-9a-f]{32}', target):
        return f'<a href="{target}">{label}</a>'
    # 相对路径指向知识库里的其他文件，本页面不代理它们，所以只标出引用目标。
    return f'<span class="md-ref" title="{target}">{label}</span>'


def _md_inline(escaped: str) -> str:
    stash: list[str] = []

    def keep(match):
        stash.append(match.group(1))
        return f"\x00{len(stash) - 1}\x00"

    escaped = _MD_INLINE_CODE.sub(keep, escaped)
    escaped = _MD_BOLD.sub(r"<strong>\1</strong>", escaped)
    escaped = _MD_EM.sub(r"<em>\1</em>", escaped)
    escaped = _MD_LINK.sub(_md_link, escaped)
    for index, code in enumerate(stash):
        escaped = escaped.replace(f"\x00{index}\x00", f"<code>{code}</code>")
    return escaped


def md_to_html(body: str, *, image_renderer=None) -> str:
    """Render a deliberately small Markdown subset of an already-trusted file."""
    body = str(body or "").replace("\r\n", "\n")
    images: list[str] = []
    if image_renderer is not None:
        # Use the same prose boundary as the image endpoint. Extract before
        # block parsing so multiline comments/code cannot become resources.
        matches = list(mail_media.IMAGE.finditer(mail_media.prose_only(body)))
        for match in reversed(matches):
            images.append(image_renderer(html.unescape(match.group(2)), html.unescape(match.group(1))))
            body = body[:match.start()] + f"\x02image{len(images) - 1}\x03" + body[match.end():]
    lines = body.split("\n")
    out: list[str] = []
    paragraph: list[str] = []
    quote: list[str] = []
    items: list[str] = []
    list_kind = ""
    index = 0

    def close_paragraph():
        if paragraph:
            out.append(f"<p>{_md_inline(html.escape(' '.join(paragraph)))}</p>")
            paragraph.clear()

    def close_quote():
        if quote:
            inner = "".join(f"<p>{_md_inline(html.escape(line))}</p>" for line in quote)
            out.append(f"<blockquote>{inner}</blockquote>")
            quote.clear()

    def close_list():
        nonlocal list_kind
        if items:
            rows = "".join(f"<li>{_md_inline(html.escape(item))}</li>" for item in items)
            out.append(f"<{list_kind}>{rows}</{list_kind}>")
            items.clear()
        list_kind = ""

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        fence = re.match(r"^(`{3,}|~{3,})", stripped)
        if fence:
            close_paragraph(); close_quote(); close_list()
            index += 1
            code: list[str] = []
            closing = re.compile(re.escape(fence.group(1)[0]) + "{" + str(len(fence.group(1))) + r",}\s*")
            while index < len(lines) and not closing.fullmatch(lines[index].strip()):
                code.append(lines[index])
                index += 1
            index += 1
            out.append(f"<pre><code>{html.escape(chr(10).join(code))}</code></pre>")
            continue

        if not stripped:
            close_paragraph(); close_quote(); close_list()
            index += 1
            continue

        heading = _MD_HEADING.match(stripped)
        if heading:
            close_paragraph(); close_quote(); close_list()
            level = min(len(heading.group(1)) + 1, 6)
            out.append(f"<h{level}>{_md_inline(html.escape(heading.group(2)))}</h{level}>")
            index += 1
            continue

        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", stripped):
            close_paragraph(); close_quote(); close_list()
            out.append("<hr>")
            index += 1
            continue

        if stripped.startswith("> "):
            close_paragraph(); close_list()
            quote.append(stripped[2:].strip())
            index += 1
            continue

        # 简易表格：本行含 |，下一行是分隔行
        if "|" in stripped and index + 1 < len(lines) and "|" in lines[index + 1] and _MD_TABLE_RULE.match(lines[index + 1]):
            close_paragraph(); close_quote(); close_list()
            header = [cell.strip() for cell in stripped.strip("|").split("|")]
            out.append("<table><thead><tr>" + "".join(f"<th>{_md_inline(html.escape(cell))}</th>" for cell in header) + "</tr></thead><tbody>")
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
                out.append("<tr>" + "".join(f"<td>{_md_inline(html.escape(cell))}</td>" for cell in cells) + "</tr>")
                index += 1
            out.append("</tbody></table>")
            continue

        unordered = _MD_UL.match(stripped)
        ordered = _MD_OL.match(stripped)
        if unordered or ordered:
            close_paragraph(); close_quote()
            want = "ul" if unordered else "ol"
            if list_kind and list_kind != want:
                close_list()
            list_kind = want
            items.append((unordered or ordered).group(1))
            index += 1
            continue

        close_quote(); close_list()
        paragraph.append(stripped)
        index += 1

    close_paragraph(); close_quote(); close_list()
    rendered = "\n".join(out)
    for index, image in enumerate(images):
        rendered = rendered.replace(f"\x02image{index}\x03", image)
    return rendered


def _human_time(value) -> str:
    """ISO 时间 → 人看的「2026-09-19 00:00」。解析不了就原样返回，不吞掉信息。"""
    text = str(value or "").strip()
    if not text:
        return "—"
    try:
        return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text


def render_wiki_page(item: dict, embed: bool = False, return_to: str = "/#view=knowledge") -> str:
    """Build the standalone page for one knowledge entry (no scripts)."""
    relations = mail_knowledge._relations(item.get("metadata") or {})
    badges = [item.get("kind_label") or "", item.get("status_label") or ""]
    if item.get("is_skill") and item.get("type_label"):
        badges.append(str(item["type_label"]))
    if item.get("truncated"):
        badges.append("正文在投影中截断")

    # 面向普通读者：显示中文标签而不是 frontmatter 原始值，
    # 把「文件路径 / 时间来源」这类给维护者看的信息降级到页脚的展开说明里。
    tag_names = list(item.get("tag_labels") or [])
    if not tag_names:
        tag_names = [mail_knowledge.tag_label(t) for t in (item.get("tags") or [])]
    tag_names = [name for name in tag_names if name]
    rows = [
        ("知识域", item.get("area_label") or item.get("area") or "—"),
    ]
    if item.get("is_skill") and item.get("type_label"):
        rows.append(("治理类型", str(item["type_label"])))
    rows += [
        ("条目状态", item.get("status_label") or "—"),
        ("资料校对" if item.get("content_role") == "source_material" else "人审证据",
         ("未经校对" if (item.get("metadata") or {}).get("ocr_review_status") == "unreviewed" else "以原文记录为准")
         if item.get("content_role") == "source_material" else (item.get("review") or {}).get("label") or "审核记录未知"),
        ("最近更新", _human_time(item.get("updated_at"))),
        ("标签", "、".join(tag_names) or "—"),
    ]
    meta_html = "".join(
        f"<dt>{html.escape(str(key))}</dt><dd>{html.escape(str(value))}</dd>" for key, value in rows
    )
    if relations:
        rel_rows = "".join(
            f'<li><span class="rel-kind">{html.escape(r.get("type_label") or r.get("type") or "")}</span>'
            f'<span class="rel-target">{html.escape(str(r.get("target_title") or r.get("target") or ""))}</span>'
            f'<span class="rel-src">{html.escape(str(r.get("source_label") or r.get("source") or ""))}</span></li>'
            for r in relations
        )
        rel_html = f'<h2>关系（{len(relations)}）</h2><ul class="wiki-rel">{rel_rows}</ul>'
    else:
        rel_html = '<h2>关系</h2><p class="wiki-none">这条知识没有声明关系，也没有与其他条目共享标签。</p>'

    title = html.escape(str(item.get("title") or "未命名知识"))
    summary = html.escape(str(item.get("summary") or ""))
    body_html = item.get("body_html") if isinstance(item.get("body_html"), str) else md_to_html(item.get("body") or "")
    first_heading = re.match(r"^<h[2-6]>(.*?)</h[2-6]>\s*", body_html, re.S)
    if first_heading and re.sub(r"<[^>]+>", "", first_heading.group(1)) == title:
        body_html = body_html[first_heading.end():]
    truncated = (
        '<p class="wiki-cut">正文在本页中被截断，完整内容以知识库文件为准。</p>'
        if item.get("truncated") else ""
    )
    if return_to != "/" and not return_to.startswith("/#"):
        return_to = "/#view=knowledge"
    chrome = "" if embed else (
        '<nav class="wiki-crumbs">'
        f'<a class="wiki-back" href="{html.escape(return_to, quote=True)}">← 返回面板</a>'
        '<span class="sep">|</span>'
        '<span>知识工作区</span><span class="sep">›</span>'
        f'<span class="cur">{title}</span></nav>'
    )
    detail_bits = [f"文件：{html.escape(str(item.get('path') or '—'))}"]
    source = str(item.get("timestamp_source") or "").strip()
    if source:
        detail_bits.append(f"时间来源：{html.escape(mail_knowledge.time_source_label(source))}")
    footer = "" if embed else (
        '<footer class="wiki-foot">本页是 OKS Mail 观察面板打开的只读投影；'
        '写入与审核仍在知识库与人的流程里完成。'
        f'<details class="why"><summary>这份信息从哪来？</summary>'
        f'<p>{" · ".join(detail_bits)}</p></details></footer>'
    )
    # 内嵌模式（抽屉里）不再重复标题 / 徽章 / 摘要 —— 抽屉自己已经展示了这三样，
    # 重复一遍只是噪音。两种模式共用同一份正文渲染，所以不会漂移。
    if embed:
        head = ""
    else:
        head = (
            f"<h1>{title}</h1>\n"
            f"<p class=\"wiki-badges\">{''.join(f'<span class=\"chip\">{html.escape(str(b))}</span>' for b in badges if b)}</p>\n"
            + (f'<p class="wiki-summary">{summary}</p>\n' if summary else "")
            + f'<dl class="wiki-meta">{meta_html}</dl>\n'
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · OKS Wiki</title>
<link rel="stylesheet" href="/wiki-page.css">
<link rel="stylesheet" href="/knowledge-reading.css?v=8">
<link rel="stylesheet" href="/studio-theme.css">
</head>
<body class="{'embed' if embed else 'full'}">
<main class="wiki">
{chrome}
{head}<section class="wiki-body markdown-body">
{body_html}
</section>
{truncated}
{rel_html}
{footer}
</main>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.kb_root = getattr(self.server, "kb_root", None)
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
            self.send_json(403, {"error": "loopback Host required"})
            return
        route = self.path.split("?", 1)[0]
        if route.startswith('/api/evaluation/'):
            from . import studio_evaluation as ev
            query = parse_qs(urlsplit(self.path).query)
            try:
                if route == '/api/evaluation/catalog':
                    result = ev.catalog(self.kb_root)
                elif route == '/api/evaluation/run':
                    result = ev.run(self.kb_root, query.get('id',[''])[0])
                elif route == '/api/evaluation/job':
                    result = ev.read(self.kb_root, 'jobs/' + ev.identifier(query.get('id',[''])[0]) + '.json')
                elif route == '/api/evaluation/candidates':
                    from .evaluation_feedback import candidates
                    result = candidates(self.kb_root)
                else:
                    self.send_json(404, {'error':'Unknown evaluation view'})
                    return
                self.send_json(200, result)
            except (OSError, ValueError, KeyError) as exc:
                self.send_json(400, {'error':str(exc)})
            return
        if route.startswith('/api/studio/'):
            from . import studio
            import yaml
            query = parse_qs(urlsplit(self.path).query)
            try:
                if route == '/api/studio/scopes':
                    result = studio.scopes(self.kb_root, query.get("kind", ["goal"])[0])
                elif route == '/api/studio/view':
                    result = studio.day_view(self.kb_root, query.get('kind',['goal'])[0], query['date'][0]) if 'date' in query else studio.view(self.kb_root, query.get('scope', [''])[0])
                elif route == '/api/studio/revision':
                    result = studio.revision_view(self.kb_root, query.get('id',[''])[0])
                elif route == '/api/studio/onboarding':
                    from .studio_history import onboarding
                    result = onboarding(self.kb_root)
                elif route == '/api/studio/activity':
                    result = studio.activity(self.kb_root,query.get('date',[''])[0])
                elif route == '/api/studio/file':
                    result = studio.read_file(self.kb_root, query.get('path', [''])[0])
                    _, body, _ = studio._markdown(result['text'])
                    result['body'] = body
                    result['body_html'] = md_to_html(body)
                elif route == '/api/studio/workflow':
                    from .studio_workflow import workflow
                    result = workflow(self.kb_root, query.get('path', [''])[0])
                elif route == '/api/studio/contexts':
                    result = studio.context_catalog(self.kb_root)
                elif route == '/api/studio/fs':
                    from .vfs_observation import execute
                    result = execute(self.kb_root, query.get('operation',['ls'])[0], query.get('uri',['oks://'])[0],
                        query=query.get('query',[''])[0], offset=int(query.get('offset',['0'])[0]), limit=int(query.get('limit',['20000'])[0]))
                elif route == '/api/studio/fs-history':
                    from .vfs_observation import history
                    result = history(self.kb_root)
                elif route == '/api/studio/calls':
                    from .vfs_observation import history
                    result = history(self.kb_root, query.get('kind',['recall'])[0])
                elif route == '/api/studio/skills':
                    result = studio.local_skills(self.kb_root)
                elif route == '/api/studio/usage':
                    result = studio.usage(self.kb_root)
                elif route == '/api/studio/libraries':
                    from .studio_libraries import libraries
                    result = libraries(self.kb_root)
                elif route == '/api/studio/settings':
                    result = studio.settings(self.kb_root)
                else:
                    self.send_json(404, {'error': 'Unknown workspace view'})
                    return
                self.send_json(200, result)
            except (OSError, ValueError, TypeError, UnicodeError, yaml.YAMLError) as exc:
                self.send_json(400, {'error': str(exc) if isinstance(exc, ValueError) else '无法读取所选文件，原记录保留。'})
            return
        if route in {'/api/daily/overview', '/api/daily/entry'}:
            try:
                from . import daily_capture, daily_learning
                query = parse_qs(urlsplit(self.path).query)
                result = daily_learning.overview(self.kb_root) if route.endswith('/overview') else daily_capture.entry(self.kb_root, query.get('id', [''])[0])
                self.send_json(200, result)
            except (OSError, ValueError, KeyError, TypeError, UnicodeError):
                self.send_json(400, {'error': '来源记录暂时无法读取；原文保留。'})
            return
        if route in {'/api/workspace/overview', '/api/workspace/retrieval'}:
            try:
                if route.endswith('/overview'):
                    from .workspace_home import build
                    result = build(self.kb_root)
                else:
                    from .retrieval_audit import report
                    result = report(self.kb_root)
                self.send_json(200, result)
            except (OSError, ValueError, KeyError, TypeError, UnicodeError):
                self.send_json(400, {'error': '无法完整读取工作区；原记录保留。'})
            return
        if route in {'/api/workspace', '/api/tasks/work-review', '/api/tasks/workflow', '/api/tasks/source', '/api/tasks/artifact', '/api/tasks/options', '/api/tasks/goal', '/api/tasks/reminders', '/api/tasks/overview', '/api/tasks/review', '/api/tasks/handoff', '/api/tasks/sources', '/api/learning/draft', '/api/skills/versions', '/api/skills/diff', '/api/skills/bundled-diff', '/api/skills/catalog', '/api/skills/source', '/api/skills/merge-preview'}:
            from . import workspace
            query = parse_qs(urlsplit(self.path).query)
            try:
                if route == '/api/workspace':
                    result = workspace.diagnostics(self.kb_root, port=self.server.server_port,
                        local_review=self.server.local_review, local_edit=self.server.local_edit)
                elif route.startswith('/api/skills/') and route.rsplit('/', 1)[-1] in ('catalog', 'source', 'merge-preview'):
                    action = route.rsplit('/', 1)[-1]
                    payload = {} if action == 'catalog' else {'ref': {'id': query.get('id', [''])[0], 'version': query.get('version', [''])[0]}} if action == 'source' else {
                        'ours': {'id': query.get('id', [''])[0], 'version': query.get('version', [''])[0]},
                        'theirs': {'id': query.get('upstream_id', [''])[0], 'version': query.get('upstream_version', [''])[0]}}
                    result = workspace.invoke(self.kb_root, {'catalog':'skill-catalog', 'source':'skill-detail', 'merge-preview':'skill-merge-preview'}[action], payload)
                elif route == '/api/tasks/work-review':
                    from .work_review import build
                    result = build(self.kb_root, period=query.get('period', ['week'])[0], date=query.get('date', [None])[0])
                elif route == '/api/tasks/workflow':
                    from .task_workflow import overview
                    result = overview(self.kb_root, query.get('id', [''])[0])
                elif route == '/api/tasks/options':
                    result = workspace.task_options(self.kb_root)
                elif route == '/api/tasks/goal':
                    result = workspace.goal(self.kb_root, query.get('path', [''])[0])
                elif route == '/api/tasks/reminders':
                    from .reminders import listing
                    result = listing(self.kb_root, query.get('id', [''])[0])
                elif route == '/api/tasks/overview':
                    from .tasks import overview
                    result = overview(self.kb_root)
                elif route == '/api/tasks/review':
                    result = workspace.task_review(self.kb_root, query.get('id', [''])[0])
                elif route == '/api/tasks/handoff':
                    result = workspace.task_handoff(self.kb_root, query.get('id', [''])[0], int(query.get('revision', ['0'])[0]))
                elif route == '/api/tasks/sources':
                    result = workspace.task_sources(self.kb_root, query.get('id', [''])[0], int(query.get('revision', ['0'])[0]))
                elif route == '/api/tasks/source':
                    result = workspace.artifact_source(self.kb_root, query.get('id', [''])[0], query.get('path', [''])[0],
                        int(query.get('revision', ['0'])[0]), query.get('source', [''])[0])
                    reading = re.sub(r'^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)', '', result['text'], count=1)
                    result['body_html'] = md_to_html(reading) if result['format'] == 'markdown' else '<pre>' + html.escape(result['text']) + '</pre>'
                elif route == '/api/tasks/artifact':
                    result = workspace.artifact(self.kb_root, query.get('id', [''])[0],
                                                query.get('path', [''])[0], int(query.get('revision', ['0'])[0]))
                    result['source_links'] = workspace.artifact_source_links(self.kb_root, result['path'], result['text'])
                    result['body_html'] = md_to_html(result['text']) if result['format'] == 'markdown' else '<pre>' + html.escape(result['text']) + '</pre>'
                elif route == '/api/learning/draft':
                    result = workspace.draft(self.kb_root, query.get('path', [''])[0], query.get('revision', [None])[0])
                    raw = result['text'].lstrip('\ufeff')
                    front = re.match(r'^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)', raw)
                    body = raw[front.end():] if front else raw
                    if result.get('workflow_context') and '\n## 本次依据\n' in body.replace('\r\n', '\n'):
                        body, evidence = body.replace('\r\n', '\n').rsplit('\n## 本次依据\n', 1)
                        result['evidence_html'] = md_to_html(evidence)
                    result['body_html'] = md_to_html(body)
                else:
                    operation = 'bundled-diff' if route.endswith('/bundled-diff') else 'diff' if route.endswith('/diff') else 'versions'
                    result = workspace.invoke(self.kb_root, operation,
                                              {key: query.get(key, [''])[0] for key in ('id', 'from', 'to', 'version')})
                self.send_json(200, result)
            except (OSError, ValueError, KeyError, TypeError, UnicodeError):
                self.send_json(400, {'error': '无法读取。请核对实例、文件或修订；原记录保留。'})
            return
        if route in {"/api/tasks", "/api/tasks/show"}:
            from knowledge_studio import tasks
            try:
                identifier = parse_qs(urlsplit(self.path).query).get('id', [''])[0]
                self.send_json(200, {'tasks': tasks.list_tasks(self.kb_root)} if route == '/api/tasks' else {
                    **tasks.show(self.kb_root, identifier), 'knowledge_base': str(self.kb_root)})
            except (OSError, ValueError, KeyError, TypeError):
                self.send_json(400, {'error': 'Cannot read task; existing records preserved'})
            return
        if route == "/api/retrieval/debug":
            from knowledge_studio.retrieval_debug import overview
            try:
                query = parse_qs(urlsplit(self.path).query)
                task_id = query.get('task', [None])[0]
                if task_id is not None and not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}', task_id):
                    raise ValueError('Invalid task filter')
                self.send_json(200, overview(self.kb_root, task_id=task_id))
            except (OSError, ValueError):
                self.send_json(400, {"error": "Cannot read local debug storage"})
            return
        if route == "/api/mail/capabilities":
            self.send_json(200, {
                "mode": self.server.mode,
                "read_only": self.server.mode == "reader",
                "local_review": bool(getattr(self.server, 'local_review', False)),
                "local_edit": bool(getattr(self.server, 'local_edit', False)),
                "viewer": "@human",
                "knowledge_base": str(self.kb_root),
                "knowledge_base_name": self.kb_root.name,
                "wake_supported": False,
                "server_id": getattr(self.server, "background_id", ""),
                "server_pid": getattr(self.server, "background_pid", None),
            })
            return
        if route == "/api/mail/overview":
            query = parse_qs(urlsplit(self.path).query)
            try:
                result = mail_observation.overview_data(
                    self.kb_root, UI_AGENT,
                    filter_kind=query.get("filter", ["all"])[0],
                    query=query.get("q", [""])[0],
                    limit=int(query.get("limit", ["50"])[0]),
                    cursor=query.get("cursor", [""])[0],
                )
            except ValueError as exc:
                self.send_json(400, {"error": str(exc)})
                return
            self.send_json(200, result)
            return
        if route == "/api/mail/knowledge-image":
            query = parse_qs(urlsplit(self.path).query)
            try:
                data, mime = mail_media.read_image(
                    self.kb_root,
                    query.get("path", [""])[0],
                    query.get("asset", [""])[0],
                )
            except (OSError, ValueError, IndexError):
                self.send_json(404, {"error": "Referenced knowledge image unavailable"})
                return
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
            self.end_headers()
            self.wfile.write(data)
            return
        if route == "/api/mail/activity":
            self.send_json(200, activity_data(self.kb_root, UI_AGENT))
            return
        if route == "/api/mail/thread":
            thread_id = parse_qs(urlsplit(self.path).query).get("id", [""])[0]
            rows = mail.thread_messages(self.kb_root, thread_id, UI_AGENT)
            if not rows:
                self.send_json(404, {"error": "thread not found"})
                return
            deliveries = delivery_records(self.kb_root, rows)
            messages = []
            for row in rows:
                meta = row["meta"]
                state = row.get("state") or {}
                messages.append({**meta, "title": row.get("title", ""), "body": row["body"],
                                 "body_html": md_to_html(row["body"]), "read_at": state.get("read_at"),
                                 "deliveries": deliveries.get(str(meta.get("message_id")), [])})
            self.send_json(200, {"thread_id": thread_id, "messages": messages,
                                 "title": rows[0].get("title", "未命名对话"),
                                 "observation": mail_observation.thread_observation(self.kb_root, rows),
                                 "state": "archived" if all((row.get("state") or {}).get("archived_at") for row in rows) else "open"})
            return
        if route == "/api/mail/status":
            self.send_json(200, connection_status(self.kb_root, UI_AGENT))
            return
        if route == "/api/mail/team":
            self.send_json(200, team_sync.status(self.kb_root))
            return
        if route in {"/api/mail/members", "/api/members"}:
            self.send_json(200, member_profiles(self.kb_root))
            return
        if route in {"/api/memory", "/api/mail/memory"}:
            self.send_json(200, memory_status(self.kb_root))
            return
        if route in {"/api/memory/item", "/api/mail/memory/item"}:
            query = parse_qs(urlsplit(self.path).query)
            relative = query.get("path", [""])[0]
            try:
                self.send_json(200, _memory_item(self.kb_root, relative, full=query.get("full", [""])[0] in {"1", "true"}))
            except FileNotFoundError as exc:
                self.send_json(404, {"error": str(exc)})
            except ValueError as exc:
                self.send_json(400, {"error": str(exc)})
            return
        if route == "/api/mail/snapshot":
            self.send_json(200, mail.snapshot_data(self.kb_root, UI_AGENT))
            return
        if route == "/api/mail/timeline":
            query = parse_qs(urlsplit(self.path).query)
            raw_limit = query.get("limit", [None])[0]
            try:
                limit = int(raw_limit) if raw_limit not in (None, "") else mail_timeline.DEFAULT_LIMIT
            except (TypeError, ValueError):
                limit = mail_timeline.DEFAULT_LIMIT
            self.send_json(200, mail_timeline.timeline_data(self.kb_root, UI_AGENT, limit))
            return
        if route == "/api/mail/knowledge-map":
            source = self.server.knowledge_source
            query = parse_qs(urlsplit(self.path).query)
            snapshot = source.snapshot(force=query.get("refresh", [""])[0] == "1") if source is not None else None
            self.send_json(200, mail_knowledge.knowledge_map(self.kb_root, worker_snapshot=snapshot))
            return
        if route in {"/api/mail/wiki-page", "/wiki-page"}:
            query = parse_qs(urlsplit(self.path).query)
            relative = query.get("path", [""])[0]
            embed = query.get("embed", ["0"])[0] in {"1", "true", "yes"}
            try:
                item = _memory_item(self.kb_root, relative, full=not embed)
            except FileNotFoundError as exc:
                self.send_html(404, f"<p>{html.escape(str(exc))}</p>")
                return
            except ValueError as exc:
                self.send_html(400, f"<p>{html.escape(str(exc))}</p>")
                return
            self.send_html(200, render_wiki_page(item, embed=embed, return_to=query.get("return_to", ["/#view=knowledge"])[0]))
            return
        if route == "/api/connection-guide":
            self.send_json(200, {
                "knowledge_base": str(self.kb_root),
                "guide": connection_guide(self.kb_root),
            })
            return
        entry = FILES.get(route)
        panel = parse_qs(urlsplit(self.path).query).get('panel') == ['1']
        if route == '/' and not panel:
            entry = ('studio.html', 'text/html')
        if not entry:
            self.send_error(404)
            return
        data = (ROOT / entry[0]).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", entry[1] + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'; form-action 'self'")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, status, value):
        data = json_bytes(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def send_html(self, status, markup):
        data = markup.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", WIKI_PAGE_CSP)
        self.end_headers()
        self.wfile.write(data)

    def read_json(self, max_bytes=65536):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0 or length > max_bytes:
            if length > 0:
                self.connection.settimeout(1)
                self.rfile.read(min(length, 131072))
            raise ValueError(f"request body must be between 1 and {max_bytes} bytes")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def _reject_post(self, status, message, **details):
        """Consume a bounded body before rejecting, so clients receive the response."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            limit = 65536
            if self.path.split("?", 1)[0] == "/api/evaluation/import":
                from .studio_evaluation import MAX_UPLOAD
                limit += MAX_UPLOAD
            if 0 < length <= limit:
                deadline = monotonic() + 1
                while length > 0:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        break
                    self.connection.settimeout(remaining)
                    chunk = self.rfile.read1(min(length, 65536))
                    if not chunk:
                        break
                    length -= len(chunk)
        except (ValueError, OSError):
            pass
        finally:
            self.connection.settimeout(None)
        self.send_json(status, {"error": message, **details})

    def do_POST(self):
        self.kb_root = getattr(self.server, "kb_root", None)
        allowed_origin = f"http://127.0.0.1:{self.server.server_port}"
        if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}' or self.headers.get('Origin', allowed_origin) != allowed_origin or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            self._reject_post(403, 'same-origin JSON requests required')
            return
        route = self.path.split("?", 1)[0]
        if route == '/api/studio/libraries':
            if not getattr(self.server, 'local_edit', False) or self.headers.get('Origin') != allowed_origin:
                self._reject_post(403, 'Local editing and an explicit same-origin request are required')
                return
            from . import studio_libraries
            import yaml
            try:
                payload = self.read_json()
                with self.server.library_lock:
                    if payload.get('expected_knowledge_base') != str(self.server.kb_root):
                        self.send_json(409, {'error': '知识库已切换，请重新打开。', 'code': 'instance_changed'})
                        return
                    if payload.get('action') == 'switch':
                        result = studio_libraries.switch_personal(self.server, payload)
                    elif payload.get('action') == 'sources':
                        result = studio_libraries.save_sources(self.kb_root, payload)
                    else:
                        raise ValueError('Unknown library configuration action')
                self.send_json(200, result)
            except (OSError, ValueError, TypeError, UnicodeError, yaml.YAMLError) as exc:
                self.send_json(400, {'error': str(exc)})
            return
        if route in {'/api/evaluation/import', '/api/evaluation/start', '/api/evaluation/compare', '/api/evaluation/review', '/api/evaluation/export', '/api/evaluation/preferences'}:
            from . import studio_evaluation as ev
            import yaml
            try:
                if route != '/api/evaluation/compare':
                    if not self.server.local_edit or self.headers.get('Origin') != allowed_origin:
                        self._reject_post(403, 'Local editing and explicit same-origin requests are required')
                        return
                payload = self.read_json(max_bytes=ev.MAX_UPLOAD+65536 if route.endswith('/import') else 65536)
                if payload.get('expected_knowledge_base') != str(self.kb_root):
                    raise ValueError('Knowledge base changed; reload before continuing')
                from . import evaluation_feedback as feedback
                operation = {'import':ev.import_dataset, 'start':ev.start, 'compare':ev.compare,
                             'review':feedback.review, 'export':feedback.export, 'preferences':feedback.configure}[route.rsplit('/',1)[1]]
                self.send_json(200, operation(self.kb_root,payload))
            except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
                self.send_json(400, {'error':str(exc)})
            return
        if route in {'/api/studio/file', '/api/studio/settings', '/api/studio/onboarding'}:
            if not getattr(self.server, 'local_edit', False):
                self._reject_post(403, 'Local editing is disabled; use oks mail serve --local-edit')
                return
            if self.headers.get('Origin') != allowed_origin:
                self._reject_post(403, 'An explicit same-origin request is required for local editing')
                return
            from . import studio
            import yaml
            try:
                request = self.read_json()
                if request.get('expected_knowledge_base') != str(self.kb_root):
                    self.send_json(409, {'error': '知识库已切换，请重新读取。', 'code': 'instance_changed'})
                    return
                from .studio_history import onboarding
                operation = studio.save_file if route.endswith('/file') else onboarding if route.endswith('/onboarding') else studio.save_settings
                self.send_json(200, operation(self.kb_root, request))
            except (OSError, ValueError, KeyError, TypeError, UnicodeError, yaml.YAMLError) as exc:
                self.send_json(409, {'error': str(exc) if isinstance(exc, ValueError) else '保存失败，原文件保留。'})
            return
        if route in {'/api/tasks/create', '/api/skills/import-bundled', '/api/skills/derive', '/api/skills/merge-prepare', '/api/tasks/reminders', '/api/tasks/lifecycle', '/api/tasks/accept-sources', '/api/tasks/progress', '/api/tasks/correction'}:
            if not getattr(self.server, 'local_edit', False):
                self._reject_post(403, 'Local editing is disabled; use oks mail serve --local-edit')
                return
            if self.headers.get('Origin') != allowed_origin:
                self._reject_post(403, 'An explicit same-origin request is required for local editing')
                return
            from . import workspace
            try:
                request = self.read_json()
                if request.get('expected_knowledge_base') != str(self.kb_root):
                    self.send_json(409, {'error': '知识库已切换，请重试连接后重新查看。', 'code': 'instance_changed'})
                    return
                if route in ('/api/skills/derive', '/api/skills/merge-prepare'):
                    result = workspace.invoke(self.kb_root, 'skill-derive' if route.endswith('/derive') else 'skill-merge-prepare', request)
                elif route == '/api/tasks/correction':
                    result = workspace.propose_task_correction(self.kb_root, request)
                elif route == '/api/tasks/accept-sources':
                    result = workspace.accept_task_sources(self.kb_root, request)
                elif route == '/api/tasks/progress':
                    result = workspace.save_task_progress(self.kb_root, request)
                elif route == '/api/tasks/lifecycle':
                    from .tasks import transition
                    result = transition(self.kb_root, request.get('task_id'), request.get('expected_revision'), request.get('action'), request.get('reason'))
                elif route == '/api/tasks/reminders':
                    from . import reminders
                    result = reminders.add(self.kb_root, request) if request.get('action') == 'add' else reminders.update(self.kb_root, request)
                else:
                    result = workspace.create_task(self.kb_root, request) if route.endswith('/create') else workspace.invoke(self.kb_root, 'import-bundled', request)
                if isinstance(result, dict) and 'agreement' in result:
                    result = {**result, 'knowledge_base': str(self.kb_root)}
                self.send_json(201, result)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.send_json(409, {'error': str(exc) if isinstance(exc, ValueError) else 'Cannot save; inspect the current state before retrying'})
            return
        if route == '/api/workspace/query':
            from . import workspace
            try:
                self.send_json(200, workspace.invoke(self.kb_root, 'query', self.read_json()))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.send_json(400, {'error': str(exc)})
            return
        if route == "/api/feedback/inspect":
            # Read-only POST avoids placing private scope labels in URL/history.
            from knowledge_studio.feedback import inspect
            try:
                request = self.read_json()
                self.send_json(200, inspect(self.kb_root, request.get("scope")))
            except (OSError, ValueError, KeyError, TypeError):
                self.send_json(400, {"error": "Cannot read this exact private scope; data preserved"})
            return
        if route in {'/api/feedback/review', '/api/feedback/withdraw-candidate', '/api/feedback/export', '/api/learning/promote', '/api/learning/reject'}:
            if not getattr(self.server, 'local_review', False):
                self._reject_post(403, 'Local review is disabled; use oks mail serve --local-review')
                return
            # Unlike read-only POST, mutations require an explicit browser origin.
            if self.headers.get('Origin') != allowed_origin:
                self._reject_post(403, 'An explicit same-origin request is required for local review')
                return
            from . import feedback, workspace
            try:
                request = self.read_json()
                if route == '/api/learning/promote':
                    result = workspace.invoke(self.kb_root, 'promote', request)
                elif route == '/api/learning/reject':
                    result = workspace.invoke(self.kb_root, 'reject', request)
                elif route == '/api/feedback/export':
                    result = feedback.export(self.kb_root, request, confirm_share=request.get('confirm_share') is True)
                elif route == '/api/feedback/withdraw-candidate':
                    result = feedback.withdraw_candidate(self.kb_root, request)
                else:
                    result = feedback.review(self.kb_root, request)
                self.send_json(200, result)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.send_json(409, {'error': str(exc) if isinstance(exc, ValueError) else 'Operation failed; inspect current state before retrying'})
            return
        # Reader mode rejects all writes. Legacy collaboration mode is an explicit
        # opt-in; its team/sync endpoint can commit/rebase/push KB files and is not
        # a Mail-only write. The removed knowledge toggle remains unsupported.
        if route not in {"/api/mail/send", "/api/mail/reply", "/api/mail/invite", "/api/mail/read", "/api/mail/archive", "/api/mail/unarchive", "/api/mail/team/sync"}:
            self._reject_post(404, "unknown POST route")
            return
        if self.server.mode == "reader":
            self._reject_post(403, "reader mode does not permit writes", mode="reader")
            return
        try:
            payload = self.read_json()
            if route == "/api/mail/team/sync":
                result = team_sync.sync(
                    self.kb_root,
                    push=bool(payload.get("push", False)),
                    message=str(payload.get("message", "同步 OKS 团队资料")),
                )
                self.send_json(200, result)
                return
            if route == "/api/mail/send":
                title = str(payload.get("title", "")).strip()
                body = str(payload.get("body", "")).strip()
                recipient = str(payload.get("to", "")).strip()
                if not title or not body or not recipient:
                    raise ValueError("title, body and recipient are required")
                recipient = ["@" + agent_id(value) for value in recipient.split(",")]
                if len(title) > 120 or len(body) > 12000:
                    raise ValueError("title/body too long")
                record_kind = mail.normalise_record_kind(payload.get("record_kind", "message"))
                delivery_reason = str(payload.get("delivery_reason", "direct") or "direct").strip().lower()
                if delivery_reason not in mail.REASONS:
                    raise ValueError("unsupported delivery reason")
                evidence_refs = mail.normalise_evidence_refs(payload.get("evidence_refs", []))
                result = mail.write_message(
                    self.kb_root,
                    body=body,
                    sender=UI_AGENT,
                    sender_kind="human",
                    recipients=recipient,
                    title=title,
                    origin_session_id=self.server.session_id,
                    origin_machine_id=identity.normalise_machine_id(),
                    delivery_reason=delivery_reason,
                    record_kind=record_kind,
                    evidence_refs=evidence_refs,
                    session_policy="next_prompt",
                )
                self.send_json(201, {"status": "saved", "message_id": result["message_id"], "thread_id": result["thread_id"], "record_kind": record_kind, "evidence_refs": evidence_refs})
                return
            if route == "/api/mail/reply":
                thread_id = str(payload.get("thread_id", "")).strip()
                body = str(payload.get("body", "")).strip()
                if not thread_id or not body:
                    raise ValueError("thread_id and body are required")
                recipients, latest = reply_recipients(self.kb_root, thread_id)
                result = mail.write_message(
                    self.kb_root,
                    body=body,
                    sender=UI_AGENT,
                    sender_kind="human",
                    recipients=recipients,
                    title=f"Re: {latest['title']}",
                    thread_id=thread_id,
                    reply_to=str(latest["meta"].get("message_id", "")),
                    origin_session_id=self.server.session_id,
                    origin_machine_id=identity.normalise_machine_id(),
                    delivery_reason="thread_reply",
                    record_kind="note",
                    session_policy="next_prompt",
                )
                self.send_json(201, {"status": "saved", "message_id": result["message_id"], "thread_id": thread_id})
                return
            if route == "/api/mail/invite":
                thread_id = str(payload.get("thread_id", "")).strip()
                recipient = agent_id(str(payload.get("to", "")).strip())
                body = str(payload.get("body", "")).strip()
                if not thread_id or not body:
                    raise ValueError("thread_id, recipient and body are required")
                if recipient.lower() in {"human", "all", "unknown"}:
                    raise ValueError("Invite a named Agent, not human, all or unknown")
                messages = mail.thread_messages(self.kb_root, thread_id, UI_AGENT)
                if not messages:
                    raise ValueError("thread not found")
                latest = messages[-1]
                invited = "@" + recipient
                participants = {
                    "@" + value.lstrip("@").strip()
                    for message in messages
                    for value in ({str(message["meta"].get("from", ""))} | set(message["meta"].get("to", [])))
                    if value and value.lstrip("@").strip().lower() not in {"human", "all", "unknown"}
                }
                if invited.casefold() in {value.casefold() for value in participants}:
                    raise ValueError("Agent is already in this Thread")
                recipients = sorted(participants)
                result = mail.write_message(
                    self.kb_root,
                    body=body,
                    sender=UI_AGENT,
                    sender_kind="human",
                    recipients=sorted(set(recipients + [invited])),
                    title=f"邀请 {recipient} 加入对话",
                    thread_id=thread_id,
                    reply_to=str(latest["meta"].get("message_id", "")),
                    origin_session_id=self.server.session_id,
                    origin_machine_id=identity.normalise_machine_id(),
                    delivery_reason="direct",
                    record_kind="note",
                    session_policy="next_prompt",
                )
                self.send_json(201, {"status": "saved", "message_id": result["message_id"], "thread_id": thread_id, "recipients": result["recipients"]})
                return
            if route == "/api/mail/archive":
                thread_id = str(payload.get("thread_id", "")).strip()
                message_id = str(payload.get("message_id", "")).strip()
                target = thread_id or message_id
                if not target:
                    raise ValueError("thread_id or message_id is required")
                selected = [
                    item for item in mail.iter_messages(self.kb_root, UI_AGENT)
                    if item["meta"].get("thread_id") == target or item["meta"].get("message_id") == target
                ]
                if not selected:
                    raise ValueError("mail or thread not found")
                archived_at = mail.iso_now()
                for message in selected:
                    message_id = str(message["meta"].get("message_id"))
                    changes = {"archived_at": archived_at, "thread_state": "closed"}
                    if message["path"].parent != mail.messages_dir(self.kb_root):
                        # A legacy Markdown file is shared by all recipients.
                        # Seed a new recipient projection from its old read
                        # marker, but never rewrite the shared file.
                        state_path = mail.recipient_state_path(self.kb_root, UI_AGENT, message_id)
                        if not state_path.is_file() and str(message["meta"].get("read", "false")).lower() == "true":
                            changes["read_at"] = (
                                message["meta"].get("read_at")
                                or message["meta"].get("timestamp")
                                or mail.iso_now()
                            )
                    mail.update_recipient_state(
                        self.kb_root, UI_AGENT, message_id, **changes,
                    )
                self.send_json(200, {"status": "archived", "target": target, "count": len(selected)})
                return
            if route == "/api/mail/unarchive":
                thread_id = str(payload.get("thread_id", "")).strip()
                message_id = str(payload.get("message_id", "")).strip()
                target = thread_id or message_id
                if not target:
                    raise ValueError("thread_id or message_id is required")
                selected = [
                    item for item in mail.iter_messages(self.kb_root, UI_AGENT)
                    if item["meta"].get("thread_id") == target or item["meta"].get("message_id") == target
                ]
                if not selected:
                    raise ValueError("mail or thread not found")
                for message in selected:
                    message_id = str(message["meta"].get("message_id"))
                    mail.update_recipient_state(
                        self.kb_root, UI_AGENT, message_id,
                        archived_at=None, thread_state="open",
                    )
                self.send_json(200, {"status": "unarchived", "target": target, "count": len(selected)})
                return
            if route == "/api/mail/read":
                message = visible_message(self.kb_root, str(payload.get("message_id", "")).strip())
                if not message:
                    raise ValueError("message not found")
                message_id = str(message["meta"].get("message_id", ""))
                # Read state is per-recipient: even for a legacy shared Markdown
                # file, persist the transition in this Agent's projection only —
                # the shared file is never rewritten.
                state = mail.update_recipient_state(self.kb_root, UI_AGENT, message_id, read_at=mail.iso_now())
                self.send_json(200, {"status": "read", "message_id": message_id, "state": state})
                return
            self._reject_post(404, "unknown POST route")
        except team_sync.TeamSyncError as exc:
            self.send_json(409, {"error": str(exc)})
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})

class _LoopbackHTTPServer(ThreadingHTTPServer):
    def server_close(self):
        history_service = getattr(self,'history_service',None)
        if history_service is not None:history_service.stop()
        service = getattr(self, 'daily_service', None)
        if service is not None:
            service.stop()
        super().server_close()

    def server_bind(self):
        # HTTPServer's reverse DNS can block macOS detached startup. This
        # service only binds loopback and needs no externally resolved name.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


def create_server(root: Path, port: int = 3182, *, mode: str = "reader", knowledge_source=None, local_review: bool = False, local_edit: bool = False) -> ThreadingHTTPServer:
    if mode not in {"reader", "collaboration"}:
        raise ValueError("Mail mode must be reader or collaboration")
    if (local_review or local_edit) and mode != 'reader':
        raise ValueError('Use --local-review with reader mode; collaboration writes are a separate capability')
    root = validate_root(root)
    server = _LoopbackHTTPServer(("127.0.0.1", port), Handler)
    server.kb_root = root
    server.library_lock = RLock()
    server.mode = mode
    server.local_review = bool(local_review or local_edit)
    server.local_edit = bool(local_edit)
    server.knowledge_source = knowledge_source
    server.session_id = None
    if local_edit:
        from .studio_history import Watcher
        server.history_service = Watcher(root).start()
    if local_edit and (root / 'settings/daily-capture.json').is_file():
        from .daily_learning import CaptureService
        server.daily_service = CaptureService(root).start()
    if mode == "reader":
        return server
    machine_id = identity.normalise_machine_id()
    machine_token = hashlib.sha256(machine_id.encode("utf-8")).hexdigest()[:12]
    server.session_id = f"mail-ui-{server.server_port}-{machine_token}"
    mail.register_session(
        root,
        server.session_id,
        UI_AGENT,
        scope="mail-web",
        machine_id=machine_id,
    )
    return server
