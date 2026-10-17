"""Privilege drop for the kit container (J0).

The container starts as root only so that the read-only SSH key mount can be copied into tmpfs with
the right owner; then the process drops to uid/gid 10001 and keeps no capabilities. On the host and
in unit tests (not root) every function is a no-op or touches only the given paths.
"""
import os
from pathlib import Path


def copy_key(src, dst, uid=None, gid=None):
    """Copy key bytes to dst with mode 0600. The content is never logged."""
    data = Path(src).read_bytes()
    dst = Path(dst)
    dst.parent.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    os.chmod(dst, 0o600)
    if os.geteuid() == 0 and uid is not None and gid is not None:
        os.chmod(dst.parent, 0o700)
        os.chown(dst.parent, uid, gid)
        os.chown(dst, uid, gid)


def _own_top(path, uid, gid, mode=None):
    path = Path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = path.stat()
    if (st.st_uid, st.st_gid) == (uid, gid):
        return  # already ours; root without CAP_FOWNER cannot chmod it, and the image set the mode
    if mode is not None:
        os.chmod(path, mode)  # must run while still root-owned
    os.chown(path, uid, gid)


def should_copy_key(mount):
    """True when the mount is a regular, non-empty file. An empty docker/no-key placeholder is never copied."""
    try:
        return os.path.isfile(mount) and os.path.getsize(mount) > 0
    except OSError:
        return False


def key_needs_update(mount, key):
    """True when the key copy is missing or differs from the mount (avoids rewriting an identical copy on every start)."""
    try:
        return not (os.path.isfile(key) and Path(key).read_bytes() == Path(mount).read_bytes())
    except OSError:
        return True


def prepare_and_drop(uid=10001, gid=10001):
    if os.geteuid() != 0:
        return
    mount = os.environ.get('KIT_SSH_KEY_MOUNT', '/run/secrets/nl_ssh_key')
    key = os.environ.get('KIT_SSH_KEY_FILE', '/tmp/kit-ssh/id_nl')
    if should_copy_key(mount) and key_needs_update(mount, key):
        copy_key(mount, key, uid, gid)
    _own_top(os.environ.get('KIT_DATA_DIR', '/data'), uid, gid, 0o700)
    _own_top(os.environ.get('KIT_GEN_DIR', '/kit-gen'), uid, gid, 0o700)
    _own_top(os.environ.get('HOME', '/tmp/kit-home'), uid, gid, 0o700)
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)
    if os.getuid() == 0:
        raise SystemExit('Не удалось сбросить права root')
