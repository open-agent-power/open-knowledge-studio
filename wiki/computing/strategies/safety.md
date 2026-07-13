---
title: Safety Conventions
area: autpilot
source: auto-promote
last_verified: '2026-06-27'
type: strategy
status: active
importance: 0.7
confidence: 0.8
created: '2026-06-27'
pinned: false
archived: false
access_count: 0
---

# Safety Conventions

> Auto-promoted from 9 learnings. Source: 20260627-destructive-action-prevention, 20260627-prevent-destructive-file-overwrites-14, 20260627-prevent-destructive-file-overwrites-10, 20260627-prevent-destructive-file-overwrites-11, 20260627-prevent-destructive-file-overwrites-5.

## Destructive Action Prevention
Agents must evaluate existing file contents before executing overwrite tasks to prevent accidental destruction of critical documentation. When a conflict between a generic test task and existing valuable data is detected, the agent should halt and request clarification.

## Prevent Destructive File Overwrites
Agents must evaluate the existing state of critical files like README.md before executing write operations. Overwriting important project documentation with test content is destructive and requires task clarification instead of blind execution.

## Prevent Destructive File Overwrites
Before overwriting existing files like README.md, verify their current content to avoid destroying important project documentation. When a task conflicts with existing critical data, pause and clarify requirements rather than executing blindly.

## Prevent Destructive File Overwrites
Before executing file creation or modification tasks, always check if the target file already exists and contains important data. Blindly overwriting files like README.md with test content can cause destructive data loss.

## Prevent Destructive File Overwrites
Blindly executing instructions to overwrite existing files like README.md can destroy important project documentation. Always verify file contents and clarify tasks before performing potentially destructive actions.
