---
title: Trace Call Chain
type: concept
status: active
importance: 0.7
confidence: 0.8
created: '2026-07-11'
pinned: false
archived: false
access_count: 0
---

# fix-duplicate-cleanup-on-fix

## Symptom

- A PR reviewer points out that your fix runs an operation that's already performed by a function you call
- The operation is idempotent (so it doesn't crash), but it's redundant
- Common in cleanup/error-handling paths where multiple functions perform the same teardown

## Example

```typescript
// Original code: closeProcess calls killProcess, then does cleanup
function killProcess() {
    process.kill(pid, 'SIGKILL');
    deleteDirectory(dir);        // ← cleanup happens here
    removeEventListeners(listeners);
}

// Fix attempt: move cleanup to .then() to wait for exit
function closeProcess() {
    killProcess();  // ← already does deleteDirectory + removeEventListeners
    return processClosing.then(() => {
        deleteDirectory(dir);        // ← DUPLICATE!
        removeEventListeners(listeners);  // ← DUPLICATE!
    });
}
```

## Root Cause

When fixing a timing bug (e.g. "cleanup runs before process exits"), it's tempting to move cleanup into a callback. But if the function you're calling (`killProcess`) already performs cleanup, you end up running it twice.

## Fix

Trace the full call chain before modifying:

1. What does `killProcess()` do? → kills process + cleanup
2. What did the original `closeProcess()` do? → calls `killProcess()` + cleanup (redundant in original too!)
3. What should the fix do? → just wait for process exit, don't add more cleanup

```typescript
// Correct fix: killProcess already handles cleanup, just wait for exit
function closeProcess() {
    killProcess();  // handles kill + cleanup
    return processClosing;  // just wait for exit, no duplicate cleanup
}
```

## Detection

Before submitting a fix:
1. Read the function you're calling — what does it already do?
2. Check if your fix adds operations that are already performed
3. Search for duplicate calls: `grep -n "deleteDirectory\|removeEventListeners" file.ts`

## Prevention

- Always trace the call chain: who calls whom, and what does each function do?
- Don't add cleanup in a wrapper if the inner function already handles it
- If you need to change timing (wait for exit), just change the return value — don't move operations
