# Terminal tools and lifecycle management

Status: accepted for this implementation, 2026-11-13.

## Context

The session requests nano as the default editor, background discovery of tmux and
five assistants, launches in tmux, a visible beginner-friendly detach shortcut,
and install/update/purge and session-management actions. The user explicitly
clarified that purge includes settings, credentials, and history. Existing
editor choices and file-management workflows must remain available.

## Decision

Keep session and assistant actions in a dedicated Tools menu, split into
Sessions, Assistants, and Install / update / purge. Discover tools in a child
process and consume its output through MC's select channels so startup does not
wait for external commands. Use tmux session IDs and argument arrays or quoted
shell arguments; show the configured prefix in a session-local detach hint.

Separate the C interface from the installed POSIX-shell lifecycle helper.
Use recognized installation ownership for updates and removals. New npm-based
installs have private per-tool prefixes; Hermes and Claude Code use official
installers, and tmux uses a supported system package manager. Require explicit
confirmation for purge and stopping sessions. Purge logs Claude/Codex out before
uninstalling and rejects unsafe paths or unidentified installation ownership.

## Rationale and alternatives

A single mixed command list made everyday launches harder to distinguish from
maintenance. Separate sections retain the existing File/Command/Options menus.
Keeping lifecycle logic in a helper makes package routing and failure paths
independently testable without invoking real installers from UI tests.

Blindly deleting an executable or updating a guessed global package could affect
an unrelated installation. Recognized ownership and isolated new npm prefixes
bound those effects. Unknown layouts fail explicitly; they require the original
installer or package manager.

## Consequences and validation

Lifecycle actions require the appropriate external installer/runtime and may
require administrator rights for system packages. Native Pi removal delegates
to its interactive official installer and checks removal before deleting data.
Symlinked data locations and locations outside HOME require separate handling.

The existing C suite, PTY tests, and lifecycle fixtures cover discovery,
launching, cancellation, session selection, purge boundaries, and failure paths.
Real tmux smoke checks exercise the detach hint and selected-session management.
Vendor installations and real credential deletion were not executed.

Implementation: [tools.c](../../src/filemanager/tools.c),
[mymc-tool](../../misc/mymc-tool).
Usage and test commands: [tests/README](../../tests/README).
