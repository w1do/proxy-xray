# Mihomo USA Proxy Kit

## Для чего нужен этот проект

Этот набор устанавливает на ваш компьютер локальный прокси Mihomo и настраивает
его для подключения к вашему серверу в США по VLESS/Reality. Приложения,
поддерживающие переменные прокси, смогут отправлять запросы через этот сервер,
поэтому сайты будут видеть внешний IP сервера. Mihomo также настраивает системный
HTTP/HTTPS/SOCKS-прокси в macOS.

По умолчанию правила направляют через прокси сервисы OpenAI/ChatGPT, Anthropic/Claude,
JetBrains AI и Grazie; остальной внешний трафик также направляется через прокси.
Запросы к частным локальным адресам идут напрямую. Это не VPN: скрипт не создаёт
сетевой интерфейс и сам по себе не перенаправляет приложения, которые игнорируют
системные настройки и переменные прокси.

Чтобы подключиться, уже должен быть настроен сервер VLESS/Reality. Нужны его IP,
UUID, публичный ключ Reality и Short ID. Скрипт устанавливает Mihomo, создаёт его
конфигурацию, запускает прокси на `127.0.0.1:7890` и проверяет подключение по
внешнему IP.

Храните `proxy.env` и репозиторий с учётными данными в безопасности: имея эти
параметры, другой человек сможет использовать ваш прокси. Файл `proxy.env`
исключён из Git.

## Файлы проекта

- `install.sh` — установка и запуск прокси в macOS, Linux и WSL.
- `proxy.env.example` — шаблон настроек; скопируйте его в `proxy.env`.
- `proxy.env` — локальные параметры подключения к серверу, не публикуйте этот файл.
- `bin/` — архивы Mihomo; подходящий архив позволяет установить программу без загрузки.

## Установка

Понадобятся `git`, `curl`, `bash` и параметры VLESS/Reality сервера: `SERVER_IP`,
`UUID`, `PUBLIC_KEY`, `SHORT_ID`. Для Linux x64 архив Mihomo включён в проект;
на других поддерживаемых платформах установщик загружает подходящий архив с GitHub.

Скопируйте команду целиком. При первом запуске редактор откроет файл настроек:
впишите значения, сохраните файл и закройте редактор, чтобы установка продолжилась.

```bash
git clone git@github.com:w1do/proxy-xray.git mihomo-proxy-kit && cd mihomo-proxy-kit && cp proxy.env.example proxy.env && nano proxy.env && bash ./install.sh
```

Если SSH-доступ к GitHub не настроен, используйте HTTPS-адрес репозитория в команде
`git clone`.

Можно выполнить те же действия по очереди:

```bash
git clone git@github.com:w1do/proxy-xray.git mihomo-proxy-kit
cd mihomo-proxy-kit
cp proxy.env.example proxy.env
nano proxy.env        # укажите SERVER_IP, UUID, PUBLIC_KEY и SHORT_ID
bash ./install.sh
```

После успешной установки появится сообщение `Verified exit IP: ...`. Откройте новый
терминал, чтобы применились переменные прокси, либо выполните:

```bash
source ~/.bashrc 2>/dev/null || true
```

Проверить внешний IP через прокси можно командой:

```bash
curl https://api.ipify.org
```

Должен отобразиться IP сервера. Для явной проверки через локальный прокси:

```bash
curl -x http://127.0.0.1:7890 https://api.ipify.org
```

## Логи и проверка проксирования

Лог Mihomo: `~/.config/mihomo/mihomo.log`.

```bash
# следить за журналом в реальном времени (Ctrl+C — выход)
tail -f ~/.config/mihomo/mihomo.log

# показать последние 50 строк
tail -n 50 ~/.config/mihomo/mihomo.log
```

Каждое соединение пишется строкой вида
`[TCP] 127.0.0.1:48012 --> api.openai.com:443 match DomainSuffix(openai.com) using PROXY[USA]`.
Фрагмент `using PROXY[USA]` означает, что запрос ушёл через USA-сервер.
`DIRECT` означает прямое соединение; по текущим правилам так идут частные локальные адреса.

Посмотреть проксирование нужных сервисов (OpenAI/ChatGPT, Anthropic/Claude, JetBrains AI):

```bash
# в одном терминале — фильтр журнала по сервисам
tail -f ~/.config/mihomo/mihomo.log | grep -Ei 'openai|chatgpt|anthropic|claude|jetbrains|grazie'

# в другом терминале — выполнить запросы
curl -sI https://api.openai.com >/dev/null
curl -sI https://claude.ai >/dev/null
```

В логе должны появиться строки с `using PROXY[USA]`. Ошибки подключения ищите так:
`grep -Ei 'error|timeout|fail' ~/.config/mihomo/mihomo.log`.

Проверить, что процесс жив: `kill -0 $(cat ~/.config/mihomo/mihomo.pid) && echo running`.
Список сервисов, идущих через прокси, - блок `rules:` в `~/.config/mihomo/config.yaml`
(остальной трафик тоже идёт через `PROXY` по правилу `MATCH`).

## Параметры (`proxy.env`)

- `SERVER_IP`, `UUID`, `PUBLIC_KEY`, `SHORT_ID` — обязательные параметры.
- `REALITY_SERVER_NAME` — имя сервера TLS/Reality; по умолчанию `dl.google.com`.
- `PROXY_PORT` — локальный порт прокси; по умолчанию `7890`.
- `EXPECTED_EXIT_IP` — ожидаемый внешний IP; по умолчанию равен `SERVER_IP`.
- `RU_SERVER_IP`, `RU_UUID`, `RU_PUBLIC_KEY`, `RU_SHORT_ID`, `RU_REALITY_SERVER_NAME` — необязательный RU-сервер для остального трафика (см. «Схема: USA для AI-сервисов, RU для остального»).

