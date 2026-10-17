import { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import { Alert, AlertDescription } from './ui/alert.jsx';
import { Button } from './ui/button.jsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card.jsx';
import { Checkbox } from './ui/checkbox.jsx';
import { Input } from './ui/input.jsx';
import { Label } from './ui/label.jsx';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select.jsx';
import { Switch } from './ui/switch.jsx';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table.jsx';

const POLICY_LABEL = { PROXY: 'PROXY', DIRECT: 'DIRECT', REJECT: 'REJECT' };
const POLICY_TONE = {
  PROXY: 'border-primary/50 text-primary',
  DIRECT: 'border-success/60 text-success',
  REJECT: 'border-destructive/60 text-destructive',
};
const NO_RESOLVE_TYPES = ['GEOIP', 'IP-CIDR'];

export default function RulesEditor({ busy, onJob, onSaved }) {
  const [meta, setMeta] = useState(null);
  const [rules, setRules] = useState([]); // each row: { id, type, value, policy, no_resolve, enabled, note }
  const nextId = useRef(1);
  const [match, setMatch] = useState('PROXY');
  const [err, setErr] = useState('');
  const [msg, setMsg] = useState('');

  useEffect(() => {
    let alive = true;
    api('GET', '/api/rules')
      .then((d) => {
        if (!alive) return;
        setMeta(d);
        setRules(d.rules.map((r) => ({ ...r, id: nextId.current++ })));
        setMatch(d.match);
      })
      .catch((e) => alive && setErr(e.message));
    return () => {
      alive = false;
    };
  }, []);

  if (!meta) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          {err || 'Загрузка правил…'}
        </CardContent>
      </Card>
    );
  }

  function setRule(index, patch) {
    setRules((prev) => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  }

  function move(index, delta) {
    setRules((prev) => {
      const target = index + delta;
      if (target < 0 || target >= prev.length) return prev;
      const next = prev.slice();
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  function remove(index) {
    setRules((prev) => prev.filter((_, i) => i !== index));
  }

  function add() {
    setRules((prev) => [
      ...prev,
      { id: nextId.current++, type: 'DOMAIN-SUFFIX', value: '', policy: 'DIRECT', no_resolve: false, enabled: true, note: '' },
    ]);
  }

  async function save() {
    setErr('');
    setMsg('');
    try {
      const res = await api('PUT', '/api/rules', { rules: rules.map(({ id, ...rule }) => rule), match });
      setMsg('Правила сохранены');
      if (res.job_id) onJob(res.job_id, 'Применение правил');
      onSaved();
    } catch (e) {
      setErr(e.message);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Правила сайтов</CardTitle>
        <CardDescription>Первое совпадение побеждает. Политика PROXY идёт через NL, DIRECT — напрямую.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-col gap-2 rounded-md border border-dashed border-border p-3 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
          <span>Служебное правило (всегда первое, только чтение)</span>
          <span className="font-mono text-foreground">DOMAIN,api.ipify.org,PROXY</span>
        </div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Тип</TableHead>
              <TableHead>Значение</TableHead>
              <TableHead>Политика</TableHead>
              <TableHead className="hidden md:table-cell">no-resolve</TableHead>
              <TableHead>Вкл.</TableHead>
              <TableHead className="hidden xl:table-cell">Примечание</TableHead>
              <TableHead className="text-right">Порядок</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rules.map((r, i) => (
              <TableRow key={r.id} className={r.enabled ? '' : 'opacity-60'}>
                <TableCell>
                  <Select value={r.type} onValueChange={(v) => setRule(i, { type: v })} disabled={busy}>
                    <SelectTrigger className="w-36" aria-label="Тип правила">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {meta.types.map((t) => (
                        <SelectItem key={t} value={t}>{t}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </TableCell>
                <TableCell>
                  <Input className="min-w-36" aria-label="Значение" value={r.value} onChange={(e) => setRule(i, { value: e.target.value })} />
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <Select value={r.policy} onValueChange={(v) => setRule(i, { policy: v })} disabled={busy}>
                      <SelectTrigger className={`w-32 font-medium ${POLICY_TONE[r.policy]}`} aria-label="Политика">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {meta.policies.map((p) => (
                          <SelectItem key={p} value={p}>{POLICY_LABEL[p]}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </TableCell>
                <TableCell className="hidden md:table-cell">
                  {NO_RESOLVE_TYPES.includes(r.type) && (
                    <Checkbox
                      aria-label="no-resolve"
                      checked={r.no_resolve}
                      onCheckedChange={(v) => setRule(i, { no_resolve: v === true })}
                      disabled={busy}
                    />
                  )}
                </TableCell>
                <TableCell>
                  <Switch aria-label="Включено" checked={r.enabled} onCheckedChange={(v) => setRule(i, { enabled: v })} disabled={busy} />
                </TableCell>
                <TableCell className="hidden xl:table-cell">
                  <Input aria-label="Примечание" value={r.note} onChange={(e) => setRule(i, { note: e.target.value })} />
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-1">
                    <Button variant="ghost" size="sm" onClick={() => move(i, -1)} disabled={busy} aria-label="Выше">↑</Button>
                    <Button variant="ghost" size="sm" onClick={() => move(i, 1)} disabled={busy} aria-label="Ниже">↓</Button>
                    <Button variant="ghost" size="sm" onClick={() => remove(i)} disabled={busy} className="text-destructive">Удалить</Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <div className="flex flex-wrap items-end gap-3">
          <Button variant="outline" onClick={add} disabled={busy}>Добавить правило</Button>
          <div className="flex flex-col gap-1.5">
            <Label>MATCH (всё остальное)</Label>
            <Select value={match} onValueChange={setMatch} disabled={busy}>
              <SelectTrigger className="w-40" aria-label="MATCH">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {meta.policies.map((p) => (
                  <SelectItem key={p} value={p}>{POLICY_LABEL[p]}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button onClick={save} disabled={busy} className="ml-auto">Сохранить и применить</Button>
        </div>
        {err && <Alert variant="destructive"><AlertDescription>{err}</AlertDescription></Alert>}
        {msg && <p className="text-sm text-success">{msg}</p>}
      </CardContent>
    </Card>
  );
}
