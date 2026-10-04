# Mihomo Proxy Kit: клиент → Netherlands → USA

## Что это

Набор поднимает на вашем компьютере локальный прокси **Mihomo** и настраивает
двухступенчатую (two-hop) цепочку:

```
Client (WSL/macOS) → Netherlands (релей) → USA (выход) → Internet
```

- Клиент подключается по **VLESS + Reality** к серверу-релею в Нидерландах.
- Нидерланды пересылают **весь** полученный трафик на сервер в США.
- Финальный внешний IP — американский (**108.61.222.91**), а не нидерландский.
- Сервер США не изменяется — он остаётся рабочим выходом.

Mihomo слушает `127.0.0.1:7890` и отдаёт HTTP/HTTPS/SOCKS-прокси. Приложения, которые
уважают системные настройки прокси или переменные `http_proxy`/`https_proxy`, ходят
через цепочку, поэтому сайты видят IP США. На macOS установщик также включает системный
прокси.

Через прокси идут AI-сервисы (OpenAI/ChatGPT, Anthropic/Claude, JetBrains AI, Grazie)
и весь остальной внешний трафик (правило `MATCH`). Запросы к частным локальным адресам
идут напрямую (`GEOIP,PRIVATE,DIRECT`). Это не VPN: сетевой интерфейс не создаётся, а
приложения, игнорирующие прокси, сами через него не пойдут.

Храните `proxy.env` и сам репозиторий в тайне: имея эти данные, посторонний сможет
пользоваться вашим прокси.

## Схема

```
   ┌───────────────────────────────┐
   │ Client: WSL / macOS           │
   │ Mihomo 127.0.0.1:7890         │
   └───────────────┬───────────────┘
                   │ VLESS + Reality, TCP 443
                   │ SNI dl.google.com
                   ▼
   ┌───────────────────────────────┐
   │ Netherlands   185.245.107.19  │
   │ Xray relay: весь трафик       │
   │  → outbound to-usa            │
   └───────────────┬───────────────┘
                   │ VLESS + Reality, TCP 443
                   │ SNI dl.google.com (fingerprint chrome)
                   ▼
   ┌───────────────────────────────┐
   │ USA   108.61.222.91           │
   │ Xray (не изменяется)          │
   └───────────────┬───────────────┘
                   ▼
               Internet
         внешний IP 108.61.222.91
```

## Файлы проекта

- `install.sh` — устанавливает Mihomo, генерирует конфиг, запускает прокси и проверяет внешний IP.
- `proxy.env.example` — шаблон настроек; скопируйте в `proxy.env`.
- `proxy.env` — локальные параметры подключения (точка входа — Нидерланды). Не публикуйте.
- `bin/` — архивы Mihomo v1.19.32 (linux amd64, darwin arm64, darwin amd64), чтобы не качать при установке.
- `server/setup-server.sh` — поднимает Xray на сервере по SSH: обычный сервер, AI-релей (`CHAIN_USA`) или полный релей (`CHAIN_ALL`).
- `server/xray-config.json` — дамп рабочего конфига Xray (с приватным ключом, в Git не хранится).

## Быстрый старт

Нужны `git`, `curl`, `bash`. Для Linux x64 архив Mihomo уже лежит в `bin/`; на других
поддерживаемых платформах установщик скачает подходящий архив с GitHub.

```bash
git clone git@github.com:w1do/proxy-xray.git mihomo-proxy-kit
cd mihomo-proxy-kit
cp proxy.env.example proxy.env
nano proxy.env        # впишите выданные значения точки входа (Нидерланды)
bash ./install.sh
```

Если SSH-доступ к GitHub не настроен, используйте HTTPS-адрес репозитория.
`proxy.env` содержит секреты и не хранится в Git — получите готовый файл с данными
точки входа либо заполните шаблон сами:

```bash
SERVER_IP=<NL_IP>
UUID=<NL_UUID>
PUBLIC_KEY=<NL_PUBLIC_KEY>
SHORT_ID=<NL_SHORT_ID>
REALITY_SERVER_NAME=dl.google.com
EXPECTED_EXIT_IP=108.61.222.91
```

При успехе установщик завершится сообщением:

```
Mihomo is running on 127.0.0.1:7890
...
Verified exit IP: 108.61.222.91
```

Откройте новый терминал (`source ~/.bashrc`, в macOS/`zsh` — `source ~/.zshrc`), чтобы
применились переменные прокси.

## Проверка, что всё работает

```bash
# внешний IP через локальный прокси — должен быть IP США
curl -x http://127.0.0.1:7890 https://api.ipify.org
# → 108.61.222.91

# процесс жив
kill -0 "$(cat ~/.config/mihomo/mihomo.pid)" && echo running

# порт слушается
ss -ltnp | grep 7890
```

