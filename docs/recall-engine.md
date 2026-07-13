# 6-Factor Recall Engine

Scores wiki pages using six factors to find the most relevant knowledge.

## Scoring Formula

```
total = token_overlap×0.3 + substring_bonus + topic_trace_bonus
        × type_boost + review_penalty × memory_curve
```

## Factors

### 1. Token Overlap (×0.3)

jieba tokenization. `overlap = len(query∩page) / len(query) × 0.3`

### 2. Substring Match (+1.0/+0.5)

Title contains query: +1.0. Body contains query: +0.5.

### 3. Topic Trace (+2.0)

Page has trace with `id == topic_id`.

### 4. Type Boost (1.5/0.8/0.6)

anti-pattern ×1.5, strategy ×0.8, concept ×0.6.

### 5. Review Penalty (+2.0/+1.0)

`decision_correct=false`: +2.0. `outcome=failure`: +1.0.

### 6. Memory Curve (×0.5)

`importance × e^(-λ×age) + 0.5×ln(1+access) + pin_bonus`. Active ×1.2.

## Two-Path Recall

- **Episodic** — searches `raw/` + `profiles/` by keyword + freshness (`0.95^days_old`)
- **Knowledge** — scores all wiki/ pages via 6 factors
- **Combined** — `{"episodic": [...], "knowledge": [...]}`

## Implementation

Source: `cli/knowledge_studio/recall.py`
