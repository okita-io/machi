#!/bin/sh
set -e
case "$SERVICE" in
  asr)
    exec uvicorn speech_cpu.asr_app:app --host 0.0.0.0 --port 8101
    ;;
  tts)
    exec uvicorn speech_cpu.tts_app:app --host 0.0.0.0 --port 8102
    ;;
  *)
    echo "Set SERVICE=asr or SERVICE=tts"
    exit 1
    ;;
esac