#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 deepseek-agent-studio-update.json 更新清单。

用法示例：
  python publish_update.py 1.0.1 dist/DeepSeek-Agent-Studio.exe ^
      https://github.com/hawkongz/deepseek-eyes/releases/download/v1.0.1/DeepSeek-Agent-Studio.exe ^
      "更新说明"

生成后把 JSON 和 exe 一起传到 GitHub Release / 仓库根目录即可。
"""

import hashlib
import json
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2

    version = sys.argv[1]
    exe_path = Path(sys.argv[2]).resolve()
    download_url = sys.argv[3]
    notes = sys.argv[4] if len(sys.argv) > 4 else ""

    if not exe_path.is_file():
        print(f"[ERROR] 找不到 exe：{exe_path}")
        return 1

    manifest = {
        "version": version,
        "download_url": download_url,
        "filename": exe_path.name,
        "sha256": sha256(exe_path),
        "notes": notes,
        "size": exe_path.stat().st_size,
    }

    out = exe_path.parent.parent / "deepseek-agent-studio-update.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] {out}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
