# Перенос клиента Mihomo на Docker

Инструкция описывает, как заменить установку через `install.sh` на Docker-контейнер
Mihomo с тем же результатом: локальный прокси на `127.0.0.1:7890`, цепочка
клиент → Нидерланды → США и финальный внешний IP `108.61.222.91`.

Это необязательный вариант. Штатный `install.sh` работает без Docker. Перенос имеет
смысл, когда нужен переносимый и самовосстанавливающийся прокси, а Docker на машине
уже стоит. Меняется только **клиентская** часть; серверы (NL-релей и USA-выход) —
см. «Серверная часть».

## Что заменяется

| | `install.sh` (systemd / cron / LaunchAgent) | Docker |
|---|---|---|
| Автозапуск после перезагрузки | unit / cron `@reboot` / plist | `restart: unless-stopped` + автозапуск Docker |
| Перезапуск после падения | ~3 с (systemd) или до 1 мин (cron) | секунды, средствами движка |
| Файлы на хосте | `~/.local/bin/mihomo`, `~/.config/mihomo/*` | образ `metacubex/mihomo` + ваш `config.yaml` |
| Перенос между машинами | нет | да (образ + конфиг) |
| Лог | `~/.config/mihomo/mihomo.log` | `docker compose logs` |

Хостовую обвязку контейнер не заменяет — см. «Что остаётся на хосте».

## Образ

Официальный образ — **`metacubex/mihomo`** на Docker Hub.

- Теги: `latest` и версионные. Версия этого набора — **`v1.19.32`** (совпадает с архивами
  в `bin/`).
- Платформы: `amd64`, `arm64` (в теге есть также `arm`, `386`).
- Устройство (по официальному `Dockerfile`): база `alpine`, `ENTRYPOINT ["/mihomo"]`, том
  `/root/.config/mihomo/`. В каталог конфига уже положены `geoip.dat`, `geosite.dat`,
  `geoip.metadb`. В образе есть `ca-certificates`, `tzdata`, `iptables`, но **нет `curl`** —
  прокси проверяем с хоста.

Пиньте версию (`v1.19.32`), а не `latest`, чтобы обновление образа не меняло поведение
неожиданно.

## Ключевая правка конфига

Конфиг, который генерирует `install.sh`, содержит `allow-lan: false`. При этом Mihomo
биндится на `127.0.0.1` **внутри контейнера**, а Docker при публикации порта заходит в
контейнер по его сетевому IP. Итог: `-p 127.0.0.1:7890:7890` «висит» и не отвечает.

В исходниках Mihomo (`listener/listener.go`, `genAddr`) это видно прямо:

```go
if allowLan {
    if host == "*" {
        return fmt.Sprintf(":%d", port)
    }
    return fmt.Sprintf("%s:%d", host, port)
}
return fmt.Sprintf("127.0.0.1:%d", port) // allowLan = false
```

Поэтому для bridge-сети (вариант A) в конфиге нужно:

```yaml
allow-lan: true
bind-address: "*"
```

`bind-address` действует только при `allow-lan: true` (значения по умолчанию — `0.0.0.0/0`
и `::/0`; официальная документация: `wiki.metacubex.one/en/config/general/`). Наружу
публикуйте **только loopback хоста** (`127.0.0.1:7890`) — иначе при `allow-lan: true` прокси
станет доступен всей локальной сети.

Для варианта B (`network_mode: host`, только Linux) правка не нужна.

## Подготовка

1. Возьмите рабочий конфиг с хоста (в нём уже значения точки входа NL) и положите его в
   отдельный каталог вне репозитория, чтобы `install.sh` его не перезаписывал:

```bash
mkdir -p ~/mihomo-docker
cp ~/.config/mihomo/config.yaml ~/mihomo-docker/config.yaml
```

2. Для варианта A включите LAN-доступ и `bind-address`:

```bash
sed -i 's/^allow-lan: false/allow-lan: true/' ~/mihomo-docker/config.yaml
grep -q '^bind-address:' ~/mihomo-docker/config.yaml \
  || printf 'bind-address: "*"\n' >> ~/mihomo-docker/config.yaml
```

