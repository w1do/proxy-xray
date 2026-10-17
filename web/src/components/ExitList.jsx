import { api } from '../api.js';
import { Alert, AlertDescription } from './ui/alert.jsx';
import { Badge } from './ui/badge.jsx';
import { Button } from './ui/button.jsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card.jsx';
import { useState } from 'react';

// One card per exit. The active exit carries an "Активен" badge.
export default function ExitList({ exits, busy, onSelect, onJob }) {
  const [err, setErr] = useState('');

  async function checkAll() {
    setErr('');
    try {
      const d = await api('POST', '/api/check-all', {});
      onJob(d.job_id, 'Проверка всех входов');
    } catch (e) {
      setErr(e.message);
    }
  }

  if (exits.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          Входов пока нет. Укажите NL и нажмите «Обнаружить входы».
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">Выходы USA, доступные через NL</p>
        <Button variant="outline" size="sm" onClick={checkAll} disabled={busy}>Проверить все</Button>
      </div>
      {err && <Alert variant="destructive"><AlertDescription>{err}</AlertDescription></Alert>}
      <div className="grid gap-3 sm:grid-cols-2">
        {exits.map((exit) => {
          const active = exit.inbounds.some((i) => i.active);
          const ok = exit.inbounds.filter((i) => i.check.ok === true).length;
          return (
            <button
              key={exit.exit_ip}
              type="button"
              onClick={() => onSelect(exit.exit_ip)}
              disabled={busy}
              className="cursor-pointer rounded-lg text-left disabled:cursor-default disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-ring"
            >
              <Card className={`h-full transition-colors hover:bg-accent ${active ? 'border-success ring-1 ring-success' : ''}`}>
                <CardHeader className="flex-row items-start justify-between gap-2">
                  <div>
                    <CardTitle>{exit.label}</CardTitle>
                    <CardDescription className="font-mono">{exit.exit_ip}</CardDescription>
                  </div>
                  {active && <Badge variant="success">Активен</Badge>}
                </CardHeader>
                <CardContent className="flex gap-3 text-sm text-muted-foreground">
                  <span>Входов: {exit.inbounds.length}</span>
                  <span>Проверено OK: {ok}</span>
                </CardContent>
              </Card>
            </button>
          );
        })}
      </div>
    </div>
  );
}
