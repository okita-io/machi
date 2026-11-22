#!/bin/sh
# Download the OpenJTalk dictionary into the installed pyopenjtalk package.
# The library fetches this tarball on first use. Running it at image build
# keeps the container offline at runtime.
set -eu
python - <<'PY'
import pyopenjtalk

kana = pyopenjtalk.g2p("あ", kana=True)
path = pyopenjtalk.OPEN_JTALK_DICT_DIR
if isinstance(path, bytes):
    path = path.decode()
print(kana)
print(path)
PY
