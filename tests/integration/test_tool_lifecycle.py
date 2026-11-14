#!/usr/bin/env python3
"""Exercise lifecycle routing and purge boundaries without network or real tools."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HELPER = Path(__file__).resolve().parents[2] / 'misc' / 'mymc-tool'
MOCK = r'''#!/usr/bin/python3
import json, os, subprocess, sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['MOCK_LOG'], 'a') as f:
    f.write(json.dumps([name, args]) + '\n')
if name == os.environ.get('MOCK_FAIL'):
    print('simulated failure', file=sys.stderr)
    sys.exit(42)
if name == 'npm':
    if args[:2] == ['root', '-g']:
        print(os.environ['MOCK_NPM_ROOT'])
    elif args[:1] == ['install'] and '--prefix' in args:
        prefix = Path(args[args.index('--prefix') + 1])
        package = args[-1].rsplit('@', 1)[0]
        binary = {'@earendil-works/pi-coding-agent':'pi', '@opencode/cli':'opencode', '@openai/codex':'codex'}[package]
        (prefix / 'bin').mkdir(parents=True, exist_ok=True)
        app = prefix / 'bin' / binary
        app.write_text(Path(__file__).read_text())
        app.chmod(0o755)
elif name == 'curl':
    if os.environ.get('MOCK_DOWNLOAD_FAIL'):
        sys.exit(22)
    path = Path(args[args.index('-o') + 1])
    path.write_text('echo installer-executed >> "$MOCK_INSTALL_LOG"\n')
elif name == 'hermes' and args[:1] == ['uninstall']:
    Path(sys.argv[0]).unlink()
elif name == 'sudo':
    sys.exit(subprocess.call(args[1:] if args[:1] == ['--'] else args))
'''


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        self.log = self.home / 'commands.jsonl'
        self.env = os.environ.copy()
        for key in ('HERMES_HOME', 'CLAUDE_CONFIG_DIR', 'CODEX_HOME', 'PI_CODING_AGENT_DIR',
                    'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'XDG_STATE_HOME'):
            self.env.pop(key, None)
        self.env.update(HOME=str(self.home), PATH=str(self.bin), MOCK_LOG=str(self.log),
                        MOCK_NPM_ROOT=str(self.home / 'global/node_modules'),
                        MOCK_INSTALL_LOG=str(self.home / 'installer.log'))
        for name in ('dirname', 'basename', 'readlink', 'mkdir', 'rm', 'mktemp', 'id'):
            (self.bin / name).symlink_to('/usr/bin/' + name)
        (self.bin / 'bash').symlink_to('/bin/bash')
        self.mock('npm')
        self.mock('curl')

    def tearDown(self):
        self.temp.cleanup()

    def mock(self, name, path=None):
        path = path or self.bin / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(MOCK)
        path.chmod(0o755)
        return path

    def run_helper(self, action, tool, plan=False, ok=True):
        result = subprocess.run(['/bin/sh', str(HELPER), *(['--plan'] if plan else []), action, tool],
                                env=self.env, text=True, capture_output=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_install_update_and_full_purge_private_npm(self):
        for tool in ('pi', 'opencode', 'codex'):
            with self.subTest(tool=tool):
                self.run_helper('install', tool)
                managed = self.home / '.local/share/mymc/tools' / tool
                self.assertTrue((managed / 'bin' / tool).is_file())
                data = self.home / ('.pi' if tool == 'pi' else '.' + tool)
                data.mkdir()
                secret = data / 'credentials-and-history'
                secret.write_text('do-not-print-this-secret')
                self.run_helper('update', tool)
                result = self.run_helper('purge', tool)
                self.assertFalse(managed.exists())
                self.assertFalse(data.exists())
                self.assertNotIn('do-not-print-this-secret', result.stdout + result.stderr)
        self.assertIn(['codex', ['logout']], self.commands())
        pi_install = next(c for c in self.commands() if c[0] == 'npm' and c[1][-1] == '@earendil-works/pi-coding-agent@latest')
        self.assertIn('--ignore-scripts', pi_install[1])

    def test_plan_does_not_install_or_delete(self):
        data = self.home / '.codex'
        data.mkdir()
        (data / 'auth.json').write_text('secret')
        self.run_helper('install', 'codex', plan=True)
        self.run_helper('purge', 'codex', plan=True)
        self.assertTrue((data / 'auth.json').exists())
        self.assertEqual(self.commands(), [])

    def test_already_installed_is_not_shadowed(self):
        self.run_helper('install', 'pi')
        result = self.run_helper('install', 'pi', ok=False)
        self.assertIn('Choose Update', result.stderr)

    def test_update_missing_tool_does_not_install(self):
        result = self.run_helper('update', 'codex', ok=False)
        self.assertIn('Choose Install', result.stderr)
        self.assertFalse(self.commands())

    def test_failed_package_install_does_not_report_success(self):
        self.env['MOCK_FAIL'] = 'npm'
        result = self.run_helper('install', 'opencode', ok=False)
        self.assertNotIn('Completed:', result.stdout)

    def test_global_npm_update_and_purge_use_original_package(self):
        package = self.home / 'global/node_modules/@mariozechner/pi-coding-agent'
        app = self.mock('pi', package / 'bin/pi')
        (self.bin / 'pi').symlink_to(app)
        self.run_helper('update', 'pi')
        self.run_helper('purge', 'pi')
        self.assertIn(['npm', ['install', '--global', '@mariozechner/pi-coding-agent@latest']], self.commands())
        self.assertIn(['npm', ['uninstall', '--global', '@mariozechner/pi-coding-agent']], self.commands())

    def test_unknown_installation_is_not_deleted(self):
        app = self.mock('opencode')
        data = self.home / '.opencode'
        data.mkdir()
        result = self.run_helper('purge', 'opencode', ok=False)
        self.assertIn('installation method not recognized', result.stderr)
        self.assertTrue(app.exists())
        self.assertTrue(data.exists())

    def test_symlinked_parent_cannot_redirect_purge(self):
        outside = self.home / 'keep'
        outside.mkdir()
        (outside / 'credentials').write_text('secret')
        (self.home / '.config').symlink_to(outside)
        self.run_helper('purge', 'opencode', ok=False)
        self.assertTrue((outside / 'credentials').exists())

    def test_data_home_outside_home_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as outside:
            self.env['CODEX_HOME'] = outside
            result = self.run_helper('purge', 'codex', ok=False)
            self.assertIn('outside HOME', result.stderr)
            self.assertTrue(Path(outside).exists())

    def test_purge_cannot_remove_home_via_repeated_slashes(self):
        self.env['CODEX_HOME'] = str(self.home) + '//'
        marker = self.home / 'keep-home'
        marker.write_text('keep')
        self.run_helper('purge', 'codex', ok=False)
        self.assertTrue(marker.exists())

    def test_symlinked_data_is_not_misreported_as_fully_purged(self):
        elsewhere = self.home / 'keep-data'
        elsewhere.mkdir()
        (elsewhere / 'credentials').write_text('secret')
        (self.home / '.codex').symlink_to(elsewhere)
        self.run_helper('purge', 'codex', ok=False)
        self.assertTrue((elsewhere / 'credentials').exists())

    def test_logout_failure_prevents_uninstall_and_data_loss(self):
        self.run_helper('install', 'codex')
        data = self.home / '.codex'
        data.mkdir()
        self.env['MOCK_FAIL'] = 'codex'
        self.run_helper('purge', 'codex', ok=False)
        self.assertTrue(data.exists())
        self.assertTrue((self.home / '.local/share/mymc/tools/codex/bin/codex').exists())

    def test_native_hermes_full_uninstall_and_data_removal(self):
        app = self.mock('hermes')
        data = self.home / '.hermes'
        data.mkdir()
        (data / 'history').write_text('private')
        self.run_helper('purge', 'hermes')
        self.assertFalse(app.exists())
        self.assertFalse(data.exists())
        self.assertIn(['hermes', ['uninstall', '--full', '-y']], self.commands())

    def test_native_claude_logout_and_purge(self):
        app = self.mock('claude', self.home / '.local/share/claude/versions/current')
        launcher = self.home / '.local/bin/claude'
        launcher.parent.mkdir(parents=True)
        launcher.symlink_to(app)
        (self.bin / 'claude').symlink_to(launcher)
        data = self.home / '.claude'
        data.mkdir()
        (self.home / '.claude.json').write_text('private')
        self.run_helper('purge', 'claude')
        self.assertFalse(data.exists())
        self.assertFalse(launcher.exists())
        self.assertFalse(app.exists())
        self.assertIn(['claude', ['auth', 'logout']], self.commands())

    def test_failed_https_download_is_never_executed(self):
        self.env['MOCK_DOWNLOAD_FAIL'] = '1'
        self.run_helper('install', 'hermes', ok=False)
        self.assertFalse((self.home / 'installer.log').exists())
        curl = next(c for c in self.commands() if c[0] == 'curl')
        self.assertIn('--proto', curl[1])
        self.assertNotIn('--insecure', curl[1])

    def test_tmux_package_install_uses_admin_wrapper(self):
        self.mock('apt-get')
        self.mock('sudo')
        # The simulated package install publishes tmux for the post-install readiness check.
        original = (self.bin / 'apt-get').read_text()
        (self.bin / 'apt-get').write_text(original + "\nif args[:1] == ['install']:\n    app = Path(os.environ['HOME']) / 'bin/tmux'\n    app.write_text(Path(__file__).read_text())\n    app.chmod(0o755)\n")
        self.run_helper('install', 'tmux')
        self.assertIn(['apt-get', ['update']], self.commands())
        self.assertIn(['apt-get', ['install', '-y', 'tmux']], self.commands())


if __name__ == '__main__':
    unittest.main()
