import csv
import os
import sys
import threading
import time
import traceback
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from pypdf import PdfReader, PdfWriter


# ====== 拖拽支持 ======
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    root = TkinterDnD.Tk()
    DND_AVAILABLE = True
except Exception:
    root = tk.Tk()
    DND_AVAILABLE = False


root.title("PDF Tools")
root.geometry("1100x900")
root.minsize(1000, 760)
root.configure(bg="#eef2f7")
VERSION = "v3.1.1"


def ui(func):
    root.after(0, func)


LOG_FLUSH_MS = 40
PROGRESS_UPDATE_INTERVAL = 0.08
log_lock = threading.Lock()
pending_logs = []
log_flush_scheduled = False
last_progress_update = 0.0


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


icon_path = resource_path("icon.ico")
try:
    root.iconbitmap(icon_path)
except Exception:
    pass


# ====== 样式 ======
style = ttk.Style()
style.theme_use("default")

style.configure(
    "Vertical.TScrollbar",
    background="#2b2b2b",
    troughcolor="#1a1a1a",
    bordercolor="#1a1a1a",
)
style.map("Vertical.TScrollbar", background=[("active", "#444")])

style.configure(
    "Horizontal.TScrollbar",
    background="#2b2b2b",
    troughcolor="#1a1a1a",
    bordercolor="#1a1a1a",
)
style.map("Horizontal.TScrollbar", background=[("active", "#444")])

style.configure(
    "green.Horizontal.TProgressbar",
    troughcolor="#e6e6e6",
    background="#2ecc71",
    lightcolor="#2ecc71",
    darkcolor="#2ecc71",
)
style.configure(
    "blue.Horizontal.TProgressbar",
    troughcolor="#e6e6e6",
    background="#3498db",
    lightcolor="#3498db",
    darkcolor="#3498db",
)
style.configure(
    "red.Horizontal.TProgressbar",
    troughcolor="#e6e6e6",
    background="#e74c3c",
    lightcolor="#e74c3c",
    darkcolor="#e74c3c",
)


# ====== 变量 ======
input_pdf = tk.StringVar()
output_dir = tk.StringVar(value=os.path.join(os.getcwd(), "output"))
output_csv = tk.BooleanVar(value=False)
multi_files = []
is_processing = False


# ====== 颜色 ======
CARD = "#ffffff"
PRIMARY = "#4a90e2"
PRIMARY_HOVER = "#357ABD"
TEXT = "#2f3640"
MUTED = "#667085"
LOG_BG = "#111111"
FONT_TITLE = ("微软雅黑", 12, "bold")
FONT_TEXT = ("微软雅黑", 11)
FONT_SMALL = ("微软雅黑", 10)
FONT_BUTTON = ("微软雅黑", 11)
FONT_RUN = ("微软雅黑", 13, "bold")
FONT_LOG_TITLE = ("微软雅黑", 12, "bold")
FONT_LOG = ("Consolas", 11)


# ====== 主布局 ======
GAP = 12
CARD_Y_PAD = 7
TOP_HEADER_HEIGHT = 70
LOG_BOTTOM_OFFSET = 22

main = tk.Frame(root, bg="#eef2f7")
main.pack(fill="both", expand=True, padx=GAP, pady=GAP)
main.rowconfigure(0, weight=1)
main.columnconfigure(0, weight=1, uniform="main")
main.columnconfigure(1, weight=1, uniform="main")

left = tk.Frame(main, bg="#eef2f7")
right = tk.Frame(main, bg=LOG_BG)

