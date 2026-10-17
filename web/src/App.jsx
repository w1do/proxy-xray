import { useCallback, useEffect, useRef, useState } from 'react';
import { api, setUnauthorizedHandler } from './api.js';
import { TooltipProvider } from './components/ui/tooltip.jsx';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './components/ui/tabs.jsx';
import LoginHint from './components/LoginHint.jsx';
import StatusBar from './components/StatusBar.jsx';
import NlSettings from './components/NlSettings.jsx';
import ImportLinks from './components/ImportLinks.jsx';
import ExitList from './components/ExitList.jsx';
import ServerView from './components/ServerView.jsx';
import RulesEditor from './components/RulesEditor.jsx';
import JobLog from './components/JobLog.jsx';
import { Alert, AlertDescription } from './components/ui/alert.jsx';
import { Button } from './components/ui/button.jsx';

export default function App() {
  const [state, setState] = useState(null);
  const [needLogin, setNeedLogin] = useState(false);
  const [error, setError] = useState('');
  const [selectedExit, setSelectedExit] = useState(null);
  const [tab, setTab] = useState('servers');
  const [showImport, setShowImport] = useState(false);
  const [job, setJob] = useState(null); // { id, title }
  const [jobRunning, setJobRunning] = useState(false);
  const jobRunningRef = useRef(false);

  const refresh = useCallback(async () => {
    try {
      setState(await api('GET', '/api/state'));
      setError('');
    } catch (err) {
      if (err.status === 401) setNeedLogin(true);
      else setError(err.message);
    }
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => setNeedLogin(true));
    refresh();
    const timer = setInterval(() => {
      if (!jobRunningRef.current) refresh();
    }, 10000);
    return () => clearInterval(timer);
  }, [refresh]);

  const startJob = useCallback((id, title) => {
    jobRunningRef.current = true;
    setJobRunning(true);
    setJob({ id, title });
  }, []);

  const onJobDone = useCallback(() => {
    jobRunningRef.current = false;
    setJobRunning(false);
    refresh();
  }, [refresh]);

  const shell = (children) => (
    <TooltipProvider delayDuration={200}>
      <main className="mx-auto flex max-w-5xl flex-col gap-4 p-4 sm:p-6">
        <header className="flex items-baseline justify-between gap-3">
          <h1 className="text-xl font-semibold tracking-tight">Proxy Kit</h1>
          <span className="text-xs text-muted-foreground">127.0.0.1 · Mihomo + Xray</span>
        </header>
        {children}
      </main>
    </TooltipProvider>
  );

  if (needLogin) return shell(<LoginHint />);
  if (!state) {
    return shell(error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : <p className="text-sm text-muted-foreground">Загрузка…</p>);
  }

  const exit = selectedExit ? state.exits.find((e) => e.exit_ip === selectedExit) || null : null;

  return shell(
    <>
      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
      <StatusBar proxy={state.proxy} active={state.active} exits={state.exits} busy={jobRunning} />
      {job && <JobLog key={job.id} jobId={job.id} title={job.title} onDone={onJobDone} />}
      {state.nl_key_mounted && (
        <NlSettings
          nl={state.nl}
          keyMounted={state.nl_key_mounted}
          hostTrusted={state.nl_host_trusted}
          busy={jobRunning}
          onSaved={refresh}
          onJob={startJob}
        />
      )}
      {state.nl_key_mounted && (
        <div className="flex justify-end">
          <Button variant="outline" size="sm" onClick={() => setShowImport((v) => !v)}>Импорт ссылок</Button>
        </div>
      )}
      {(!state.nl_key_mounted || showImport) && (
        <ImportLinks busy={jobRunning} onImported={refresh} />
      )}
      <Tabs value={tab} onValueChange={(v) => { setTab(v); }}>
        <TabsList>
          <TabsTrigger value="servers">Серверы</TabsTrigger>
          <TabsTrigger value="rules">Правила</TabsTrigger>
        </TabsList>
        <TabsContent value="servers">
          {!exit && <ExitList exits={state.exits} busy={jobRunning} onSelect={setSelectedExit} onJob={startJob} />}
          {exit && <ServerView exit={exit} busy={jobRunning} onBack={() => setSelectedExit(null)} onJob={startJob} />}
        </TabsContent>
        <TabsContent value="rules">
          <RulesEditor busy={jobRunning} onJob={startJob} onSaved={refresh} />
        </TabsContent>
      </Tabs>
    </>,
  );
}
