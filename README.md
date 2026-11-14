# mymc

mymc is a terminal file manager based on GNU Midnight Commander. It retains
MC's familiar two-panel interface and adds a **Tools** menu for tmux sessions
and terminal-based AI assistants. It runs in a terminal emulator; it is not a
separate graphical desktop application.

## Ubuntu/Xubuntu 26.04 test package

The current release-candidate package targets **amd64** Ubuntu/Xubuntu 26.04:

```sh
sudo apt install ./mymc_0.0~git20261114.0fa30caef-3_amd64.deb
mymc
```

Download the `.deb` from the release assets first and run the install command
from its directory. APT can resolve its dependencies. Review the proposed
changes before accepting them.

This package installs under `/opt/mymc` and provides `/usr/bin/mymc`. It is
designed to coexist with the distribution's `mc` and `mc-data` packages. Its
user configuration, data, and cache live in the `mymc` directories under the
corresponding XDG locations (normally `~/.config/mymc`,
`~/.local/share/mymc`, and `~/.cache/mymc`). It does not import regular MC's
settings automatically. The package is a test build and does **not** include
SFTP virtual filesystem support. See [release notes](RELEASE_NOTES.md) for
artifact provenance, verification, and other limitations.

## Using Tools

1. Start `mymc` in a terminal and press **F9**.
2. Select **Tools** between **Command** and **Options**.
3. Choose **Sessions**, **Assistants**, or **Install / update / purge**.

Sessions can be listed, attached, created, renamed, detached, and stopped.
Assistant launches require tmux; supported assistants are Hermes, Pi,
OpenCode, Claude Code, and Codex CLI. Tool discovery happens in the background.
The tmux status line shows the detach shortcut; by default, press **Ctrl+b**,
release the keys, then press **d**. The session keeps running after detaching.

New assistant sessions launched from mymc use the lowest available numbered
name, such as `pi-00`, `pi-01`, or `claude-code-00`. Hermes, OpenCode, and
Codex CLI use `hermes`, `opencode`, and `codex-cli` prefixes; both Codex
executable names share a sequence. Existing sessions, manual names, and session
titles are not changed. Ordinary shell sessions use tmux's default naming.

The default editor is nano unless an existing editor preference or `EDITOR`
overrides it. Install nano separately if it is not present.

**Purge is destructive:** it removes the selected tool and its supported
settings, credentials, and history after confirmation. Review the preview
carefully. Installation and maintenance may invoke external installers or a
system package manager and may require administrator rights. See
[tests/README](tests/README) for prerequisites and ownership limitations.

## Building and testing from source

See [doc/INSTALL](doc/INSTALL) for dependencies, configuration options, and
build instructions. A checkout requires `./autogen.sh` before `configure`.
The standalone `.deb` above was assembled as a local test artifact; this
repository does not currently contain a Debian packaging recipe that
reproduces it. In particular, a normal source build does not automatically
use the package's isolated installation and user configuration paths.

For the unit and terminal-tool integration tests, see
[tests/README](tests/README). The Check framework is required for the full C
unit suite. The naming integration tests use a private tmux server.

## More information and license

The upstream MC overview is in [doc/README](doc/README), and project changes
are listed in [doc/NEWS](doc/NEWS). mymc is distributed under the
[GNU GPL version 3 or later](doc/COPYING).