left.grid(row=0, column=0, sticky="nsew", padx=(0, GAP // 2), pady=0)
right.grid(
    row=0,
    column=1,
    sticky="nsew",
    padx=(GAP // 2, 0),
    pady=(CARD_Y_PAD, LOG_BOTTOM_OFFSET),
)


# ====== 工具函数 ======
def log(msg, level="info"):
    global log_flush_scheduled
    now = time.strftime("%H:%M:%S")

    if isinstance(msg, str):
        msg = msg.replace("\\", "/")

    with log_lock:
        pending_logs.append((now, msg, level))
        should_schedule = not log_flush_scheduled
        log_flush_scheduled = True

    if should_schedule:
        ui(lambda: root.after(LOG_FLUSH_MS, flush_logs))


def flush_logs():
    global log_flush_scheduled

    with log_lock:
        items = pending_logs[:]
        pending_logs.clear()
        log_flush_scheduled = False

    if not items:
        return

    for now, msg, level in items:
        text_log.insert("end", f"[{now}]{msg}\n", level)
    text_log.see("end")

    with log_lock:
        has_more = bool(pending_logs)
        if has_more:
            log_flush_scheduled = True

    if has_more:
        root.after(LOG_FLUSH_MS, flush_logs)


def log_block(title):
    log("==========" + title + "==========")


def init_log_tags():
    colors = {
        "info": "#cccccc",
        "ok": "#00ffcc",
        "warn": "#ffcc00",
        "error": "#ff4d4f",
    }
    for tag, color in colors.items():
        text_log.tag_config(tag, foreground=color)


def set_progress(
    style_name=None,
    mode=None,
    value=None,
    text=None,
    start=False,
    stop=False,
    force=False,
):
    global last_progress_update

    now = time.monotonic()
    has_state_change = style_name is not None or mode is not None or start or stop
    if not force and not has_state_change and value is not None:
        if now - last_progress_update < PROGRESS_UPDATE_INTERVAL and value < 100:
            return
    last_progress_update = now

    def update():
        if stop:
            progress.stop()
        if style_name or mode:
            kwargs = {}
            if style_name:
                kwargs["style"] = style_name
            if mode:
                kwargs["mode"] = mode
            progress.config(**kwargs)
        if value is not None:
            progress["value"] = value
        if text is not None:
            progress_label.config(text=text)
        if start:
            progress.start(10)

    ui(update)


def reset_processing():
    global is_processing
    is_processing = False

    def update():
        btn_run.config(state=tk.NORMAL)

    ui(update)


def parse_input(text):
    raw = text.replace("，", ",")
    out = []
    for part in raw.split(","):
        for line in part.splitlines():
            value = line.strip()
            if value:
                out.append(value)
    return out


def build_splits(rule, total):
    if not rule:
        raise ValueError("拆分规则不能为空")

    parts = parse_input(rule)
    splits = [int(item) for item in parts]
    if not splits or any(num <= 0 for num in splits):
        raise ValueError("拆分规则必须全部为大于 0 的数字")

    if len(splits) == 1:
        size = splits[0]
        count = total // size
        if total % size:
            count += 1
        return [size] * count

    split_total = sum(splits)
    if split_total < total:
        rest = total - split_total
        log(f"[WARN]拆分规则少于总页数，剩余 {rest} 页不会自动追加", "warn")
    elif split_total > total:
        log(f"[WARN]拆分规则总页数 {split_total} 超过 PDF 总页数 {total}，校验会提示不一致", "warn")

    return splits


# ====== 卡片 ======
def card(title, parent=left):
    frame = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground="#dcdfe6")
    frame.pack(fill="x", padx=8, pady=CARD_Y_PAD)

    tk.Label(
        frame,
        text=title,
        bg=CARD,
        font=("微软雅黑", 11, "bold"),
        fg=TEXT,
    ).pack(anchor="w", padx=14, pady=(10, 4))

    return frame


def styled_entry(parent, var=None):
    entry = tk.Entry(
        parent,
        textvariable=var,
        font=("微软雅黑", 10),
        relief="flat",
        highlightthickness=1,
        highlightbackground="#c0c4cc",
        highlightcolor=PRIMARY,
    )
    entry.pack(fill="x", padx=14, pady=6, ipady=7)
    return entry


def styled_text(parent, h=6):
    text = tk.Text(
        parent,
        height=h,
        font=("Consolas", 10),
        relief="flat",
        highlightthickness=1,
        highlightbackground="#c0c4cc",
        highlightcolor=PRIMARY,
    )
    text.pack(fill="both", padx=14, pady=(6, 12))
    return text


def action_button(parent, text, command):
    btn = tk.Button(
        parent,
        text=text,
        width=12,
        bg=PRIMARY,
        fg="white",
        relief="flat",
        activebackground=PRIMARY_HOVER,
        activeforeground="white",
        cursor="hand2",
        command=command,
    )
    btn.pack(anchor="e", padx=14, pady=(2, 12), ipadx=18, ipady=5)
    hover(btn)
    return btn


class Tooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)
        widget.bind("<Motion>", self.move)

    def show(self, event=None):
        if self.tip:
            return

        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.configure(bg="#d0d5dd")

        label = tk.Label(
            self.tip,
            text=self.text,
            justify="left",
            bg="#ffffff",
            fg=TEXT,
            font=("微软雅黑", 9),
            relief="flat",
            padx=12,
            pady=10,
            wraplength=560,
        )
        label.pack(padx=1, pady=1)
        self.move(event)

    def move(self, event=None):
        if not self.tip:
            return

        x = self.widget.winfo_pointerx() + 16
        y = self.widget.winfo_pointery() + 16
        self.tip.wm_geometry(f"+{x}+{y}")

    def hide(self, event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


def hover(btn):
    btn.bind("<Enter>", lambda event: btn.config(bg=PRIMARY_HOVER))
    btn.bind("<Leave>", lambda event: btn.config(bg=PRIMARY))


# ====== 文件 ======
def select_file():
    global multi_files
    files = filedialog.askopenfilenames(
        filetypes=[("PDF 文件", "*.pdf"), ("所有文件", "*.*")]
    )
    if files:
        multi_files = list(files)
        input_pdf.set(files[0])
        log(f"[INFO]已选择{len(files)}个文件")
        for file_path in files:
            log(f"[FILE]{file_path}")


def select_folder():
    folder = filedialog.askdirectory()
    if folder:
        output_dir.set(folder)
        log(f"[INFO]输出目录:{folder}")


def drop(event):
    global multi_files
    try:
        files = root.tk.splitlist(event.data)
    except Exception:
        files = [event.data.strip("{}").strip('"')]

    multi_files = list(files)

    if files:
        input_pdf.set(files[0])
        log(f"[INFO]拖入{len(files)}个文件")
        for file_path in files:
            log(f"[FILE]{file_path}")


# ====== 主逻辑 ======
def process_worker(path, outdir, rule, name_input, selected_files, save_csv):
    start_time = time.time()
    try:
        log_block("开始处理")
        set_progress(
            style_name="blue.Horizontal.TProgressbar",
            mode="indeterminate",
            text="处理中...",
            start=True,
            force=True,
        )

        if not path:
            log("[ERROR]未选择PDF文件", "error")
            set_progress(
                style_name="red.Horizontal.TProgressbar",
                mode="determinate",
                value=0,
                stop=True,
                force=True,
            )
            return

        if len(selected_files) > 1:
            rename_multi_files(selected_files, name_input)
            return

        split_pdf(path, outdir, rule, name_input, save_csv, start_time)
    except Exception:
        err = traceback.format_exc()
        log("[ERROR]处理失败\n" + err, "error")
        set_progress(
            style_name="red.Horizontal.TProgressbar",
            mode="determinate",
            value=0,
            text="失败",
            stop=True,
            force=True,
        )
    finally:
        reset_processing()


def rename_multi_files(selected_files, name_input):
    log_block("多文件重命名")
    names = parse_input(name_input)

    if len(names) != len(selected_files):
        log("[ERROR]名称数量不一致", "error")
        set_progress(
            style_name="red.Horizontal.TProgressbar",
            mode="determinate",
            value=0,
            text="失败",
            stop=True,
            force=True,
        )
        return

    if len(names) != len(set(names)):
        log("[ERROR]存在重复名称", "error")
        set_progress(
            style_name="red.Horizontal.TProgressbar",
            mode="determinate",
            value=0,
            text="失败",
            stop=True,
            force=True,
        )
        return

    for old_path, new_name in zip(selected_files, names):
        ext = os.path.splitext(old_path)[1]
        new_path = os.path.join(os.path.dirname(old_path), f"{new_name}{ext}")

        if os.path.exists(new_path):
            log(f"[WARN]已存在:{new_path}", "warn")
            continue

        try:
            os.rename(old_path, new_path)
            log(f"[OK]{old_path}->{new_path}", "ok")
        except Exception as exc:
            log(f"[ERROR]重命名失败:{old_path} {exc}", "error")

    set_progress(
        style_name="green.Horizontal.TProgressbar",
        mode="determinate",
        value=100,
        text="完成",
        stop=True,
        force=True,
    )
    log_block("完成")


def split_pdf(path, outdir, rule, name_input, save_csv, start_time):
    log(f"[INFO]输入文件:{path}")

    if not outdir:
        outdir = os.getcwd()
        log(f"[INFO]输出目录未指定，默认使用当前目录:{outdir}")
    else:
        try:
            if not os.path.exists(outdir):
                os.makedirs(outdir)
                log(f"[INFO]已创建输出目录:{outdir}")
            elif not os.path.isdir(outdir):
                log(f"[ERROR]指定路径不是有效目录:{outdir}", "error")
                set_progress(
                    style_name="red.Horizontal.TProgressbar",
                    mode="determinate",
                    value=0,
                    text="失败",
                    stop=True,
                    force=True,
                )
                return
        except Exception as exc:
            log(f"[ERROR]无法创建或访问输出目录:{exc}", "error")
            set_progress(
                style_name="red.Horizontal.TProgressbar",
                mode="determinate",
                value=0,
                text="失败",
                stop=True,
                force=True,
            )
            return

    log(f"[INFO]输出目录:{outdir}")

    try:
        reader = PdfReader(path)
        total = len(reader.pages)
        log(f"[INFO]总页数:{total}")
    except Exception as exc:
        log(f"[ERROR]读取失败:{exc}", "error")
        set_progress(
            style_name="red.Horizontal.TProgressbar",
            mode="determinate",
            value=0,
            text="失败",
            stop=True,
            force=True,
        )
        return

    try:
        splits = build_splits(rule, total)
        log(f"[INFO]拆分规则:{splits}")
    except Exception as exc:
        log(f"[ERROR]拆分规则格式错误:{exc}", "error")
        set_progress(
            style_name="red.Horizontal.TProgressbar",
            mode="determinate",
            value=0,
            text="失败",
            stop=True,
            force=True,
        )
        return

    set_progress(
        style_name="green.Horizontal.TProgressbar",
        mode="determinate",
        value=0,
        stop=True,
        force=True,
    )

    start_page = 0
    output_files = []

    for index, num in enumerate(splits):
        file_name = f"{index + 1:02d}_output.pdf"

        if start_page >= total:
            log(f"[ERROR]第{index + 1}段期望:{num}页，但 PDF 已无剩余页", "error")
            output_files.append(
                {
                    "path": "",
                    "name": file_name,
                    "expected": num,
                    "actual": 0,
                    "generated": False,
                }
            )
            continue

        end_page = min(start_page + num, total)
        actual_pages = end_page - start_page
        log(f"[STEP]第{index + 1}段:期望{num}页|实际{actual_pages}页(起始{start_page + 1})")

        writer = PdfWriter()
        for page_index in range(start_page, end_page):
            writer.add_page(reader.pages[page_index])

        full_path = os.path.join(outdir, file_name)

        try:
            with open(full_path, "wb") as file:
                writer.write(file)
            log(f"[OK]生成:{full_path}", "ok")
        except Exception as exc:
            log(f"[ERROR]写入失败:{file_name} {exc}", "error")
            set_progress(
                style_name="red.Horizontal.TProgressbar",
                mode="determinate",
                value=0,
                text="失败",
                force=True,
            )
            return

        output_files.append(
            {
                "path": full_path,
                "name": file_name,
                "expected": num,
                "actual": actual_pages,
                "generated": True,
            }
        )
        start_page = end_page

        percent = min((start_page / total) * 100, 100)
        set_progress(value=percent, text=f"{percent:.1f}%")

    set_progress(value=100, text="100%", force=True)

    generated_files = [item for item in output_files if item["generated"]]
    if not generated_files:
        log("[ERROR]未生成文件", "error")
        set_progress(
            style_name="red.Horizontal.TProgressbar",
            mode="determinate",
            value=0,
            text="失败",
            force=True,
        )
        return

    check_results = check_outputs(output_files)
    if save_csv:
        write_csv(outdir, check_results)
    else:
        log("[INFO]未输出CSV")
    rename_outputs(outdir, generated_files, name_input)

    duration = time.time() - start_time
    errors = sum(1 for item in check_results if item["结果"] != "正确")
    if errors:
        set_progress(
            style_name="red.Horizontal.TProgressbar",
            mode="determinate",
            value=100,
            text="页数不一致",
            force=True,
        )
        ui(lambda: messagebox.showwarning("页数不一致", f"发现 {errors} 个文件页数与手动输入不一致，请查看运行日志。"))
    else:
        set_progress(
            style_name="green.Horizontal.TProgressbar",
            mode="determinate",
            value=100,
            text="完成",
            force=True,
        )

    log_block("完成")
    log(f"[INFO]输出:{len(generated_files)}")
    log(f"[INFO]错误:{errors}")
    log(f"[INFO]耗时:{duration:.2f}s")


def check_outputs(output_files):
    log_block("校验")
    result = []
    errors = 0

    for item in output_files:
        file_path = item["path"]
        file_name = item["name"]
        expected_pages = item["expected"]

        if item["generated"]:
            try:
                reader = PdfReader(file_path)
                actual_pages = len(reader.pages)
            except Exception:
                actual_pages = "失败"
        else:
            actual_pages = item["actual"]

        ok = actual_pages == expected_pages
        log(f"[CHECK]{file_name}|期望:{expected_pages}|实际:{actual_pages}")
        if not ok:
            errors += 1
            log(f"[ERROR]页数不一致:{file_name}", "error")

        result.append(
            {
                "文件名": file_name,
                "期望页数": expected_pages,
                "实际页数": actual_pages,
                "结果": "正确" if ok else "错误",
            }
        )

    if errors == 0:
        log(f"[OK]全部正确:{len(result)}个", "ok")
    else:
        log(f"[WARN]存在问题:{errors}个", "warn")

    return result


def write_csv(outdir, result):
    try:
        if result:
            csv_path = os.path.join(outdir, "拆分结果.csv")
            with open(csv_path, "w", newline="", encoding="utf-8-sig") as file:
                writer = csv.DictWriter(file, fieldnames=result[0].keys())
                writer.writeheader()
                writer.writerows(result)
            log(f"[INFO]CSV路径:{csv_path}")
    except Exception as exc:
        log(f"[ERROR]CSV写入失败:{exc}", "error")


def rename_outputs(outdir, output_files, name_input):
    if not name_input:
        log("[INFO]未执行重命名")
        return

    log_block("重命名")
    names = parse_input(name_input)

    if len(names) != len(output_files):
        log("[ERROR]名称数量不一致", "error")
        return

    if len(names) != len(set(names)):
        log("[ERROR]存在重复名称", "error")
        return

    for item, new_name in zip(output_files, names):
        old_path = item["path"]
        new_path = os.path.join(outdir, f"{new_name}.pdf")

        if os.path.exists(new_path):
            log(f"[WARN]已存在:{new_path}", "warn")
            continue

        try:
            os.rename(old_path, new_path)
            log(f"[OK]{old_path}->{new_path}", "ok")
        except Exception as exc:
            log(f"[ERROR]重命名失败:{old_path} {exc}", "error")


def start_process():
    global is_processing, log_flush_scheduled

    if is_processing:
        log("[WARN]正在处理中，请稍候...", "warn")
        return

    is_processing = True
    btn_run.config(state=tk.DISABLED)
    with log_lock:
        pending_logs.clear()
        log_flush_scheduled = False
    text_log.delete("1.0", "end")

    path = input_pdf.get().strip()
    outdir = output_dir.get().strip()
    rule = text_rules.get("1.0", "end").strip()
    name_input = text_names.get("1.0", "end").strip()
    save_csv = output_csv.get()
    selected_files = list(multi_files)
    if selected_files and path != selected_files[0]:
        selected_files = [path]

    threading.Thread(
        target=process_worker,
        args=(path, outdir, rule, name_input, selected_files, save_csv),
        daemon=True,
    ).start()


# ====== UI ======
c_tip = card("使用说明")
c_tip.config(height=TOP_HEADER_HEIGHT)
c_tip.pack_propagate(False)
usage_hint = tk.Label(
    c_tip,
    text="鼠标停在这里查看使用说明（点击打开开源地址）",
    bg=CARD,
    fg=MUTED,
    justify="left",
    font=("微软雅黑", 9),
)

usage_hint.pack(anchor="w", padx=14, pady=(0, 10))

open_url = "https://github.com/XinlingLabs/PDFTools"

usage_hint.bind(
    "<Button-1>",
    lambda e: webbrowser.open(open_url)
)
usage_tooltip_text = (
    "使用说明\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "1. 选择文件\n"
    "   选择或拖入 PDF 文件，单文件用于拆分。\n"
    "   一次选择多个文件时，用于批量重命名。\n\n"
    "2. 规则拆分\n"
    "   只输入一个数字，例如 3。\n"
    "   程序会按每 3 页一直拆到 PDF 结束。\n"
    "   每段期望页数都按手动输入的 3 计算。\n\n"
    "3. 不规则拆分\n"
    "   输入多个数字，例如 2,3,5。\n"
    "   也可以逐行输入 2、3、5。\n"
    "   期望页数只取手动输入的每个数字。\n\n"
    "4. 页数校验\n"
    "   实际页数与期望页数不一致时会提示。\n"
    "   日志标红、进度条变红，并弹窗提醒。\n\n"
    "5. 文件命名\n"
    "   新文件名可选，支持逐行或逗号分隔。\n"
    "   名称数量必须与生成文件数量一致。\n"
    "   文件名不能重复，已存在文件不会覆盖。\n\n"
    "6. 输出设置\n"
    "   输出路径为空时，默认使用当前目录。\n"
    "   路径不存在时，程序会自动创建。\n"
    "   勾选输出 CSV 后，才生成拆分结果.csv。\n\n"
    "by xinling"
)
Tooltip(usage_hint, usage_tooltip_text)

c1 = card("PDF文件")
e = styled_entry(c1, input_pdf)
if DND_AVAILABLE:
    e.drop_target_register(DND_FILES)
    e.dnd_bind("<<Drop>>", drop)

btn_file = action_button(c1, "选择文件", select_file)

c_out = card("输出路径")
styled_entry(c_out, output_dir)
btn_folder = action_button(c_out, "选择文件夹", select_folder)
tk.Checkbutton(
    c_out,
    text="输出 CSV 校验表",
    variable=output_csv,
    bg=CARD,
    fg=TEXT,
    activebackground=CARD,
    activeforeground=TEXT,
    selectcolor=CARD,
    font=("微软雅黑", 10),
    anchor="w",
).pack(fill="x", padx=14, pady=(0, 12))

c2 = card("拆分规则")
text_rules = styled_text(c2, 5)

c3 = card("新文件名")
text_names = styled_text(c3, 5)

bottom_bar = tk.Frame(left, bg="#eef2f7")
bottom_bar.pack(side="bottom", fill="x", padx=8, pady=(GAP, 0))

btn_run = tk.Button(
    bottom_bar,
    text="开始处理",
    height=2,
    bg=PRIMARY,
    fg="white",
    activebackground=PRIMARY_HOVER,
    activeforeground="white",
    relief="flat",
    cursor="hand2",
    font=("微软雅黑", 12, "bold"),
    command=start_process,
)
btn_run.pack(fill="x", pady=(0, 8))
hover(btn_run)

progress = ttk.Progressbar(bottom_bar, style="green.Horizontal.TProgressbar")
progress.pack(fill="x")
progress_label = tk.Label(
    bottom_bar,
    text="0%",
    bg="#eef2f7",
    fg=MUTED,
    font=("微软雅黑", 9),
    anchor="center",
)
progress_label.pack(fill="x", pady=(2, 0))

frame_log = tk.Frame(right, bg=LOG_BG)
frame_log.pack(side="top", fill="both", expand=True, padx=(0, 0), pady=(0, 0))
frame_log.rowconfigure(2, weight=1)
frame_log.columnconfigure(0, weight=1)

log_title = tk.Label(
    frame_log,
    text="运行日志",
    bg=LOG_BG,
    fg="white",
    font=("微软雅黑", 11, "bold"),
    anchor="w",
)
log_title.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 6))

