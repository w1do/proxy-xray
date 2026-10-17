# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM node:24.21.0-alpine3.23@sha256:9ec4a2e289874ed0d722e1772ec2de45d2801541db8612f3638b26f128c69ac2 AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY web/ ./
RUN npm run build && test -f dist/index.html

FROM --platform=$BUILDPLATFORM python:3.12-alpine3.22@sha256:a190708a2dec1bd18b1decb539f8e8f5407abaa9bf39cacda583f7f8c11db322 AS fetch
ARG TARGETARCH
WORKDIR /fetch
RUN set -eu; \
    case "$TARGETARCH" in \
      amd64) M=mihomo-linux-amd64-compatible-v1.19.32.gz; MS=ba3ce607747a07f948fc35780e108a4a7c7f552a38b9bd4d115f313ebcb89c20; \
             X=Xray-linux-64.zip; XS=72a5fde819713a103c6fc26a87aa025c1518c918a34eba4bc38d64dc0728e5d9 ;; \
      arm64) M=mihomo-linux-arm64-v1.19.32.gz; MS=9dd862e28b46ff7d775f169cceebc28deccaa0a9e804237d421cd2571e0caba0; \
             X=Xray-linux-arm64-v8a.zip; XS=58e339e67827220175b3a1c6f66f48ccd086b79209f30ba1c0bcb47885d4c22a ;; \
      *) echo "unsupported TARGETARCH=$TARGETARCH" >&2; exit 1 ;; \
    esac; \
    wget -q -O m.gz "https://github.com/MetaCubeX/mihomo/releases/download/v1.19.32/$M"; \
    echo "$MS  m.gz" | sha256sum -c -; \
    wget -q -O x.zip "https://github.com/XTLS/Xray-core/releases/download/v26.10.10/$X"; \
    echo "$XS  x.zip" | sha256sum -c -; \
    gunzip -c m.gz > mihomo; unzip -q x.zip xray; chmod 0755 mihomo xray

FROM metacubex/mihomo:v1.19.32@sha256:bac1a74de365ea59270ba134016762c6be05654d55246518de256113bd1c225e AS geo

FROM python:3.12-alpine3.22@sha256:a190708a2dec1bd18b1decb539f8e8f5407abaa9bf39cacda583f7f8c11db322
RUN apk add --no-cache openssh-client openssh-keygen curl ca-certificates \
 && addgroup -S -g 10001 kit && adduser -S -D -H -u 10001 -G kit -h /tmp/kit-home kit \
 && mkdir -p /data /kit-gen /kit-state /opt/kit/geo \
 && chown 10001:10001 /data /kit-gen /kit-state && chmod 0700 /data /kit-gen /kit-state
COPY --from=fetch /fetch/mihomo /fetch/xray /usr/local/bin/
COPY --from=geo /root/.config/mihomo/geoip.dat /root/.config/mihomo/geoip.metadb /root/.config/mihomo/geosite.dat /opt/kit/geo/
RUN cd /opt/kit/geo \
 && printf '%s  %s\n' \
      3cf2236c19063c1c80803368cca5ff589c5033129fdf9ba154230c689b81fc2a geoip.dat \
      76ad4ba5d45b1d35b57c3ef26a31c420f7e5afa1e03baf18a47f2d2c933f783b geoip.metadb \
      bff76f6b4d87c3a4c7d9612b926e762b21ba4fe2c5bf8c5a43af25fe8de71b7e geosite.dat | sha256sum -c - \
 && chmod 0644 /opt/kit/geo/* \
 && /usr/local/bin/xray version | head -n1 | grep -q '^Xray 26.10.10 ' \
 && /usr/local/bin/mihomo -v | grep -q 'v1.19.32'
COPY ui/ /app/ui/
COPY --from=web /web/dist/ /app/web/
RUN printf '#!/bin/sh\nexec python3 /app/ui/kit_cli.py "$@"\n' > /usr/local/bin/kit \
 && chmod 0755 /usr/local/bin/kit && python3 -m compileall -q /app/ui
ENV KIT_DATA_DIR=/data KIT_GEN_DIR=/kit-gen KIT_STATE_DIR=/kit-state KIT_GEO_DIR=/opt/kit/geo \
    KIT_XRAY_BIN=/usr/local/bin/xray KIT_MIHOMO_BIN=/usr/local/bin/mihomo \
    KIT_SSH_KEY_MOUNT=/run/secrets/nl_ssh_key KIT_SSH_KEY_FILE=/tmp/kit-ssh/id_nl \
    KIT_WEB_ROOT=/app/web HOME=/tmp/kit-home PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE 4050 7890
CMD ["python3", "/app/ui/server.py"]
