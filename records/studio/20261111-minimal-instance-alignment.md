# Minimal knowledge instance alignment

User direction: keep external materials as evidence/indexes, reusable judgments as Wiki and executable procedures as Skills; tool-owned schemas/templates should not be copied into every instance. Preserve personal/team ownership and existing user configuration.

## Implemented

- `init` no longer materializes top-level `_meta/` or `templates/`, author-specific team content, goals or example recipes. Existing custom directories are not removed.
- Existing settings and profile index/content survive `--upgrade`; missing defaults can still be added. Tool integration resources remain refreshable.
- `team init` creates a minimal team profile only when absent, keeps the folder name by default and does not invent an active goal or rewrite existing team content.
- The bundled context index, Raw intake rules and `oh-my-oks` explain selective source reading, source/evidence versus interpretation, declared Skill dependencies and retained failure history. No new top-level knowledge category.
- Instance layout documentation reflects Learning without date selection and current phase playback semantics.

## Validation

31 init/Skill bundle tests and 63 Raw commit tests passed. Skill structure validation and diff whitespace checks passed. No remote publication was performed.

## Intentionally unresolved

The legacy Raw episodic retrieval still scans Markdown/JSONL. Source manifests are not yet a unified searchable metadata index. This patch neither replaces that retrieval path nor claims lower latency or model cost. Evaluate metadata discovery and local evidence location against current retrieval before selecting the implementation.

WikiSkill-inspired automatic Skill evolution, held-out evaluation gating and cross-model transfer require separate validation; preserving a design principle is not evidence that those systems are implemented.
