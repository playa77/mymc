# Names for newly launched assistant sessions

Status: accepted, 2026-11-14. Supplements [0001](0001-terminal-tools.md).

## Context

The user requested predictable numbered tmux names for assistant sessions created
through mymc, without modifying session titles, existing sessions, or manual
renames. Several mymc instances can create sessions concurrently.

## Decision

The installed `mymc-session` helper creates assistant sessions with the lowest
available per-assistant number from 00 to 9999. The prefixes are `pi`,
`claude-code`, `hermes`, `opencode`, and `codex-cli`; both Codex executable
names share the latter prefix. Numbers above 99 expand naturally. Ordinary
shell sessions continue to use tmux's default naming. No renaming, title changes,
background process, or global tmux configuration is involved.

Creation uses tmux's atomic named-session creation, retrying only if the exact
candidate exists after a failure. Other errors are reported, not treated as
collisions. The helper returns the new session ID so existing attachment logic
continues to target the session independently of its name.

## Rationale and consequences

Choosing a name by listing sessions and then creating it alone would race with
other clients. Atomic creation and a bounded retry handle concurrent creators
without a shared lock or persistent state. Reusing vacant numbers is predictable
but does not assign a permanent identity to an assistant conversation. A
concurrent deletion after a collision may cause a safe, reported creation failure
rather than retry. The existing manual rename action continues to work.
