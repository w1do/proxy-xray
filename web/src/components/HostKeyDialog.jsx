import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { Alert, AlertDescription } from './ui/alert.jsx';
import { Button } from './ui/button.jsx';
import { DialogContent, DialogDescription, DialogHeader, DialogTitle, Dialog } from './ui/dialog.jsx';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table.jsx';

// Scans the NL host key, shows the SHA256 fingerprints, and writes them to known_hosts only after the user confirms.
export default function HostKeyDialog({ onClose, onTrusted }) {
  const [scan, setScan] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    api('POST', '/api/nl/hostkey/scan', {})
      .then((d) => alive && setScan(d))
      .catch((e) => alive && setErr(e.message));
    return () => {
      alive = false;
    };
  }, []);

  async function confirm() {
    setBusy(true);
    setErr('');
    try {
      await api('POST', '/api/nl/hostkey/accept', { scan_id: scan.scan_id });
      onTrusted();
      onClose();
    } catch (e) {
      setErr(e.message);
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Ключ хоста NL</DialogTitle>
          <DialogDescription>Сравните отпечатки с ключом на сервере перед подтверждением.</DialogDescription>
        </DialogHeader>
        {!scan && !err && <p className="text-sm text-muted-foreground">Сканирование…</p>}
        {scan && (
          <div className="flex flex-col gap-3">
            <p className="text-sm">
              {scan.host}:{scan.port}
              {scan.already_trusted ? ' (уже подтверждён; подтверждение заменит записи)' : ''}
            </p>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Тип</TableHead>
                  <TableHead>Отпечаток SHA256</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {scan.keys.map((k) => (
                  <TableRow key={k.type}>
                    <TableCell>{k.type}</TableCell>
                    <TableCell className="font-mono text-xs break-all">{k.fingerprint}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <p className="text-xs text-muted-foreground">
              Сравните с <code>ssh-keygen -lF {scan.host}</code> на вашей машине или с{' '}
              <code>ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub</code> на NL.
            </p>
          </div>
        )}
        {err && <Alert variant="destructive" className="mt-3"><AlertDescription>{err}</AlertDescription></Alert>}
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Отмена</Button>
          <Button onClick={confirm} disabled={!scan || busy}>Подтвердить</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
