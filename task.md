Ты senior Linux/Xray/Mihomo engineer. Нужно реализовать двух-hop прокси-цепочку:

Client WSL/macOS → Netherlands server → USA server → Internet

Финальный внешний IP должен быть USA, не Netherlands.

Контекст:
- Уже есть рабочий USA сервер Xray VLESS Reality.
- USA Xray слушает TCP 443.
- Текущий клиент WSL/Mihomo уже успешно ходит напрямую через USA.
- Проверка `curl -x http://127.0.0.1:7890 https://api.ipify.org` сейчас возвращает USA IP: 108.61.222.91.
- На USA уже используется Reality `servername/target = dl.google.com`.
- Локальный Mihomo слушает 127.0.0.1:7890.
- Нужно добавить Netherlands сервер как первый hop.
- Client должен подключаться к Netherlands, а Netherlands должен отправлять весь трафик дальше на USA.
- USA сервер желательно не изменять, потому что он уже рабочий.

Используй только эту документацию. Не придумывай поля из памяти. Если поле не найдено в docs, пометь как unsure и не используй:

1. Xray VLESS inbound:
   https://xtls.github.io/en/config/inbounds/vless.html

2. Xray VLESS outbound:
   https://xtls.github.io/en/config/outbounds/vless.html

3. Xray transport / REALITY:
   https://xtls.github.io/en/config/transport.html

4. Xray routing:
   https://xtls.github.io/en/config/routing.html

5. Xray official installer:
   https://github.com/XTLS/Xray-install

6. Mihomo VLESS proxy:
   https://wiki.metacubex.one/en/config/proxies/vless/

7. Mihomo TLS/REALITY options:
   https://wiki.metacubex.one/en/config/proxies/tls/

Ключевые правила:
- Не использовать 3x-ui.
- Только standalone Xray-core.
- Не выводить UUID, PRIVATE_KEY, PUBLIC_KEY, SHORT_ID в публичный лог/ответ.
- Не просить пользователя вставлять приватные ключи в чат.
- Все существующие `/usr/local/etc/xray/config.json` перед изменением бэкапить:
  `/usr/local/etc/xray/config.json.backup.YYYYMMDD-HHMMSS`
- Не использовать naked `exit` в интерактивных SSH-командах. Если нужен `exit`, заворачивать всё в subshell `( ... )`.
- После записи Xray config выставить права с учётом systemd user. Если сервис запускается от `nobody`, использовать:
  `chown nobody:nogroup /usr/local/etc/xray/config.json`
  `chmod 600 /usr/local/etc/xray/config.json`
- Проверять конфиг:
  `xray run -test -config /usr/local/etc/xray/config.json`
- Проверять сервис:
  `systemctl is-active xray`
  `ss -H -ltnp '( sport = :443 )'`
  `journalctl -u xray -n 50 --no-pager`

Что нужно реализовать:

1. На Netherlands сервере установить Xray-core официальным installer-скриптом XTLS/Xray-install.

2. На Netherlands сгенерировать новые значения для клиентского входа:
    - `NL_UUID` через `xray uuid`
    - `NL_PRIVATE_KEY` и `NL_PUBLIC_KEY` через `xray x25519`
    - `NL_SHORT_ID` через `openssl rand -hex 8`

3. Взять существующие USA upstream значения из уже рабочего клиента/конфига, не из чата:
    - `USA_IP = 108.61.222.91`
    - `USA_UUID`
    - `USA_PUBLIC_KEY`
    - `USA_SHORT_ID`
    - `USA_SERVER_NAME = dl.google.com`

4. Создать на Netherlands `/usr/local/etc/xray/config.json` со схемой:

   inbound:
    - listen `0.0.0.0`
    - port `443`
    - protocol `vless`
    - client id = `NL_UUID`
    - client flow = `xtls-rprx-vision`
    - decryption = `none`
    - stream security = `reality`
    - stream network = `raw` или актуальное поле из docs для текущего Xray
    - reality inbound:
        - target = `dl.google.com:443`
        - serverNames = [`dl.google.com`]
        - privateKey = `NL_PRIVATE_KEY`
        - shortIds = [`NL_SHORT_ID`]

   outbound:
    - tag = `to-usa`
    - protocol `vless`
    - address = `108.61.222.91`
    - port = `443`
    - user id = `USA_UUID`
    - encryption = `none`
    - flow = `xtls-rprx-vision`
    - stream security = `reality`
    - serverName = `dl.google.com`
    - fingerprint = `chrome`
    - publicKey = `USA_PUBLIC_KEY`
    - shortId = `USA_SHORT_ID`

   routing:
    - весь трафик из Netherlands inbound отправлять в outbound tag `to-usa`.

5. После настройки Netherlands:
    - проверить config test;
    - restart xray;
    - убедиться, что xray active;
    - убедиться, что слушает TCP 443.