Если вернулся IP Нидерландов (`185.245.107.19`), значит на релее сработал не тот
маршрут: смотрите логи клиента (ниже) и `journalctl -u xray` на NL-сервере.

## Логи Mihomo: как смотреть, как обрабатываются и проксируются запросы

Mihomo работает в фоне, и весь его вывод пишется в файл **`~/.config/mihomo/mihomo.log`**
(уровень `info`). Это основной инструмент диагностики: в логе видно каждое соединение,
какое правило сработало и через какой узел ушёл запрос.

### Смотреть в реальном времени

```bash
# следить за логом (Ctrl+C — выход); -F продолжит читать после пересоздания файла
tail -f ~/.config/mihomo/mihomo.log
```

Делайте запросы в другом терминале (откройте сайт, запустите приложение) и смотрите,
как появляются строки.

### Как читать строку лога

Каждое соединение — одна строка. Пример:

```
[TCP] 127.0.0.1:48012 --> api.openai.com:443 match DomainSuffix(openai.com) using PROXY[USA]
```

Разберём по частям:

| Фрагмент | Значение |
|---|---|
| `[TCP]` | тип соединения (TCP или UDP) |
| `127.0.0.1:48012` | локальный адрес приложения |
| `--> api.openai.com:443` | куда обращается запрос |
| `match DomainSuffix(openai.com)` | какое правило сработало |
| `using PROXY[USA]` | запрос ушёл через узел `USA` в группе `PROXY` |

Ключевые значения в конце строки:

- `using PROXY[USA]` — запрос реально пошёл через цепочку клиент → NL → USA (то, что нужно);
- `using DIRECT` — соединение напрямую, без прокси (по текущим правилам так идут только
  частные локальные адреса — правило `GEOIP,PRIVATE`).

### Показать только трафик через США

```bash
grep -F 'using PROXY[USA]' ~/.config/mihomo/mihomo.log | tail
```

### Следить только за нужными сервисами

```bash
tail -F ~/.config/mihomo/mihomo.log \
  | grep --line-buffered -iE 'anthropic|claude|openai|chatgpt|jetbrains|grazie|USA'
```

Затем запустите Claude Code / Codex / Junie или откройте нужный сайт. В логе должны
появиться строки вида:

```
api.anthropic.com:443 match ... using PROXY[USA]
api.openai.com:443    match ... using PROXY[USA]
chatgpt.com:443       match ... using PROXY[USA]
api.jetbrains.ai:443  match ... using PROXY[USA]
```

### Проверить конкретный сервис вручную

В одном терминале — фильтр, в другом — запросы:

```bash
tail -F ~/.config/mihomo/mihomo.log | grep --line-buffered -iE 'openai|claude|anthropic|jetbrains'
```
```bash
curl -sI https://api.openai.com   >/dev/null
curl -sI https://claude.ai        >/dev/null
curl -sI https://api.jetbrains.ai >/dev/null
```

### Найти ошибки соединения

```bash
grep -Ei 'error|timeout|fail|rejected' ~/.config/mihomo/mihomo.log | tail -n 50
```

Проблемы рукопожатия с сервером видны и на самом релее:

```bash
ssh root@185.245.107.19 'journalctl -u xray -n 50 --no-pager'
```

### Более подробный лог (debug)

Уровень логирования задаётся в `~/.config/mihomo/config.yaml` строкой `log-level: info`.
Для диагностики его можно поднять до `debug`:

```bash
sed -i 's/^log-level: info/log-level: debug/' ~/.config/mihomo/config.yaml
bash ./install.sh      # перезапустит Mihomo с текущими настройками
```

Учтите: `install.sh` каждый раз генерирует `config.yaml` заново, поэтому правка
`log-level` вручную не сохранится после следующего запуска установщика.

## Параметры (proxy.env)

- `SERVER_IP`, `UUID`, `PUBLIC_KEY`, `SHORT_ID` — обязательные параметры точки входа
  (сейчас это сервер **Нидерландов**).
- `REALITY_SERVER_NAME` — имя сервера TLS/Reality; по умолчанию `dl.google.com`.
- `PROXY_PORT` — локальный порт прокси; по умолчанию `7890`.
- `CLIENT_FINGERPRINT` — TLS-отпечаток клиента; по умолчанию `firefox` (`chrome` на
  некоторых сетях не проходит рукопожатие).
- `EXPECTED_EXIT_IP` — ожидаемый внешний IP для проверки установщиком. **Для цепочки
  NL→USA обязательно `108.61.222.91`** (IP США). Если не задать, будет взят `SERVER_IP`
  (IP Нидерландов), и `install.sh` завершится с кодом `6`.
