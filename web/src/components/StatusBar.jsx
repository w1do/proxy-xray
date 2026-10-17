import { useState } from 'react';
import { api } from '../api.js';
import { Alert, AlertDescription, AlertTitle } from './ui/alert.jsx';
import { Badge } from './ui/badge.jsx';
import { Button } from './ui/button.jsx';
import { Card, CardContent } from './ui/card.jsx';



const STATE_TEXT = { running: 'работает', idle: 'ожидает настройки', failed: 'ошибка', down: 'не работает' };
const STATE_VARIANT = { running: 'success', idle: 'secondary', failed: 'destructive', down: 'destructive' };

export default function StatusBar({ proxy, active, exits, busy }) {
  const [health, setHealth] = useState(null);
  const [logs, setLogs] = useState(null);
  const [err, setErr] = useState('');

  const inbounds = exits.flatMap((e) => e.inbounds);
  const activeInbound = active ? inbounds.find((i) => i.id === active.inbound_id) : null;

  async function checkProxy() {
    setErr('');
    try {
      setHealth(await api('POST', '/api/health', {}));
    } catch (e) {
      setErr(e.message);
    }
  }

  async function loadLogs(name) {
    setErr('');
    try {
      const d = await api('GET', `/api/proxy/logs?name=${name}`);
      setLogs({ name, lines: d.lines.slice(-200) });
    } catch (e) {
      setErr(e.message);
    }
  }

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 pt-5">
        {proxy.state === 'down' && (
          <Alert variant="destructive">
            <AlertTitle>Прокси-контейнер не работает</AlertTitle>
            <AlertDescription>
              <p>
                Чаще всего порт 7890 занят старой установкой на хосте. UI ничего не останавливает сам. Одноразовый переход
                описан в README, раздел 8 «Переход с установки на хосте». После него выполните <code>docker compose up -d</code>.
              </p>
            </AlertDescription>
          </Alert>
        )}
        {proxy.state === 'failed' && (
          <Alert variant="destructive">
            <AlertTitle>Прокси не применил конфигурацию</AlertTitle>
            <AlertDescription>{proxy.error || 'Причина не указана'}</AlertDescription>
          </Alert>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">Прокси</span>
            <Badge variant={STATE_VARIANT[proxy.state] || 'secondary'}>{STATE_TEXT[proxy.state] || proxy.state}</Badge>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">Активный вход</span>
            {activeInbound ? (
              <Badge variant="outline" className="font-mono">
                NL:{activeInbound.port} → {activeInbound.exit_ip} · {activeInbound.network_label}
              </Badge>
            ) : (
              <Badge variant="secondary">не установлен</Badge>
            )}
          </div>
          <div className="ml-auto flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={checkProxy} disabled={busy}>Проверить прокси</Button>
            <Button variant="outline" size="sm" onClick={() => loadLogs('xray')} disabled={busy}>Журнал xray</Button>
            <Button variant="outline" size="sm" onClick={() => loadLogs('mihomo')} disabled={busy}>Журнал mihomo</Button>
          </div>
        </div>
        {health && (
          <p className={`text-sm ${health.ok ? 'text-success' : 'text-destructive'}`}>
            {health.ok ? 'OK' : 'Ошибка'}: выходной IP {health.ip || 'не получен'}
            {health.expected_ip ? ` (ожидается ${health.expected_ip})` : ''}
          </p>
        )}
        {logs && (
          <div className="flex flex-col gap-1">
            <p className="text-xs text-muted-foreground">Журнал {logs.name}, последние строки</p>
            <pre className="max-h-[40vh] overflow-auto whitespace-pre-wrap break-all rounded-md border border-border bg-muted p-3 text-xs">
              {logs.lines.join('\n')}
            </pre>
          </div>
        )}
        {err && <p className="text-sm text-destructive">{err}</p>}
      </CardContent>
    </Card>
  );
}
