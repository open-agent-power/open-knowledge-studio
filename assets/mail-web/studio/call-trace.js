// Shared rendering for measured recall and VFS spans; no synthetic timings.
export function callTimeline({ el }, record) {
  const host = el('div', 'call-timeline');
  const spans = record.spans || [];
  for (const span of spans) {
    const row = el('div', 'call-span');
    let parent = span.parent_id, depth = 0;
    while (parent != null && depth < 20) { depth++; parent = spans.find(s => s.id === parent)?.parent_id; }
    row.style.paddingLeft = depth * 8 + 'px';
    row.append(el('span', null, span.name), el('small', null, ` ${span.duration_ms.toFixed(3)} ms`));
    const track = el('div', 'call-track'), bar = el('i');
    bar.style.left = `${100 * span.start_ms / Math.max(record.total_ms, .001)}%`;
    bar.style.width = `${Math.min(100, 100 * span.duration_ms / Math.max(record.total_ms, .001))}%`;
    track.append(bar); row.append(track); host.append(row);
  }
  return host;
}
