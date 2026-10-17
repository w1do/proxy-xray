import { useState } from 'react';
import { Button } from './ui/button.jsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card.jsx';

// Shown after a successful install. It only displays the commands; nothing is run automatically.
const COMMANDS = './proxy env on\nsource ~/.bashrc';

export default function ProxyEnvHint() {
  const [note, setNote] = useState('');

  async function copy() {
    try {
      await navigator.clipboard.writeText(COMMANDS);
      setNote('Скопировано');
    } catch {
      setNote('Не удалось скопировать: выделите текст вручную');
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Прокси в терминале</CardTitle>
        <CardDescription>
          Чтобы терминал пользовался прокси, выполните в папке проекта на этом компьютере. Для zsh вместо
          <code> ~/.bashrc </code> используйте <code>~/.zshrc</code>.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <pre className="overflow-x-auto rounded-md border border-border bg-muted p-3 text-xs">{COMMANDS}</pre>
        <div className="flex items-center gap-3">
          <Button variant="outline" size="sm" onClick={copy}>Копировать</Button>
          {note && <span className="text-xs text-muted-foreground">{note}</span>}
        </div>
      </CardContent>
    </Card>
  );
}
