#!/bin/sh
# HTTPS is opt-in. HTTP :5173 always comes from conf.d/default.conf.
# HTTPS=1 copies the TLS server onto :5174. Certs are mounted at runtime.
set -e
if [ "${HTTPS}" = "1" ]; then
  if [ ! -s /etc/nginx/certs/machi.crt ] || [ ! -s /etc/nginx/certs/machi.key ]; then
    echo "HTTPS=1 needs .certs/machi.crt and .certs/machi.key. Run scripts/make_lan_https.sh" >&2
    exit 1
  fi
  cp /etc/nginx/https.conf /etc/nginx/conf.d/https.conf
fi
exec "$@"
