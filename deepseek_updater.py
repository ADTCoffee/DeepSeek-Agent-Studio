#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek Agent Studio 自动更新模块（纯标准库）

更新源优先级：
  1. 仓库里的 deepseek-agent-studio-update.json
  2. GitHub Releases（repo = hawkongz/deepseek-eyes）

流程：
  检查版本 -> 弹窗确认 -> 下载 .exe 到临时目录 -> 写 update.bat
  -> 退出当前程序 -> update.bat 等待进程结束后覆盖旧 exe -> 自动重启。
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

DEFAULT_REPO = "ADTCoffee/DeepSeek-Agent-Studio"
DEFAULT_MANIFEST_URL = (
    "https://raw.githubusercontent.com/ADTCoffee/DeepSeek-Agent-Studio/main/"
    "deepseek-agent-studio-update.json"
)
DEFAULT_RELEASES_API = "https://api.github.com/repos/ADTCoffee/DeepSeek-Agent-Studio/releases/latest"

DOWNLOAD_CHUNK = 256 * 1024
REQUEST_TIMEOUT = 25


@dataclass
class UpdateInfo:
    version: str = ""
    download_url: str = ""
    filename: str = "DeepSeek-Agent-Studio.exe"
    sha256: str = ""
    notes: str = ""
    size: int = 0


def parse_version(value: str) -> tuple:
    text = str(value or "").strip().lstrip("vV")
    parts: list = []
    for chunk in text.split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _fetch_json(url: str, timeout: int = REQUEST_TIMEOUT) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "DeepSeek-Agent-Studio-Updater"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _fetch_text(url: str, timeout: int = REQUEST_TIMEOUT) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "DeepSeek-Agent-Studio-Updater"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def find_update(
    current_version: str,
    manifest_url: str = DEFAULT_MANIFEST_URL,
    repo: str = DEFAULT_REPO,
) -> Optional[UpdateInfo]:
    """检查更新。找不到更新源或没有新版本时返回 None。"""
    info: Optional[UpdateInfo] = None

    # 1) 优先读取仓库里的 manifest
    try:
        data = _fetch_json(manifest_url)
        if isinstance(data, dict) and data.get("version"):
            info = UpdateInfo(
                version=str(data.get("version", "")),
                download_url=str(data.get("download_url", "")),
                filename=str(data.get("filename", "DeepSeek-Agent-Studio.exe")),
                sha256=str(data.get("sha256", "")),
                notes=str(data.get("notes", "")),
                size=int(data.get("size", 0) or 0),
            )
    except Exception:
        info = None

    # 2) 回退到 GitHub Releases
    if not info or not info.download_url:
        try:
            api_url = f"https://api.github.com/repos/{repo}/releases/latest"
            release = _fetch_json(api_url)
            assets = release.get("assets") or []
            chosen = None
            for asset in assets:
                name = str(asset.get("name", ""))
                if "deepseek" in name.lower() and name.lower().endswith(".exe"):
                    chosen = asset
                    break
            if chosen:
                info = UpdateInfo(
                    version=str(release.get("tag_name", "")).lstrip("vV"),
                    download_url=str(chosen.get("browser_download_url", "")),
                    filename=str(chosen.get("name", "DeepSeek-Agent-Studio.exe")),
                    size=int(chosen.get("size", 0) or 0),
                    notes=str(release.get("body", "")),
                )
        except Exception:
            pass

    if not info or not info.download_url:
        return None
    if parse_version(info.version) <= parse_version(current_version):
        return None
    return info


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def download_update(
    info: UpdateInfo,
    dest_dir: Path,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Path:
    """下载更新文件。progress_cb(done_bytes, total_bytes)。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = info.filename or "DeepSeek-Agent-Studio.exe"
    dest = dest_dir / filename
    tmp = dest.with_suffix(dest.suffix + ".part")

    request = urllib.request.Request(info.download_url, headers={"User-Agent": "DeepSeek-Agent-Studio-Updater"})
    with urllib.request.urlopen(request, timeout=120) as response:
        total = int(response.headers.get("Content-Length", 0) or 0)
        done = 0
        with tmp.open("wb") as out:
            while True:
                if cancel_check and cancel_check():
                    out.close()
                    tmp.unlink(missing_ok=True)
                    raise RuntimeError("下载已取消")
                block = response.read(DOWNLOAD_CHUNK)
                if not block:
                    break
                out.write(block)
                done += len(block)
                if progress_cb:
                    progress_cb(done, total)

    if info.sha256:
        actual = _sha256(tmp)
        if actual.lower() != info.sha256.lower():
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"SHA256 校验失败：\n期望 {info.sha256}\n实际 {actual}")

    tmp.replace(dest)
    return dest


def apply_update_and_restart(downloaded: Path) -> bool:
    """覆盖当前 exe 并重启。仅在 PyInstaller 冻结的 exe 中执行。"""
    if not getattr(sys, "frozen", False):
        return False

    current = Path(sys.executable).resolve()
    target = current.with_name("DeepSeek-Agent-Studio.update.exe")
    backup = current.with_name("DeepSeek-Agent-Studio.old.exe")

    try:
        if target.exists():
            target.unlink()
        downloaded.replace(target)
    except Exception as exc:
        raise RuntimeError(f"准备更新文件失败：{exc}")

    script = Path(tempfile.gettempdir()) / "deepseek_agent_studio_update.ps1"
    process_name = current.stem
    script.write_text(
        "\n".join(
            [
                "$ErrorActionPreference = 'Stop'",
                "Start-Sleep -Seconds 2",
                f"$procName = '{process_name}'",
                "while (Get-Process -Name $procName -ErrorAction SilentlyContinue) {",
                "    Start-Sleep -Seconds 1",
                "}",
                f"$current = '{current}'",
                f"$backup  = '{backup}'",
                f"$target  = '{target}'",
                "if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Force }",
                "if (Test-Path -LiteralPath $current) { Move-Item -LiteralPath $current -Destination $backup -Force }",
                "Move-Item -LiteralPath $target -Destination $current -Force",
                "Start-Process -FilePath $current",
            ]
        ),
        encoding="utf-8-sig",
    )

    if os.name == "nt":
        subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(script),
            ],
            shell=False,
            close_fds=True,
        )
        return True
    return False
