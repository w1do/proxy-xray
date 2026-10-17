"""SQLite storage for the local web UI: schema, migrations and queries.

Data lives in $KIT_DATA_DIR (the kit-data volume in the container), or ${XDG_CONFIG_HOME:-~/.config}/mihomo-proxy-kit.
Secrets (uuid, pbk, sid, sni) are stored here but never returned by public_inbound().
"""
import os, sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 2

V1_SQL = """
CREATE TABLE nl_settings (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  host TEXT NOT NULL, ssh_user TEXT NOT NULL DEFAULT 'root',
  ssh_port INTEGER NOT NULL DEFAULT 22,
  updated_at TEXT NOT NULL);
CREATE TABLE inbounds (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  port INTEGER NOT NULL, uuid TEXT NOT NULL,
  exit_ip TEXT NOT NULL, exit_tag TEXT NOT NULL DEFAULT '',
  network TEXT NOT NULL CHECK (network IN ('xhttp','tcp','grpc')),
  remark TEXT NOT NULL DEFAULT '', flow TEXT NOT NULL DEFAULT '',
  pbk TEXT NOT NULL, sid TEXT NOT NULL, sni TEXT NOT NULL,
  xhttp_json TEXT NOT NULL DEFAULT '{}', grpc_service TEXT NOT NULL DEFAULT '',
  grpc_multi INTEGER NOT NULL DEFAULT 0,
  present INTEGER NOT NULL DEFAULT 1,
  discovered_at TEXT NOT NULL,
  check_ok INTEGER, check_ip TEXT, check_error TEXT, check_at TEXT,
  UNIQUE (port, uuid));
CREATE TABLE jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL CHECK (kind IN ('discover','check','install','apply_rules')),
  inbound_id INTEGER REFERENCES inbounds(id) ON DELETE SET NULL,
  status TEXT NOT NULL CHECK (status IN ('running','ok','failed')),
  started_at TEXT NOT NULL, finished_at TEXT,
  result_ip TEXT, summary TEXT NOT NULL DEFAULT '');
CREATE TABLE rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  position INTEGER NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('DOMAIN','DOMAIN-SUFFIX','DOMAIN-KEYWORD','GEOSITE','GEOIP','IP-CIDR')),
  value TEXT NOT NULL,
  policy TEXT NOT NULL CHECK (policy IN ('PROXY','DIRECT','REJECT')),
  no_resolve INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 1,
  note TEXT NOT NULL DEFAULT '',
  UNIQUE (type, value));
CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE active (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  inbound_id INTEGER REFERENCES inbounds(id) ON DELETE SET NULL,
  generation INTEGER NOT NULL, applied_at TEXT NOT NULL);
"""

V2_SQL = """
ALTER TABLE inbounds ADD COLUMN source TEXT NOT NULL DEFAULT 'discover' CHECK (source IN ('discover','import'));
ALTER TABLE inbounds ADD COLUMN nl_host TEXT NOT NULL DEFAULT '';
"""

MIGRATIONS = [V1_SQL, V2_SQL]


PUBLIC_INBOUND_KEYS = ('id', 'port', 'exit_ip', 'exit_tag', 'network', 'network_label', 'remark', 'flow',
                       'present', 'installable', 'active', 'check', 'source')


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def data_dir():
    base = os.environ.get('KIT_DATA_DIR')
    path = Path(base) if base else Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'mihomo-proxy-kit'
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def db_path():
    return data_dir() / 'kit.db'


