#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek Agent Studio —— 属于 DeepSeek 的桌面自主 Agent 工具

由 DeepSeek Agent Core 驱动：
  - 直接调用 DeepSeek Chat Completions API
  - 内置文件 / 命令 / 搜索工具，能自主完成任务
  - 实时显示 Agent 运行指标（轮次、步骤、LLM 耗时、首 token、tok/s...）
"""

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from deepseek_agent_core import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_STEPS,
    DEFAULT_MODEL,
    AgentEngine,
)
from deepseek_eyes import DeepSeekEyes
from deepseek_updater import (
    DEFAULT_MANIFEST_URL,
    DEFAULT_REPO,
    apply_update_and_restart,
    download_update,
    find_update,
)

APP_TITLE = "DeepSeek Agent Studio"
APP_VERSION = "1.1.0"

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "deepseek-agent-studio.json"

DEFAULT_CONFIG = {
    "api_key": "",
    "model": DEFAULT_MODEL,
    "base_url": DEFAULT_BASE_URL,
    "project_dir": str(BASE_DIR),
    "max_steps": DEFAULT_MAX_STEPS,
    "save_api_key": False,
    "update_manifest_url": DEFAULT_MANIFEST_URL,
    "update_repo": DEFAULT_REPO,
    "auto_check_update": True,
}

# ---------------------------------------------------------------- DeepSeek 品牌配色
BG = "#0b0f1a"
PANEL = "#10182b"
CARD = "#151f36"
CARD_BORDER = "#243354"
FG = "#eef2ff"
SUB = "#8291b4"
ACCENT = "#4d6bfe"
ACCENT_BRIGHT = "#6f8cff"
CYAN = "#22d3ee"
BLUE = "#60a5fa"
GREEN = "#4ade80"
RED = "#f87171"
YELLOW = "#fbbf24"
LOG_BG = "#0d1322"
LOG_FG = "#c7d2fe"

MONO = "Consolas"
UI_FONT = "Microsoft YaHei UI"


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in DEFAULT_CONFIG:
                    if key in data:
                        cfg[key] = data[key]
    except Exception:
        return dict(DEFAULT_CONFIG)
    env_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if env_key:
        cfg["api_key"] = env_key
    elif not cfg.get("api_key"):
        # 兼容本目录下的 dsfree_key.txt（只读取第一行，不会自动写回配置）。
        key_file = BASE_DIR / "dsfree_key.txt"
        try:
            if key_file.is_file():
                first_line = key_file.read_text(encoding="utf-8", errors="replace").strip().splitlines()
                if first_line and first_line[0].strip():
                    cfg["api_key"] = first_line[0].strip()
        except Exception:
            pass
    return cfg


def save_config(cfg: dict) -> None:
    try:
        data = dict(cfg)
        if not data.get("save_api_key"):
            data["api_key"] = ""
        CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def fmt_duration(seconds: Optional[float]) -> str:
    if seconds is None or seconds <= 0:
        return "0s"
    if seconds < 60:
        return f"{seconds:.1f}s" if seconds < 10 else f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(round(seconds % 60))
    if secs == 60:
        minutes += 1
        secs = 0
    return f"{minutes}m{secs:02d}s"


def fmt_tokens(value: Optional[int]) -> str:
    value = int(value or 0)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def draw_logo(canvas: tk.Canvas, size: int = 46) -> None:
    """在 Tk Canvas 上绘制 DeepSeek Agent Studio 标志：深海鲸 + 数据节点。"""
    s = size
    canvas.delete("all")
    canvas.create_oval(1, 1, s - 1, s - 1, fill="#1c2a52", outline=ACCENT, width=2)

    # 鲸鱼身体
    canvas.create_oval(int(s * 0.14), int(s * 0.36), int(s * 0.70), int(s * 0.82),
                       fill="#3b5bdb", outline="")
    # 鲸鱼腹部高光
    canvas.create_oval(int(s * 0.20), int(s * 0.50), int(s * 0.66), int(s * 0.84),
                       fill="#5c7cfa", outline="")
    # 尾鳍
    canvas.create_polygon(
        int(s * 0.62), int(s * 0.52), int(s * 0.82), int(s * 0.34),
        int(s * 0.78), int(s * 0.56), int(s * 0.92), int(s * 0.72),
        int(s * 0.72), int(s * 0.66), fill="#2f6df6", outline=""
    )
    # 背鳍
    canvas.create_polygon(
        int(s * 0.30), int(s * 0.30), int(s * 0.42), int(s * 0.16),
        int(s * 0.50), int(s * 0.32), fill="#2f6df6", outline=""
    )
    # 眼睛
    canvas.create_oval(int(s * 0.22), int(s * 0.46), int(s * 0.30), int(s * 0.54),
                       fill="white", outline="")
    canvas.create_oval(int(s * 0.26), int(s * 0.48), int(s * 0.29), int(s * 0.52),
                       fill="#0b0f1a", outline="")
    # 数据节点 / 信号点
    canvas.create_line(int(s * 0.78), int(s * 0.12), int(s * 0.88), int(s * 0.22),
                       fill=CYAN, width=2)
    canvas.create_oval(int(s * 0.82), int(s * 0.08), int(s * 0.94), int(s * 0.20),
                       fill=CYAN, outline="")
    canvas.create_oval(int(s * 0.86), int(s * 0.12), int(s * 0.90), int(s * 0.16),
                       fill="#0b0f1a", outline="")


class DeepSeekAgentStudio:
    CARD_KEYS = [
        ("turns", "轮次", "发起的任务数"),
        ("steps", "步骤", "Agent 循环次数"),
        ("llm_seconds", "LLM 耗时", "模型推理累计"),
        ("tool_seconds", "工具耗时", "工具执行累计"),
        ("avg_ttft", "首 Token 平均", "真实流式首字延迟"),
        ("tokens_per_sec", "Tok/s", "输出 ÷ LLM 耗时"),
        ("cache_hit_rate", "缓存命中", "DeepSeek 上下文缓存"),
        ("input_tokens", "输入 Tok", "prompt tokens"),
        ("output_tokens", "输出 Tok", "completion tokens"),
        ("tool_calls", "工具调用", "累计调用次数"),
    ]

    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = load_config()
        self.event_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self.metrics = None
        self.engine: Optional[AgentEngine] = None
        self.worker: Optional[threading.Thread] = None
        self.agent_running = False
        self._streaming_block = False
        self._last_stream_tag = ""
        self.eyes = DeepSeekEyes()
        self.update_worker: Optional[threading.Thread] = None
        self.eyes_worker: Optional[threading.Thread] = None

        self.api_key_var = tk.StringVar(value=str(self.cfg.get("api_key", "")))
        self.model_var = tk.StringVar(value=str(self.cfg.get("model", DEFAULT_MODEL)))
        self.base_url_var = tk.StringVar(value=str(self.cfg.get("base_url", DEFAULT_BASE_URL)))
        self.project_var = tk.StringVar(value=str(self.cfg.get("project_dir", BASE_DIR)))
        try:
            max_steps = int(self.cfg.get("max_steps", DEFAULT_MAX_STEPS))
        except (TypeError, ValueError):
            max_steps = DEFAULT_MAX_STEPS
        self.max_steps_var = tk.IntVar(value=max(1, min(100, max_steps)))
        self.save_key_var = tk.BooleanVar(value=bool(self.cfg.get("save_api_key", False)))
        self.status_var = tk.StringVar(value="待命")
        self.summary_var = tk.StringVar(value="输入任务后，这里会实时显示 Agent 运行指标。")
        self.card_vars: Dict[str, tk.StringVar] = {}

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(200, self._poll_loop)
        if self.cfg.get("auto_check_update", True):
            self.root.after(1500, self.check_for_updates)

    # ------------------------------------------------------------ 界面
    def _build_ui(self) -> None:
        self.root.title(f"{APP_TITLE} v{APP_VERSION}")
        self.root.geometry("1280x840")
        self.root.minsize(1080, 700)
        self.root.configure(bg=BG)

        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="both", expand=True, padx=12, pady=10)

        # 左侧栏
        sidebar = tk.Frame(outer, bg=PANEL, width=280)
        sidebar.pack(side="left", fill="y", padx=(0, 10))
        sidebar.pack_propagate(False)

        # Logo 区
        logo_row = tk.Frame(sidebar, bg=PANEL)
        logo_row.pack(fill="x", padx=12, pady=(14, 6))
        self.logo_canvas = tk.Canvas(logo_row, width=48, height=48, bg=PANEL, highlightthickness=0)
        self.logo_canvas.pack(side="left")
        draw_logo(self.logo_canvas, 46)

        brand_box = tk.Frame(logo_row, bg=PANEL)
        brand_box.pack(side="left", padx=(10, 0))
        tk.Label(brand_box, text="DeepSeek", font=(UI_FONT, 15, "bold"), bg=PANEL, fg=FG).pack(anchor="w")
        tk.Label(brand_box, text="AGENT STUDIO", font=(MONO, 8, "bold"), bg=PANEL, fg=CYAN).pack(anchor="w")
        tk.Label(sidebar, text="自主智能体 · 文件 / 命令 / 搜索",
                 font=(UI_FONT, 8), bg=PANEL, fg=SUB).pack(anchor="w", padx=12, pady=(0, 10))

        # 模型配置
        model_box = tk.LabelFrame(sidebar, text=" 模型配置 ", font=(UI_FONT, 9, "bold"),
                                  bg=PANEL, fg=FG, padx=10, pady=8, bd=1, relief="solid")
        model_box.pack(fill="x", padx=10, pady=(0, 8))

        tk.Label(model_box, text="API Key", bg=PANEL, fg=SUB, font=(UI_FONT, 8)).pack(anchor="w")
        self.api_entry = tk.Entry(model_box, textvariable=self.api_key_var, show="•",
                                  bg="#0a0e18", fg=FG, insertbackground=FG, relief="flat",
                                  font=(MONO, 9))
        self.api_entry.pack(fill="x", pady=(2, 4))

        tk.Checkbutton(model_box, text="保存密钥到本机配置", variable=self.save_key_var,
                       bg=PANEL, fg=SUB, selectcolor=PANEL, activebackground=PANEL,
                       activeforeground=FG, font=(UI_FONT, 8), cursor="hand2").pack(anchor="w")

        tk.Label(model_box, text="模型", bg=PANEL, fg=SUB, font=(UI_FONT, 8)).pack(anchor="w", pady=(6, 0))
        model_combo = ttk.Combobox(model_box, textvariable=self.model_var, state="readonly",
                                   values=["deepseek-chat", "deepseek-reasoner"], font=(UI_FONT, 9))
        model_combo.pack(fill="x", pady=(2, 4))

        tk.Label(model_box, text="API Base URL", bg=PANEL, fg=SUB, font=(UI_FONT, 8)).pack(anchor="w")
        tk.Entry(model_box, textvariable=self.base_url_var, bg="#0a0e18", fg=FG,
                 insertbackground=FG, relief="flat", font=(MONO, 8)).pack(fill="x", pady=(2, 4))

        # 项目配置
        project_box = tk.LabelFrame(sidebar, text=" 工作目录 ", font=(UI_FONT, 9, "bold"),
                                    bg=PANEL, fg=FG, padx=10, pady=8, bd=1, relief="solid")
        project_box.pack(fill="x", padx=10, pady=(0, 8))
        tk.Entry(project_box, textvariable=self.project_var, bg="#0a0e18", fg=FG,
                 insertbackground=FG, relief="flat", font=(MONO, 8)).pack(fill="x")
        btn_row = tk.Frame(project_box, bg=PANEL)
        btn_row.pack(fill="x", pady=(6, 0))
        tk.Button(btn_row, text="浏览", command=self._browse_project, bg=CARD, fg=FG,
                  activebackground=CARD_BORDER, activeforeground=FG, relief="flat",
                  padx=8, cursor="hand2", font=(UI_FONT, 8)).pack(side="left")
        tk.Button(btn_row, text="打开目录", command=self._open_project, bg=CARD, fg=FG,
                  activebackground=CARD_BORDER, activeforeground=FG, relief="flat",
                  padx=8, cursor="hand2", font=(UI_FONT, 8)).pack(side="left", padx=(6, 0))

        tk.Label(project_box, text="最大步骤", bg=PANEL, fg=SUB, font=(UI_FONT, 8)).pack(anchor="w", pady=(6, 0))
        tk.Spinbox(project_box, from_=1, to=100, textvariable=self.max_steps_var,
                   bg="#0a0e18", fg=FG, relief="flat", font=(MONO, 9), width=8).pack(fill="x", pady=(2, 0))

        # 操作按钮
        self.run_btn = tk.Button(sidebar, text="▶  开始任务", command=self.start_task,
                                 font=(UI_FONT, 10, "bold"), bg=ACCENT, fg="white",
                                 activebackground=ACCENT_BRIGHT, activeforeground="white",
                                 relief="flat", padx=12, pady=9, cursor="hand2")
        self.run_btn.pack(fill="x", padx=10, pady=(4, 0))

        self.stop_btn = tk.Button(sidebar, text="■  停止 Agent", command=self.stop_task,
                                  font=(UI_FONT, 10, "bold"), bg="#5b1a2d", fg=RED,
                                  activebackground="#7a2038", relief="flat", padx=12, pady=8,
                                  cursor="hand2", state="disabled")
        self.stop_btn.pack(fill="x", padx=10, pady=(8, 0))

        tk.Button(sidebar, text="↺  重置指标", command=self.reset_metrics,
                  font=(UI_FONT, 9), bg=CARD, fg=FG, activebackground=CARD_BORDER,
                  activeforeground=FG, relief="flat", padx=10, pady=7,
                  cursor="hand2").pack(fill="x", padx=10, pady=(8, 0))
        tk.Button(sidebar, text="🧹  清空对话", command=self.clear_chat,
                  font=(UI_FONT, 9), bg=CARD, fg=FG, activebackground=CARD_BORDER,
                  activeforeground=FG, relief="flat", padx=10, pady=7,
                  cursor="hand2").pack(fill="x", padx=10, pady=(8, 0))
          tk.Button(sidebar, text="👁  安装/更新 Eyes", command=self.install_eyes,
                    font=(UI_FONT, 9), bg="#0f2b3d", fg=CYAN, activebackground="#123a52",
                    activeforeground=CYAN, relief="flat", padx=10, pady=7,
                    cursor="hand2").pack(fill="x", padx=10, pady=(8, 0))
          tk.Button(sidebar, text="📷  眼睛看屏幕", command=self.eyes_look_now,
                    font=(UI_FONT, 9), bg=CARD, fg=FG, activebackground=CARD_BORDER,
                    activeforeground=FG, relief="flat", padx=10, pady=7,
                    cursor="hand2").pack(fill="x", padx=10, pady=(8, 0))
          tk.Button(sidebar, text="🔄  检查更新", command=self.check_for_updates,
                    font=(UI_FONT, 9), bg=CARD, fg=FG, activebackground=CARD_BORDER,
                    activeforeground=FG, relief="flat", padx=10, pady=7,
                    cursor="hand2").pack(fill="x", padx=10, pady=(8, 0))


        self.status_label = tk.Label(sidebar, textvariable=self.status_var, bg=PANEL, fg=SUB,
                                     font=(UI_FONT, 9, "bold"), pady=10)
        self.status_label.pack(side="bottom", fill="x", padx=10)

        # 右侧主区
        right = tk.Frame(outer, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        # 实时总览
        summary = tk.LabelFrame(right, text=" 实时运行指标 ", font=(UI_FONT, 10, "bold"),
                                bg=PANEL, fg=FG, padx=12, pady=10, bd=1, relief="solid")
        summary.pack(fill="x")
        tk.Label(summary, textvariable=self.summary_var, font=(MONO, 11, "bold"),
                 bg=PANEL, fg=ACCENT_BRIGHT, anchor="w", justify="left",
                 wraplength=940).pack(fill="x")

        # 指标卡片
        cards = tk.Frame(right, bg=BG)
        cards.pack(fill="x", pady=(8, 0))
        for idx, (key, title, hint) in enumerate(self.CARD_KEYS):
            self._make_card(cards, key, title, hint, idx)

        # 对话 / 日志
        chat_frame = tk.LabelFrame(right, text=" Agent 工作台 ", font=(UI_FONT, 10, "bold"),
                                   bg=PANEL, fg=FG, padx=8, pady=6, bd=1, relief="solid")
        chat_frame.pack(fill="both", expand=True, pady=(8, 0))

        self.chat_text = scrolledtext.ScrolledText(
            chat_frame, font=(UI_FONT, 10), bg=LOG_BG, fg=LOG_FG, insertbackground=FG,
            relief="flat", wrap="word", state="normal", padx=10, pady=8,
        )
        self.chat_text.pack(fill="both", expand=True)
        self._configure_chat_tags()

        # 输入区
        input_box = tk.Frame(right, bg=BG)
        input_box.pack(fill="x", pady=(8, 0))
        self.prompt_text = tk.Text(input_box, height=4, font=(UI_FONT, 10), bg="#0a0e18",
                                   fg=FG, insertbackground=FG, relief="flat", wrap="word",
                                   padx=10, pady=8)
        self.prompt_text.pack(side="left", fill="both", expand=True)
        self.prompt_text.bind("<Control-Return>", lambda e: self.start_task())

        send_btn = tk.Button(input_box, text="发送\nCtrl+Enter", command=self.start_task,
                             font=(UI_FONT, 10, "bold"), bg=ACCENT, fg="white",
                             activebackground=ACCENT_BRIGHT, activeforeground="white",
                             relief="flat", padx=16, pady=10, cursor="hand2")
        send_btn.pack(side="right", fill="y", padx=(8, 0))

    def _configure_chat_tags(self) -> None:
        self.chat_text.tag_config("system", foreground=YELLOW, font=(UI_FONT, 9, "bold"))
        self.chat_text.tag_config("user", foreground="#93c5fd", font=(UI_FONT, 10, "bold"))
        self.chat_text.tag_config("agent", foreground=FG, font=(UI_FONT, 10))
        self.chat_text.tag_config("reasoning", foreground="#64748b", font=(UI_FONT, 9))
        self.chat_text.tag_config("tool", foreground=CYAN, font=(MONO, 9, "bold"))
        self.chat_text.tag_config("tool_result", foreground=GREEN, font=(MONO, 9))
        self.chat_text.tag_config("error", foreground=RED, font=(UI_FONT, 9, "bold"))

    def _make_card(self, parent: tk.Frame, key: str, title: str, hint: str, idx: int) -> None:
        row, col = divmod(idx, 5)
        var = tk.StringVar(value="—")
        self.card_vars[key] = var
        for c in range(5):
            parent.columnconfigure(c, weight=1)

        frame = tk.Frame(parent, bg=CARD, highlightbackground=CARD_BORDER,
                         highlightthickness=1, padx=10, pady=8)
        frame.grid(row=row, column=col, sticky="nsew", padx=3, pady=3)
        tk.Label(frame, text=title, bg=CARD, fg=SUB, font=(UI_FONT, 8), anchor="w").pack(fill="x")
        tk.Label(frame, textvariable=var, bg=CARD, fg=FG, font=(MONO, 14, "bold"),
                 anchor="w").pack(fill="x", pady=(1, 0))
        tk.Label(frame, text=hint, bg=CARD, fg="#4f5b7a", font=(UI_FONT, 7), anchor="w").pack(fill="x")

    # ------------------------------------------------------------ 任务控制
    def _validated_settings(self) -> Optional[Dict[str, Any]]:
        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showwarning(APP_TITLE, "请先填写 DeepSeek API Key。")
            return None
        project = self.project_var.get().strip()
        if not project or not Path(project).is_dir():
            messagebox.showwarning(APP_TITLE, "请先选择有效的工作目录。")
            return None
        return {
            "api_key": api_key,
            "model": self.model_var.get().strip() or DEFAULT_MODEL,
            "base_url": self.base_url_var.get().strip() or DEFAULT_BASE_URL,
            "project": project,
            "max_steps": int(self.max_steps_var.get()),
        }

    def start_task(self) -> None:
        if self.agent_running:
            messagebox.showinfo(APP_TITLE, "Agent 正在运行，请先停止或等待完成。")
            return
        settings = self._validated_settings()
        if not settings:
            return
        prompt = self.prompt_text.get("1.0", "end").strip()
        if not prompt:
            messagebox.showwarning(APP_TITLE, "请输入任务内容。")
            return

        self.cfg.update({
            "api_key": settings["api_key"] if self.save_key_var.get() else "",
            "model": settings["model"],
            "base_url": settings["base_url"],
            "project_dir": settings["project"],
            "max_steps": settings["max_steps"],
            "save_api_key": bool(self.save_key_var.get()),
        })
        save_config(self.cfg)

        self._chat_system(f"任务开始 · 工作目录：{settings['project']}\n")
        self._chat_user(prompt + "\n")

        self.agent_running = True
        self.run_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self._set_status("Agent 运行中…", ACCENT_BRIGHT)

        self.engine = AgentEngine(
            api_key=settings["api_key"],
            cwd=settings["project"],
            model=settings["model"],
            max_steps=settings["max_steps"],
            on_event=self.event_queue.put,
            base_url=settings["base_url"],
            eyes_manager=self.eyes,
        )
        self.metrics = self.engine.metrics

        self.worker = threading.Thread(target=self._worker_main, args=(prompt,), daemon=True)
        self.worker.start()
        self.prompt_text.delete("1.0", "end")

    def _worker_main(self, prompt: str) -> None:
        try:
            if self.engine is not None:
                self.engine.run_task(prompt)
        except Exception as exc:
            self.event_queue.put({"type": "error", "message": f"Agent 线程异常：{exc}"})
        finally:
            self.event_queue.put({"type": "worker_finished"})

    def stop_task(self) -> None:
        if self.engine is not None:
            self.engine.stop()
        self._chat_system("已请求停止 Agent…\n")
        self._set_status("正在停止…", YELLOW)

    def reset_metrics(self) -> None:
        if self.engine is not None:
            self.engine.metrics = type(self.engine.metrics)()
            self.metrics = self.engine.metrics
        else:
            self.metrics = None
        self.summary_var.set("指标已重置。")
        for var in self.card_vars.values():
            var.set("—")

    def clear_chat(self) -> None:
        self.chat_text.config(state="normal")
        self.chat_text.delete("1.0", "end")
        self.chat_text.config(state="normal")
    # ------------------------------------------------------------ Eyes
    def install_eyes(self) -> None:
        if self.eyes_worker is not None and self.eyes_worker.is_alive():
            messagebox.showinfo(APP_TITLE, "DeepSeek Eyes 正在安装/更新中，请稍候。")
            return
        self._set_status("Eyes 安装中…", CYAN)
        self._chat_system("正在从 GitHub 下载 DeepSeek Eyes 插件…\n")

        def worker() -> None:
            try:
                self.eyes.install_or_update(
                    progress_cb=lambda done, total: self.event_queue.put(
                        {"type": "eyes_progress", "done": done, "total": total}
                    ),
                    log_cb=lambda text: self.event_queue.put({"type": "eyes_log", "message": text}),
                )
                self.event_queue.put({"type": "eyes_done"})
            except Exception as exc:
                self.event_queue.put({"type": "eyes_error", "message": str(exc)})

        self.eyes_worker = threading.Thread(target=worker, daemon=True)
        self.eyes_worker.start()

    def eyes_look_now(self) -> None:
        self._set_status("Eyes 正在观察屏幕…", CYAN)
        self._chat_system("DeepSeek Eyes 正在观察屏幕…\n")

        def worker() -> None:
            try:
                output = self.eyes.capture_and_analyze("请描述当前屏幕上有什么，重点说明关键文字和按钮。")
                self.event_queue.put({"type": "eyes_result", "output": output})
            except Exception as exc:
                self.event_queue.put({"type": "eyes_error", "message": str(exc)})

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------ 自动更新
    def check_for_updates(self) -> None:
        if self.update_worker is not None and self.update_worker.is_alive():
            messagebox.showinfo(APP_TITLE, "正在检查更新，请稍候。")
            return
        self._set_status("检查更新中…", BLUE)
        self._chat_system("正在检查软件更新…\n")

        def worker() -> None:
            try:
                info = find_update(
                    APP_VERSION,
                    manifest_url=str(self.cfg.get("update_manifest_url", DEFAULT_MANIFEST_URL)),
                    repo=str(self.cfg.get("update_repo", DEFAULT_REPO)),
                )
                if info is None:
                    self.event_queue.put({"type": "update_none"})
                else:
                    self.event_queue.put({
                        "type": "update_available",
                        "version": info.version,
                        "notes": info.notes,
                        "download_url": info.download_url,
                        "filename": info.filename,
                    })
            except Exception as exc:
                self.event_queue.put({"type": "update_error", "message": str(exc)})

        self.update_worker = threading.Thread(target=worker, daemon=True)
        self.update_worker.start()

    def _download_update(self, info: Dict[str, Any]) -> None:
        self._set_status("下载更新中…", BLUE)
        self._chat_system(f"开始下载新版本 {info.get('version')} …\n")

        def worker() -> None:
            try:
                from deepseek_updater import UpdateInfo
                update = UpdateInfo(
                    version=info.get("version", ""),
                    download_url=info.get("download_url", ""),
                    filename=info.get("filename", "DeepSeek-Agent-Studio.exe"),
                    notes=info.get("notes", ""),
                )
                dest_dir = Path(tempfile.gettempdir()) / "deepseek-agent-studio-update"
                downloaded = download_update(
                    update,
                    dest_dir,
                    progress_cb=lambda done, total: self.event_queue.put(
                        {"type": "update_download_progress", "done": done, "total": total}
                    ),
                )
                self.event_queue.put({"type": "update_ready", "path": str(downloaded)})
            except Exception as exc:
                self.event_queue.put({"type": "update_error", "message": str(exc)})

        threading.Thread(target=worker, daemon=True).start()

    def _apply_update(self, downloaded_path: str) -> None:
        try:
            if apply_update_and_restart(Path(downloaded_path)):
                self._on_close()
            else:
                messagebox.showinfo(
                    APP_TITLE,
                    "当前不是 exe 运行模式，无法覆盖自身。\n请手动替换源码后重新运行。",
                )
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"更新失败：{exc}")



    # ------------------------------------------------------------ 事件 / 刷新
    def _poll_loop(self) -> None:
        try:
            while True:
                event = self.event_queue.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass

        if self.metrics is not None:
            snap = self.metrics.snapshot()
            self._update_metrics(snap)

        if self.agent_running and self.worker is not None and not self.worker.is_alive():
            self.agent_running = False
            self.run_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
            self._set_status("待命", SUB)

        self.root.after(200, self._poll_loop)

    def _handle_event(self, event: Dict[str, Any]) -> None:
        etype = event.get("type")
        if etype == "turn_start":
            self._streaming_block = False
        elif etype == "step_start":
            self._chat_system(f"\n— Step {event.get('step')} —\n")
            self._streaming_block = False
        elif etype == "assistant_delta":
            if not self._streaming_block:
                self._chat_agent_prefix()
                self._streaming_block = True
                self._last_stream_tag = "agent"
            elif self._last_stream_tag == "reasoning":
                self._chat_insert("\n", "agent")
                self._last_stream_tag = "agent"
            self._chat_insert(event.get("text", ""), "agent")
        elif etype == "reasoning_delta":
            if not self._streaming_block:
                self._chat_system("\nDeepSeek 思考：")
                self._streaming_block = True
                self._last_stream_tag = "reasoning"
            self._chat_insert(event.get("text", ""), "reasoning")
        elif etype == "tool_call":
            self._streaming_block = False
            args = event.get("arguments", "")
            self._chat_tool(f"\n⚙ {event.get('name')}({args[:180]})")
        elif etype == "tool_result":
            self._streaming_block = False
            output = event.get("output", "")
            preview = output[:700] + ("..." if len(output) > 700 else "")
            tag = "error" if event.get("is_error") else "tool_result"
            self._chat_line(f"  → {preview}", tag)
        elif etype == "done":
            self._streaming_block = False
            self._chat_system("\n✓ 任务完成\n")
        elif etype == "error":
            self._chat_error("\n✗ " + event.get("message", "未知错误") + "\n")
        elif etype == "stopped":
            self._chat_system("\n■ 任务已停止\n")
          elif etype == "eyes_log":
              self._chat_system("[Eyes] " + event.get("message", "") + "\n")
          elif etype == "eyes_progress":
              done, total = int(event.get("done", 0)), int(event.get("total", 0))
              percent = f"{done / total * 100:.0f}%" if total else "…"
              self._set_status(f"Eyes 下载中 {percent}", CYAN)
          elif etype == "eyes_done":
              self._set_status("Eyes 已就绪", CYAN)
              self._chat_system("DeepSeek Eyes 插件安装/更新完成。\n")
              messagebox.showinfo(APP_TITLE, "DeepSeek Eyes 安装完成。\nAgent 现在可以使用 deepseek_eyes 工具观察屏幕了。")
          elif etype == "eyes_result":
              self._set_status("待命", SUB)
              self._chat_line("\n👁 " + event.get("output", "") + "\n", "tool_result")
          elif etype == "eyes_error":
              self._set_status("待命", SUB)
              self._chat_error("\n✗ Eyes 错误：" + event.get("message", "") + "\n")
          elif etype == "update_none":
              self._set_status("已是最新版", GREEN)
              self._chat_system("检查完成：当前已经是最新版本。\n")
          elif etype == "update_available":
              self._set_status("发现新版本", YELLOW)
              info = {
                  "version": event.get("version", ""),
                  "notes": event.get("notes", ""),
                  "download_url": event.get("download_url", ""),
                  "filename": event.get("filename", "DeepSeek-Agent-Studio.exe"),
              }
              self._chat_system(f"发现新版本：{info['version']}\n")
              if messagebox.askyesno(
                  APP_TITLE,
                  f"发现新版本 {info['version']}\n\n{info['notes'][:500]}\n\n是否立即下载并覆盖安装？",
              ):
                  self._download_update(info)
              else:
                  self._set_status("待命", SUB)
          elif etype == "update_download_progress":
              done, total = int(event.get("done", 0)), int(event.get("total", 0))
              if total:
                  self._set_status(f"更新下载中 {done / total * 100:.0f}%", BLUE)
              else:
                  self._set_status(f"更新下载中 {done // 1024} KB", BLUE)
          elif etype == "update_ready":
              self._set_status("更新已下载", GREEN)
              self._chat_system("新版本下载完成。\n")
              self._apply_update(event.get("path", ""))
          elif etype == "update_error":
              self._set_status("更新失败", RED)
              self._chat_error("\n✗ 更新错误：" + event.get("message", "") + "\n")
        elif etype == "worker_finished":
            self.agent_running = False
            self.run_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
            self._set_status("待命", SUB)

    def _update_metrics(self, s: Dict[str, Any]) -> None:
        summary = (
            f"{s['turns']} 轮 · {s['steps']} 步"
            f"    |    LLM {fmt_duration(s['llm_seconds'])} · 工具调用 {fmt_duration(s['tool_seconds'])}"
            f"    |    首 token 平均 {fmt_duration(s['avg_ttft'])} · {s['tokens_per_sec']:.0f} tok/s"
            f"    |    缓存命中 {s['cache_hit_rate']:.1f}%"
            f"    |    输入 {fmt_tokens(s['input_tokens'])} tok · 输出 {fmt_tokens(s['output_tokens'])} tok"
        )
        self.summary_var.set(summary)
        values = {
            "turns": str(s["turns"]),
            "steps": str(s["steps"]),
            "llm_seconds": fmt_duration(s["llm_seconds"]),
            "tool_seconds": fmt_duration(s["tool_seconds"]),
            "avg_ttft": fmt_duration(s["avg_ttft"]),
            "tokens_per_sec": f"{s['tokens_per_sec']:.0f} tok/s",
            "cache_hit_rate": f"{s['cache_hit_rate']:.1f}%",
            "input_tokens": fmt_tokens(s["input_tokens"]),
            "output_tokens": fmt_tokens(s["output_tokens"]),
            "tool_calls": str(s["tool_calls"]),
        }
        for key, var in self.card_vars.items():
            if key in values:
                var.set(values[key])

    # ------------------------------------------------------------ 对话渲染
    def _chat_insert(self, text: str, tag: str) -> None:
        self.chat_text.config(state="normal")
        self.chat_text.insert("end", text, tag)
        self.chat_text.see("end")
        self.chat_text.config(state="normal")

    def _chat_line(self, text: str, tag: str) -> None:
        self._chat_insert(text + "\n", tag)

    def _chat_system(self, text: str) -> None:
        self._chat_line(text, "system")

    def _chat_user(self, text: str) -> None:
        self._chat_line("\n你：" + text, "user")

    def _chat_agent_prefix(self) -> None:
        self._chat_insert("\nDeepSeek：", "user")

    def _chat_tool(self, text: str) -> None:
        self._chat_line(text, "tool")

    def _chat_error(self, text: str) -> None:
        self._chat_line(text, "error")

    # ------------------------------------------------------------ 设置按钮
    def _set_status(self, text: str, color: str) -> None:
        self.status_var.set(text)
        self.status_label.config(fg=color)

    def _browse_project(self) -> None:
        path = filedialog.askdirectory(title="选择 Agent 工作目录", initialdir=self.project_var.get())
        if path:
            self.project_var.set(path)
            self.cfg["project_dir"] = path
            save_config(self.cfg)

    def _open_project(self) -> None:
        path = self.project_var.get().strip()
        if not Path(path).is_dir():
            messagebox.showwarning(APP_TITLE, "工作目录不存在。")
            return
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"无法打开目录：{exc}")

    def _on_close(self) -> None:
        if self.engine is not None:
            self.engine.stop()
        try:
            self.cfg.update({
                "api_key": self.api_key_var.get() if self.save_key_var.get() else "",
                "model": self.model_var.get(),
                "base_url": self.base_url_var.get(),
                "project_dir": self.project_var.get(),
                "max_steps": int(self.max_steps_var.get()),
                "save_api_key": bool(self.save_key_var.get()),
            })
            save_config(self.cfg)
        except Exception:
            pass
        self.root.destroy()


def main() -> int:
    root = tk.Tk()
    try:
        DeepSeekAgentStudio(root)
    except Exception as exc:
        try:
            messagebox.showerror(APP_TITLE, f"软件启动失败：\n{exc}")
        except Exception:
            pass
        return 1
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
