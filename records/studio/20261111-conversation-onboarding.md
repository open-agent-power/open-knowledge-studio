# One-sentence setup and conversation onboarding

The public root SKILL.md remains the bootstrap URL. It now routes from environment/instance detection to the current host's daily oh-my-oks entry, optional independent team linking and a small real-user Discuss → Goal → Learning exercise.

## Changes

- `skills-install --global --editor codex|claude|agents` installs only the core entry without needing a KB. Existing packages stay intact unless force is explicit; force backs up the existing package first. CODEX_HOME is respected, linked destinations are rejected and other hosts are not claimed as supported global targets.
- `onboarding status|complete|skip|reset` shares records/studio/onboarding.json with Studio. Completion is teaching progress, not Wiki approval. Skip retains incomplete steps.
- The core Skill includes a first-use reference; installation documentation keeps one user-facing sentence. Existing users need not repeat the tutorial.
- The setup guide reuses sources link/list and VFS for separately committed team repositories. A Git URL is cloned separately when requested; it does not imply running code, overwriting a repository, automatic approval or remote push.
- The cloud contract checks installed command availability rather than assuming PyPI already includes main changes. Hooks, global Skill presence and actual host discovery remain separate acceptance steps.

## Verification and limits

55 tests passed across init, Skill bundles, onboarding CLI, Studio history and linked-source behavior. Tests include a temporary new-user flow with global entry, personal init, independent committed team linking, shared teaching completion and no Wiki/Draft fabrication. Both Skill entrypoints pass structure validation; diff whitespace check passed.

The local CLI was rebuilt. Existing personal onboarding state was read, not reset or completed. No real global host directory was overwritten by the tests. Cross-workspace host discovery and automatic recall require a live new-session acceptance; WorkBuddy global loading is not asserted. No cloud document edit, Git push or package release was performed.

## Shared-library follow-up

The user-facing prompt is now only “请按 <canonical SKILL.md URL> 安装OKS。” Setup details stay inside the contract. Init adds a minimal prerequisites README only when absent, preserving a user's existing one. `sources inspect` reads the committed README before registration; it does not execute instructions or install dependencies. Root README is available as a VFS reference and excluded from approved-knowledge retrieval. The default core entry is installed to host locations rather than also copied into a personal skills/ source folder.

57 related tests passed after this follow-up. A separate real local team repository adopted the core package, the personal source package was backed up and removed, and the existing federation successfully read its committed Skill and README. The selected host's global package was installed from that shared package and checked byte-for-byte; this is installation validation, not proof of new-session automatic discovery. Only a local team commit was created; no remote was pushed.
