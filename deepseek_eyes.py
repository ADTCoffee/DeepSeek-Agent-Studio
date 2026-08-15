#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek Eyes 插件管理器

把 https://github.com/hawkongz/deepseek-eyes 作为 DeepSeek Agent Studio 的“眼睛”：
  - 一键下载 / 更新插件仓库
  - 屏幕截图（Windows PowerShell，无需第三方包）
  - 调用插件仓库的入口脚本，把截图 / 问题交给 DeepSeek Eyes 处理
  - 如果插件未安装，截图功能仍然可用
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

DEFAULT_INSTALL_DIR = BASE_DIR / "plugins" / "deepseek-eyes"
DEFAULT_SCREENSHOT_DIR = BASE_DIR / "eyes_shots"
REPO_URL = "https://github.com/hawkongz/deepseek-eyes"
ZIP_URLS = [
    "https://codeload.github.com/hawkongz/deepseek-eyes/zip/refs/heads/main",
    "https://codeload.github.com/hawkongz/deepseek-eyes/zip/refs/heads/master",
]

ENTRY_CANDIDATES = [
    "deepseek_eyes.py",
    "deepseek-eyes.py",
    "eyes.py",
    "main.py",
    "app.py",
    "cli.py",
    "index.js",
    "main.js",
    "deepseek-eyes.exe",
    "eyes.exe",
    "main.exe",
]

ProgressCb = Callable[[int, int], None]
LogCb = Callable[[str], None]


def _find_python() -> Optional[str]:
    for name in ("python", "python3", "py"):
        path = shutil.which(name)
        if path:
            return path
    return None