6. Сохранить на Netherlands файл `/root/nl-client-values.txt`:
   SERVER_IP=<NL_IPV4>
   UUID=<NL_UUID>
   PUBLIC_KEY=<NL_PUBLIC_KEY>
   SHORT_ID=<NL_SHORT_ID>
   SERVER_NAME=dl.google.com

   Файл chmod 600. Не печатать его содержимое в финальном ответе.

7. Обновить локальный Mihomo/proxy-kit:
   Теперь клиент должен подключаться не напрямую к USA, а к Netherlands entrypoint:
    - `SERVER_IP = NL_IPV4`
    - `UUID = NL_UUID`
    - `PUBLIC_KEY = NL_PUBLIC_KEY`
    - `SHORT_ID = NL_SHORT_ID`
    - `REALITY_SERVER_NAME = dl.google.com`

   При этом имя группы можно оставить `USA`, потому что финальный egress остаётся USA.

8. Локальные Mihomo правила должны включать USA routing для:
    - `DOMAIN-SUFFIX,openai.com,USA`
    - `DOMAIN-SUFFIX,chatgpt.com,USA`
    - `DOMAIN-SUFFIX,oaiusercontent.com,USA`
    - `DOMAIN-SUFFIX,oaistatic.com,USA`
    - `DOMAIN-SUFFIX,jetbrains.ai,USA`
    - `DOMAIN-SUFFIX,jetbrains.cloud,USA`
    - `DOMAIN-SUFFIX,jetbrains.com,USA`
    - `DOMAIN,api.app.prod.grazie.aws.intellij.net,USA`
    - `DOMAIN-SUFFIX,grazie.ai,USA`
    - `DOMAIN-SUFFIX,anthropic.com,USA`
    - `DOMAIN-SUFFIX,claude.ai,USA`
    - `DOMAIN-SUFFIX,claude.com,USA`
    - `DOMAIN-SUFFIX,claudeusercontent.com,USA`
    - `DOMAIN-SUFFIX,console.anthropic.com,USA`
    - `GEOIP,PRIVATE,DIRECT,no-resolve`
    - `MATCH,USA`

9. Проверка с клиента:
    - Перезапустить Mihomo.
    - Выполнить:
      `curl -x http://127.0.0.1:7890 https://api.ipify.org`
    - Ожидаемый результат:
      `108.61.222.91`
    - Это означает:
      Client подключился к Netherlands, Netherlands прокинул в USA, финальный выход USA.

10. Проверить Claude/Codex/Junie:
    Запустить лог:
    `tail -F ~/.config/mihomo/mihomo.log | grep --line-buffered -iE 'anthropic|claude|openai|chatgpt|jetbrains|grazie|USA'`

Затем запустить Claude Code / Codex / Junie.
В логе должны быть строки вида:
- `api.anthropic.com:443 ... using USA`
- `api.openai.com:443 ... using USA`
- `chatgpt.com:443 ... using USA`
- `api.jetbrains.ai:443 ... using USA`

11. Обновить private repo installer:
    Репозиторий должен позволять начальнику выполнить:
    `git clone <private_repo>`
    `cd <repo>`
    `bash ./install.sh`

В repo должны лежать:
- `install.sh`
- `proxy.env`
- `README.md`
- `bin/mihomo-linux-amd64-compatible-v1.19.32.gz`
- `bin/mihomo-darwin-arm64-v1.19.32.gz`
- `bin/mihomo-darwin-amd64-compatible-v1.19.32.gz`

`proxy.env` должен содержать Netherlands entrypoint credentials, не USA напрямую:
- `SERVER_IP=<NL_IPV4>`
- `UUID=<NL_UUID>`
- `PUBLIC_KEY=<NL_PUBLIC_KEY>`
- `SHORT_ID=<NL_SHORT_ID>`
- `REALITY_SERVER_NAME=dl.google.com`
- `PROXY_PORT=7890`

Repo обязательно private, потому что `proxy.env` даёт доступ к прокси.

12. Rollback:
- USA сервер не менять.
- Если Netherlands не работает, восстановить backup `/usr/local/etc/xray/config.json.backup.*`.
- Если клиент не работает, вернуть старый Mihomo config/proxy.env с прямым USA.
- Проверить rollback через `curl -x http://127.0.0.1:7890 https://api.ipify.org`.

Критерий готовности:
- Client подключается к Netherlands.
- Netherlands прокидывает в USA.
- `curl -x http://127.0.0.1:7890 https://api.ipify.org` возвращает `108.61.222.91`.
- Claude/Anthropic/Codex/OpenAI/Junie/JetBrains/Grazie домены идут через USA group.
- В финальном отчёте не раскрыты UUID, PRIVATE_KEY, PUBLIC_KEY, SHORT_ID.