- `RU_SERVER_IP`, `RU_UUID`, `RU_PUBLIC_KEY`, `RU_SHORT_ID`, `RU_REALITY_SERVER_NAME`,
  `CHAIN_MODE` — необязательный второй сервер для альтернативной схемы (см. ниже).
  Для цепочки NL→USA их задавать не нужно.
- `SSH_TUNNEL_SERVER`, `SSH_TUNNEL_NL` — адреса SSH к серверам
  (`root@108.61.222.91` и `root@185.245.107.19`); используются только при обслуживании серверов.

## Серверы: что где настроено

### США (108.61.222.91) — выход

Рабочий Xray VLESS+Reality на TCP 443, SNI `dl.google.com`. **Мы его не меняем.**
Именно он даёт финальный американский IP.

### Нидерланды (185.245.107.19) — релей

На NL стоит standalone Xray с inbound VLESS+Reality на `0.0.0.0:443` и одним catch-all
правилом маршрутизации: **весь** трафик входящего соединения уходит в outbound `to-usa`
(VLESS+Reality к США). Клиентские значения NL хранятся на сервере в
`/root/nl-client-values.txt` (режим 600, содержимое в открытый лог не печатается).

Порт 443 на NL полностью занят Xray-релеем: перед установкой `setup-server.sh`
проверяет это и прерывается с кодом `10`, если порт занят. Поэтому другие сервисы,
слушающие 443 (например, ранее работавший здесь Caddy), нужно остановить и отключить
(`systemctl disable --now <service>`), прежде чем запускать установку.

## Настройка сервера-релея (режим CHAIN_ALL)

Скрипт `server/setup-server.sh` с `CHAIN_ALL=1` поднимает на сервере Xray-релей,
пересылающий весь трафик на апстрим. Нужны данные апстрима (США):

```bash
CHAIN_ALL=1 \
  U_IP=108.61.222.91 \
  U_ID=<USA_UUID> \
  U_PK=<USA_PUBLIC_KEY> \
  U_SID=<USA_SHORT_ID> \
  bash server/setup-server.sh root@185.245.107.19
```

Что скрипт делает по SSH:

1. Проверяет, свободен ли TCP 443; если занят — останавливается (код `10`) и показывает владельца порта.
2. Ставит Xray официальным installer'ом XTLS/Xray-install.
3. Бэкапит существующий `/usr/local/etc/xray/config.json` в `config.json.backup.YYYYMMDD-HHMMSS`.
4. Генерирует новый `UUID`, пару `x25519` (`PRIVATE_KEY`/`PUBLIC_KEY`) и `SHORT_ID`.
5. Пишет конфиг: inbound `vless-reality-in` (`0.0.0.0:443`, Reality, target/SNI `dl.google.com`),
   outbound `to-usa` (VLESS+Reality к США, fingerprint `chrome`), запасной `direct`,
   маршрут `inboundTag vless-reality-in → to-usa`.
6. Выставляет `chown nobody:nogroup` + `chmod 600`, затем `xray run -test -config ...`.
7. Включает BBR, открывает 443 при активном файрволе, перезапускает `xray`.
8. Проверяет `systemctl is-active xray` и слушатель на `:443`.
9. Кладёт клиентские значения в `/root/nl-client-values.txt` (`chmod 600`) и печатает
   только факт успеха **без вывода секретов**.

Тот же скрипт без `CHAIN_*` поднимает обычный VLESS+Reality сервер и печатает готовый
блок `proxy.env`. `KEEP_CONFIG=1` заливает `server/xray-config.json` вместо генерации.
Другой SSH-ключ/порт: `bash server/setup-server.sh root@IP -i ~/.ssh/key -p 2222`.

### Проверка релея на сервере

```bash
ssh root@185.245.107.19 \
  'systemctl is-active xray; ss -H -ltnp "( sport = :443 )"; journalctl -u xray -n 50 --no-pager'
```

### Откат релея

- Восстановить прежний конфиг:
  `cp /usr/local/etc/xray/config.json.backup.<timestamp> /usr/local/etc/xray/config.json && systemctl restart xray`.
- Либо остановить Xray: `systemctl stop xray`.
- Сервер США при этом не затрагивается.

## Обновление клиента после перезагрузки

Mihomo запускается как фоновый процесс и **не переживает перезагрузку WSL/компьютера**.
После перезапуска системы выполните:

```bash
bash ./install.sh
```

Скрипт заново возьмёт бинарник из `bin/`, сгенерирует конфиг и запустит прокси.

