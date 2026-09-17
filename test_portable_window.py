"""Verify the ordinary double-click startup path and normal window close."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import subprocess
import time

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parent
exe = json.loads((ROOT/'test-output'/'portable-validation.json').read_text(encoding='utf-8'))['extracted_exe']
process = subprocess.Popen([exe], cwd=Path(exe).parent)
user = ctypes.windll.user32
user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user.IsWindowVisible.argtypes = [wintypes.HWND]
user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user.UpdateWindow.argtypes = [wintypes.HWND]
user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
CALLBACK = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
windows = []
@CALLBACK
def visit(hwnd, extra):
    pid = wintypes.DWORD(); user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == process.pid:
        text = ctypes.create_unicode_buffer(512); user.GetWindowTextW(hwnd, text,512)
        if text.value.startswith('格识'):
            windows.append((hwnd,text.value,bool(user.IsWindowVisible(hwnd))))
    return True
deadline = time.monotonic()+30
while time.monotonic()<deadline:
    windows.clear(); user.EnumWindows(visit,0)
    if windows:
        break
    if process.poll() is not None:
        raise RuntimeError(f'App quit unexpectedly: {process.returncode}')
    time.sleep(.25)
assert windows, 'No application window found'
hwnd, title, visible = windows[0]
user.ShowWindow(hwnd, 1); user.UpdateWindow(hwnd); time.sleep(1)
image = ImageGrab.grab(window=hwnd)
image.save(ROOT/'test-output'/'portable-exe'/'独立软件启动窗口.png')
assert len(image.getcolors(image.width*image.height)) > 100, 'Window appears unrendered'
user.PostMessageW(hwnd,0x0010,0,0)
process.wait(timeout=15)
assert process.returncode==0
print(json.dumps({'title':title,'visible_at_start':visible,'window_rendered':True,'window_size':image.size,'normal_close_exit_code':process.returncode},ensure_ascii=False))
