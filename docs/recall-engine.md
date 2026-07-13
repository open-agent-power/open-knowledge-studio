# 6-Factor Recall Engine

Scores wiki pages using six factors to find the most relevant knowledge. The engine combines semantic search, keyword matching, and graph connections — all in one unified scoring pass.

## Three Search Modes in One

| Mode | What it does | Which factors |
|------|-------------|--------------|
| **Semantic** | Finds by meaning, not just exact words | Token overlap |
| **Keyword** | Exact match for specific terms | Substring match |
| **Graph** | Finds through topic connections and type weighting | Topic trace + type boost + review penalty |

All three modes run automatically on every query. The 6-factor engine combines them with a memory curve multiplier to produce the final relevance score.

## Scoring Formula

```
total = (token_overlap×0.3 + substring_bonus + topic_trace_bonus)
        × type_boost + review_penalty
        × memory_curve
```

## The Six Factors

### 1. Token Overlap (×0.3)

jieba tokenization splits both the query and the page content into tokens. The overlap ratio measures how many query tokens appear in the page.

```
overlap = len(query_tokens ∩ page_tokens) / len(query_tokens) × 0.3
```

This is the **semantic** layer — it finds pages about "architectural approaches" when you search for "design patterns", because the token overlap catches shared concepts.

### 2. Substring Match (+1.0 / +0.5)

Direct string matching for the **keyword** layer:

- Title contains the query string: **+1.0**
- Body contains the query string: **+0.5**

Both can apply — a page with the query in both title and body gets +1.5.

### 3. Topic Trace (+2.0)

If the page was created from a specific conversation topic, and you're querying with the same `topic_id`, the page gets a **+2.0** bonus. This is the **graph** connection — it links a memory back to the conversation that produced it.

```python
if page.get("trace_id") == topic_id:
    relevance += 2.0
```

### 4. Type Boost (×1.5 / ×0.8 / ×0.6)

Different knowledge types have different recall priority. This is a **multiplier** on the base relevance, not an additive bonus:

| Type | Boost | Rationale |
|------|-------|-----------|
| `anti-pattern` | ×1.5 | Mistakes are the most valuable to recall — find them before you repeat them |
| `strategy` | ×0.8 | Strategies are useful but less urgent than mistakes |
| `concept` | ×0.6 | Concepts are background knowledge — lowest priority |

### 5. Review Penalty (+2.0 / +1.0)

Pages from failed decisions or negative outcomes get a boost, because you want to recall what went wrong:

- `decision_correct = false`: **+2.0**
- `outcome = failure`: **+1.0**

This seems counterintuitive — why boost "bad" knowledge? Because the most valuable knowledge is often "we tried X and it didn't work." Recalling failures prevents repeating them.

### 6. Memory Curve (×0.5)

The memory curve applies a time-decay multiplier based on the page's age, access count, and importance:

```
curve = importance × e^(-λ × days_old) + 0.5 × ln(1 + access_count) + pin_bonus
```

- Active pages get ×1.2 multiplier
- Archived/dropped pages get 0.0 (excluded from recall)
- Well-used pages (high access_count) resist decay
- Pinned pages get +0.5 bonus

See [Decay System](decay-system.md) for the full curve formula.

## Two-Path Recall

| Path | Source | Scoring |
|------|--------|---------|
| **Episodic** | `raw/` + `profiles/` | Keyword + freshness (`0.95^days_old`) |
| **Knowledge** | `wiki/` | 6-factor relevance + memory curve |
| **Combined** | Both | `{"episodic": [...], "knowledge": [...]}` |

```bash
# Episodic only (raw materials)
oks search "authentication" --source raw

# Knowledge only (wiki pages)
oks search "authentication" --source wiki

# Both paths (default)
oks recall "authentication" --limit 5
```

## Implementation

Source: `cli/knowledge_studio/recall.py`

Key functions:
- `recall_episodic(query)` — searches raw/ by keyword + freshness
- `recall_knowledge(query, topic_id)` — scores all wiki/ pages via 6 factors
- `recall(query, topic_id)` — combines both paths

## Next Steps

* **[Memories](memories.md)**: Memory anatomy, types, and creation paths
* **[Decay System](decay-system.md)**: Memory curve formula and tier classification
* **[Architecture](architecture.md)**: Five-bucket structure
