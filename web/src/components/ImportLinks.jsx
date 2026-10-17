import { useState } from 'react';
import { api, ApiError } from '../api.js';
import { Alert, AlertDescription } from './ui/alert.jsx';
import { Button } from './ui/button.jsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card.jsx';
import { Label } from './ui/label.jsx';

const MAX_LINKS = 40;

// Import of vless:// links from the owner. The text lives only in this component's state until the import succeeds.
export default function ImportLinks({ busy, onImported }) {
  const [text, setText] = useState('');
  const [err, setErr] = useState(null);
  const [itemErrors, setItemErrors] = useState([]);
  const [done, setDone] = useState('');

  async function submit() {
    setErr(null);
    setItemErrors([]);
    setDone('');
    const links = text.split('\n').map((line) => line.trim()).filter(Boolean);
    if (links.length === 0) {
      setErr('Вставьте хотя бы одну ссылку');
      return;
    }
    if (links.length > MAX_LINKS) {
      setErr(`Не больше ${MAX_LINKS} ссылок`);
      return;
    }
    try {
      const res = await api('POST', '/api/inbounds/import', { links });
      setText('');
      setDone(`Импортировано: ${res.imported}` + (res.removed > 0 ? `, удалено: ${res.removed}` : ''));
      onImported();
    } catch (e) {
      if (e instanceof ApiError) {
        setErr(e.message);
        setItemErrors(Array.isArray(e.data?.errors) ? e.data.errors : []);
      } else {
        setErr('Не удалось импортировать');
      }
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Импорт ссылок</CardTitle>
        <CardDescription>По одной ссылке vless:// в строке. Ссылки хранятся только в этой панели</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="text-xs text-muted-foreground">Новый импорт заменяет ранее импортированный список.</p>
        <Label htmlFor="import-links">Ссылки</Label>
        <textarea
          id="import-links"
          className="min-h-32 w-full rounded-md border border-input bg-card p-2 font-mono text-xs text-foreground"
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={busy}
          spellCheck={false}
        />
        <div className="flex items-center gap-3">
          <Button onClick={submit} disabled={busy || !text.trim()}>Импортировать</Button>
          {done && <span className="text-sm text-success">{done}</span>}
        </div>
        {err && (
          <Alert variant="destructive">
            <AlertDescription>
              <p>{err}</p>
              {itemErrors.map((item) => (
                <p key={`${item.index}:${item.error}`}>Строка {item.index}: {item.error}</p>
              ))}
            </AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
}
