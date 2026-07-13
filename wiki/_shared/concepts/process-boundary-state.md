---
title: Process Boundary State
type: concept
status: active
importance: 0.7
confidence: 0.8
created: '2026-07-11'
pinned: false
archived: false
access_count: 0
---

# fix-process-boundary-module-state

## Symptom

- A function returns correct data when called from within the server (Gateway, daemon, etc.)
- The same function returns empty/null/undefined when called from a CLI tool
- The fix "looks correct" (passing the right arguments) but doesn't actually solve the problem
- AI reviewer (like ClawSweeper) flags: "this helper only sees module-local state populated by server handlers"

## Root Cause

Module-level mutable state (e.g. `const remoteNodes = new Map()`) is:
- Populated by the server process's event handlers (connection handlers, startup routines)
- Empty in a separate CLI process that imports the same module
- Not shared between processes — each process has its own module instance

When the CLI calls `getRemoteSkillEligibility()` which reads from `remoteNodes`, it gets `undefined` because the CLI process never ran the connection handlers that populate the map.

## Diagnosis

Check if the function reads from module-level state:

```bash
# Search for module-level mutable declarations
grep -n "^const.*= new Map\|^const.*= new Set\|^let .*\|^var .*" src/module.ts
# Check what populates the state
grep -n "\.set(\|\.add(\|\.delete(" src/module.ts
```

If the populating code is called by server event handlers (not by the module itself), the state is process-local.

## Fix

Use "remote-first, local-fallback" pattern:

```typescript
async function loadData(): Promise<Data> {
  // 1. Try to get data from the server process (has full state)
  try {
    const serverData = await callGateway("method.name", opts, params);
    if (serverData) return serverData;
  } catch {
    // Gateway unreachable — fall through to local
  }

  // 2. Fall back to local (may have incomplete state, but works offline)
  return buildLocalData();
}
```

### Key elements:
- **Try RPC first**: the server process has the complete state
- **Catch transport errors only**: don't catch auth errors or logical errors
- **Timeout**: use a short timeout (e.g. 1500ms) so the CLI doesn't hang when the server is down
- **Silent fallback**: don't log errors for the fallback — it's expected when the server is offline

## Prevention

- Before calling a function from a different process (CLI → server module), check if it depends on module-level mutable state
- If it does, use RPC/IPC to call the server instead
- The "Gateway-first, local-fallback" pattern is common in well-architected projects — look for existing examples (e.g. `logs-cli.ts` in openclaw)
