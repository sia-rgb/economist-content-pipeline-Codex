#!/usr/bin/env python3
"""
最小 provider 对比测试：同一批输入、同一并发配置下比较 DeepSeek 与 Moonshot。
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from translate_articles import DIAGNOSTICS_FILENAME, load_config, translate_articles


SOURCE_DIR = Path("runs/TE20260425/mvp3")
COMPARE_DIR = Path("runs/TE20260425/compare_api")
SAMPLE_DIR = COMPARE_DIR / "input_first10"
SUMMARY_FILE = COMPARE_DIR / "summary.json"
PROVIDERS = ("deepseek", "moonshot")
SAMPLE_SIZE = 10


def prepare_sample_input() -> None:
    if SAMPLE_DIR.exists():
        shutil.rmtree(SAMPLE_DIR)
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)

    files = sorted(SOURCE_DIR.glob("*.txt"))[:SAMPLE_SIZE]
    if len(files) != SAMPLE_SIZE:
        raise RuntimeError(f"样本不足: expected={SAMPLE_SIZE}, actual={len(files)}")

    for file_path in files:
        shutil.copy2(file_path, SAMPLE_DIR / file_path.name)


def read_summary(output_dir: Path) -> dict:
    diagnostics_path = output_dir / DIAGNOSTICS_FILENAME
    if not diagnostics_path.exists():
        return {}
    with open(diagnostics_path, "r", encoding="utf-8") as f:
        diagnostics = json.load(f)
    return diagnostics.get("summary", {})


def run_provider(provider: str) -> dict:
    output_dir = COMPARE_DIR / f"{provider}_mvp4"
    if output_dir.exists():
        shutil.rmtree(output_dir)

    run_id = f"compare_{provider}_{int(time.time())}"
    start_time = time.time()
    ok = translate_articles(
        str(SAMPLE_DIR),
        str(output_dir),
        use_real_api=True,
        provider=provider,
        run_id=run_id,
    )
    duration_sec = round(time.time() - start_time, 3)
    summary = read_summary(output_dir)
    total_files = summary.get("total_files") or SAMPLE_SIZE
    success_files = summary.get("success_files") or 0
    initial_success_files = summary.get("initial_success_files") or 0
    retry_success_files = summary.get("retry_success_files") or 0

    return {
        "provider": provider,
        "run_id": run_id,
        "ok": ok,
        "duration_sec": duration_sec,
        "total_files": total_files,
        "success_files": success_files,
        "initial_success_files": initial_success_files,
        "retry_success_files": retry_success_files,
        "failed_files": summary.get("failed_files") or 0,
        "empty_output_failed_files": summary.get("empty_output_failed_files") or 0,
        "initial_success_rate": round(initial_success_files / total_files, 4) if total_files else 0,
        "final_success_rate": round(success_files / total_files, 4) if total_files else 0,
        "output_dir": str(output_dir),
    }


def main() -> int:
    COMPARE_DIR.mkdir(parents=True, exist_ok=True)
    prepare_sample_input()

    config = load_config("deepseek")
    if config["max_concurrent"] != 6:
        print(f"INVALID: MAX_CONCURRENT 实际为 {config['max_concurrent']}，不是 6")
        return 1

    for provider in PROVIDERS:
        provider_config = load_config(provider)
        if not provider_config["api_key"]:
            print(f"INVALID: {provider} 缺少 API key")
            return 1

    results = [run_provider(provider) for provider in PROVIDERS]

    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"对比结果已写入: {SUMMARY_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
