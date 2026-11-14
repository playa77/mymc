# mymc release candidate — Ubuntu/Xubuntu 26.04 amd64

This is a **test release candidate**, not a final release. mymc is a terminal
file manager based on GNU Midnight Commander; its familiar interface now has a
Tools menu for tmux and terminal assistants.

## Highlights

- Manage tmux sessions from **F9 → Tools → Sessions**: list, attach, create,
  rename, detach clients, or stop a session. A status-line hint shows how to
  detach while leaving the session running.
- Discover and launch Hermes, Pi, OpenCode, Claude Code, and Codex CLI in tmux.
  Discovery runs in the background.
- Newly launched assistant sessions receive the lowest available numbered name,
  for example `pi-00`, `pi-01`, or `claude-code-00`. Existing sessions, manual
  names, and titles are not changed. Ordinary shell sessions retain tmux's
  default naming.
- Install, update, or purge supported tools through the Tools menu, with
  confirmation before destructive operations. **Purge removes supported tool
  settings, credentials, and history as well as the program.** Review its
  preview carefully.
- Default to nano while preserving explicit editor preferences and `EDITOR`.

## Install and run

Download `mymc_0.0~git20261114.0fa30caef-3_amd64.deb` and, from the directory
containing it, run:

```sh
sudo apt install ./mymc_0.0~git20261114.0fa30caef-3_amd64.deb
mymc
```

The package installs to `/opt/mymc` with a `/usr/bin/mymc` launcher and separate
`mymc` user configuration, data, and cache directories. It is designed to
coexist with the distribution's `mc` and `mc-data`; it does not migrate their
settings. tmux and nano are optional package suggestions and may need to be
installed separately. Assistant installation and maintenance may require
additional runtimes, external installers, or administrator privileges; see
[tests/README](tests/README).

## Artifact and provenance

- File: `mymc_0.0~git20261114.0fa30caef-3_amd64.deb`
- SHA-256: `4ade480f4772a6a55cd25369193817ade422ac6fd3dfa0554a5887114d87e55f`
- Target/build host: Ubuntu 26.04.1 LTS, amd64; intended for Ubuntu/Xubuntu
  26.04 amd64.
- Built from commit `0fa30caef` plus the then-uncommitted assistant session
  naming changes. The package build also changed `MC_USERCONF_DIR` from `mc`
  to `mymc` in its temporary source tree and configured `/opt/mymc` as its
  installation prefix. The checkout itself does not contain that build-time
  isolation change or a Debian packaging recipe; a normal source build is not
  equivalent to this package. The artifact's version string therefore does not
  identify a complete, reproducible source revision.

## Verification and limitations

- The preceding `-2` package was installed and launched by the tester. The
  `-3` candidate has **not** been installed or interactively tested; APT
  simulated its upgrade from `-2` without removals.
- A separate installation of the same modified source passed 19 terminal
  integration tests. The lifecycle suite passed 16 tests, and three naming
  tests passed against private tmux servers, including concurrent creation.
  Tests used fake assistant executables and did not exercise live assistant
  services or real vendor installation and removal.
- The package-target build and `make check` completed, but the Check framework
  was unavailable, so the full C unit suite was not run.
- This build uses ncurses and lacks optional SFTP VFS support, console GPM
  mouse support, and ext2 filesystem attribute support. It has not been tested
  on other architectures or Ubuntu releases.

Please report installation, terminal rendering, session-management, or
assistant-launch problems with the command used and `mymc --version` output.
Do not include credentials or private conversation contents.