class DeepSeekEyes:
    def __init__(
        self,
        install_dir: Optional[Path] = None,
        screenshots_dir: Optional[Path] = None,
    ) -> None:
        self.install_dir = Path(install_dir or DEFAULT_INSTALL_DIR).resolve()
        self.screenshots_dir = Path(screenshots_dir or DEFAULT_SCREENSHOT_DIR).resolve()
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.repo_url = REPO_URL
        self._last_log = ""

    @property
    def installed(self) -> bool:
        return self.install_dir.is_dir() and any(self.install_dir.iterdir())

    def status(self) -> Dict[str, str]:
        if not self.installed:
            return {"installed": "false", "path": str(self.install_dir), "entry": ""}
        entry = self.detect_entry()
        return {
            "installed": "true",
            "path": str(self.install_dir),
            "entry": str(entry or "未识别到入口文件"),
            "repo": self.repo_url,
        }

    def detect_entry(self) -> Optional[Path]:
        if not self.install_dir.is_dir():
            return None
        files: List[Path] = []
        try:
            for root, dirs, names in os.walk(self.install_dir):
                dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".venv", "venv")]
                depth = len(Path(root).relative_to(self.install_dir).parts)
                if depth > 2:
                    continue
                for name in names:
                    lower = name.lower()
                    if lower in {c.lower() for c in ENTRY_CANDIDATES}:
                        files.append(Path(root) / name)
        except Exception:
            pass

        def score(path: Path) -> Tuple[int, str]:
            lower = path.name.lower()
            priority = ENTRY_CANDIDATES.index(lower) if lower in [c.lower() for c in ENTRY_CANDIDATES] else 99
            return (priority, str(path))

        files.sort(key=score)
        return files[0] if files else None

    def install_or_update(
        self,
        progress_cb: Optional[ProgressCb] = None,
        log_cb: Optional[LogCb] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        """下载 GitHub 仓库 ZIP 并解压安装。"""
        self.install_dir.parent.mkdir(parents=True, exist_ok=True)
        last_error = ""
        for url in ZIP_URLS:
            try:
                self._download_and_extract(url, progress_cb, log_cb, cancel_check)
                self._last_log = f"DeepSeek Eyes 已安装到 {self.install_dir}"
                if log_cb:
                    log_cb(self._last_log)
                return
            except Exception as exc:
                last_error = str(exc)
                if log_cb:
                    log_cb(f"下载失败（{url}）：{last_error}，尝试下一个源…")
        raise RuntimeError("DeepSeek Eyes 安装失败：" + last_error)

    def _download_and_extract(
        self,
        url: str,
        progress_cb: Optional[ProgressCb],
        log_cb: Optional[LogCb],
        cancel_check: Optional[Callable[[], bool]],
    ) -> None:
        tmp_zip = Path(tempfile.gettempdir()) / "deepseek-eyes-repo.zip"
        request = urllib.request.Request(url, headers={"User-Agent": "DeepSeek-Agent-Studio"})
        with urllib.request.urlopen(request, timeout=90) as response:
            total = int(response.headers.get("Content-Length", 0) or 0)
            done = 0
            with tmp_zip.open("wb") as out:
                while True:
                    if cancel_check and cancel_check():
                        raise RuntimeError("安装已取消")
                    block = response.read(256 * 1024)
                    if not block:
                        break
                    out.write(block)
                    done += len(block)
                    if progress_cb:
                        progress_cb(done, total)

        extract_dir = Path(tempfile.gettempdir()) / "deepseek-eyes-extract"
        if extract_dir.exists():
            shutil.rmtree(extract_dir, ignore_errors=True)
        extract_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(tmp_zip) as archive:
            archive.extractall(extract_dir)

        roots = [p for p in extract_dir.iterdir() if p.is_dir() and p.name.lower() != "__macosx"]
        src = roots[0] if len(roots) == 1 else extract_dir

        if self.install_dir.exists():
            shutil.rmtree(self.install_dir, ignore_errors=True)
        self.install_dir.mkdir(parents=True, exist_ok=True)

        for child in src.iterdir():
            dst = self.install_dir / child.name
            if dst.exists():
                if dst.is_dir():
                    shutil.rmtree(dst, ignore_errors=True)
                else:
                    dst.unlink(missing_ok=True)
            shutil.move(str(child), str(dst))

        tmp_zip.unlink(missing_ok=True)
        if log_cb:
            log_cb("插件文件已解压")

    def run_plugin(
        self,
        action: str,
        question: Optional[str] = None,
        image: Optional[Path] = None,
        extra_args: Optional[List[str]] = None,
        timeout: int = 180,
    ) -> str:
        """调用 deepseek-eyes 仓库入口。"""
        if not self.installed:
            return (
                "DeepSeek Eyes 插件未安装。\n"
                "请在主界面点击“安装/更新 Eyes”，或先连接网络后重试。"
            )
        entry = self.detect_entry()
        if entry is None:
            files = "\n".join(
                str(p.relative_to(self.install_dir))
                for p in sorted(self.install_dir.rglob("*"))
                if p.is_file()
            )[:1200]
            return "已下载 deepseek-eyes 仓库，但没有识别到标准入口文件。仓库文件：\n" + files

        args: List[str] = [str(entry)]
        if action and action not in ("run",):
            args.append(action)
        if question:
            args += ["--question", question]
        if image:
            args += ["--image", str(image)]
        if extra_args:
            args += extra_args

        cmd: List[str]
        suffix = entry.suffix.lower()
        if suffix == ".py":
            python = _find_python()
            if not python:
                return "已找到 eyes 入口 %s，但当前系统没有 Python，无法运行。" % entry.name
            cmd = [python] + args
        elif suffix == ".js":
            node = shutil.which("node")
            if not node:
                return "已找到 eyes 入口 %s，但当前系统没有 Node.js，无法运行。" % entry.name
            cmd = [node] + args
        elif suffix == ".exe":
            cmd = args
        else:
            return "不支持的 eyes 入口类型：" + str(entry)

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.install_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return f"DeepSeek Eyes 执行超时（{timeout}s）。"
        except Exception as exc:
            return f"DeepSeek Eyes 执行失败：{exc}"

        output = (proc.stdout or "").strip()
        if proc.stderr:
            output += ("\n[stderr]\n" + proc.stderr.strip()) if output else (proc.stderr.strip())
        return output or f"DeepSeek Eyes 执行完成（退出码 {proc.returncode}，无输出）。"

    def capture_screen(self, path: Optional[Path] = None) -> Path:
        """截取主屏幕并保存为 PNG。"""
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        target = Path(path) if path else (self.screenshots_dir / f"eyes_{time.strftime('%Y%m%d_%H%M%S')}.png")
        target = target.resolve()

        if os.name == "nt":
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "Add-Type -AssemblyName System.Drawing;"
                "$b=[Windows.Forms.Screen]::PrimaryScreen.Bounds;"
                "$bmp=New-Object Drawing.Bitmap $b.Width,$b.Height;"
                "$g=[Drawing.Graphics]::FromImage($bmp);"
                "$g.CopyFromScreen($b.Location,[Drawing.Point]::Empty,$b.Size);"
                f"$bmp.Save('{target}',[Drawing.Imaging.ImageFormat]::Png);"
                "$g.Dispose();$bmp.Dispose()"
            )
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            if proc.returncode != 0 or not target.is_file():
                raise RuntimeError((proc.stderr or proc.stdout or "截图失败").strip())
        else:
            try:
                import tkinter as tk  # type: ignore
                root = tk.Tk()
                root.withdraw()
                root.update()
                root.attributes("-alpha", 0.0)
                # 无第三方包时使用 ImageGrab；Linux 需先保证 X 可用。
                try:
                    from PIL import ImageGrab  # type: ignore
                    img = ImageGrab.grab()
                    img.save(target)
                finally:
                    root.destroy()
            except Exception as exc:
                raise RuntimeError("当前平台截图需要安装 Pillow：pip install pillow") from exc

        return target

    def capture_and_analyze(self, question: Optional[str] = None) -> str:
        """截图 -> 调用 eyes 插件分析。"""
        try:
            image = self.capture_screen()
        except Exception as exc:
            return f"屏幕截图失败：{exc}"
        if not self.installed:
            return (
                f"已截图：{image}\n"
                "DeepSeek Eyes 插件未安装，无法自动分析图片。"
                "请在主界面点击“安装/更新 Eyes”，或把截图交给支持视觉的模型分析。"
            )
        return self.run_plugin("look", question=question or "你看到了什么？请描述屏幕内容", image=image)

    def look(self, question: Optional[str] = None) -> str:
        if not self.installed:
            return self.capture_and_analyze(question)
        return self.run_plugin("look", question=question or "观察当前屏幕并描述你看到了什么")