log_separator = tk.Frame(frame_log, bg="#5a5a5a", height=1)
log_separator.grid(row=1, column=0, columnspan=2, sticky="ew")

scroll_y = ttk.Scrollbar(frame_log)
scroll_y.grid(row=2, column=1, rowspan=2, sticky="ns")

scroll_x = ttk.Scrollbar(frame_log, orient="horizontal")
scroll_x.grid(row=3, column=0, sticky="ew")

text_log = tk.Text(
    frame_log,
    bg=LOG_BG,
    fg="#eee",
    insertbackground="white",
    font=("Consolas", 10),
    yscrollcommand=scroll_y.set,
    xscrollcommand=scroll_x.set,
    wrap="none",
    borderwidth=0,
    highlightthickness=0,
)
text_log.grid(row=2, column=0, sticky="nsew", padx=(8, 0))

scroll_y.config(command=text_log.yview)
scroll_x.config(command=text_log.xview)
init_log_tags()
log(f"[INFO]程序已启动 {VERSION}")


def global_exception_hook(exc_type, exc_value, exc_traceback):
    err = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    try:
        log("[ERROR]崩溃\n" + err, "error")
    except Exception:
        print(err)


sys.excepthook = global_exception_hook

if not DND_AVAILABLE:
    log("[WARN]未安装tkinterdnd2", "warn")

root.mainloop()
