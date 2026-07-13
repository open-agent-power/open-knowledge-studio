---
title: Shared Constants
type: concept
status: active
importance: 0.7
confidence: 0.8542
created: '2026-07-11'
pinned: false
archived: false
access_count: 0
---




# fix-string-drift-constant-extraction

## Symptom

- A string literal (e.g. event type, status code, protocol field) is hardcoded in multiple files
- One copy is updated but others remain stale → silent mismatch
- Tests pass because they test each file in isolation, not the cross-file contract
- Bugs are invisible until runtime (e.g. feedback never attached, messages never matched)

## Root Cause

When the same string value is duplicated across files, there is no compile-time or test-time guarantee that all copies stay in sync. The pattern is especially dangerous for:

- Event type strings (producer writes `"llm.ai.response"`, consumer checks `"ai_message"`)
- Status codes / error codes
- Protocol field names
- Configuration keys

## Fix

Extract the string to a module-level constant in the producer module, then import it in all consumers:

```python
# producer.py (the source of truth)
AI_RESPONSE_EVENT_TYPE = "llm.ai.response"

class RunJournal:
    def on_llm_end(self, ...):
        self._put(event_type=AI_RESPONSE_EVENT_TYPE, ...)
```

```python
# consumer.py (imports the constant)
from producer import AI_RESPONSE_EVENT_TYPE

def list_thread_messages(...):
    if msg.get("event_type") == AI_RESPONSE_EVENT_TYPE:
        ...
```

## Detection

Search for duplicated string literals across files:
```bash
# Find strings that appear in multiple files
grep -rn '"llm\.ai\.response"' src/ backend/
# Or for any repeated string patterns
grep -rn 'event_type.*==' src/ | sort -t'"' -k2 | uniq -f2 -d
```

## Prevention

- Never hardcode the same string in more than one file
- When fixing a string mismatch bug, always extract to a constant (not just fix one copy)
- Reviewers should flag duplicated string literals in PR reviews
- Consider using an enum for bounded sets of values (event types, status codes)
