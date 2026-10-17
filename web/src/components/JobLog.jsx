import { useEffect, useState } from 'react';
import { pollJob } from '../api.js';
import { Badge } from './ui/badge.jsx';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card.jsx';

const LABEL = { running: 'Выполняется…', ok: 'Готово', failed: 'Ошибка' };
const VARIANT = { running: 'secondary', ok: 'success', failed: 'destructive' };

// Live job log. Visible while the job runs and after it finishes, until the next action replaces it.
export default function JobLog({ jobId, title, onDone }) {
  const [job, setJob] = useState({ lines: [], status: 'running', summary: '', resultIp: null });

  useEffect(() => {
    const cancel = pollJob(jobId, (update) => {
      setJob(update);
      if (update.done) onDone(update);
    });
    return cancel;
  }, [jobId]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>{title}</CardTitle>
        <Badge variant={VARIANT[job.status]}>{LABEL[job.status]}</Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <pre className="max-h-[50vh] overflow-auto whitespace-pre-wrap break-all rounded-md border border-border bg-muted p-3 text-xs">
          {job.lines.join('\n') || '…'}
        </pre>
        {job.summary && <p className="text-sm font-medium">{job.summary}</p>}
        {job.resultIp && <p className="text-sm text-muted-foreground">Выходной IP: {job.resultIp}</p>}
      </CardContent>
    </Card>
  );
}
