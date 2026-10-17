import importlib, os, stat, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ui'))
kit_db = importlib.import_module('kit_db')
kit_render = importlib.import_module('kit_render')


def inbound(**kw):
    row = {'port': 2088, 'uuid': 'uuid-1', 'exit_ip': '149.28.240.154', 'exit_tag': 'USA2', 'network': 'tcp',
           'remark': 'phone', 'flow': 'xtls-rprx-vision', 'pbk': 'PUB', 'sid': 'ab', 'sni': 'dl.google.com',
           'xhttp_json': '{}', 'grpc_service': '', 'grpc_multi': 0}
    row.update(kw)
    return row


class DbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_env = os.environ.get('KIT_DATA_DIR')
        os.environ['KIT_DATA_DIR'] = self.tmp.name
        self.conn = kit_db.connect(Path(self.tmp.name) / 'kit.db')

    def tearDown(self):
        self.conn.close()
        if self.old_env is None:
            os.environ.pop('KIT_DATA_DIR', None)
        else:
            os.environ['KIT_DATA_DIR'] = self.old_env
        self.tmp.cleanup()

    def test_tables_and_version(self):
        names = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({'nl_settings', 'inbounds', 'jobs', 'rules', 'kv', 'active'} <= names)
        self.assertEqual(self.conn.execute('PRAGMA user_version').fetchone()[0], 2)
        cols = {r[1] for r in self.conn.execute('PRAGMA table_info(nl_settings)')}
        self.assertNotIn('ssh_key_path', cols)

    def test_file_modes_and_idempotent_migrate(self):
        path = Path(self.tmp.name) / 'kit.db'
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        kit_db.migrate(self.conn)
        self.assertEqual(self.conn.execute('PRAGMA user_version').fetchone()[0], 2)

    def test_seeding_once(self):
        self.assertEqual(len(kit_db.get_rules(self.conn)), len(kit_render.DEFAULT_RULES))
        self.assertEqual(kit_db.get_match(self.conn), 'PROXY')
        self.conn.execute('DELETE FROM rules')
        self.conn.commit()
        path = Path(self.tmp.name) / 'kit.db'
        self.conn.close()
        self.conn = kit_db.connect(path)
        self.assertEqual(kit_db.get_rules(self.conn), [])

    def test_replace_rules_and_match(self):
        rules = [{'type': 'DOMAIN', 'value': 'a.example', 'policy': 'DIRECT', 'no_resolve': False,
                  'enabled': True, 'note': ''},
                 {'type': 'GEOIP', 'value': 'RU', 'policy': 'DIRECT', 'no_resolve': True,
                  'enabled': False, 'note': 'n'}]
        kit_db.replace_rules(self.conn, rules, 'REJECT')
        got = kit_db.get_rules(self.conn)
        self.assertEqual([r['value'] for r in got], ['a.example', 'RU'])
        self.assertEqual(got[1]['no_resolve'], True)
        self.assertEqual(got[1]['enabled'], False)
        self.assertEqual(kit_db.get_match(self.conn), 'REJECT')

    def test_active_set_get(self):
        self.assertIsNone(kit_db.get_active(self.conn))
        kit_db.upsert_inbounds(self.conn, [inbound()])
        iid = kit_db.list_inbounds(self.conn)[0]['id']
        kit_db.set_active(self.conn, iid, 3)
        self.assertEqual(kit_db.get_active(self.conn)['generation'], 3)
        self.assertEqual(kit_db.get_active(self.conn)['inbound_id'], iid)

    def test_upsert_keeps_check_values(self):
        kit_db.upsert_inbounds(self.conn, [inbound()])
        iid = kit_db.list_inbounds(self.conn)[0]['id']
        kit_db.set_check(self.conn, iid, True, '149.28.240.154', None)
        kit_db.upsert_inbounds(self.conn, [inbound(remark='new')])
        row = kit_db.get_inbound(self.conn, iid)
        self.assertEqual(row['check_ok'], 1)
        self.assertEqual(row['remark'], 'new')

    def test_public_inbound_allowlist(self):
        kit_db.upsert_inbounds(self.conn, [inbound()])
        row = kit_db.list_inbounds(self.conn)[0]
        pub = kit_db.public_inbound(row, True, active=True)
        self.assertEqual(set(pub), set(kit_db.PUBLIC_INBOUND_KEYS))
        for secret in ('uuid', 'pbk', 'sid', 'sni', 'xhttp_json', 'grpc_service'):
            self.assertNotIn(secret, pub)
        self.assertEqual(pub['network_label'], 'TCP+Vision')
        self.assertTrue(pub['active'])
        self.assertEqual(kit_db.public_inbound(dict(row, network='tcp', flow=''), False)['network_label'], 'TCP')
        self.assertEqual(kit_db.public_inbound(dict(row, network='grpc'), False)['network_label'], 'gRPC')
        self.assertEqual(kit_db.public_inbound(dict(row, network='xhttp'), False)['network_label'], 'XHTTP')

    def test_newer_db_rejected(self):
        self.conn.execute('PRAGMA user_version = 99')
        with self.assertRaises(RuntimeError):
            kit_db.migrate(self.conn)


