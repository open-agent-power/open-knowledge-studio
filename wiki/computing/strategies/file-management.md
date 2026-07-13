---
title: File-Management Conventions
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

# File-Management Conventions

> Auto-promoted from 9 learnings. Source: 20260627-protect-existing-documentation, 20260627-prevent-destructive-file-overwrites-4, 20260627-prevent-destructive-file-overwrites-1, 20260627-prevent-destructive-file-overwrites-15, 20260627-prevent-destructive-file-overwrites-6.

## Preventing Destructive File Overwrites
When tasked with creating simple files like a test README, the agent must verify if the file already contains critical project documentation. Blindly overwriting existing files leads to destructive data loss, necessitating context-aware decision-making.

## Prevent Destructive File Overwrites
Overwriting critical project documentation files like README.md with test content is a destructive action that causes data loss. Agents must verify file importance and existence before applying overwrites to protect actual project documentation.

## Protect Existing Documentation
Overwriting existing files like README.md with test content is destructive. Always verify file contents before replacing them to preserve important project documentation.

## Prevent Destructive File Overwrites
Before executing file creation or overwrite tasks, the system must check if the target file already contains important project documentation. Blindly replacing existing files with test content like 'Hello World' can cause destructive data loss.

## Prevent Destructive File Overwrites
Blindly executing file creation tasks can overwrite and destroy existing critical project documentation like README.md. Always verify file existence and contents before performing write operations to avoid unintended data loss.
