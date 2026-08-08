# Recipe: Office

source_type: office
description: DOCX, PPTX, XLSX, and HTML documents.

required_capabilities:
  - document.text.extract

optional_capabilities:
  - document.structure.extract
  - document.render
  - image.observe
  - chart.interpret
  - layout.understand

complete_when:
  - main_text_content_extracted
  - tables_preserved_when_present
  - slide_or_sheet_structure_accounted_for

remote_processing:
  policy_required: true

degradation:
  - priority: 1
    capability: document.text.extract
    condition: default
    note: "Extract text with structure. Handles DOCX, PPTX, XLSX."
  - priority: 2
    capability: document.structure.extract
    condition: tables_or_lists_detected
    note: "Structural extraction for complex layouts."
  - priority: 3
    capability: chart.interpret
    condition: chart_or_diagram_content
    note: "Chart interpretation — requires Agent vision capability."
  - priority: 4
    capability: human.supply
    condition: all_automated_failed
notes: |
  MarkItDown is the default local path (DOCX table structure preserved, PPTX
  list structure weaker than native, XLSX formulas lost).
  Firecrawl /parse is remote alternative (1 credit/file, ~1-3s).
  Complex layouts with formulas, embedded media, or charts need agent-runtime
  visual supplement (requires rendered pages — soffice/LibreOffice needed).
  Office 278MB dependency not in default lightweight install.