## Управление и диагностика

- Журнал Mihomo: `~/.config/mihomo/mihomo.log`.
- Конфиг Mihomo: `~/.config/mihomo/config.yaml`.
- PID-файл: `~/.config/mihomo/mihomo.pid`.
- Перезапуск с текущими настройками: `bash ./install.sh`.
- Остановить: `kill "$(cat ~/.config/mihomo/mihomo.pid)"`.
- Коды завершения `install.sh`:
  - `2` — не заданы обязательные параметры / неподдерживаемая платформа;
  - `3` — не найден архив Mihomo;
  - `4` — Mihomo не запустился (смотрите лог);
  - `5` — проверка HTTPS через прокси не прошла (смотрите лог и серверы);
  - `6` — внешний IP отличается от `EXPECTED_EXIT_IP`.

Типичные проблемы:

| Симптом | Причина | Что делать |
|---|---|---|
| `Could not connect ... via 127.0.0.1` | Mihomo не запущен | `bash ./install.sh`; проверьте `~/.config/mihomo/mihomo.log` |
| `FAILED ... invalid REALITY public key` | неверный `PUBLIC_KEY` в `proxy.env` | уточните ключ и запустите `install.sh` снова |
| Внешний IP = `185.245.107.19` | на NL сработал `direct` вместо `to-usa` | проверьте routing в `/usr/local/etc/xray/config.json`, `journalctl -u xray` |
| Код `6` | `EXPECTED_EXIT_IP` не совпал | задайте `EXPECTED_EXIT_IP=108.61.222.91` |

## Автоустановка Xray на новый сервер и перенос

### Дамп рабочего конфига (`server/xray-config.json`)

Дамп содержит приватный ключ Reality, поэтому в Git не хранится — копируйте вручную.
При переносе на новый IP в `proxy.env` клиента меняйте только `SERVER_IP`; `UUID`,
`PUBLIC_KEY`, `SHORT_ID` остаются прежними. Порт 443 должен быть открыт.

### Установка Xray и импорт конфига

1. Подготовьте VPS (Debian/Ubuntu), откройте порт 443.
2. Поставьте Xray:

```bash
ssh root@NEW_IP 'bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install'
```

3. Загрузите дамп и перезапустите:

```bash
scp server/xray-config.json root@NEW_IP:/usr/local/etc/xray/config.json
ssh root@NEW_IP 'chown nobody:nogroup /usr/local/etc/xray/config.json && chmod 600 /usr/local/etc/xray/config.json && systemctl enable --now xray && systemctl restart xray && ss -ltnp | grep :443'
```

4. Для нового сервера лучше сгенерировать свои ключи:

```bash
ssh root@NEW_IP '/usr/local/bin/xray uuid; /usr/local/bin/xray x25519; openssl rand -hex 8'
```

Подставьте новые `id` (UUID), `privateKey`, `shortIds` в конфиг и перезапустите `xray`;
`PublicKey` из вывода `x25519` уйдёт клиенту.

## Альтернативные схемы

### Один сервер вместо цепочки

Если IP одного сервера стабилен (NL-сервер может и полностью заменить USA), релей не
нужен: впишите данные этого сервера как основные (`SERVER_IP`, `UUID`, `PUBLIC_KEY`,
`SHORT_ID`) и задайте `EXPECTED_EXIT_IP` равным его IP. `RU_*`/`CHAIN_MODE` не задавайте.
Предварительно проверьте доступность порта: `nc -vz -w5 SERVER_IP 443`.

### AI-домены через USA, остальное — через релей (`CHAIN_USA` + `CHAIN_MODE`)

Режим `CHAIN_USA=1` на релее отправляет на США **только** AI-домены, остальное выпускает
напрямую. Тогда релей описывается в `proxy.env` клиента как второй сервер:

```bash
CHAIN_USA=1 U_IP=<USA_IP> U_ID=<USA_UUID> U_PK=<USA_PUBLIC_KEY> U_SID=<USA_SHORT_ID> \
  bash server/setup-server.sh root@RELAY_IP
```

Вывод скрипта впишите как `RU_SERVER_IP`, `RU_UUID`, `RU_PUBLIC_KEY`, `RU_SHORT_ID` и
добавьте `CHAIN_MODE=1`. `install.sh` создаст узел `RU-NODE` и группу `RU`; AI-домены
останутся на `PROXY` (США), а правило `MATCH` пойдёт в `RU`. Имена `RU_*` исторические —
релеем может быть любой сервер.

**Важно:** в цепочке NL→USA переменные `RU_*`/`CHAIN_MODE` задавать нельзя — они
переключают основной маршрут и ломают двухступенчатую схему.
