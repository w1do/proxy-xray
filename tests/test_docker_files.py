import os, re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DockerFileTests(unittest.TestCase):
    def setUp(self):
        self.compose = (ROOT / 'compose.yaml').read_text(encoding='utf-8')
        self.dockerfile = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
        self.dockerignore = (ROOT / '.dockerignore').read_text(encoding='utf-8').splitlines()

    def test_compose_forbidden_settings(self):
        for word in ('docker.sock', 'privileged', 'network_mode', 'pid:'):
            self.assertNotIn(word, self.compose, word)

    def test_compose_ports_loopback_only(self):
        lines = self.compose.splitlines()
        start = [i for i, l in enumerate(lines) if l.strip() == 'ports:']
        self.assertEqual(len(start), 2)
        published = []
        for i in start:
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith('- '):
                published.append(lines[j].strip())
                j += 1
        self.assertEqual(len(published), 2)
        for entry in published:
            self.assertTrue(entry.startswith('- "127.0.0.1:'), entry)

    def test_compose_key_defaults_to_placeholder(self):
        self.assertIn('source: ${KIT_SSH_KEY:-./docker/no-key}', self.compose)
        self.assertIn('create_host_path: false', self.compose)
        self.assertNotIn('${HOME}/.ssh', self.compose)
        self.assertEqual((ROOT / 'docker' / 'no-key').stat().st_size, 0)
        env = (ROOT / 'docker' / 'env.example').read_text(encoding='utf-8')
        self.assertIn('KIT_SSH_KEY', env)
        self.assertFalse([line for line in env.splitlines() if line.startswith('KIT_SSH_KEY=')])

    def test_compose_single_build_and_image(self):
        self.assertEqual(self.compose.count('build: .'), 1)
        self.assertIn('pull_policy: never', self.compose)
        self.assertIn('${KIT_IMAGE:-mihomo-proxy-kit:local}', self.compose)
        self.assertNotIn('depends_on', self.compose)
        env = (ROOT / 'docker' / 'env.example').read_text(encoding='utf-8')
        self.assertIn('KIT_IMAGE=mihomo-proxy-kit:local', env)

    def test_compose_hardening(self):
        self.assertIn('  read_only: true', self.compose)
        self.assertIn('read_only: true', self.compose.split('target: /run/secrets/nl_ssh_key')[1][:80])
        self.assertIn('cap_drop: [ALL]', self.compose)
        self.assertIn('create_host_path: false', self.compose)
        self.assertIn('restart: unless-stopped', self.compose)
        self.assertIn('no-new-privileges:true', self.compose)
        self.assertIn('cap_add: [CHOWN, SETUID, SETGID, DAC_READ_SEARCH]', self.compose)

    def test_dockerfile_pins(self):
        digests = [
            'a190708a2dec1bd18b1decb539f8e8f5407abaa9bf39cacda583f7f8c11db322',
            'bac1a74de365ea59270ba134016762c6be05654d55246518de256113bd1c225e',
            'ba3ce607747a07f948fc35780e108a4a7c7f552a38b9bd4d115f313ebcb89c20',
            '9dd862e28b46ff7d775f169cceebc28deccaa0a9e804237d421cd2571e0caba0',
            '72a5fde819713a103c6fc26a87aa025c1518c918a34eba4bc38d64dc0728e5d9',
            '58e339e67827220175b3a1c6f66f48ccd086b79209f30ba1c0bcb47885d4c22a',
            '3cf2236c19063c1c80803368cca5ff589c5033129fdf9ba154230c689b81fc2a',
            '76ad4ba5d45b1d35b57c3ef26a31c420f7e5afa1e03baf18a47f2d2c933f783b',
            'bff76f6b4d87c3a4c7d9612b926e762b21ba4fe2c5bf8c5a43af25fe8de71b7e',
        ]
        for digest in digests:
            self.assertIn(digest, self.dockerfile)
        self.assertIn('USER 10001:10001', self.dockerfile)
        self.assertNotIn('COPY . ', self.dockerfile)
        self.assertEqual(self.dockerfile.count('sha256sum -c -'), 3)

    def test_dockerignore_whitelist(self):
        self.assertEqual(self.dockerignore[0], '*')
        self.assertIn('!ui/', self.dockerignore)


class Amendment2dDockerTests(unittest.TestCase):
    def test_no_kit_run_references(self):
        for name in ('compose.yaml', 'Dockerfile'):
            text = (ROOT / name).read_text(encoding='utf-8')
            for word in ('kit-run', '/run-kit', 'KIT_RUN_DIR'):
                self.assertNotIn(word, text, f'{word} in {name}')

    def test_dockerfile_gen_and_state_dirs(self):
        text = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
        self.assertIn('KIT_GEN_DIR=/kit-gen', text)
        self.assertIn('KIT_STATE_DIR=/kit-state', text)
        self.assertIn('chown 10001:10001 /data /kit-gen /kit-state', text)

    def test_compose_volume_modes(self):
        import json, shutil, subprocess, tempfile
        if shutil.which('docker') is None:
            self.skipTest('docker not installed')
        with tempfile.TemporaryDirectory() as d:
            key = Path(d) / 'key'
            key.write_text('x')
            env = {k: v for k, v in os.environ.items() if k != 'KIT_SSH_KEY'}
            r = subprocess.run(['docker', 'compose', '-f', 'compose.yaml', 'config', '--format', 'json'],
                               cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                self.skipTest('docker compose unavailable: ' + r.stderr[:200])
            cfg = json.loads(r.stdout)
        def norm(vols):
            return [{k: v for k, v in x.items() if k != 'volume'} for x in vols]
        proxy, kit = dict(cfg['services']['proxy']), dict(cfg['services']['kit'])
        proxy['volumes'], kit['volumes'] = norm(proxy['volumes']), norm(kit['volumes'])
        self.assertIn({'type': 'volume', 'source': 'kit-gen', 'target': '/kit-gen', 'read_only': True}, proxy['volumes'])
        state_p = [v for v in proxy['volumes'] if v.get('target') == '/kit-state']
        self.assertEqual(len(state_p), 1)
        self.assertFalse(state_p[0].get('read_only', False))
        gen_k = [v for v in kit['volumes'] if v.get('target') == '/kit-gen']
        self.assertEqual(len(gen_k), 1)
        self.assertFalse(gen_k[0].get('read_only', False))
        self.assertIn({'type': 'volume', 'source': 'kit-state', 'target': '/kit-state', 'read_only': True}, kit['volumes'])
        self.assertEqual(sorted(cfg['volumes']), ['kit-data', 'kit-gen', 'kit-state'])
        key_bind = [v for v in kit['volumes'] if v.get('target') == '/run/secrets/nl_ssh_key']
        self.assertEqual(len(key_bind), 1)
        self.assertEqual(key_bind[0]['source'], str(ROOT / 'docker' / 'no-key'))
        self.assertTrue(key_bind[0].get('read_only'))
        for svc in (proxy, kit):
            self.assertTrue(svc.get('read_only'))
            self.assertEqual(svc.get('cap_drop'), ['ALL'])
            self.assertIn('no-new-privileges:true', svc.get('security_opt', []))
            for port in svc.get('ports', []):
                self.assertEqual(port.get('host_ip'), '127.0.0.1')


if __name__ == '__main__':
    unittest.main()
