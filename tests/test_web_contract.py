import json, os, re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'web'
SRC = WEB / 'src'
ASSET_RE = re.compile(r'[A-Za-z0-9._-]+\.(js|css|svg|png|woff2)')
BANNED_SRC = ['dangerouslySetInnerHTML', 'innerHTML', 'eval(', 'new Function', 'localStorage', 'sessionStorage',
              'http://', 'https://', 'style={{']
DEPS = {
    '@radix-ui/react-checkbox': '1.3.11', '@radix-ui/react-dialog': '1.1.23', '@radix-ui/react-label': '2.1.15',
    '@radix-ui/react-select': '2.3.7', '@radix-ui/react-separator': '1.1.15', '@radix-ui/react-slot': '1.3.3',
    '@radix-ui/react-switch': '1.3.7', '@radix-ui/react-tabs': '1.1.21', '@radix-ui/react-tooltip': '1.2.16',
    'class-variance-authority': '0.7.1', 'clsx': '2.1.1', 'qrcode-generator': '2.0.4', 'react': '19.3.0',
    'react-dom': '19.3.0', 'tailwind-merge': '3.7.0',
}
DEV_DEPS = {'@tailwindcss/vite': '4.3.3', '@vitejs/plugin-react': '6.1.1', 'tailwindcss': '4.3.3', 'vite': '8.3.2'}
SCRIPT_RE = re.compile(r'<script\b([^>]*)>(.*?)</script>', re.S | re.I)
LINK_RE = re.compile(r'<link\b([^>]*)>', re.I)


def built_dir():
    env = os.environ.get('WEB_DIST')
    if env:
        return Path(env)
    default = WEB / 'dist'
    return default if (default / 'index.html').is_file() else None


class SourceContractTests(unittest.TestCase):
    def test_package_json_pins(self):
        pkg = json.loads((WEB / 'package.json').read_text(encoding='utf-8'))
        self.assertEqual(pkg['dependencies'], DEPS)
        self.assertEqual(pkg['devDependencies'], DEV_DEPS)
        for table in ('dependencies', 'devDependencies'):
            for name, version in pkg[table].items():
                self.assertFalse(version[:1] in '^~>', name)

    def test_lockfile_matches_root(self):
        lock = json.loads((WEB / 'package-lock.json').read_text(encoding='utf-8'))
        self.assertEqual(lock['lockfileVersion'], 3)
        root = lock['packages']['']
        self.assertEqual(root['dependencies'], DEPS)
        self.assertEqual(root['devDependencies'], DEV_DEPS)

    def test_vite_config_flags(self):
        text = (WEB / 'vite.config.js').read_text(encoding='utf-8')
        self.assertIn('polyfill: false', text)
        self.assertIn('@tailwindcss/vite', text)
        self.assertIn('sourcemap: false', text)

    def test_index_html_shape(self):
        html = (WEB / 'index.html').read_text(encoding='utf-8')
        self.assertEqual(html.count('<script type="module" src="/src/main.jsx"></script>'), 1)
        for match in SCRIPT_RE.finditer(html):
            self.assertIn('src=', match.group(1))
            self.assertEqual(match.group(2).strip(), '')
        self.assertNotIn('<style', html)
        self.assertIsNone(re.search(r'\son[a-z]+\s*=', html, re.I))

    def test_import_component_exists(self):
        self.assertTrue((SRC / 'components' / 'ImportLinks.jsx').is_file())

    def test_src_code_rules(self):
        files = [p for p in SRC.rglob('*') if p.is_file()]
        self.assertTrue(files)
        for path in files:
            text = path.read_text(encoding='utf-8')
            for banned in BANNED_SRC:
                self.assertFalse(banned in text, f'{banned} in {path.name}')


@unittest.skipUnless(built_dir(), 'no built frontend (set WEB_DIST or run the web build)')
class BuiltOutputContractTests(unittest.TestCase):
    def setUp(self):
        self.dist = built_dir()
        self.html = (self.dist / 'index.html').read_text(encoding='utf-8')

    def test_scripts_and_links_point_to_assets(self):
        scripts = SCRIPT_RE.findall(self.html)
        self.assertTrue(scripts)
        for attrs, body in scripts:
            src = re.search(r'src="([^"]+)"', attrs)
            self.assertIsNotNone(src)
            self.assertTrue(src.group(1).startswith('/assets/'), src.group(1))
            self.assertEqual(body.strip(), '')
        for attrs in LINK_RE.findall(self.html):
            href = re.search(r'href="([^"]+)"', attrs)
            if href:
                self.assertTrue(href.group(1).startswith('/assets/'), href.group(1))
        self.assertNotIn('<style', self.html)
        self.assertIsNone(re.search(r'\son[a-z]+\s*=', self.html, re.I))
        self.assertNotIn('//', self.html)
        self.assertNotIn('http', self.html)

    def test_referenced_files_exist_and_names_allowed(self):
        for ref in re.findall(r'(?:src|href)="(/assets/[^"]+)"', self.html):
            self.assertTrue((self.dist / ref.lstrip('/')).is_file(), ref)
        for path in (self.dist / 'assets').iterdir():
            self.assertTrue(ASSET_RE.fullmatch(path.name), path.name)

    def test_no_sourcemaps_and_no_eval(self):
        self.assertEqual(list(self.dist.rglob('*.map')), [])
        for path in (self.dist / 'assets').glob('*.js'):
            text = path.read_text(encoding='utf-8')
            self.assertFalse('eval(' in text, path.name)
            self.assertFalse('new Function' in text, path.name)


if __name__ == '__main__':
    unittest.main()
