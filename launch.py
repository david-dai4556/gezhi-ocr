"""Double-click launcher. Starts only this application's private local server."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:18657'


def healthy():
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(BASE+'/api/health', timeout=1) as response:
            return json.load(response).get('app') == 'local-table-ocr-v1'
    except Exception:
        return False


if not healthy():
    with (ROOT/'server.log').open('a', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, str(ROOT/'app.py')], cwd=ROOT,
                                   stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
    (ROOT/'server.pid').write_text(str(process.pid), encoding='ascii')
    for _ in range(90):
        if healthy():
            break
        if process.poll() is not None:
            break
        time.sleep(.5)
    else:
        pass
if healthy():
    webbrowser.open(BASE)
else:
    import ctypes
    ctypes.windll.user32.MessageBoxW(0, f'启动失败，请查看日志：\n{ROOT / "server.log"}\n可能是端口 18657 被其他程序占用。', '格识 · 启动失败', 16)