## Диагностика и управление

- Журнал: `~/.config/mihomo/mihomo.log`.
- Повторный запуск `bash ./install.sh` перезапускает Mihomo с текущими настройками.
- Остановить прокси: `kill "$(cat ~/.config/mihomo/mihomo.pid)"`.
- Коды завершения: `2` — не заданы обязательные параметры; `3` — не найден архив Mihomo;
  `4` — Mihomo не запустился; `5` — проверка прокси не прошла; `6` — внешний IP
  отличается от ожидаемого.

## Перенос сервера Xray на новую машину

Дамп конфигурации Xray с рабочего сервера лежит в `server/xray-config.json`
(содержит приватный ключ Reality, поэтому исключён из Git — копируйте вручную).
На новом сервере с установленным Xray:

```bash
scp server/xray-config.json root@NEW_IP:/usr/local/etc/xray/config.json
ssh root@NEW_IP 'chown nobody /usr/local/etc/xray/config.json && chmod 600 /usr/local/etc/xray/config.json && systemctl restart xray'
```

В `proxy.env` клиента замените `SERVER_IP` на IP нового сервера; `UUID`, `PUBLIC_KEY`
и `SHORT_ID` остаются прежними. Порт 443 должен быть открыт.

## Импорт конфига Xray на новый сервер (USA или RU)

1. Подготовьте VPS (Debian/Ubuntu), откройте порт 443 в файрволе.
2. Установите Xray:

```bash
ssh root@NEW_IP 'bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install'
```

3. Загрузите дамп и перезапустите сервис:

```bash
scp server/xray-config.json root@NEW_IP:/usr/local/etc/xray/config.json
ssh root@NEW_IP 'chown nobody /usr/local/etc/xray/config.json && chmod 600 /usr/local/etc/xray/config.json && systemctl enable --now xray && systemctl restart xray && ss -ltnp | grep :443'
```

4. Для RU-сервера лучше сгенерировать свои ключи, а не переиспользовать USA:

```bash
ssh root@NEW_IP '/usr/local/bin/xray uuid; /usr/local/bin/xray x25519; openssl rand -hex 8'
```

Подставьте в `/usr/local/etc/xray/config.json` новые `id` (UUID), `privateKey`, `shortIds`,
затем `systemctl restart xray`. `PublicKey` из вывода `x25519` пойдёт клиенту.

## Схема: USA для AI-сервисов, RU для остального

- USA-сервер: OpenAI/ChatGPT/Codex, Anthropic/Claude, JetBrains AI/Grazie.
- RU-сервер: весь остальной трафик (правило `MATCH`).

Оба сервера описываются в `proxy.env`; `install.sh` сам создаёт конфиг Mihomo.
Добавьте к параметрам USA блок RU:

```bash
RU_SERVER_IP=1.2.3.4
RU_UUID=...
RU_PUBLIC_KEY=...
RU_SHORT_ID=...
RU_REALITY_SERVER_NAME=dl.google.com   # необязательно
```

Если `RU_SERVER_IP` задан, `RU_UUID`, `RU_PUBLIC_KEY` и `RU_SHORT_ID` обязательны
(иначе код выхода `2`). В конфиг добавляются прокси `RU-NODE` и группа `RU`;
правила AI-сервисов остаются на `PROXY` (USA), а `MATCH` идёт в `RU`. Без `RU_*`
всё идёт через USA, как раньше. Данные для RU получите так же, как для USA:
`bash server/setup-server.sh root@RU_IP`.

Запуск и проверка:

```bash
bash ./install.sh
curl -x http://127.0.0.1:7890 https://api.ipify.org     # IP RU-сервера
curl -x http://127.0.0.1:7890 -sI https://claude.ai >/dev/null
grep -E 'PROXY\[USA\]|RU\[RU-NODE\]' ~/.config/mihomo/mihomo.log | tail
```

`install.sh` при RU ожидает внешний IP RU-сервера (`EXPECTED_EXIT_IP` можно
переопределить). Выход через USA проверяйте по логу: claude/openai — `using PROXY[USA]`,
остальное — `using RU[RU-NODE]`.

## Автоустановка Xray на новый сервер одной командой

С вашего компьютера (нужен SSH-доступ root или sudo-пользователя к чистому Linux-серверу):

```bash
bash server/setup-server.sh root@NEW_SERVER_IP
```

Скрипт по SSH ставит Xray, зависимости, создаёт VLESS+Reality на :443 с новыми UUID и ключами,
открывает порт 443, включает BBR, запускает `xray` и в конце печатает блок `proxy.env`
(`SERVER_IP`, `UUID`, `PUBLIC_KEY`, `SHORT_ID`) — вставьте его в `proxy.env` и запустите `bash install.sh`.

Чтобы вместо новых ключей залить сохранённый конфиг: `KEEP_CONFIG=1 bash server/setup-server.sh root@NEW_SERVER_IP`.
Другой SSH-ключ/порт: `bash server/setup-server.sh root@IP -i ~/.ssh/key -p 2222`.

Если установка сообщает, что `443/tcp` уже занят, скрипт остановится до установки Xray
и покажет процесс-владелец порта. Не останавливайте его вслепую: сначала выясните,
нужен ли он (например, это может быть Nginx, Caddy или уже запущенный Xray). Остановите
или перенастройте службу вручную и повторите установку. Если `apt-get update` сообщает,
что у репозитория нет `Release` файла (например, `https://pkg.cloudflare.com noble`),
исправьте или отключите именно этот сторонний APT-источник на сервере и повторите команду.
