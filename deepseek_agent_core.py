#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek Agent Studio - 核心 Agent 引擎

纯 Python 标准库实现，不依赖第三方包：
  - DeepSeek Chat Completions API（流式 + 非流式回退）
  - OpenAI 兼容的 function calling / tool calls
  - 本地工具：读文件、写文件、列目录、搜索文件、执行命令
  - 实时指标：轮次 / 步骤 / LLM 耗时 / 工具耗时 / 首 token / tok/s
"""

import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_MAX_STEPS = 24
DEFAULT_TIMEOUT = 600

SYSTEM_PROMPT = """你是 DeepSeek Agent Studio 的自主智能体。
你可以使用工具完成用户交给你的任务。工作原则：
1. 先用 list_dir / search_files / read_file 了解现场，不要凭空猜。
2. 修改文件前先 read_file；写完代码后立即用 run_command 做最小验证。
3. 命令失败时阅读报错并修复，不要反复重复同一个失败操作。
4. 回答使用用户使用的语言，简洁、可执行。
5. 如果任务需要观察电脑屏幕，调用 deepseek_eyes 工具（action=capture 或 look）。
6. 如果任务不可能完成，直接说明原因和下一步建议。"""


# ---------------------------------------------------------------- 指标


def _fmt_duration(seconds: Optional[float]) -> str:
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


def _fmt_tokens(value: Optional[int]) -> str:
    value = int(value or 0)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


class RunMetrics:
    """线程安全的实时指标。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.turns = 0
        self.steps = 0
        self.llm_seconds = 0.0
        self.tool_seconds = 0.0
        self.ttft_sum = 0.0
        self.ttft_count = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cache_hit_tokens = 0
        self.cache_miss_tokens = 0
        self.tool_calls = 0
        self.started_at: Optional[float] = None
        self.last_activity_at: Optional[float] = None
        self.last_model = ""

    def start_turn(self) -> None:
        with self._lock:
            self.turns += 1
            now = time.time()
            if self.started_at is None:
                self.started_at = now
            self.last_activity_at = now

    def record_step(self) -> None:
        with self._lock:
            self.steps += 1

    def record_api(
        self,
        seconds: float,
        ttft: Optional[float],
        usage: Optional[Dict[str, Any]],
        model: str = "",
    ) -> None:
        with self._lock:
            self.llm_seconds += max(0.0, seconds)
            if ttft is not None and ttft >= 0:
                self.ttft_sum += ttft
                self.ttft_count += 1
            if usage:
                self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
                self.completion_tokens += int(usage.get("completion_tokens") or 0)
                self.cache_hit_tokens += int(usage.get("prompt_cache_hit_tokens") or 0)
                self.cache_miss_tokens += int(usage.get("prompt_cache_miss_tokens") or 0)
            if model:
                self.last_model = model
            self.last_activity_at = time.time()

    def record_tool(self, seconds: float, count: int = 1) -> None:
        with self._lock:
            self.tool_seconds += max(0.0, seconds)
            self.tool_calls += max(0, count)
            self.last_activity_at = time.time()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            cache_denom = self.cache_hit_tokens + self.cache_miss_tokens
            cache_hit = (self.cache_hit_tokens / cache_denom * 100.0) if cache_denom > 0 else 0.0
            tps = (self.completion_tokens / self.llm_seconds) if self.llm_seconds > 0 else 0.0
            avg_ttft = (self.ttft_sum / self.ttft_count) if self.ttft_count > 0 else 0.0
            span = ((self.last_activity_at - self.started_at) if (self.started_at and self.last_activity_at) else 0.0)
            return {
                "turns": self.turns,
                "steps": self.steps,
                "llm_seconds": self.llm_seconds,
                "tool_seconds": self.tool_seconds,
                "avg_ttft": avg_ttft,
                "ttft_count": self.ttft_count,
                "tokens_per_sec": tps,
                "cache_hit_rate": cache_hit,
                "input_tokens": self.prompt_tokens,
                "output_tokens": self.completion_tokens,
                "cache_hit_tokens": self.cache_hit_tokens,
                "cache_miss_tokens": self.cache_miss_tokens,
                "tool_calls": self.tool_calls,
                "session_span": span,
                "model": self.last_model or DEFAULT_MODEL,
            }

    def summary_line(self) -> str:
        s = self.snapshot()
        return (
            f"{s['turns']} 轮 · {s['steps']} 步"
            f"    |    LLM {_fmt_duration(s['llm_seconds'])} · 工具调用 {_fmt_duration(s['tool_seconds'])}"
            f"    |    首 token 平均 {_fmt_duration(s['avg_ttft'])} · {s['tokens_per_sec']:.0f} tok/s"
            f"    |    缓存命中 {s['cache_hit_rate']:.1f}%"
            f"    |    输入 {_fmt_tokens(s['input_tokens'])} tok · 输出 {_fmt_tokens(s['output_tokens'])} tok"
        )


