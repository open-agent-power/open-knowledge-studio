"""HTML usage report for ``oks metrics --html``.

Split out of :mod:`knowledge_studio.cli` (B4-1): pure string assembly over
``records/inject.jsonl`` plus knowledge metrics, with no Typer surface.
"""
from __future__ import annotations

from pathlib import Path


def _generate_metrics_html(root: Path) -> str:
    """Generate HTML usage report from inject + trace-feedback + knowledge metrics."""
    import json
    from collections import defaultdict
    from datetime import datetime

    # 读 inject.jsonl
    inject_path = root / "records" / "inject.jsonl"
    injects = []
    if inject_path.is_file():
        for line in inject_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    injects.append(json.loads(line))
                except Exception:
                    continue

    # 按 slug 聚合
    slug_stats = defaultdict(lambda: {"count": 0, "used": 0, "rel_sum": 0.0})
    for rec in injects:
        slugs = rec.get("slugs", [])
        rels = rec.get("rels", [])
        for i, slug in enumerate(slugs):
            s = slug_stats[slug]
            s["count"] += 1
            s["rel_sum"] += rels[i] if i < len(rels) else 0
        if rec.get("used"):
            for slug in slugs:
                slug_stats[slug]["used"] += 1

    total = len(injects)
    accepted = sum(1 for r in injects if r.get("used"))
    rate = (accepted / total * 100) if total else 0

    rows = []
    for slug, s in sorted(slug_stats.items(), key=lambda x: -x[1]["count"])[:20]:
        avg_rel = s["rel_sum"] / s["count"] if s["count"] else 0
        sr = (s["used"] / s["count"] * 100) if s["count"] else 0
        rows.append(
            f"<tr><td>{slug}</td><td>{s['count']}</td><td>{s['used']}</td>"
            f"<td>{avg_rel:.2f}</td><td>{sr:.0f}%</td></tr>"
        )

    fb_path = root / "records" / "trace-feedback.jsonl"
    feedbacks = []
    if fb_path.is_file():
        for line in fb_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    feedbacks.append(json.loads(line))
                except Exception:
                    continue
    fb_rows = []
    for fb in feedbacks[-20:]:
        outcome = fb.get("outcome", "?")
        cls = "accepted" if outcome == "accepted" else ("rejected" if outcome == "rejected" else "")
        fb_rows.append(
            f"<tr><td>{fb.get('run_id', '?')}</td>"
            f"<td class='{cls}'>{outcome}</td>"
            f"<td>{fb.get('comment', '')}</td>"
            f"<td class='muted'>{fb.get('recorded_at', '?')[:19]}</td></tr>"
        )

    from knowledge_studio.metrics import get_knowledge_report
    report = get_knowledge_report()
    k_rows = [
        f"<tr><td>Scale</td><td>Wiki pages</td><td>{report['scale']['total_wiki_pages']}</td></tr>",
        f"<tr><td>Vitality</td><td>Active ratio</td><td>{report['vitality']['active_wiki_ratio']:.0%}</td></tr>",
        f"<tr><td>Value</td><td>Total access</td><td>{report['value']['total_access_count']}</td></tr>",
        f"<tr><td>Credibility</td><td>Avg confidence</td><td>{report['credibility']['avg_confidence']:.2f}</td></tr>",
    ]

    # 调参建议：accepted/rejected rel 分布 + floor + cooldown
    import statistics
    from collections import Counter
    accepted_rels = []
    rejected_rels = []
    for rec in injects:
        used = rec.get("used", False)
        for rel in rec.get("rels", []):
            (accepted_rels if used else rejected_rels).append(rel)
    acc_med = statistics.median(accepted_rels) if accepted_rels else 0
    rej_med = statistics.median(rejected_rels) if rejected_rels else 0
    from knowledge_studio.recall import load_recall_params
    params = load_recall_params(root)
    cur_floor = params["recall_floor"]
    # PostToolUse 注入统计（source=posttool）
    posttool_injects = [r for r in injects if r.get("source") == "posttool"]
    pt_total = len(posttool_injects)
    pt_accepted = sum(1 for r in posttool_injects if r.get("used"))
    pt_rate = (pt_accepted / pt_total * 100) if pt_total else 0
    # 当前生效参数（从 settings/recall.yaml + legacy env override）
    suggested_floor = max(0.7, acc_med - 0.2) if accepted_rels else 0.7
    slug_freq = Counter()
    for rec in injects:
        for slug in rec.get("slugs", []):
            slug_freq[slug] += 1
    top_freq = slug_freq.most_common(3)
    freq_str = ", ".join(f"{s}({c})" for s, c in top_freq) if top_freq else "—"

    ts = datetime.now().isoformat(timespec="seconds")
    inject_table = (
        "<table><tr><th>Slug</th><th>注入次数</th><th>被采纳</th><th>平均 rel</th><th>接受率</th></tr>"
        + "".join(rows) + "</table>"
    ) if rows else "<p class='muted'>无注入记录</p>"
    fb_table = (
        "<table><tr><th>Run</th><th>Outcome</th><th>Comment</th><th>时间</th></tr>"
        + "".join(fb_rows) + "</table>"
    ) if fb_rows else "<p class='muted'>无反馈记录</p>"

    return f"""<!DOCTYPE html>
<html lang="zh">
<head><meta charset="utf-8"><title>OKS 使用记录</title>
<style>
body {{ font: 14px/1.6 -apple-system, sans-serif; max-width: 900px; margin: 2em auto; padding: 0 1em; color: #222; }}
h1 {{ border-bottom: 2px solid #0af; padding-bottom: .3em; }}
h2 {{ color: #0af; margin-top: 2em; }}
table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; }}
th {{ background: #f4f4f8; }}
.muted {{ color: #888; }}
.accepted {{ color: #080; font-weight: bold; }}
.rejected {{ color: #c00; font-weight: bold; }}
</style>
</head>
<body>
<h1>OKS 使用记录</h1>
<p class="muted">生成于 {ts} | KB: {root}</p>
<h2>注入统计（inject.jsonl）</h2>
<p>总注入 <b>{total}</b> 次，<b>{accepted}</b> 条被采纳（<b>{rate:.0f}%</b>）</p>
{inject_table}
<h2>Trace 反馈（trace-feedback.jsonl）</h2>
{fb_table}
<h2>调参建议</h2>
<table><tr><th>指标</th><th>当前</th><th>建议</th></tr>
<tr><td>accepted rel 中位数</td><td>{acc_med:.2f}</td><td>—</td></tr>
<tr><td>rejected rel 中位数</td><td>{rej_med:.2f}</td><td>—</td></tr>
<tr><td>recall.floor</td><td>{cur_floor}</td><td>{suggested_floor:.2f}</td></tr>
</table>
<p>频繁注入（cooldown 可能太短）：{freq_str}</p>
<h2>PostToolUse 注入统计</h2>
<p>PostToolUse 注入 <b>{pt_total}</b> 次，<b>{pt_accepted}</b> 条被采纳（<b>{pt_rate:.0f}%</b>）</p>
<h2>当前生效参数（settings/recall.yaml + legacy env override）</h2>
<table><tr><th>参数</th><th>当前值</th></tr>
<tr><td>recall.floor</td><td>{params["recall_floor"]}</td></tr>
<tr><td>recall.topn</td><td>{params["recall_topn"]}</td></tr>
<tr><td>posttool.mode</td><td>{params["posttool_mode"]}</td></tr>
<tr><td>posttool.signal_rel_floor</td><td>{params["posttool_signal_rel_floor"]}</td></tr>
<tr><td>search_backend</td><td>{params["search_backend"]}</td></tr>
</table>
<p class="muted">settings/recall.yaml 是持久配置源；旧环境变量仅作兼容覆盖。临时调参用 oks recall --floor 0.9。</p>
<h2>知识指标</h2>
<table><tr><th>维度</th><th>指标</th><th>值</th></tr>{"".join(k_rows)}</table>
</body>
</html>"""
