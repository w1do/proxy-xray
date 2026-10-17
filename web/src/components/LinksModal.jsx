import { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import { Alert, AlertDescription } from './ui/alert.jsx';
import { Badge } from './ui/badge.jsx';
import { Button } from './ui/button.jsx';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card.jsx';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from './ui/dialog.jsx';
import { Input } from './ui/input.jsx';
import QrCode from './QrCode.jsx';

// The vless links live only in this component's state: cleared on close and dropped on unmount.
// Never stored in web storage, never logged, never placed in a URL.
export default function LinksModal({ exitIp, onClose }) {
  const [items, setItems] = useState([]);
  const [err, setErr] = useState('');

  useEffect(() => {
    let alive = true;
    api('GET', `/api/exits/${exitIp}/links`)
      .then((d) => alive && setItems(d.items))
      .catch((e) => alive && setErr(e.message));
    return () => {
      alive = false;
      setItems([]);
    };
  }, [exitIp]);

  function close() {
    setItems([]);
    onClose();
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open) close(); }}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Ссылки для клиентов</DialogTitle>
          <DialogDescription>Ссылка vless:// — это ключ доступа. Не передавайте её посторонним.</DialogDescription>
        </DialogHeader>
        {err && <Alert variant="destructive"><AlertDescription>{err}</AlertDescription></Alert>}
        <div className="flex flex-col gap-3">
          {items.map((item) => (
            <LinkItem key={item.id} item={item} />
          ))}
        </div>
        <div className="mt-5 flex justify-end">
          <Button variant="outline" onClick={close}>Закрыть</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function LinkItem({ item }) {
  const inputRef = useRef(null);
  const [note, setNote] = useState('');

  async function copy() {
    try {
      await navigator.clipboard.writeText(item.link);
      setNote('Скопировано');
    } catch {
      inputRef.current?.select();
      setNote('Выделено: нажмите Ctrl+C или Cmd+C');
    }
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-2">
        <CardTitle className="flex items-center gap-2">
          NL:{item.port}
          <Badge variant="outline">{item.network_label}</Badge>
        </CardTitle>
        <span className="text-xs text-muted-foreground">{item.remark}</span>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-start">
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <Input ref={inputRef} className="font-mono text-xs" readOnly value={item.link} onFocus={(e) => e.target.select()} />
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={copy}>Копировать</Button>
            <span className="text-xs text-muted-foreground">{note}</span>
          </div>
        </div>
        <QrCode value={item.link} />
      </CardContent>
    </Card>
  );
}