Проверьте результат:

```bash
grep -E '^(allow-lan|bind-address|mixed-port):' ~/mihomo-docker/config.yaml
# allow-lan: true
# bind-address: "*"
# mixed-port: 7890
```

`~/mihomo-docker/config.yaml` содержит секреты (UUID, public-key точки входа NL) — держите
его вне Git и не встраивайте в образ.

## Вариант A: bridge-сеть + публикация на loopback (любая ОС)

`~/mihomo-docker/docker-compose.yml`:

```yaml
services:
  mihomo:
    image: metacubex/mihomo:v1.19.32      # или :latest
    container_name: mihomo
    restart: unless-stopped               # автозапуск и самовосстановление
    ports:
      - "127.0.0.1:7890:7890"             # доступен только с loopback хоста
    volumes:
      - ./config.yaml:/root/.config/mihomo/config.yaml:ro
    command: ["-d", "/root/.config/mihomo"]
```

Запуск:

```bash
cd ~/mihomo-docker
docker compose up -d
docker compose ps
docker compose logs -f
```

То же самое без compose, одной командой:

```bash
docker run -d --name mihomo --restart unless-stopped \
  -p 127.0.0.1:7890:7890 \
  -v "$HOME/mihomo-docker/config.yaml:/root/.config/mihomo/config.yaml:ro" \
  metacubex/mihomo:v1.19.32 -d /root/.config/mihomo
```

> Монтируется **только файл** `config.yaml`. Если смонтировать весь каталог
> `/root/.config/mihomo`, вы скроете вложенные в образ `geoip.dat` / `geosite.dat` /
> `geoip.metadb`.

## Вариант B: host-сеть (только Linux)

Если Docker работает на Linux (в том числе внутри WSL2), можно отдать контейнеру сеть
хоста. Тогда Mihomo слушает `127.0.0.1:7890` хоста напрямую: правка `allow-lan` /
`bind-address` не нужна, публикация порта тоже.

```yaml
services:
  mihomo:
    image: metacubex/mihomo:v1.19.32
    container_name: mihomo
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./config.yaml:/root/.config/mihomo/config.yaml:ro
    command: ["-d", "/root/.config/mihomo"]
```

`network_mode: host` поддерживает только Docker Engine на Linux. В Docker Desktop для
macOS/Windows host-сети нет — там используйте вариант A.

## Проверка

```bash
docker compose ps                                   # состояние контейнера
docker compose logs -f                              # логи Mihomo в реальном времени
curl -s --noproxy '' -x http://127.0.0.1:7890 https://api.ipify.org
# → 108.61.222.91
```

Однострочник со сравнением:

```bash
got=$(curl -s --noproxy '' -x http://127.0.0.1:7890 https://api.ipify.org)
echo "returned=$got expected=108.61.222.91"
[ "$got" = "108.61.222.91" ] && echo OK || echo MISMATCH
```

Как читать ответ — тот же, что в README: `108.61.222.91` — правильный выход США;
`185.245.107.19` — на релее сработал `direct` вместо `to-usa`; ваш собственный IP — запрос
не использовал прокси.

## Автозапуск и самовосстановление

Политика `restart: unless-stopped` перезапускает Mihomo после падения и возвращает
контейнер после перезапуска движка. Остаётся поднять сам Docker при загрузке:

- **Linux (Docker Engine):** `sudo systemctl enable --now docker`. Контейнер вернётся
  вместе с движком при загрузке хоста.
- **macOS / Windows (Docker Desktop):** включите запуск Docker Desktop при входе
  (Settings → General → *Start Docker Desktop when you sign in*).
- **WSL:** либо Docker внутри WSL (включите systemd в `/etc/wsl.conf`, затем
  `sudo systemctl enable docker`), либо Docker Desktop с WSL-интеграцией.

### Важно: отключите хостовый супервизор

Иначе после перезагрузки поднимутся **два** Mihomo (systemd/cron/LaunchAgent и контейнер)
и начнут драться за порт `7890`:

