"""Standalone Windows desktop interface for the offline OCR engine."""
import io
import json
import logging
import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import warnings

import cv2
import numpy as np
from PIL import Image, ImageGrab, ImageOps, ImageTk, UnidentifiedImageError

from excel import make_xlsx
from ocr import recognize, reconstruct

VERSION = '1.0.0'
LOG_DIR = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'GezhiOCR'
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(filename=LOG_DIR / 'desktop.log', level=logging.INFO,
                    encoding='utf-8', format='%(asctime)s %(levelname)s %(message)s')
Image.MAX_IMAGE_PIXELS = 25_000_000


class Desktop:
    def __init__(self, root):
        self.root = root
        self.image = None
        self.photo = None
        self.data, self.merges, self.scores = [], [], []
        self.filename = '识别结果'
        self.busy = False
        self.events = queue.Queue()
        self.editor = None
        self.selected_col = 0
        self.closed = False
        root.title(f'格识 · 图片转 Excel  {VERSION}')
        self.scale = max(1., root.winfo_fpixels('1i') / 96.)
        width = min(int(1180*self.scale), root.winfo_screenwidth()-80)
        height = min(int(780*self.scale), root.winfo_screenheight()-100)
        root.geometry(f'{width}x{height}')
        root.minsize(min(int(940*self.scale), width), min(int(660*self.scale), height))
        root.configure(bg='#f2f5ef')
        icon = Path(__file__).resolve().parent / 'assets' / 'gezhi.ico'
        if icon.exists():
            root.iconbitmap(str(icon))
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 10))
        style.configure('TFrame', background='#f2f5ef')
        style.configure('Card.TFrame', background='#fbfcf9')
        style.configure('TLabel', background='#f2f5ef', foreground='#203b34')
        style.configure('Card.TLabel', background='#fbfcf9', foreground='#203b34')
        style.configure('TButton', padding=(12, 8), background='#edf2eb', foreground='#203b34')
        style.map('TButton', background=[('active', '#dceade')])
        style.configure('Primary.TButton', background='#126b59', foreground='white', padding=(16, 11))
        style.map('Primary.TButton', background=[('disabled', '#adc8bc'), ('active', '#095544')], foreground=[('disabled', '#f6f8f4')])
        style.configure('Treeview', font=('Microsoft YaHei UI', 10), rowheight=int(34*self.scale),
                        background='white', fieldbackground='white', borderwidth=0)
        style.configure('Treeview.Heading', font=('Microsoft YaHei UI', 10, 'bold'),
                        background='#e8efe7', padding=(8, 8))
        style.map('Treeview', background=[('selected', '#cee5d9')], foreground=[('selected', '#173f32')])
        header = tk.Frame(root, bg='#fbfcf9', padx=28, pady=18)
        header.pack(fill='x')
        tk.Label(header, text='▦  格识', font=('Microsoft YaHei UI', 23, 'bold'), fg='#126b59', bg='#fbfcf9').pack(side='left')
        tk.Label(header, text='图片转 Excel', font=('Microsoft YaHei UI', 11), fg='#73847b', bg='#fbfcf9').pack(side='left', padx=20)
        tk.Label(header, text='● 本地离线识别', font=('Microsoft YaHei UI', 10), fg='#478462', bg='#fbfcf9').pack(side='right')
        intro = ttk.Frame(root, padding=(28, 20, 28, 16)); intro.pack(fill='x')
        ttk.Label(intro, text='把图片里的表格，变成你的 Excel。', font=('Microsoft YaHei UI', 22, 'bold')).pack(anchor='w')
        ttk.Label(intro, text='1  添加图片     →     2  识别并校对     →     3  保存 Excel', foreground='#75817c').pack(anchor='w', pady=(10, 0))
        main = ttk.Frame(root, padding=(24, 0, 24, 12)); main.pack(fill='both', expand=True)
        main.columnconfigure(0, weight=4, uniform='panels'); main.columnconfigure(1, weight=6, uniform='panels'); main.rowconfigure(0, weight=1)
        left = ttk.Frame(main, style='Card.TFrame', padding=18); left.grid(row=0, column=0, sticky='nsew', padx=(0, 12))
        right = ttk.Frame(main, style='Card.TFrame', padding=18); right.grid(row=0, column=1, sticky='nsew')
        ttk.Label(left, text='原始图片', style='Card.TLabel', font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor='w')
        self.canvas = tk.Canvas(left, bg='#f1f6ee', highlightthickness=1, highlightbackground='#dce6d9', cursor='hand2')
        self.canvas.pack(fill='both', expand=True, pady=14)
        self.canvas.bind('<Configure>', lambda _: self.draw_preview())
        self.canvas.bind('<Button-1>', lambda _: self.choose_file() if self.image is None else self.preview_full())
        self.file_label = ttk.Label(left, text='PNG / JPG / WEBP / BMP · 最大 24 MB', style='Card.TLabel', foreground='#75817c')
        self.file_label.pack(anchor='w')
        actions = ttk.Frame(left, style='Card.TFrame'); actions.pack(fill='x', pady=12)
        self.choose_btn = ttk.Button(actions, text='选择图片', command=self.choose_file); self.choose_btn.pack(side='left')
        self.paste_btn = ttk.Button(actions, text='粘贴截图', command=self.paste_image); self.paste_btn.pack(side='left', padx=6)
        self.rotate_btn = ttk.Button(actions, text='旋转 90°', command=self.rotate); self.rotate_btn.pack(side='right')
        modes = ttk.Frame(left, style='Card.TFrame'); modes.pack(fill='x', pady=(0, 12))
        ttk.Label(modes, text='识别模式', style='Card.TLabel').pack(side='left')
        self.mode = ttk.Combobox(modes, values=['自动判断', '有边框表格', '无边框 / 对齐文字'], state='readonly', width=20)
        self.mode.current(0); self.mode.pack(side='right')
        self.recognize_btn = ttk.Button(left, text='识别表格  →', style='Primary.TButton', command=self.start_ocr); self.recognize_btn.pack(fill='x')
        ttk.Label(left, text='点击原图可放大查看。建议先裁剪到单个表格。\n复杂合并、模糊或手写内容需人工核对。', style='Card.TLabel', foreground='#75817c', font=('Microsoft YaHei UI', 9)).pack(anchor='w', pady=(12, 0))
        top = ttk.Frame(right, style='Card.TFrame'); top.pack(fill='x')
        ttk.Label(top, text='识别结果', style='Card.TLabel', font=('Microsoft YaHei UI', 12, 'bold')).pack(side='left')
        self.dimensions = ttk.Label(top, text='等待识别', style='Card.TLabel', foreground='#75817c'); self.dimensions.pack(side='right')
        toolbar = ttk.Frame(right, style='Card.TFrame'); toolbar.pack(fill='x', pady=12)
        self.edit_buttons = []
        for label, command in [('＋ 行', self.add_row), ('＋ 列', self.add_col), ('删行', self.delete_row), ('删列', self.delete_col), ('取消合并', self.unmerge)]:
            button = ttk.Button(toolbar, text=label, command=command, padding=(7, 6)); button.pack(side='left', padx=(0, 5)); self.edit_buttons.append(button)
        table_frame = ttk.Frame(right, style='Card.TFrame'); table_frame.pack(fill='both', expand=True)
        table_frame.rowconfigure(0, weight=1); table_frame.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(table_frame, show='tree headings', selectmode='browse')
        self.tree.heading('#0', text='行'); self.tree.column('#0', width=int(44*self.scale), minwidth=44, stretch=False)
        self.tree.grid(row=0, column=0, sticky='nsew')
        ybar = ttk.Scrollbar(table_frame, orient='vertical', command=self.scroll_y); ybar.grid(row=0, column=1, sticky='ns')
        xbar = ttk.Scrollbar(table_frame, orient='horizontal', command=self.scroll_x); xbar.grid(row=1, column=0, sticky='ew')
        self.tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.tree.tag_configure('low', background='#fff5d6')
        self.tree.bind('<Double-1>', self.edit_cell)
        self.tree.bind('<Button-1>', self.select_column)
        self.tree.bind('<MouseWheel>', lambda _: self.commit_edit())
        self.note = ttk.Label(right, text='双击单元格编辑。淡黄色行含低置信度文字。', style='Card.TLabel', foreground='#75817c', wraplength=520, font=('Microsoft YaHei UI', 9)); self.note.pack(anchor='w', pady=12)
        right.bind('<Configure>', lambda event: self.note.configure(wraplength=max(250, event.width-42)))
        self.export_btn = ttk.Button(right, text='保存 Excel  ↓', style='Primary.TButton', command=self.save_dialog); self.export_btn.pack(fill='x')
        ttk.Label(right, text='编号与前导零按文本保留；不自动执行公式。', style='Card.TLabel', foreground='#75817c', font=('Microsoft YaHei UI', 9)).pack(anchor='w', pady=(8, 0))
        bottom = ttk.Frame(root, padding=(28, 0, 28, 18)); bottom.pack(fill='x')
        self.progress = ttk.Progressbar(bottom, mode='indeterminate', length=110); self.progress.pack(side='right')
        self.status = ttk.Label(bottom, text='就绪 · 选择图片或粘贴截图开始', foreground='#52755e'); self.status.pack(side='left')
        root.bind('<Control-v>', self.keyboard_paste)
        root.bind('<Control-o>', lambda _: self.choose_file())
        root.bind('<Control-s>', lambda _: self.save_dialog())
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.report_callback_exception = self.callback_error
        self.set_busy(False)
        root.after(100, self.poll)

    def callback_error(self, kind, value, traceback):
        logging.error('UI error', exc_info=(kind, value, traceback))
        messagebox.showerror('操作失败', f'操作未完成，请重试。\n日志：{LOG_DIR / "desktop.log"}', parent=self.root)

    def set_busy(self, value):
        self.busy = value
        for button in (self.choose_btn, self.paste_btn):
            button.configure(state='disabled' if value else 'normal')
        for button in (self.rotate_btn, self.recognize_btn):
            button.configure(state='disabled' if value or self.image is None else 'normal')
        for button in [self.export_btn] + self.edit_buttons:
            button.configure(state='disabled' if value or not self.data else 'normal')
        self.mode.configure(state='disabled' if value else 'readonly')
        if value:
            self.progress.start(12)
        else:
            self.progress.stop()

    def load_image(self, source, name):
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            if source.width * source.height > 25_000_000:
                raise ValueError('图片超过 2500 万像素，请缩小后重试。')
            if min(source.size) < 25:
                raise ValueError('图片太小，无法识别表格。')
            image = ImageOps.exif_transpose(source).convert('RGBA')
            white = Image.new('RGBA', image.size, 'white'); white.alpha_composite(image)
            self.image = white.convert('RGB')
        self.commit_edit()
        self.filename = Path(name).stem
        self.data, self.merges, self.scores = [], [], []
        self.file_label.configure(text=f'{Path(name).name[:36]} · {self.image.width} × {self.image.height}')
        self.render_table(); self.draw_preview(); self.set_busy(False)
        self.status.configure(text='图片已就绪 · 点击“识别表格”')

    def choose_file(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(parent=self.root, title='选择表格图片', filetypes=[('图片', '*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff'), ('所有文件', '*.*')])
        if path:
            self.load_path(path)

    def load_path(self, path):
        try:
            if Path(path).stat().st_size > 24 * 1024 * 1024:
                raise ValueError('请选择小于 24 MB 的图片。')
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(path) as source:
                    self.load_image(source, path)
            return True
        except Exception as error:
            messagebox.showerror('无法打开图片', str(error), parent=self.root)
            return False

    def keyboard_paste(self, event):
        if not isinstance(event.widget, (tk.Entry, ttk.Entry, tk.Text)):
            self.paste_image()
            return 'break'

    def paste_image(self):
        if self.busy:
            return
        try:
            source = ImageGrab.grabclipboard()
            if isinstance(source, Image.Image):
                self.load_image(source, '粘贴的截图.png')
            elif isinstance(source, list) and source:
                self.load_path(source[0])
            else:
                self.status.configure(text='剪贴板中没有图片。请先截图或复制一个图片文件。')
        except Exception as error:
            messagebox.showerror('粘贴失败', str(error), parent=self.root)

    def rotate(self):
        if not self.busy and self.image is not None:
            self.load_image(self.image.transpose(Image.Transpose.ROTATE_270), self.filename + '.png')

    def draw_preview(self):
        self.canvas.delete('all')
        w, h = max(50, self.canvas.winfo_width()), max(50, self.canvas.winfo_height())
        if self.image is None:
            self.canvas.create_text(w/2, h/2, text='＋  选择表格图片\n\n或按 Ctrl + V 粘贴截图', justify='center', fill='#6b8570', font=('Microsoft YaHei UI', 12))
        else:
            image = self.image.copy(); image.thumbnail((max(1, w-14), max(1, h-14)))
            self.photo = ImageTk.PhotoImage(image)
            self.canvas.create_image(w/2, h/2, image=self.photo)

    def preview_full(self):
        if self.image is None:
            return
        window = tk.Toplevel(self.root); window.title('原图 · 可滚动查看'); window.geometry('900x650')
        window.rowconfigure(0, weight=1); window.columnconfigure(0, weight=1)
        canvas = tk.Canvas(window, bg='white'); canvas.grid(row=0, column=0, sticky='nsew')
        xb = ttk.Scrollbar(window, orient='horizontal', command=canvas.xview); xb.grid(row=1, column=0, sticky='ew')
        yb = ttk.Scrollbar(window, orient='vertical', command=canvas.yview); yb.grid(row=0, column=1, sticky='ns')
        window.photo = ImageTk.PhotoImage(self.image)
        canvas.create_image(0, 0, anchor='nw', image=window.photo)
        canvas.configure(scrollregion=(0,0,self.image.width,self.image.height), xscrollcommand=xb.set, yscrollcommand=yb.set)

    def start_ocr(self):
        if self.busy or self.image is None:
            return
        self.commit_edit(); self.set_busy(True)
        self.status.configure(text='正在本地识别… 首次加载模型需要稍等。')
        source = self.image.copy(); mode = ['auto', 'grid', 'plain'][self.mode.current()]
        def work():
            try:
                source.thumbnail((2800, 2800))
                image = cv2.cvtColor(np.asarray(source), cv2.COLOR_RGB2BGR)
                boxes = recognize(image)
                if not boxes:
                    raise ValueError('没有识别到文字，请使用清晰、正向的表格图片。')
                result = reconstruct(image, boxes, mode)
                self.events.put(('result', result))
            except Exception as error:
                logging.exception('OCR failed')
                self.events.put(('error', str(error)))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        if self.closed:
            return
        try:
            kind, result = self.events.get_nowait()
            if kind == 'result':
                self.data, self.merges, self.scores = result['data'], result['merges'], result['scores']
                self.note.configure(text=result['note'] + '\n双击编辑。淡黄色行含低置信度文字；合并区域在导出时还原。')
                self.render_table()
                self.status.configure(text=f'识别完成 · {result["method"]} · 请对照原图校对')
            else:
                self.status.configure(text='识别未完成，请调整图片或模式后重试。')
                messagebox.showerror('识别失败', result, parent=self.root)
            self.set_busy(False)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    @staticmethod
    def column(n):
        value = ''
        while True:
            value = chr(65+n%26) + value; n = n//26-1
            if n < 0:
                return value

    def render_table(self):
        self.commit_edit()
        self.tree.delete(*self.tree.get_children())
        columns = [str(c) for c in range(len(self.data[0]))] if self.data else []
        self.tree.configure(columns=columns)
        for c in columns:
            self.tree.heading(c, text=self.column(int(c))); self.tree.column(c, width=140, minwidth=65, stretch=True)
        for r, row in enumerate(self.data):
            low = any(score < .85 and row[c] for c, score in enumerate(self.scores[r])) if r < len(self.scores) else False
            display = [str(v).replace('\n', ' ⏎ ') for v in row]
            self.tree.insert('', 'end', iid=str(r), text=str(r+1), values=display, tags=('low',) if low else ())
        self.dimensions.configure(text=f'{len(self.data)} 行 × {len(columns)} 列' if self.data else '等待识别')

    def select_column(self, event):
        self.commit_edit()
        col = self.tree.identify_column(event.x)
        if col and col != '#0':
            self.selected_col = int(col[1:])-1

    def edit_cell(self, event):
        if self.busy:
            return
        row = self.tree.identify_row(event.y); col = self.tree.identify_column(event.x)
        if not row or not col or col == '#0':
            return
        r, c = int(row), int(col[1:])-1
        for a,b,d,e in self.merges:
            if a <= r <= d and b <= c <= e and (r,c) != (a,b):
                self.status.configure(text='该单元格属于合并区域，请编辑左上角，或先“取消合并”。')
                return
        self.commit_edit()
        x, y, w, h = self.tree.bbox(row, col)
        editor = tk.Text(self.tree, font=('Microsoft YaHei UI', 10), wrap='none', borderwidth=1, relief='solid')
        editor.insert('1.0', self.data[r][c]); editor.place(x=x, y=y, width=w, height=max(h, 50))
        editor.focus_set(); editor.tag_add('sel', '1.0', 'end-1c')
        self.editor = (editor, r, c)
        editor.bind('<FocusOut>', lambda _: self.commit_edit())
        editor.bind('<Return>', self.finish_edit)
        editor.bind('<Shift-Return>', lambda _: None)
        editor.bind('<Escape>', self.cancel_edit)

    def finish_edit(self, _=None):
        self.commit_edit(); return 'break'

    def cancel_edit(self, _=None):
        if self.editor:
            editor, _, _ = self.editor; self.editor = None; editor.destroy()
        return 'break'

    def commit_edit(self):
        if self.editor:
            editor, r, c = self.editor; self.editor = None
            value = editor.get('1.0', 'end-1c'); editor.destroy()
            self.data[r][c] = value
            if self.tree.exists(str(r)):
                self.tree.set(str(r), str(c), value.replace('\n', ' ⏎ '))

    def scroll_y(self, *args):
        self.commit_edit(); self.tree.yview(*args)

    def scroll_x(self, *args):
        self.commit_edit(); self.tree.xview(*args)

    def add_row(self):
        if self.busy or not self.data:
            return
        if len(self.data) >= 2000:
            return self.status.configure(text='最多支持 2000 行。')
        self.commit_edit(); self.data.append([''] * len(self.data[0])); self.render_table()

    def add_col(self):
        if self.busy or not self.data:
            return
        if len(self.data[0]) >= 200:
            return self.status.configure(text='最多支持 200 列。')
        self.commit_edit()
        for row in self.data:
            row.append('')
        self.render_table()

    def can_delete(self, axis):
        if self.busy or not self.data or not self.tree.selection():
            self.status.configure(text='请先选中要删除的行或列中的单元格。'); return False
        if self.merges:
            self.status.configure(text='请先取消合并，再删除行或列。'); return False
        if (len(self.data) if axis == '行' else len(self.data[0])) <= 1:
            self.status.configure(text='至少保留一行和一列。'); return False
        return messagebox.askyesno('确认删除', f'删除所选{axis}及其内容？', parent=self.root)

    def delete_row(self):
        if self.can_delete('行'):
            self.commit_edit(); r = int(self.tree.selection()[0]); self.data.pop(r)
            if r < len(self.scores):
                self.scores.pop(r)
            self.render_table()

    def delete_col(self):
        if self.can_delete('列'):
            self.commit_edit(); c = min(self.selected_col, len(self.data[0])-1)
            for row in self.data:
                row.pop(c)
            for row in self.scores:
                if c < len(row):
                    row.pop(c)
            self.render_table()

    def unmerge(self):
        if self.busy or not self.data:
            return
        self.merges = []; self.status.configure(text='已取消合并，内容保留在原区域左上角。')

    def save_to(self, path):
        self.commit_edit()
        if len(self.data)*len(self.data[0]) > 50000:
            raise ValueError('表格超过 5 万格，请分成多张图片识别。')
        if any(len(v) > 32767 for row in self.data for v in row):
            raise ValueError('单个单元格不能超过 32767 个字符。')
        Path(path).write_bytes(make_xlsx(self.data, self.merges).getvalue())

    def save_dialog(self):
        if self.busy or not self.data:
            return
        self.commit_edit()
        path = filedialog.asksaveasfilename(parent=self.root, title='保存 Excel', defaultextension='.xlsx', initialfile=self.filename+'.xlsx', filetypes=[('Excel 工作簿', '*.xlsx')])
        if path:
            try:
                self.save_to(path); self.status.configure(text=f'已保存：{Path(path).name}')
            except PermissionError:
                messagebox.showerror('无法保存', '文件可能正被 Excel 占用，或此位置没有写入权限。请关闭文件或更换保存位置。', parent=self.root)
            except Exception as error:
                messagebox.showerror('保存失败', str(error), parent=self.root)

    def close(self):
        if self.busy and not messagebox.askyesno('退出软件', '正在识别，退出将中止本次识别。是否退出？', parent=self.root):
            return
        self.closed = True; self.root.destroy()


def self_test(root, ui, image_path, output_dir):
    """Run the shipped GUI/engine/export path with all socket connections blocked."""
    import socket
    import time
    from unittest.mock import patch
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    def deny_network(*args, **kwargs):
        raise AssertionError('Network access attempted during offline test')
    with patch.object(socket.socket, 'connect', deny_network), patch.object(socket.socket, 'connect_ex', deny_network), patch.object(socket, 'create_connection', deny_network):
        root.update()
        if not ui.load_path(image_path):
            raise AssertionError('Image load failed')
        ui.recognize_btn.invoke()
        deadline = time.monotonic()+90
        while ui.busy and time.monotonic() < deadline:
            root.update(); time.sleep(.05)
        if ui.busy:
            raise TimeoutError('OCR timeout')
        expected = [['姓名','部门','编号'],['张三','教务处','00123'],['李四','财务处','00456'],['王五','学生处','00789']]
        assert ui.data == expected, ui.data
        root.update()
        box = ui.tree.bbox('1', '#2')
        from types import SimpleNamespace
        ui.edit_cell(SimpleNamespace(x=box[0]+10, y=box[1]+10))
        assert ui.editor is not None
        editor = ui.editor[0]; editor.delete('1.0','end'); editor.insert('1.0','独立软件中校对')
        ui.finish_edit()
        ui.save_to(out/'独立软件测试.xlsx')
        ui.add_row(); ui.add_col()
        assert len(ui.data)==5 and len(ui.data[0])==4
        ui.data.pop(); [row.pop() for row in ui.data]; ui.render_table()
        root.update()
        import ctypes
        from ctypes import wintypes
        get_ancestor = ctypes.windll.user32.GetAncestor
        get_ancestor.argtypes = [wintypes.HWND, wintypes.UINT]
        get_ancestor.restype = wintypes.HWND
        hwnd = get_ancestor(root.winfo_id(), 2)
        ImageGrab.grab(window=hwnd).save(out/'独立软件界面.png')
        (out/'result.json').write_text(json.dumps({'status':'ok','frozen':bool(getattr(sys,'frozen',False)), 'version':VERSION, 'python':sys.version, 'executable':sys.executable, 'network':'blocked', 'rows':ui.data}, ensure_ascii=False,indent=2),encoding='utf-8')
    ui.close()


def main():
    import ctypes
    if not getattr(sys, 'frozen', False):
        for variable, folder in [('TCL_LIBRARY', 'tcl8.6'), ('TK_LIBRARY', 'tk8.6')]:
            location = Path(sys.base_prefix) / 'tcl' / folder
            if location.exists():
                os.environ.setdefault(variable, str(location))
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk(); ui = Desktop(root)
    if len(sys.argv) == 4 and sys.argv[1] == '--self-test':
        try:
            self_test(root, ui, sys.argv[2], sys.argv[3])
        except Exception:
            logging.exception('Self-test failed')
            try:
                root.destroy()
            except Exception:
                pass
            raise
    else:
        root.mainloop()


if __name__ == '__main__':
    main()
