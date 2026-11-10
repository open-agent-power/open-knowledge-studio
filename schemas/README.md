# Raw Bundle Schemas

The canonical JSON schemas live in [the CLI package](../cli/knowledge_studio/schemas/).
Runtime readers use `importlib.resources.files("knowledge_studio.schemas")`.

Builds and `oks init` generate the instance copies under `_meta/schemas/`
from that package source.
