# Studio frontend

`studio.js` is the controller: routing, selected file scope, refresh and save.
It passes state and explicit actions to the view factories in this directory.

| File | Responsibility |
| --- | --- |
| `state.js` | Session-only UI state; no persisted knowledge |
| `api.js` | Instance-bound requests and edit capability |
| `dom.js` | Shared text-safe DOM constructors |
| `discussion.js` | Goal/context projection and progressive expansion |
| `graph.js` | SVG layout, gestures, resize and resource cleanup |
| `goals.js` | Markdown outline/editor view; source operations remain in `studio-model.js` |
| `learning.js` | Two Learning views: graph and parameters |
| `knowledge.js` | Graph interaction, right-side detail, draft review and refresh lifecycle |
| `knowledge-model.js` | Read-only hierarchy, visible edges, search and usage colour mapping |
| `settings.js` | Formula cards, recall parameters and non-persisting previews |
| `evaluation.js` | Dataset upload, whole-suite jobs, history, cases and controlled comparisons |
| `evaluation-charts.js` | Native SVG metric bars, empirical latency CDF and paired RR scatter |
| `formulas.js` | Pure budget/decay preview calculations, independent of DOM |

Component CSS lives alongside its view. Shared layout is in `studio.css`;
`studio-theme.css` owns the palette for both the shell and reused feature pages.
Do not copy a feature's data store into the UI or silently treat a read as approval.
