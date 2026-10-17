import { Alert, AlertDescription, AlertTitle } from './ui/alert.jsx';

export default function LoginHint() {
  return (
    <Alert variant="warning">
      <AlertTitle>Нужен вход</AlertTitle>
      <AlertDescription>
        <p>Откройте ссылку из журнала контейнера:</p>
        <pre className="mt-2 overflow-x-auto rounded-md bg-muted p-2 text-xs">docker compose logs kit</pre>
        <p className="mt-2">или выполните:</p>
        <pre className="mt-2 overflow-x-auto rounded-md bg-muted p-2 text-xs">docker compose exec kit kit token</pre>
      </AlertDescription>
    </Alert>
  );
}
