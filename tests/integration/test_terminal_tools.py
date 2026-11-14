#!/usr/bin/env python3
"""PTY integration checks. Run after make install: MC_TEST_BINARY=/path/to/mc python3 this-file.

Uses fake terminal tools; never attaches to or creates real user sessions.
"""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import struct
import subprocess
import tempfile
import termios
import time
import unittest

BINARY = os.environ.get('MC_TEST_BINARY', '/workspace/mymc-install/bin/mc')
MOCK = '''#!/usr/bin/python3
import json, os, sys, time
from pathlib import Path
name = Path(sys.argv[0]).name
with open(os.environ['TOOL_LOG'], 'a') as f:
    f.write(json.dumps([name, sys.argv[1:]]) + '\\n')
if name == 'tmux' and sys.argv[1:2] == ['list-sessions']:
    time.sleep(float(os.environ.get('DISCOVERY_DELAY', '0')))
    sessions = json.loads(os.environ.get('SESSIONS', '[]'))
    for i, name in enumerate(sessions):
        print(('$%d\\t%s' if '-F' in sys.argv else '%d: %s') % (i, name))
    sys.exit(0 if sessions else 1)
if name == 'hermes' and sys.argv[1:2] == ['uninstall']:
    Path(sys.argv[0]).unlink()
if name == 'tmux' and '-P' in sys.argv:
    print('$42')
if name == 'tmux' and sys.argv[1:2] == ['show-options']:
    print('existing status')
'''


