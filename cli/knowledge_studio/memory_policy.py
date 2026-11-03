"""Explicit time bounds, independent of ranking, decay, access count and approval."""
from datetime import UTC, datetime


def instant(value):
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('Datetime needs an explicit timezone')
        return value.astimezone(UTC)
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError('Use an ISO datetime with an explicit timezone')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('Use an ISO datetime with an explicit timezone') from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('Datetime needs an explicit timezone, such as +08:00 or Z')
    try:
        return result.astimezone(UTC)
    except (ValueError, OverflowError):
        raise ValueError('Datetime is outside the supported UTC range') from None


def validate(value):
    if not isinstance(value, dict) or set(value) - {'valid_from', 'valid_until'}:
        raise ValueError('Applicability accepts only valid_from and valid_until')
    result = {key: instant(text).isoformat() for key, text in value.items()}
    if result.get('valid_from') and result.get('valid_until') and result['valid_from'] >= result['valid_until']:
        raise ValueError('valid_until must be later than valid_from')
    return result


def evaluate(value, *, now=None):
    now = datetime.now(UTC) if now is None else now.astimezone(UTC)
    if value is None or value == {}:
        return {'status': 'unknown', 'eligible': True}
    try:
        policy = validate(value)
    except (ValueError, TypeError, OverflowError):
        return {'status': 'invalid_time', 'eligible': False}
    if policy.get('valid_from') and now < instant(policy['valid_from']):
        return {'status': 'not_yet_valid', 'eligible': False}
    if policy.get('valid_until') and now >= instant(policy['valid_until']):
        return {'status': 'expired', 'eligible': False}
    return {'status': 'active', 'eligible': True}


def admission(pages, mode='shadow', *, now=None):
    """One fixed clock/corpus policy used by every knowledge backend and Skill route."""
    if mode not in {'shadow', 'enforce'}:
        raise ValueError('memory_validity must be shadow or enforce')
    now = now or datetime.now(UTC)
    views = {p['slug']: evaluate(p.get('applicability'), now=now) for p in pages}
    counts = {}
    for view in views.values():
        counts[view['status']] = counts.get(view['status'], 0) + 1
    return views, {'mode': mode, 'evaluated_at': now.isoformat(), 'counts': counts,
                   'would_exclude': sum(not v['eligible'] for v in views.values()),
                   'state_mutated': False}
