"""Reproducible Windows portable build; run with this project's build venv."""
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
ASSETS = ROOT / 'assets'; ASSETS.mkdir(exist_ok=True)
image = Image.new('RGBA', (256,256), (0,0,0,0)); draw = ImageDraw.Draw(image)
draw.rounded_rectangle((8,8,248,248), radius=52, fill='#126b59')
draw.rounded_rectangle((55,53,201,203), radius=10, outline='white', width=10)
draw.rectangle((60,59,196,94), fill='#d8ead9')
for y in [99,149]:
    draw.line((60,y,197,y),fill='white',width=8)
for x in [104,153]:
    draw.line((x,98,x,198),fill='white',width=8)
image.save(ASSETS/'gezhi.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])

for variable, folder in [('TCL_LIBRARY','tcl8.6'),('TK_LIBRARY','tk8.6')]:
    location = Path(sys.base_prefix)/'tcl'/folder
    if location.exists():
        os.environ[variable] = str(location)

args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir', '--windowed',
        '--name', '格识', '--icon', str(ASSETS/'gezhi.ico'),
        '--add-data', f'{ASSETS}{os.pathsep}assets',
        '--collect-all', 'rapidocr_onnxruntime', '--collect-all', 'onnxruntime',
        '--distpath', str(ROOT/'dist'), '--workpath', str(ROOT/'build'),
        '--specpath', str(ROOT/'build'), '--exclude-module', 'playwright',
        '--exclude-module', 'openpyxl', '--exclude-module', 'flask',
        '--exclude-module', 'pytest', '--exclude-module', 'IPython',
        '--exclude-module', 'matplotlib', '--exclude-module', 'pandas',
        str(ROOT/'desktop.py')]
subprocess.run(args, check=True)

package = ROOT/'dist'/'格识'
shutil.copy2(ROOT/'PORTABLE_README.txt', package/'使用说明.txt')
examples = package/'示例图片'; examples.mkdir(exist_ok=True)
shutil.copy2(ROOT/'test-output'/'中文表格示例.png', examples/'中文表格示例.png')
licenses = package/'开源许可'; licenses.mkdir(exist_ok=True)
components = []
names = ['rapidocr-onnxruntime','onnxruntime','opencv-python','numpy','pillow','pyclipper',
         'shapely','PyYAML','six','flatbuffers','packaging','protobuf','pyinstaller']
for name in names:
    dist = metadata.distribution(name)
    target = licenses/name; target.mkdir(exist_ok=True)
    components.append({'name': name, 'version': dist.version,
                       'homepage': dist.metadata.get('Home-page', ''),
                       'license': dist.metadata.get('License-Expression') or dist.metadata.get('License','')})
    for item in dist.files or []:
        filename = str(item)
        if any(part in Path(filename).name.lower() for part in ['license','licence','notice','copying','copyright']):
            source = Path(dist.locate_file(item))
            if source.is_file() and source.suffix.lower() not in ('.pyc','.py','.pyd','.dll'):
                safe_name = filename.replace('..','_').replace('/','_').replace('\\','_')
                shutil.copy2(source, target/safe_name)
    (target/'package-metadata.txt').write_text(dist.read_text('METADATA') or '', encoding='utf-8')
for label, source in [('Python', Path(sys.base_prefix)/'LICENSE.txt'),
                      ('Tcl', ASSETS/'Tcl-LICENSE.txt'),
                      ('Tk', Path(sys.base_prefix)/'tcl'/'tk8.6'/'license.terms')]:
    if source.exists():
        shutil.copy2(source, licenses/f'{label}-LICENSE.txt')
(licenses/'components.json').write_text(json.dumps(components,ensure_ascii=False,indent=2),encoding='utf-8')
(package/'版本.txt').write_text('格识 1.0.0\nWindows x64 便携版\n包含独立 Python 运行时、Tcl/Tk 界面与本地 OCR 模型。\n',encoding='utf-8-sig')
print(f'PORTABLE_FOLDER={package}')