def imp(port, uuid, exit_ip='149.28.240.154', remark='r'):
    return {'port': port, 'uuid': uuid, 'exit_ip': exit_ip, 'exit_tag': '', 'network': 'tcp', 'remark': remark,
            'flow': 'xtls-rprx-vision', 'pbk': 'A' * 43, 'sid': 'abcd', 'sni': 'www.example.com', 'xhttp_json': '{}',
            'grpc_service': '', 'grpc_multi': 0, 'source': 'import', 'nl_host': '185.0.2.10'}


class ImportDbTests(unittest.TestCase):
    U1 = '11111111-2222-3333-4444-555555555501'
    U2 = '11111111-2222-3333-4444-555555555502'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ)
        os.environ['KIT_DATA_DIR'] = self.tmp.name
        self.conn = kit_db.connect(Path(self.tmp.name) / 'kit.db')

    def tearDown(self):
        self.conn.close()
        os.environ.clear()
        os.environ.update(self.env)
        self.tmp.cleanup()

    def test_v1_database_migrates_to_v2_with_defaults(self):
        import sqlite3
        path = Path(self.tmp.name) / 'v1.db'
        raw = sqlite3.connect(str(path))
        raw.executescript(kit_db.V1_SQL)
        raw.execute("INSERT INTO inbounds (port, uuid, exit_ip, network, pbk, sid, sni, discovered_at) "
                    "VALUES (2088, ?, '149.28.240.154', 'tcp', 'P', 's', 'n', '2026-10-16T00:00:00Z')", (self.U1,))
        raw.execute('PRAGMA user_version = 1')
        raw.commit()
        raw.close()
        conn = kit_db.connect(path)
        try:
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 2)
            row = conn.execute('SELECT source, nl_host FROM inbounds').fetchone()
            self.assertEqual((row['source'], row['nl_host']), ('discover', ''))
        finally:
            conn.close()

    def test_replace_imported_keeps_ids_and_checks(self):
        kit_db.replace_imported(self.conn, [imp(2088, self.U1), imp(2089, self.U2)])
        ids = {(r['port'], r['uuid']): r['id'] for r in kit_db.list_inbounds(self.conn)}
        kit_db.set_check(self.conn, ids[(2088, self.U1)], True, '149.28.240.154', None)
        result = kit_db.replace_imported(self.conn, [imp(2088, self.U1), imp(2089, self.U2)])
        self.assertEqual(result, {'total': 2, 'removed': 0})
        again = {(r['port'], r['uuid']): r for r in kit_db.list_inbounds(self.conn)}
        self.assertEqual(again[(2088, self.U1)]['id'], ids[(2088, self.U1)])
        self.assertEqual(again[(2088, self.U1)]['check_ok'], 1)

    def test_replace_imported_removes_missing_and_nulls_active(self):
        kit_db.replace_imported(self.conn, [imp(2088, self.U1), imp(2089, self.U2)])
        ids = {(r['port'], r['uuid']): r['id'] for r in kit_db.list_inbounds(self.conn)}
        kit_db.set_active(self.conn, ids[(2089, self.U2)], 1)
        result = kit_db.replace_imported(self.conn, [imp(2088, self.U1)])
        self.assertEqual(result['removed'], 1)
        self.assertIsNone(kit_db.get_active(self.conn)['inbound_id'])

    def test_conflict_with_discovered_row_raises_and_rolls_back(self):
        kit_db.upsert_inbounds(self.conn, [{'port': 2088, 'uuid': self.U1, 'exit_ip': '149.28.240.154', 'exit_tag': 'USA2',
                                            'network': 'tcp', 'remark': 'd', 'flow': '', 'pbk': 'D' * 43, 'sid': 'ab',
                                            'sni': 'd.example.com', 'xhttp_json': '{}', 'grpc_service': '', 'grpc_multi': 0}])
        before = [dict(r) for r in kit_db.list_inbounds(self.conn)]
        with self.assertRaises(kit_db.ImportConflict) as ctx:
            kit_db.replace_imported(self.conn, [imp(2089, self.U2), imp(2088, self.U1)])
        self.assertEqual(ctx.exception.index, 2)
        self.assertEqual([dict(r) for r in kit_db.list_inbounds(self.conn)], before)

    def test_discovery_does_not_hide_import_rows(self):
        kit_db.replace_imported(self.conn, [imp(2089, self.U2)])
        kit_db.upsert_inbounds(self.conn, [])
        row = kit_db.list_inbounds(self.conn)[0]
        self.assertEqual((row['source'], row['present']), ('import', 1))

    def test_public_inbound_has_source_and_no_nl_host(self):
        kit_db.replace_imported(self.conn, [imp(2089, self.U2)])
        row = kit_db.list_inbounds(self.conn)[0]
        public = kit_db.public_inbound(row, True)
        self.assertEqual(public['source'], 'import')
        self.assertNotIn('nl_host', public)
        self.assertNotIn('pbk', public)


if __name__ == '__main__':
    unittest.main()
