# Decay System

Knowledge fades over time based on type-specific decay rates.

## Memory Curve

```
score = importance × e^(-λ × days_old) + 0.5 × ln(1 + access_count) + pin_bonus
```

Active pages get ×1.2 multiplier. Dropped/archived → 0.0.

## Type-Specific Decay (λ)

| Type | λ | Behavior |
|------|---|----------|
| concept | 0.0 | No decay |
| strategy | 0.014 | Slow decay |
| anti-pattern | 0.010 | Moderate decay |
| unknown | 0.030 | Fast decay (fallback) |

## Tiers

| Tier | Score | Action |
|------|-------|--------|
| hot | ≥ 0.7 | Priority recall |
| warm | ≥ 0.4 | Normal recall |
| cold | ≥ 0.15 | Low priority |
| evictable | < 0.15 | Archive candidate |

## Lifecycle

```
Provisional → Active (access ≥ 3) → Dropped (score < threshold)
```

## Access Reinforcement

```python
new_confidence = min(1.0, current + 0.1 × (1 - current))
```

## Config

`settings/decay-config.yaml`: `archive_threshold: 0.3`, `pin_bonus: 0.5`

Source: `cli/knowledge_studio/store.py`