# ---------------------------------------------------------------- DeepSeek API


@dataclass
class APIResponse:
    text: str = ""
    reasoning: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    usage: Dict[str, Any] = field(default_factory=dict)
    finish_reason: str = ""
    model: str = ""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolResult:
    call_id: str
    name: str
    output: str
    is_error: bool = False


class DeepSeekClient:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.api_key = api_key.strip()
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        on_text: Optional[Callable[[str], None]] = None,
        on_reasoning: Optional[Callable[[str], None]] = None,
    ) -> APIResponse:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if self.model != "deepseek-reasoner":
            payload["temperature"] = 0.2
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            return self._chat_stream(payload, on_text, on_reasoning)
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            if exc.code == 400 and "stream_options" in body:
                # 某些兼容网关不支持 stream_options，退回普通流式。
                payload.pop("stream_options", None)
                return self._chat_stream(payload, on_text, on_reasoning)
            raise RuntimeError(self._http_error_message(exc.code, body)) from exc
        except Exception as exc:
            raise RuntimeError(f"DeepSeek API 请求失败：{exc}") from exc

    @staticmethod
    def _http_error_message(code: int, body: str) -> str:
        try:
            data = json.loads(body or "{}")
            err = data.get("error") or data
            msg = err.get("message") if isinstance(err, dict) else str(err)
        except Exception:
            msg = (body or "")[:300]
        return f"HTTP {code}: {msg or '未知错误'}"

    def _chat_stream(
        self,
        payload: Dict[str, Any],
        on_text: Optional[Callable[[str], None]],
        on_reasoning: Optional[Callable[[str], None]],
    ) -> APIResponse:
        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )

        resp = APIResponse()
        buffer = b""
        text_parts: List[str] = []
        reasoning_parts: List[str] = []
        tool_parts: Dict[int, Dict[str, str]] = {}
        usage: Dict[str, Any] = {}

        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            while True:
                chunk = response.read(4096)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    raw_line, buffer = buffer.split(b"\n", 1)
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        continue
                    try:
                        event = json.loads(data)
                    except Exception:
                        continue

                    choices = event.get("choices") or []
                    if choices:
                        delta = choices[0].get("delta") or {}
                        content = delta.get("content")
                        if content:
                            text_parts.append(content)
                            if on_text:
                                on_text(content)
                        reasoning = delta.get("reasoning_content")
                        if reasoning:
                            reasoning_parts.append(reasoning)
                            if on_reasoning:
                                on_reasoning(reasoning)
                        for tc_delta in delta.get("tool_calls") or []:
                            index = int(tc_delta.get("index", 0))
                            slot = tool_parts.setdefault(
                                index, {"id": "", "name": "", "arguments": ""}
                            )
                            if tc_delta.get("id"):
                                slot["id"] = tc_delta["id"]
                            fn = tc_delta.get("function") or {}
                            if fn.get("name"):
                                slot["name"] += fn["name"]
                            if fn.get("arguments"):
                                slot["arguments"] += fn["arguments"]
                        if choices[0].get("finish_reason"):
                            resp.finish_reason = choices[0]["finish_reason"]
                    if event.get("usage"):
                        usage = event["usage"]
                    if event.get("model"):
                        resp.model = event["model"]

        resp.text = "".join(text_parts)
        resp.reasoning = "".join(reasoning_parts)
        resp.usage = usage
        if not resp.model:
            resp.model = self.model
        if resp.finish_reason == "tool_calls" or tool_parts:
            for index in sorted(tool_parts.keys()):
                part = tool_parts[index]
                if not part["id"] or not part["name"]:
                    continue
                try:
                    arguments = json.loads(part["arguments"] or "{}")
                except Exception:
                    arguments = {}
                resp.tool_calls.append(
                    {
                        "id": part["id"],
                        "type": "function",
                        "function": {"name": part["name"], "arguments": json.dumps(arguments, ensure_ascii=False)},
                    }
                )
        return resp

    def chat_non_stream(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> APIResponse:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if self.model != "deepseek-reasoner":
            payload["temperature"] = 0.2
        if tools:
            payload["tools"] = tools
        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(self._http_error_message(exc.code, body)) from exc

        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        resp = APIResponse(
            text=message.get("content") or "",
            reasoning=message.get("reasoning_content") or "",
            usage=data.get("usage") or {},
            finish_reason=choice.get("finish_reason") or "",
            model=data.get("model") or self.model,
        )
        for tc in message.get("tool_calls") or []:
            resp.tool_calls.append(tc)
        return resp


# ---------------------------------------------------------------- 工具


def _clip(text: str, limit: int = 30000) -> str:
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[截断，共 {len(text)} 字符]"


class ToolRunner:
    def __init__(self, cwd: str, eyes_manager=None) -> None:
        self.cwd = str(Path(cwd).resolve())
        self.eyes_manager = eyes_manager

    def _resolve(self, raw_path: str) -> Path:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = Path(self.cwd) / path
        return Path(path)

    def execute(self, name: str, arguments: Dict[str, Any]) -> ToolResult:
        try:
            if name == "read_file":
                return self._read_file(arguments)
            if name == "write_file":
                return self._write_file(arguments)
            if name == "list_dir":
                return self._list_dir(arguments)
            if name == "search_files":
                return self._search_files(arguments)
            if name == "run_command":
                return self._run_command(arguments)
              if name == "deepseek_eyes":
                  return self._deepseek_eyes(arguments)
            return ToolResult("", name, f"未知工具：{name}", True)
        except Exception as exc:
            return ToolResult("", name, f"工具执行异常：{exc}", True)

    def _read_file(self, args: Dict[str, Any]) -> ToolResult:
        path = self._resolve(str(args.get("path", "")))
        if not path.is_file():
            return ToolResult("", "read_file", f"文件不存在：{path}", True)
        if path.stat().st_size > 3_000_000:
            return ToolResult("", "read_file", f"文件过大（>{path.stat().st_size} 字节），请用 search_files 定位后分段处理", True)
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return ToolResult("", "read_file", str(exc), True)
        return ToolResult("", "read_file", content)

    def _write_file(self, args: Dict[str, Any]) -> ToolResult:
        path = self._resolve(str(args.get("path", "")))
        content = args.get("content")
        if content is None:
            return ToolResult("", "write_file", "缺少 content 参数", True)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(content), encoding="utf-8")
        except Exception as exc:
            return ToolResult("", "write_file", str(exc), True)
        return ToolResult("", "write_file", f"已写入：{path}（{len(str(content))} 字符）")

    def _list_dir(self, args: Dict[str, Any]) -> ToolResult:
        path = self._resolve(str(args.get("path", "") or "."))
        if not path.is_dir():
            return ToolResult("", "list_dir", f"目录不存在：{path}", True)
        rows = []
        try:
            for child in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
                try:
                    suffix = "/" if child.is_dir() else f"  ({child.stat().st_size}B)" if child.is_file() else ""
                except OSError:
                    suffix = ""
                rows.append(f"{child.name}{suffix}")
        except Exception as exc:
            return ToolResult("", "list_dir", str(exc), True)
        return ToolResult("", "list_dir", "\n".join(rows) if rows else "(空目录)")

    def _search_files(self, args: Dict[str, Any]) -> ToolResult:
        pattern = str(args.get("pattern", "*"))
        base = self._resolve(str(args.get("path", "") or "."))
        if not base.is_dir():
            return ToolResult("", "search_files", f"目录不存在：{base}", True)
        matches = []
        try:
            for path in base.rglob(pattern):
                if path.is_file():
                    try:
                        matches.append(str(path))
                    except Exception:
                        pass
        except Exception as exc:
            return ToolResult("", "search_files", str(exc), True)
        matches = matches[:200]
        return ToolResult("", "search_files", "\n".join(matches) if matches else "(没有匹配文件)")

    def _run_command(self, args: Dict[str, Any]) -> ToolResult:
        command = str(args.get("command", "")).strip()
        if not command:
            return ToolResult("", "run_command", "缺少 command 参数", True)
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=self.cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            return ToolResult("", "run_command", "命令超时（180s）", True)
        except Exception as exc:
            return ToolResult("", "run_command", str(exc), True)
        output = _clip((proc.stdout or "") + ("\n[stderr]\n" + proc.stderr if proc.stderr else ""), 30000)
        if proc.returncode != 0:
            return ToolResult("", "run_command", f"[退出码 {proc.returncode}]\n{output}", True)
        return ToolResult("", "run_command", output or "(命令执行成功，无输出)")
    def _deepseek_eyes(self, args: Dict[str, Any]) -> ToolResult:
        if not self.eyes_manager:
            return ToolResult("", "deepseek_eyes", "DeepSeek Eyes 插件未初始化。", True)
        action = str(args.get("action", "status")).strip().lower()
        question = str(args.get("question", "")).strip() or None

        try:
            if action in ("status", "state"):
                status = self.eyes_manager.status()
                return ToolResult("", "deepseek_eyes", json.dumps(status, ensure_ascii=False, indent=2))
            if action in ("install", "update"):
                self.eyes_manager.install_or_update()
                status = self.eyes_manager.status()
                return ToolResult("", "deepseek_eyes", "DeepSeek Eyes 安装/更新完成。\n" + json.dumps(status, ensure_ascii=False, indent=2))
            if action == "capture":
                return ToolResult("", "deepseek_eyes", self.eyes_manager.capture_and_analyze(question))
            if action == "look":
                return ToolResult("", "deepseek_eyes", self.eyes_manager.look(question))
            if action == "plugin":
                command = str(args.get("command", "")).strip()
                if not command:
                    return ToolResult("", "deepseek_eyes", "plugin 动作需要 command 参数。", True)
                return ToolResult("", "deepseek_eyes", self.eyes_manager.run_plugin("run", question=question, extra_args=command.split()))
            return ToolResult("", "deepseek_eyes", f"未知 eyes 动作：{action}（支持 status / install / capture / look / plugin）", True)
        except Exception as exc:
            return ToolResult("", "deepseek_eyes", f"DeepSeek Eyes 执行失败：{exc}", True)


    @staticmethod
    def tool_definitions() -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_dir",
                    "description": "列出目录内容。",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string", "description": "目录路径，默认当前目录"}},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "读取文本文件内容。",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string", "description": "文件路径"}},
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "写入文本文件，会自动创建父目录。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "文件路径"},
                            "content": {"type": "string", "description": "完整文件内容"},
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_files",
                    "description": "按 glob 模式递归搜索文件。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {"type": "string", "description": "glob 模式，如 **/*.py"},
                            "path": {"type": "string", "description": "搜索根目录，默认当前目录"},
                        },
                        "required": ["pattern"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "run_command",
                    "description": "在当前项目目录执行 shell 命令并返回 stdout/stderr。",
                    "parameters": {
                        "type": "object",
                        "properties": {"command": {"type": "string", "description": "要执行的命令"}},
                        "required": ["command"],
                    },
                },
            },
              {
                  "type": "function",
                  "function": {
                      "name": "deepseek_eyes",
                      "description": "使用 DeepSeek Eyes 插件观察电脑屏幕并分析。action 支持 status / install / capture / look / plugin；question 是要问眼睛的问题。",
                      "parameters": {
                          "type": "object",
                          "properties": {
                              "action": {"type": "string", "enum": ["status", "install", "capture", "look", "plugin"]},
                              "question": {"type": "string", "description": "例如：当前屏幕上有什么？"},
                              "command": {"type": "string", "description": "plugin 动作下的插件命令参数"},
                          },
                          "required": ["action"],
                      },
                  },
              },
        ]


# ---------------------------------------------------------------- Agent


class AgentEngine:
    def __init__(
        self,
        api_key: str,
        cwd: str,
        model: str = DEFAULT_MODEL,
        max_steps: int = DEFAULT_MAX_STEPS,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
        base_url: str = DEFAULT_BASE_URL,
          eyes_manager=None,
    ) -> None:
        self.client = DeepSeekClient(api_key=api_key, model=model, base_url=base_url)
        self.tools = ToolRunner(cwd, eyes_manager=eyes_manager)
        self.max_steps = max(1, min(100, int(max_steps)))
        self.on_event = on_event
        self.metrics = RunMetrics()
        self._stop_event = threading.Event()
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def stop(self) -> None:
        self._stop_event.set()

    def _emit(self, event: Dict[str, Any]) -> None:
        if self.on_event:
            try:
                self.on_event(event)
            except Exception:
                pass

    def run_task(self, user_prompt: str) -> str:
        if self._running:
            raise RuntimeError("Agent 已在运行中")
        self._running = True
        self._stop_event.clear()
        self.metrics.start_turn()

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        final_text = ""
        self._emit({"type": "turn_start", "prompt": user_prompt})

        try:
            for step in range(1, self.max_steps + 1):
                if self._stop_event.is_set():
                    self._emit({"type": "stopped", "message": "用户停止"})
                    break

                self.metrics.record_step()
                self._emit({"type": "step_start", "step": step})

                text_parts: List[str] = []
                reasoning_parts: List[str] = []
                first_token_at: Optional[float] = None
                call_started = time.perf_counter()

                def on_text(delta: str) -> None:
                    nonlocal first_token_at
                    if first_token_at is None:
                        first_token_at = time.perf_counter()
                    text_parts.append(delta)
                    self._emit({"type": "assistant_delta", "text": delta})

                def on_reasoning(delta: str) -> None:
                    reasoning_parts.append(delta)
                    self._emit({"type": "reasoning_delta", "text": delta})

                try:
                    resp = self.client.chat(
                        messages,
                        tools=self.tools.tool_definitions(),
                        on_text=on_text,
                        on_reasoning=on_reasoning,
                    )
                except Exception as exc:
                    self._emit({"type": "error", "message": str(exc)})
                    break

                llm_seconds = time.perf_counter() - call_started
                ttft = (first_token_at - call_started) if first_token_at is not None else None
                self.metrics.record_api(llm_seconds, ttft, resp.usage, resp.model or self.client.model)

                if not text_parts and reasoning_parts and not resp.tool_calls:
                    text_parts = reasoning_parts  # 某些 reasoner 输出只给 reasoning_content

                assistant_message: Dict[str, Any] = {"role": "assistant", "content": "".join(text_parts)}
                if resp.tool_calls:
                    assistant_message["tool_calls"] = resp.tool_calls
                messages.append(assistant_message)

                if resp.tool_calls:
                    for raw_call in resp.tool_calls:
                        if self._stop_event.is_set():
                            break
                        try:
                            call = ToolCall(
                                id=raw_call.get("id", ""),
                                name=(raw_call.get("function") or {}).get("name", ""),
                                arguments=json.loads((raw_call.get("function") or {}).get("arguments", "{}") or "{}"),
                            )
                        except Exception as exc:
                            error_text = f"参数解析失败：{exc}"
                            if True:
                                
                              messages.append(
                                  {
                                      "role": "tool",
                                      "tool_call_id": raw_call.get("id", "call_0"),
                                      "content": error_text,
                                  }
                              )
                              self._emit({"type": "tool_call", "name": "unknown", "arguments": error_text})
                            continue

                        self._emit({"type": "tool_call", "name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)})
                        tool_started = time.perf_counter()
                        result = self.tools.execute(call.name, call.arguments)
                        tool_seconds = time.perf_counter() - tool_started
                        self.metrics.record_tool(tool_seconds, 1)
                        self._emit({"type": "tool_result", "name": result.name or call.name, "output": result.output, "is_error": result.is_error})
                        messages.append(
                            {"role": "tool", "tool_call_id": call.id or "call_0", "content": result.output}
                        )
                    continue

                final_text = "".join(text_parts)
                self._emit({"type": "done", "text": final_text, "reasoning": "".join(reasoning_parts), "steps": step})
                return final_text

            self._emit({"type": "done", "text": final_text or "(达到最大步数或已停止)", "steps": 0, "max_steps": True})
            return final_text
        finally:
            self._running = False
