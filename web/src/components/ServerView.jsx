import { useState } from 'react';
import { api } from '../api.js';
import { Alert, AlertDescription } from './ui/alert.jsx';
import { Badge } from './ui/badge.jsx';
import { Button } from './ui/button.jsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card.jsx';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table.jsx';
import { Tooltip, TooltipContent, TooltipTrigger } from './ui/tooltip.jsx';
import LinksModal from './LinksModal.jsx';

const BLOCK_443 = 'Порт 443 не устанавливается этим установщиком';

// Installed / check / install states. A disabled button always has a visible reason.
function installState(i) {
  if (i.active) return { badge: <Badge variant="success">Установлен</Badge>, reason: null };
  if (!i.installable) return { badge: <Badge variant="secondary">Не поддерживается</Badge>, reason: i.port === 443 ? BLOCK_443 : 'Вход нельзя установить' };
  return { badge: null, reason: null };
}

function checkBadge(i) {
  if (i.check.ok === null) return <Badge variant="secondary">Не проверен</Badge>;
  if (i.check.ok) return <Badge variant="success">OK {i.check.ip || ''}</Badge>;
  return <Badge variant="destructive">Ошибка</Badge>;
}

export default function ServerView({ exit, busy, onBack, onJob }) {
  const [linksOpen, setLinksOpen] = useState(false);
  const [err, setErr] = useState('');

  async function check(inbound) {
    setErr('');
    try {
      const d = await api('POST', `/api/inbounds/${inbound.id}/check`, {});
      onJob(d.job_id, `Проверка NL:${inbound.port}`);
    } catch (e) {
      setErr(e.message);
    }
  }

  async function install(inbound) {
    if (!window.confirm(`Переключить прокси на NL:${inbound.port} -> ${exit.label}?`)) return;
    setErr('');
    try {
      const d = await api('POST', `/api/inbounds/${inbound.id}/install`, { confirm: true });
      onJob(d.job_id, `Установка NL:${inbound.port}`);
    } catch (e) {
      setErr(e.message);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button variant="ghost" size="sm" onClick={onBack}>← Все серверы</Button>
        <Button variant="outline" size="sm" onClick={() => setLinksOpen(true)} disabled={busy}>Показать ссылки</Button>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>{exit.label}</CardTitle>
          <CardDescription className="font-mono">{exit.exit_ip}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {err && <Alert variant="destructive"><AlertDescription>{err}</AlertDescription></Alert>}
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Порт</TableHead>
                <TableHead>Режим</TableHead>
                <TableHead className="hidden sm:table-cell">Комментарий</TableHead>
                <TableHead>Состояние</TableHead>
                <TableHead>Проверка</TableHead>
                <TableHead className="text-right">Действия</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {exit.inbounds.map((i) => {
                const st = installState(i);
                const installDisabled = busy || !i.installable || i.active;
                const installReason = busy ? 'Выполняется задача' : st.reason || (i.active ? 'Уже установлен' : null);
                return (
                  <TableRow key={i.id}>
                    <TableCell className="font-mono">
                      {i.port}
                      {i.source === 'import' && <Badge variant="outline" className="ml-2">импорт</Badge>}
                    </TableCell>
                    <TableCell>{i.network_label}</TableCell>
                    <TableCell className="hidden sm:table-cell text-muted-foreground">{i.remark}</TableCell>
                    <TableCell>
                      <div className="flex flex-col items-start gap-1">
                        {i.active ? st.badge : st.badge || <Badge variant="outline">Доступен</Badge>}
                        {i.active && <span className="text-xs text-muted-foreground">активный вход</span>}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col items-start gap-1">
                        {checkBadge(i)}
                        {i.check.at && <span className="text-xs text-muted-foreground">{i.check.at}</span>}
                        {i.check.ok === false && i.check.error && <span className="text-xs text-destructive">{i.check.error}</span>}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-2">
                        <Button variant="outline" size="sm" onClick={() => check(i)} disabled={busy}>Проверить</Button>
                        {installReason && installDisabled ? (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <span tabIndex={0} className="inline-flex">
                                <Button size="sm" disabled>Установить</Button>
                              </span>
                            </TooltipTrigger>
                            <TooltipContent>{installReason}</TooltipContent>
                          </Tooltip>
                        ) : (
                          <Button size="sm" onClick={() => install(i)} disabled={installDisabled}>Установить</Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      {linksOpen && <LinksModal exitIp={exit.exit_ip} onClose={() => setLinksOpen(false)} />}
    </div>
  );
}
