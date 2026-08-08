# Recipe: PDF

source_type: pdf
description: Digital and scanned PDF documents.

required_capabilities:
  - document.text.extract

optional_capabilities:
  - document.structure.extract
  - document.render
  - image.ocr
  - image.observe
  - layout.understand

complete_when:
  - all_pages_accounted_for
  - text_or_observation_present_for_each_page

remote_processing:
  policy_required: true

degradation:
  - priority: 1
    capability: document.text.extract
    condition: default
    note: "Any Provider with document.text.extract maturity ≥ validated."
  - priority: 2
    capability: image.ocr
    condition: text_layer_empty
    note: "Required when text extraction returns empty/no text layer."
  - priority: 3
    capability: image.observe
    condition: page_images_available
    note: "Agent visual observation when text extraction fails. Agent-runtime only."
  - priority: 4
    capability: layout.understand
    condition: table_or_chart_content_detected
  - priority: 5
    capability: human.supply
    condition: all_automated_failed
    note: "User provides content directly — human Provider only."

notes: |
  Digital PDFs with text layers → pdf-lite (33 pages / 82K chars / 6.3s verified).
  Scanned PDFs → pdf-lite returns partial (49 chars) → rapidocr for OCR bbox
  + agent-runtime for page semantics (4 claims, offline verified).
  Remote OCR (firecrawl) requires user policy approval.
  MinerU is heavy (~300MB) — user must explicitly install.
