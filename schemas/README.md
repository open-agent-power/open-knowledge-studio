# Raw Bundle Schemas

The canonical JSON schemas live in [the CLI package](../cli/knowledge_studio/schemas/).
Runtime readers use `importlib.resources.files("knowledge_studio.schemas")`.

Builds generate bundled references under `knowledge_studio/_assets/_meta/schemas/`
from that package source. New knowledge instances use the installed tool schemas;
`oks init --upgrade` preserves any existing instance schemas.
