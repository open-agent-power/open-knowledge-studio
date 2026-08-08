# Recipe: Text

source_type: text
description: Plain text, Markdown, CSV files. Zero-dependency read.

required_capabilities:
  - document.text.extract

optional_capabilities:
  - metadata.fetch

complete_when:
  - full_text_content_available

remote_processing:
  policy_required: false

degradation:
  - priority: 1
    capability: document.text.extract
    condition: default
    note: "Direct text read. Text-read Provider (agent-native) for maximum fidelity."
  - priority: 2
    capability: human.supply
    condition: file_unreadable
notes: |
  Text files are the simplest source type.  Agent reads the file directly
  (provider: text-read or agent-runtime).  No external tools needed.
  Content hash is computed from raw bytes.  Locator uses kind=document.