```bash
# Linux с systemd
systemctl --user disable --now mihomo.service

# Linux с cron: crontab -e — удалите блок от '# mihomo local proxy begin'
# до '# mihomo local proxy end'
crontab -l

# macOS
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.mihomo.proxy.plist
```

Убедитесь, что на хосте не осталось процесса Mihomo:

```bash
pgrep -x mihomo || echo "host mihomo not running"
```

## Что остаётся на хосте

Контейнер не управляет хостовыми настройками — их нужно сохранить или задать на машине:

- **Системный прокси macOS** (`networksetup`, его включает `install.sh`). При переходе на
  Docker настройте вручную (System Settings → Network → Proxies) на `127.0.0.1:7890`.
- **Настройка AI CLI** (`setup-ai-cli-proxy.sh`): блок `env` в `~/.claude/settings.json` и
  перезапуск демона Codex. Скрипт хостовый — запускайте его на хосте, не в контейнере.
- **Переменные прокси в шелле** (`~/.bashrc` / `~/.zshrc`) — указывают на `127.0.0.1:7890`,
  это тот же порт, что публикует контейнер, поэтому менять их не нужно.
- **`install.sh`** при работе через Docker не запускается — иначе он перегенерирует конфиг
  и снова поднимет хостовый супервизор.

Наблюдать за AI-трафиком теперь удобнее через логи контейнера:

```bash
docker compose logs -f mihomo \
  | grep --line-buffered -iE 'anthropic|claude|openai|chatgpt|jetbrains|grazie|USA'
```

> По WSL: при Docker Engine внутри WSL опубликованный порт виден только внутри WSL — та же
> оговорка, что и в README про Windows-браузеры. С Docker Desktop порты форвардятся в
> Windows, и окно браузера на хосте тоже сможет ходить через `127.0.0.1:7890`.

## Секреты

- `config.yaml` содержит `uuid` / `public-key` точки входа NL. Монтируйте его read-only и
  не встраивайте в образ (`COPY`/`ADD`). Если положите файл внутрь репозитория, добавьте
  его в `.gitignore`.
- `proxy.env` в Docker не нужен: контейнеру отдаётся уже готовый `config.yaml`.

## Серверная часть (NL-релей) — не в контейнере

Docker касается только клиента. Релей Нидерландов (`server/setup-server.sh`) остаётся как
есть: он выполняет хостовые шаги — `sysctl` для BBR, открытие 443 в файрволе, права на
`/usr/local/etc/xray`, systemd-юнит. В контейнер это не завернуть; сам Xray
контейнеризовать можно, но выигрыша нет. Сервер США не изменяется.

## Откат на install.sh

```bash
cd ~/mihomo-docker && docker compose down
cd ~/mihomo-proxy-kit && bash ./install.sh
```

`install.sh` снова поднимет Mihomo на хосте и зарегистрирует systemd/cron/LaunchAgent.

## Диагностика

| Симптом | Причина | Что делать |
|---|---|---|
| `-p 127.0.0.1:7890:7890` не отвечает, порт в `docker compose ps` есть | в конфиге `allow-lan: false` | поставьте `allow-lan: true` и `bind-address: "*"`, перезапустите |
| Контейнер перезапускается в цикле | ошибка разбора `config.yaml` | `docker compose logs` — там `Parse config error` |
| Ответ `185.245.107.19` | на релее сработал `direct` вместо `to-usa` | проверьте routing в `/usr/local/etc/xray/config.json`, `journalctl -u xray` |
| Ответ — ваш реальный IP | запрос прошёл мимо прокси | используйте `curl -x http://127.0.0.1:7890 …` |
| `docker exec … curl: not found` | в образе нет `curl` | проверяйте прокси с хоста |
| После перезагрузки прокси не поднялся | Docker не стартует автоматически | включите автозапуск движка / Docker Desktop |
| `bind: address already in use` в логах | остался хостовый Mihomo | отключите systemd/cron/LaunchAgent (см. выше) |
