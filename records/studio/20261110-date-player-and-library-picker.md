# Studio date navigation, replay scrubber and folder selection

Requested behavior: remove the Skill detail workflow panel; add adjacent-day navigation; replace the standalone current-state button with a scrubber whose endpoint is live; retain the existing stage text cards and synchronize both selection directions. Personal and team labels come from folder names; native selection only fills the path until the user applies it.

## Local checks

- JavaScript suite: 38 passed, including stale history responses, dirty-edit guards, continuous playback, pause/resume, startup cancellation, live endpoint, stage-card selection, date boundaries and folder selection cancellation/read-only behavior.
- Targeted Python tests: 53 passed (`test_studio_libraries.py`, `test_studio_timeline.py`, `test_mail_reader.py`). Native picker subprocess behavior was simulated for success/cancel/error; its HTTP entry was checked for local-edit, same-origin, stale-instance and duplicate-dialog protection. No native dialog was opened during automation.
- Real browser: adjacent-day navigation, mouse dragging the Goal scrubber, historical read-only mode, endpoint restoring add controls, playback pause, default last-card highlight and folder-derived labels. Skill detail no longer renders its workflow panel.
- Source installed into the local CLI; running loopback Studio serves the updated assets. No remote push, publication or repository configuration change.

The reusable timeline is shared by Discuss and Goal. It displays retained revisions only, compresses idle gaps for playback, rejects stale async frames, and returns to live files at the endpoint. The existing history API and source Markdown are unchanged. Native folder selection runs a fixed command on the server desktop with a timeout and cancellation handling; it does not install tools or change knowledge-base settings by itself. Manual path input remains available.
