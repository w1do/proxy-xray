import { useState } from 'react';
import { api } from '../api.js';
import HostKeyDialog from './HostKeyDialog.jsx';
import { Badge } from './ui/badge.jsx';
import { Button } from './ui/button.jsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card.jsx';
import { Input } from './ui/input.jsx';
import { Label } from './ui/label.jsx';

export default function NlSettings({ nl, keyMounted, hostTrusted, busy, onSaved, onJob }) {
  const [form, setForm] = useState({
    host: nl?.host ?? '',
    ssh_user: nl?.ssh_user ?? 'root',
    ssh_port: String(nl?.ssh_port ?? 22),
  });
  const [dialogOpen, setDialogOpen] = useState(false);
  const [msg, setMsg] = useState('');
  const saved = Boolean(nl && nl.host);

  function update(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function save() {
    setMsg('');
    try {
      await api('PUT', '/api/nl', {
        host: form.host.trim(),
        ssh_user: form.ssh_user.trim() || 'root',
        ssh_port: Number(form.ssh_port) || 22,
      });
      setMsg('Настройки сохранены');
      onSaved();
    } catch (e) {
      setMsg(e.message);
    }
  }

  async function discover() {
    setMsg('');
    try {
      const d = await api('POST', '/api/discover', {});
      onJob(d.job_id, 'Обнаружение входов');
    } catch (e) {
      setMsg(e.message);
    }
  }

  const canDiscover = saved && keyMounted && hostTrusted && !busy;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Сервер NL</CardTitle>
        <CardDescription>Точка входа, с которой читаются входы и выходы USA.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid gap-3 sm:grid-cols-[1fr_9rem_6rem]">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="nl-host">Хост</Label>
            <Input id="nl-host" placeholder="185.245.107.19" value={form.host} onChange={(e) => update('host', e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="nl-user">Пользователь</Label>
            <Input id="nl-user" value={form.ssh_user} onChange={(e) => update('ssh_user', e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="nl-port">Порт SSH</Label>
            <Input id="nl-port" value={form.ssh_port} onChange={(e) => update('ssh_port', e.target.value)} />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={keyMounted ? 'success' : 'destructive'}>
            {keyMounted ? 'SSH-ключ смонтирован' : 'SSH-ключ не смонтирован: задайте KIT_SSH_KEY'}
          </Badge>
          <Badge variant={hostTrusted ? 'success' : 'warning'}>
            {hostTrusted ? 'ключ хоста подтверждён' : 'ключ хоста не подтверждён'}
          </Badge>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={save} disabled={busy}>Сохранить</Button>
          <Button variant="outline" onClick={() => setDialogOpen(true)} disabled={busy || !saved}>Проверить ключ хоста</Button>
          <Button variant="secondary" onClick={discover} disabled={!canDiscover}>Обнаружить входы</Button>
          {!canDiscover && (
            <span className="text-xs text-muted-foreground">
              {!saved ? 'Сначала сохраните NL' : !keyMounted ? 'Нет SSH-ключа' : !hostTrusted ? 'Сначала подтвердите ключ хоста' : 'Выполняется задача'}
            </span>
          )}
        </div>
        {msg && <p className="text-sm text-muted-foreground">{msg}</p>}
      </CardContent>
      {dialogOpen && (
        <HostKeyDialog
          onClose={() => setDialogOpen(false)}
          onTrusted={() => {
            setMsg('Ключ хоста подтверждён');
            onSaved();
          }}
        />
      )}
    </Card>
  );
}