def connect(path=None):
    path = Path(path) if path else db_path()
    if not path.exists():
        os.close(os.open(path, os.O_CREAT | os.O_WRONLY, 0o600))
    os.chmod(path, 0o600)
    conn = sqlite3.connect(str(path), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    migrate(conn)
    import kit_render  # lazy: kit_render does not import kit_db, but keep the dependency one-way at import time
    seed_rules(conn, kit_render.DEFAULT_RULES, kit_render.DEFAULT_MATCH)
    return conn


def migrate(conn):
    version = conn.execute('PRAGMA user_version').fetchone()[0]
    if version > len(MIGRATIONS):
        raise RuntimeError('База новее программы')
    for index in range(version, len(MIGRATIONS)):
        script = 'BEGIN;\n' + MIGRATIONS[index] + f'\nPRAGMA user_version = {index + 1};\nCOMMIT;'
        try:
            conn.executescript(script)
        except Exception:
            if conn.in_transaction:
                conn.execute('ROLLBACK')
            raise


def seed_rules(conn, defaults, match):
    """Insert the default rules once. Later deletions by the user are never re-seeded."""
    if conn.execute("SELECT 1 FROM kv WHERE key = 'rules_seeded'").fetchone():
        return
    with conn:
        for position, (rtype, value, policy, no_resolve) in enumerate(defaults):
            conn.execute('INSERT INTO rules (position, type, value, policy, no_resolve, enabled, note) '
                         'VALUES (?, ?, ?, ?, ?, 1, ?)',
                         (position, rtype, value, policy, 1 if no_resolve else 0, ''))
        conn.execute("INSERT OR REPLACE INTO kv (key, value) VALUES ('match_policy', ?)", (match,))
        conn.execute("INSERT INTO kv (key, value) VALUES ('rules_seeded', '1')")


def get_rules(conn):
    rows = conn.execute('SELECT type, value, policy, no_resolve, enabled, note FROM rules ORDER BY position, id').fetchall()
    return [{'type': r['type'], 'value': r['value'], 'policy': r['policy'], 'no_resolve': bool(r['no_resolve']),
             'enabled': bool(r['enabled']), 'note': r['note']} for r in rows]


def replace_rules(conn, rules, match):
    with conn:
        conn.execute('DELETE FROM rules')
        for position, rule in enumerate(rules):
            conn.execute('INSERT INTO rules (position, type, value, policy, no_resolve, enabled, note) '
                         'VALUES (?, ?, ?, ?, ?, ?, ?)',
                         (position, rule['type'], rule['value'], rule['policy'], 1 if rule['no_resolve'] else 0,
                          1 if rule['enabled'] else 0, rule['note']))
        conn.execute("INSERT OR REPLACE INTO kv (key, value) VALUES ('match_policy', ?)", (match,))


def get_match(conn):
    row = conn.execute("SELECT value FROM kv WHERE key = 'match_policy'").fetchone()
    return row[0] if row else 'PROXY'


def get_active(conn):
    row = conn.execute('SELECT inbound_id, generation, applied_at FROM active WHERE id = 1').fetchone()
    return dict(row) if row else None


def set_active(conn, inbound_id, generation):
    with conn:
        conn.execute('INSERT INTO active (id, inbound_id, generation, applied_at) VALUES (1, ?, ?, ?) '
                     'ON CONFLICT(id) DO UPDATE SET inbound_id = excluded.inbound_id, '
                     'generation = excluded.generation, applied_at = excluded.applied_at',
                     (inbound_id, generation, now()))


def get_nl(conn):
    row = conn.execute('SELECT host, ssh_user, ssh_port FROM nl_settings WHERE id = 1').fetchone()
    return dict(row) if row else None


def save_nl(conn, host, ssh_user, ssh_port):
    with conn:
        conn.execute(
            'INSERT INTO nl_settings (id, host, ssh_user, ssh_port, updated_at) VALUES (1, ?, ?, ?, ?) '
            'ON CONFLICT(id) DO UPDATE SET host=excluded.host, ssh_user=excluded.ssh_user, '
            'ssh_port=excluded.ssh_port, updated_at=excluded.updated_at',
            (host, ssh_user, ssh_port, now()))


def upsert_inbounds(conn, rows):
    """Store discovered inbounds. Keeps ids and check_* values; marks missing rows as not present."""
    stamp = now()
    new = 0
    with conn:
        conn.execute("UPDATE inbounds SET present = 0 WHERE source = 'discover'")
        for row in rows:
            existed = conn.execute('SELECT 1 FROM inbounds WHERE port = ? AND uuid = ?',
                                   (row['port'], row['uuid'])).fetchone()
            if not existed:
                new += 1
            conn.execute(
                'INSERT INTO inbounds (port, uuid, exit_ip, exit_tag, network, remark, flow, pbk, sid, sni, '
                'xhttp_json, grpc_service, grpc_multi, present, discovered_at) '
                'VALUES (:port, :uuid, :exit_ip, :exit_tag, :network, :remark, :flow, :pbk, :sid, :sni, '
                ':xhttp_json, :grpc_service, :grpc_multi, 1, :stamp) '
                'ON CONFLICT(port, uuid) DO UPDATE SET exit_ip=excluded.exit_ip, exit_tag=excluded.exit_tag, '
                'network=excluded.network, remark=excluded.remark, flow=excluded.flow, pbk=excluded.pbk, '
                'sid=excluded.sid, sni=excluded.sni, xhttp_json=excluded.xhttp_json, '
                'grpc_service=excluded.grpc_service, grpc_multi=excluded.grpc_multi, present=1, '
                'discovered_at=excluded.discovered_at, source=\'discover\', nl_host=\'\'',
                dict(row, stamp=stamp))
    return {'total': len(rows), 'new': new}


def replace_imported(conn, rows):
    """Replace all imported rows with `rows` in one transaction (deterministic). A link that duplicates a discovered
    (port, uuid) takes over that row (source becomes 'import')."""
    stamp = now()
    with conn:
        wanted = {(row['port'], row['uuid']) for row in rows}
        removed = 0
        for stale in conn.execute("SELECT id, port, uuid FROM inbounds WHERE source = 'import'").fetchall():
            if (stale['port'], stale['uuid']) not in wanted:
                conn.execute('DELETE FROM inbounds WHERE id = ?', (stale['id'],))
                removed += 1
        for row in rows:
            conn.execute(
                'INSERT INTO inbounds (port, uuid, exit_ip, exit_tag, network, remark, flow, pbk, sid, sni, '
                'xhttp_json, grpc_service, grpc_multi, present, discovered_at, source, nl_host) '
                'VALUES (:port, :uuid, :exit_ip, :exit_tag, :network, :remark, :flow, :pbk, :sid, :sni, '
                ':xhttp_json, :grpc_service, :grpc_multi, 1, :stamp, \'import\', :nl_host) '
                'ON CONFLICT(port, uuid) DO UPDATE SET exit_ip=excluded.exit_ip, exit_tag=excluded.exit_tag, '
                'network=excluded.network, remark=excluded.remark, flow=excluded.flow, pbk=excluded.pbk, '
                'sid=excluded.sid, sni=excluded.sni, xhttp_json=excluded.xhttp_json, '
                'grpc_service=excluded.grpc_service, grpc_multi=excluded.grpc_multi, present=1, '
                'discovered_at=excluded.discovered_at, source=\'import\', nl_host=excluded.nl_host',
                dict(row, stamp=stamp))
    return {'total': len(rows), 'removed': removed}


def list_inbounds(conn, present_only=True):
    sql = 'SELECT * FROM inbounds'
    if present_only:
        sql += ' WHERE present = 1'
    sql += ' ORDER BY exit_ip, port, id'
    return [dict(r) for r in conn.execute(sql).fetchall()]


def get_inbound(conn, inbound_id):
    row = conn.execute('SELECT * FROM inbounds WHERE id = ?', (inbound_id,)).fetchone()
    return dict(row) if row else None


def set_check(conn, inbound_id, ok, ip, error):
    with conn:
        conn.execute('UPDATE inbounds SET check_ok = ?, check_ip = ?, check_error = ?, check_at = ? WHERE id = ?',
                     (1 if ok else 0, ip, error, now(), inbound_id))


def create_job(conn, kind, inbound_id=None):
    with conn:
        cur = conn.execute("INSERT INTO jobs (kind, inbound_id, status, started_at) VALUES (?, ?, 'running', ?)",
                           (kind, inbound_id, now()))
    return cur.lastrowid


def finish_job(conn, job_id, status, result_ip, summary):
    with conn:
        conn.execute('UPDATE jobs SET status = ?, result_ip = ?, summary = ?, finished_at = ? WHERE id = ?',
                     (status, result_ip, summary, now(), job_id))


def list_jobs(conn, limit=20):
    return [dict(r) for r in conn.execute('SELECT * FROM jobs ORDER BY id DESC LIMIT ?', (limit,)).fetchall()]


def get_job(conn, job_id):
    row = conn.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()
    return dict(row) if row else None


def mark_stale_jobs(conn):
    with conn:
        conn.execute("UPDATE jobs SET status = 'failed', summary = 'Прервано перезапуском', finished_at = ? "
                     "WHERE status = 'running'", (now(),))


def prune_jobs(conn, keep=50):
    old = [r[0] for r in conn.execute('SELECT id FROM jobs ORDER BY id DESC LIMIT -1 OFFSET ?', (keep,)).fetchall()]
    if not old:
        return
    with conn:
        conn.executemany('DELETE FROM jobs WHERE id = ?', [(i,) for i in old])
    logs = data_dir() / 'logs'
    for job_id in old:
        try:
            (logs / f'job-{job_id}.log').unlink()
        except FileNotFoundError:
            pass


def network_label(row):
    if row['network'] == 'tcp':
        return 'TCP+Vision' if row.get('flow') else 'TCP'
    return {'xhttp': 'XHTTP', 'grpc': 'gRPC'}.get(row['network'], row['network'])


def public_inbound(row, installable, active=False):
    """Only the fields safe to send to the browser. Never uuid, pbk, sid, sni, xhttp_json, grpc_service."""
    ok = row.get('check_ok')
    return {
        'id': row['id'],
        'port': row['port'],
        'exit_ip': row['exit_ip'],
        'exit_tag': row['exit_tag'],
        'network': row['network'],
        'network_label': network_label(row),
        'remark': row['remark'],
        'flow': row['flow'],
        'present': bool(row['present']),
        'installable': bool(installable),
        'active': bool(active),
        'source': row.get('source') or 'discover',
        'check': {
            'ok': None if ok is None else bool(ok),
            'ip': row.get('check_ip'),
            'error': row.get('check_error'),
            'at': row.get('check_at'),
        },
    }