class MC:
    def __init__(self, root, tools=(), sessions=(), nested=False, delay=0, shortcut="TerminalSessions"):
        self.root = root
        self.bin = root / 'bin'
        self.bin.mkdir()
        self.log = root / 'commands.jsonl'
        for tool in tools:
            p = self.bin / tool
            p.write_text(MOCK)
            p.chmod(0o755)
        (self.bin / 'sh').symlink_to('/bin/sh')
        for name in ('dirname', 'basename', 'readlink', 'id', 'rm', 'mkdir', 'mktemp'):
            (self.bin / name).symlink_to('/usr/bin/' + name)
        self.folder = root / "project ' $cash; folder"
        self.folder.mkdir()
        (self.folder / 'sample.txt').write_text('sample\n')
        keymap = root / 'test.keymap'
        keymap.write_text(f'[filemanager]\n{shortcut}=f12\nQuitQuiet=f11\n')
        env = os.environ.copy()
        for key in ('EDITOR', 'VISUAL', 'TMUX', 'MC_SKIN'):
            env.pop(key, None)
        env.update(HOME=str(root), XDG_CONFIG_HOME=str(root / 'config'),
                   XDG_CACHE_HOME=str(root / 'cache'), XDG_DATA_HOME=str(root / 'data'),
                   PATH=str(self.bin), TERM='xterm-256color', LC_ALL='C.UTF-8',
                   TOOL_LOG=str(self.log), SESSIONS=json.dumps(sessions),
                   DISCOVERY_DELAY=str(delay))
        if nested:
            env['TMUX'] = '/tmp/fake,1,0'
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', int(os.environ.get('MC_TEST_ROWS', '40')),
                                                    int(os.environ.get('MC_TEST_COLS', '140')), 0, 0))
        self.p = subprocess.Popen([BINARY, '-u', '-x', '--keymap', str(keymap)],
                                  cwd=self.folder, env=env, stdin=slave, stdout=slave, stderr=slave)
        os.close(slave)
        self.output = b''
        self.wait(b'Quit')

    def send(self, keys):
        os.write(self.master, keys)

    def wait(self, text, timeout=8):
        deadline = time.monotonic() + timeout
        while text not in self.output and time.monotonic() < deadline:
            if select.select([self.master], [], [], .05)[0]:
                try:
                    self.output += os.read(self.master, 65536)
                except OSError:
                    break
        if text not in self.output:
            raise AssertionError(f'Missing {text!r}: {self.output[-2500:]!r}')

    def commands(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def wait_command(self, predicate):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if select.select([self.master], [], [], .01)[0]:
                try:
                    self.output += os.read(self.master, 65536)
                except OSError:
                    pass
            for command in self.commands():
                if predicate(command):
                    return command
            time.sleep(.05)
        raise AssertionError((self.commands(), self.output[-1800:]))

    def menu(self):
        self.wait_command(lambda c: c[0] == 'tmux' and c[1][:1] == ['list-sessions'])
        time.sleep(.15)
        self.output = b''
        self.send(b'\x1b[24~')  # F12
        self.wait(b'Sessions')
        self.wait(b'New session in this folder')
        time.sleep(.15)

    def assistants(self):
        self.wait_command(lambda c: c[0] == 'tmux')
        time.sleep(.15)
        self.output = b''
        self.send(b'\x1b[24~')  # F12
        self.wait(b'Assistants - new session')
        time.sleep(.15)

    def close(self):
        self.send(b'\x1b\x1b')
        time.sleep(.1)
        self.send(b'\x1b[23~')  # F11 / QuitQuiet
        try:
            self.p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.p.kill()
            self.p.wait()
        os.close(self.master)


class TerminalToolsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.mc = None

    def tearDown(self):
        if self.mc:
            self.mc.close()
        self.temp.cleanup()

    def start(self, **kwargs):
        self.mc = MC(self.root, **kwargs)
        return self.mc

    def test_discovery_does_not_block_startup(self):
        start = time.monotonic()
        m = self.start(tools=['tmux'], delay=3)
        self.assertLess(time.monotonic() - start, 2.5)
        m.send(b'\x1b[24~')
        m.wait(b'Checking installed tools')

    def test_no_tmux(self):
        m = self.start(tools=['hermes'])
        time.sleep(.2)
        m.send(b'\x1b[24~')
        m.wait(b'tmux is not installed')

    def test_empty_session_list_popup(self):
        m = self.start(tools=['tmux'])
        m.menu()
        self.assertNotIn(b'Attach tmux', m.output)
        m.send(b'\r')
        m.wait(b'No running sessions')

    def test_new_session_quoted_directory(self):
        m = self.start(tools=['tmux'])
        m.menu()
        m.send(b'\x1bOB\r')
        c = m.wait_command(lambda c: c[0] == 'tmux' and c[1][:1] == ['new-session'])
        self.assertEqual(c[1], ['new-session', '-d', '-P', '-F', '#{session_id}',
                                '-c', str(m.folder)])
        m.wait_command(lambda c: c[1] == ['attach-session', '-t', '$42'])
        m.wait_command(lambda c: c[1] == ['set-option', '-t', '$42', 'status-right',
                                        'Detach: #{s/C-/Ctrl+/;s/M-/Alt+/:prefix}, then d (session keeps running) | existing status'])
        m.wait_command(lambda c: c[1] == ['set-option', '-t', '$42', 'status', 'on'])

    def test_selected_directory(self):
        m = self.start(tools=['tmux'])
        directory = m.folder / "selected ' $folder"
        directory.mkdir()
        # Refresh, then select the first subdirectory after the parent entry.
        m.send(b'\x12\x1b[H\x1bOB')
        time.sleep(.15)
        m.menu()
        m.send(b'\x1bOB\r')
        c = m.wait_command(lambda c: c[1][:1] == ['new-session'])
        self.assertEqual(c[1][-2:], ['-c', str(directory)])

    def test_attach_one_session(self):
        m = self.start(tools=['tmux'], sessions=['work'])
        m.menu()
        m.send(b'\x1bOB\r')
        c = m.wait_command(lambda c: c[1][:1] == ['attach-session'])
        self.assertEqual(c[1], ['attach-session', '-t', '$0'])

    def test_choose_multiple_sessions(self):
        m = self.start(tools=['tmux'], sessions=['first', "second ' ; $name"])
        m.menu()
        m.send(b'\x1bOB\r')
        m.wait(b'Attach tmux session')
        m.send(b'\x1bOB\r')
        c = m.wait_command(lambda c: c[1][:1] == ['attach-session'])
        self.assertEqual(c[1], ['attach-session', '-t', '$1'])

    def test_assistant_and_nested_tmux(self):
        m = self.start(tools=['tmux', 'hermes'], nested=True, shortcut='TerminalAssistants')
        m.assistants()
        m.send(b'\r')
        c = m.wait_command(lambda c: c[1][:1] == ['new-session'])
        self.assertEqual(c[1], ['new-session', '-d', '-P', '-F', '#{session_id}',
                                '-s', 'hermes-00', '-c', str(m.folder), 'hermes'])
        m.wait_command(lambda c: c[1] == ['switch-client', '-t', '$42'])

    def test_only_installed_tools_shown(self):
        m = self.start(tools=['tmux', 'pi', 'opencode', 'claude', 'codex', 'codex-cli'], shortcut='TerminalAssistants')
        m.assistants()
        for tool in (b'Pi', b'OpenCode', b'Claude Code', b'Codex CLI'):
            m.wait(tool)
        self.assertNotIn(b'Hermes', m.output)
        self.assertNotIn(b'codex-cli', m.output)

    def manage_session(self, m, index=0):
        m.menu()
        m.send(b'\x1bOB' * 3 + b'\r')
        m.wait(b'Manage running sessions')
        time.sleep(.15)
        m.send(b'\x1bOB' * index + b'\r')
        m.wait(b'Stop session (ends running programs)')
        time.sleep(.15)

    def test_tools_root_has_clear_sections(self):
        m = self.start(shortcut='TerminalTools')
        m.send(b'\x1b[24~')
        m.wait(b'Install / update / purge')
        self.assertIn(b'Sessions...', m.output)
        self.assertIn(b'Assistants...', m.output)

    def test_management_available_without_tmux(self):
        m = self.start(shortcut='TerminalManage')
        time.sleep(.2)
        m.send(b'\x1b[24~')
        m.wait(b'Codex CLI')
        for label in (b'tmux', b'Hermes', b'Pi', b'OpenCode', b'Claude Code', b'Codex CLI'):
            self.assertIn(label, m.output)
        self.assertIn(b'not installed', m.output)

    def test_install_confirmation_can_be_cancelled(self):
        m = self.start(shortcut='TerminalManage')
        time.sleep(.2)
        m.send(b'\x1b[24~')
        m.wait(b'Codex CLI')
        time.sleep(.15)
        m.send(b'\x1bOB' * 5 + b'\r')
        m.wait(b'Installation details')
        time.sleep(.15)
        m.send(b'\r')
        m.wait(b'Confirm tool maintenance')
        m.wait(b'Private npm prefix')
        time.sleep(.15)
        m.send(b'\r')  # Cancel is the default.
        time.sleep(.15)
        self.assertFalse((self.root / '.local/share/mymc/tools/codex').exists())

    def open_hermes_purge(self):
        m = self.start(tools=['hermes'], shortcut='TerminalManage')
        data = self.root / '.hermes'
        data.mkdir()
        (data / 'credentials-and-history').write_text('private')
        time.sleep(.2)
        m.send(b'\x1b[24~')
        m.wait(b'Codex CLI')
        time.sleep(.15)
        m.send(b'\x1bOB\r')
        m.wait(b'Installation details')
        time.sleep(.15)
        m.send(b'\x1bOB\x1bOB\r')
        m.wait(b'Permanently purge tool and all data?')
        m.wait(b'stored credentials')
        time.sleep(.15)
        return m, data

    def test_purge_cancel_preserves_all_data(self):
        m, data = self.open_hermes_purge()
        m.send(b'\r')
        time.sleep(.2)
        self.assertTrue((data / 'credentials-and-history').exists())
        self.assertFalse(any(c[1][:1] == ['uninstall'] for c in m.commands()))

    def test_confirmed_purge_removes_program_and_data(self):
        m, data = self.open_hermes_purge()
        m.send(b'\t\r')
        m.wait_command(lambda c: c == ['hermes', ['uninstall', '--full', '-y']])
        m.wait(b'Operation finished (exit 0)')
        self.assertFalse(data.exists())
        self.assertFalse((m.bin / 'hermes').exists())
        m.send(b'\r')

    def test_session_rename_uses_exact_name(self):
        m = self.start(tools=['tmux'], sessions=["work ' ; $name"])
        self.manage_session(m)
        m.send(b'\x1bOB\r')
        m.wait(b'New session name:')
        time.sleep(.15)
        name = "renamed ' ; $folder"
        m.send(b'\x15' + name.encode() + b'\r')
        m.wait_command(lambda c: c[1] == ['rename-session', '-t', '$0', '--', name])

    def test_stop_session_requires_confirmation(self):
        m = self.start(tools=['tmux'], sessions=['work'])
        self.manage_session(m)
        m.send(b'\x1bOB' * 3 + b'\r')
        m.wait(b'Confirm session action')
        time.sleep(.15)
        m.send(b'\r')
        time.sleep(.2)
        self.assertFalse(any(c[1][:1] == ['kill-session'] for c in m.commands()))

    def test_stop_only_the_selected_session(self):
        m = self.start(tools=['tmux'], sessions=['first', 'second'])
        self.manage_session(m, 1)
        m.send(b'\x1bOB' * 3 + b'\r')
        m.wait(b'Confirm session action')
        time.sleep(.15)
        m.send(b'\t\r')
        m.wait_command(lambda c: c[1] == ['kill-session', '-t', '$1'])

    def test_detach_clients_keeps_session(self):
        m = self.start(tools=['tmux'], sessions=['work'])
        self.manage_session(m)
        m.send(b'\x1bOB' * 2 + b'\r')
        m.wait(b'Confirm session action')
        time.sleep(.15)
        m.send(b'\t\r')
        m.wait_command(lambda c: c[1] == ['detach-client', '-s', '$0'])
        self.assertFalse(any(c[1][:1] == ['kill-session'] for c in m.commands()))

    def test_nano_default(self):
        m = self.start(tools=['nano'])
        # End selects the final file in the panel, the only non-parent entry.
        m.send(b'\x1b[F')  # End
        m.send(b'\x1bOS')  # F4
        c = m.wait_command(lambda c: c[0] == 'nano')
        self.assertIn('sample.txt', ' '.join(c[1]))


if __name__ == '__main__':
    unittest.main()
