#!/usr/bin/env python3
"""Exercise assistant naming against a private tmux server; never touch user sessions."""
import concurrent.futures
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid

HELPER = Path(__file__).resolve().parents[2] / 'misc' / 'mymc-session'
TMUX = shutil.which('tmux')


@unittest.skipUnless(TMUX, 'tmux is required')
class SessionNamesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.socket = 'mymc-test-' + uuid.uuid4().hex
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        (self.bin / 'tmux').write_text('#!/bin/sh\nexec "{}" -L "$MYMC_TEST_SOCKET" -f /dev/null "$@"\n'.format(TMUX))
        (self.bin / 'tmux').chmod(0o755)
        for name in ('pi', 'claude', 'codex', 'codex-cli', 'hermes', 'opencode'):
            program = self.bin / name
            program.write_text('#!/bin/sh\nexec /bin/sleep 60\n')
            program.chmod(0o755)
        self.env = os.environ.copy()
        self.env.pop('TMUX', None)
        self.env.update(HOME=str(self.root), PATH=str(self.bin) + ':/usr/bin:/bin',
                        MYMC_TEST_SOCKET=self.socket)
        self.cwd = self.root / "folder ' $ ; é"
        self.cwd.mkdir()

    def tearDown(self):
        subprocess.run([TMUX, '-L', self.socket, 'kill-server'], env=self.env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        self.temp.cleanup()

    def tmux(self, *args):
        return subprocess.run([str(self.bin / 'tmux'), *args], env=self.env, text=True,
                              capture_output=True, check=True, timeout=10).stdout.strip()

    def launch(self, tool):
        return subprocess.run(['/bin/sh', str(HELPER), tool, str(self.cwd)], env=self.env,
                              text=True, capture_output=True, timeout=20)

    def names(self):
        return set(self.tmux('list-sessions', '-F', '#{session_name}').splitlines())

    def test_names_collision_and_existing_session_unchanged(self):
        self.tmux('new-session', '-d', '-s', 'pi-00', '-c', str(self.cwd), 'sleep 60')
        self.tmux('new-session', '-d', '-s', 'manual-name', '-c', str(self.cwd), 'sleep 60')
        self.tmux('select-pane', '-t', 'manual-name:0.0', '-T', 'custom title')
        for tool in ('pi', 'pi', 'claude', 'codex', 'codex-cli', 'hermes', 'opencode'):
            result = self.launch(tool)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertRegex(result.stdout.strip(), r'^\$\d+$')
        self.assertEqual(self.names(), {'pi-00', 'pi-01', 'pi-02', 'manual-name',
                                       'claude-code-00', 'codex-cli-00', 'codex-cli-01',
                                       'hermes-00', 'opencode-00'})
        self.assertEqual(self.tmux('display-message', '-p', '-t', 'manual-name:0.0',
                                   '#{pane_title}'), 'custom title')
        self.assertEqual(self.tmux('display-message', '-p', '-t', 'pi-01:0.0',
                                   '#{pane_current_path}'), str(self.cwd))

    def test_concurrent_creators_get_distinct_names(self):
        # Start the server first; all concurrent requests then use the same server.
        self.tmux('new-session', '-d', '-s', 'manual', 'sleep 60')
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(self.launch, ['pi'] * 8))
        self.assertTrue(all(r.returncode == 0 for r in results), [r.stderr for r in results])
        self.assertEqual(len({r.stdout.strip() for r in results}), 8)
        self.assertEqual(self.names(), {'manual'} | {f'pi-{i:02}' for i in range(8)})

    def test_invalid_tool_and_creation_failure(self):
        result = self.launch('not-a-tool')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unsupported assistant', result.stderr)
        (self.bin / 'tmux').write_text('#!/bin/sh\nprintf "simulated tmux failure\\n" >&2\nexit 1\n')
        result = self.launch('pi')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('simulated tmux failure', result.stderr)
        self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
