#!/usr/bin/env bash
# Self-signed LAN certificate for the Machi phone mic (secure context).
# Writes .certs/machi.crt and .certs/machi.key (gitignored). Does not start Docker.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/.certs"
LAN_IP="${LAN_IP:-}"
TS_IP="${TS_IP:-}"

usage() {
  echo "Usage: $0 [--lan A.B.C.D] [--tailscale A.B.C.D]" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lan)
      LAN_IP="${2:-}"
      shift 2
      ;;
    --tailscale)
      TS_IP="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "$LAN_IP" ]]; then
  if command -v ipconfig >/dev/null 2>&1; then
    LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || true)"
    if [[ -z "$LAN_IP" ]]; then
      LAN_IP="$(ipconfig getifaddr en1 2>/dev/null || true)"
    fi
  fi
  if [[ -z "$LAN_IP" ]]; then
    LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  fi
fi

if [[ -z "$TS_IP" ]] && command -v tailscale >/dev/null 2>&1; then
  TS_IP="$(tailscale ip -4 2>/dev/null | head -n 1 || true)"
fi

if [[ -z "$LAN_IP" ]]; then
  echo "Could not detect a LAN IP. Re-run with --lan A.B.C.D" >&2
  exit 1
fi

SAN="DNS:localhost,IP:127.0.0.1,IP:::1,IP:${LAN_IP}"
if [[ -n "$TS_IP" ]]; then
  SAN="${SAN},IP:${TS_IP}"
fi

mkdir -p "$OUT"
CNF="$(mktemp)"
trap 'rm -f "$CNF"' EXIT
cat >"$CNF" <<EOF
[req]
distinguished_name = dn
x509_extensions = v3_req
prompt = no
[dn]
CN = machi-lan
[v3_req]
subjectAltName = ${SAN}
basicConstraints = CA:TRUE
keyUsage = digitalSignature, keyEncipherment, keyCertSign
extendedKeyUsage = serverAuth
EOF

# 100 years. Browsers require the SAN above; the CN alone is not enough.
openssl req -x509 -newkey rsa:2048 -sha256 -days 36500 -nodes \
  -keyout "$OUT/machi.key" \
  -out "$OUT/machi.crt" \
  -config "$CNF"

chmod 600 "$OUT/machi.key"
echo "Wrote $OUT/machi.crt and $OUT/machi.key"
echo "Subject alternative names: ${SAN}"
echo
cat <<EOF
Phone mic — secure context
  getUserMedia only runs on localhost or HTTPS. http://<lan-ip>:5173 is not a
  secure context, so the mic stays blocked. Use https://${LAN_IP}:5174

Start (HTTP :5173 is unchanged; HTTPS is the extra profile):
  docker compose --profile cpu --profile https up
  # or, without Docker, from web/: HTTPS=1 npm run dev

Install this certificate on the phone, then open https://${LAN_IP}:5174

iOS
  1. AirDrop or otherwise copy $OUT/machi.crt onto the phone and open it.
  2. Settings → General → VPN & Device Management → the downloaded profile
     (it may also appear as Settings → Profile Downloaded) → Install.
  3. Settings → General → About → Certificate Trust Settings → enable full
     trust for "machi-lan".
  4. Safari → https://${LAN_IP}:5174 and allow the microphone.

Android
  1. Copy machi.crt to the phone.
  2. Settings → Security → Encryption & credentials → Install a certificate
     → CA certificate, and pick machi.crt. Confirm the warning.
  3. Chrome → https://${LAN_IP}:5174 and allow the microphone.
  Chrome trusts user-installed CAs. Some other WebViews ignore the user store.

Tailscale
  The certificate includes the Tailscale IPv4 when \`tailscale ip -4\` works
  or you pass --tailscale. Open https://<tailscale-ip>:5174 after the phone
  joins the same tailnet and trusts machi.crt.
  Alternative with a real name and no manual trust: on the Machi host run
  \`tailscale serve\` in front of port 5173 (Tailscale issues the certificate).
  Do not put that proxy in docker compose.

EOF
