# DeepSeek Agent Studio

一个属于 DeepSeek 的桌面自主 Agent 工具，带独立品牌 Logo、深色桌面端界面和实时运行指标。

不是 Claude Code 的监控器，而是直接调用 **DeepSeek API** 的完整 Agent：

- 能读文件、写文件、列目录、搜索文件、执行命令
- 自主循环：观察 → 行动 → 验证 → 修正
- 实时显示你要的指标行：
  `1 轮 · 32 步 | LLM 8m52s · 工具调用 0.4s | 首 token 平均 1s · 105 tok/s | 缓存命中 98% | 输入 1M tok · 输出 52.5K tok`

## 文件

| 文件 | 说明 |
|---|---|
| `deepseek_agent_studio.pyw` | 桌面端主程序 |
| `deepseek_agent_core.py` | Agent 核心引擎（API 流式调用、工具、指标） |
| `deepseek_eyes.py` | DeepSeek Eyes 眼睛插件（GitHub 下载、截图、调用插件） |
| `deepseek_updater.py` | 自动更新模块（检查、下载、覆盖安装、重启） |
| `deepseek_agent_logo.svg` | 品牌 Logo（深海鲸 + 数据节点） |
| `make_deepseek_icon.py` | 生成 PNG / ICO 图标（纯标准库） |
| `deepseek-agent-studio-update.json` | 更新清单模板（上传到 GitHub 仓库根目录） |
| `publish_update.py` | 发布新版本时自动生成带 SHA256 的更新清单 |
| `启动DeepSeekAgentStudio.bat` | 双击运行 |
| `build-deepseek-agent-studio.bat` | 一键打包成独立 exe |
| `assets\deepseek_agent_logo.png` | 256x256 Logo |
| `assets\deepseek_agent.ico` | exe 图标 |

## 使用

1. 双击 `启动DeepSeekAgentStudio.bat`
2. 填入 DeepSeek API Key（或设置环境变量 `DEEPSEEK_API_KEY`）
3. 选择工作目录
4. 在底部输入任务，`Ctrl+Enter` 或点“发送”
5. Agent 会自动调用工具执行，指标实时更新

示例任务：

```text
看一下当前目录结构，把 README 里的错别字找出来并修复，然后运行 python -m py_compile 验证没有语法错误
```

## 模型

- `deepseek-chat`：默认模型，支持工具调用和上下文缓存
- `deepseek-reasoner`：推理模型

API 地址默认 `https://api.deepseek.com`，也可填写兼容网关地址。

## 指标口径

| 指标 | 来源 |
|---|---|
| 轮次 | 发起的任务数 |
| 步骤 | Agent 循环次数（每次模型调用算一步） |
| LLM 耗时 | 每次 DeepSeek API 调用的真实墙钟时间累计 |
| 工具耗时 | 工具执行时间累计 |
| 首 Token 平均 | 流式响应第一个 content delta 的真实时间 |
| Tok/s | completion tokens ÷ LLM 耗时 |
| 缓存命中 | DeepSeek 返回的 prompt_cache_hit / (hit + miss) |
| 输入/输出 Tok | DeepSeek usage 字段 |

## DeepSeek Eyes（软件的眼睛）

- 点击主界面 **“安装/更新 Eyes”**，自动从 `https://github.com/hawkongz/deepseek-eyes` 下载并安装插件
- 点击 **“眼睛看屏幕”**，软件会截取当前屏幕，并调用 deepseek-eyes 插件分析屏幕内容
- Agent 运行时多了一个 `deepseek_eyes` 工具，模型需要“看屏幕”时会自动调用

如果 deepseek-eyes 仓库结构特殊，软件会尽量识别常见入口（`eyes.py` / `main.py` / `main.js` / `*.exe`）。
即使插件未安装，截图功能仍然可用。

## 自动更新

- 软件启动后自动检查更新；有新版本会弹窗
- 点击更新后自动下载，下载完成再点确认，会**覆盖安装旧 exe 并自动重启**
- 更新源默认读取 GitHub 仓库根目录的 `deepseek-agent-studio-update.json`
- 发布新版本：

```bat
python publish_update.py 1.1.0 dist\DeepSeek-Agent-Studio.exe ^
  https://github.com/ADTCoffee/DeepSeek-Agent-Studio/releases/download/v1.1.0/DeepSeek-Agent-Studio.exe ^
  "更新说明"
```

把生成的 `deepseek-agent-studio-update.json` 和 exe 一起传到 GitHub Release / 仓库根目录即可。

## 打包 exe

```bat
双击 build-deepseek-agent-studio.bat
```

生成 `dist\DeepSeek-Agent-Studio.exe`，带鲸鱼 Logo 和 ICO 图标。

## 安全提示

- API Key 默认不落盘；勾选“保存密钥”后会写入本机 `deepseek-agent-studio.json`
- `run_command` 会在工作目录执行 shell 命令，请只在可信目录使用
