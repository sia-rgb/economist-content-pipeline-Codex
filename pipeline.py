#!/usr/bin/env python3
"""
统一入口：输入 EPUB，按流水线生成最终 Word 文档。
"""

from __future__ import annotations

import sys
import shutil
from pathlib import Path

from docx_builder import build_document, output_file_for_epub
from article_processor import clean_articles, extract_articles_from_epub, filter_articles_by_length
from translate_articles import DIAGNOSTICS_FILENAME, translate_articles


RUNS_DIR = Path("runs")


def build_paths(epub_path: Path, task_dir: Path | None = None) -> dict[str, Path]:
    if task_dir is None:
        run_dir = RUNS_DIR / epub_path.stem
    else:
        run_dir = task_dir / "runs"
    return {
        "run_dir": run_dir,
        "mvp1_dir": run_dir / "mvp1",
        "mvp1_aggregate": run_dir / f"{epub_path.stem}_articles.txt",
        "mvp2_dir": run_dir / "mvp2",
        "mvp3_dir": run_dir / "mvp3",
        "mvp4_dir": run_dir / "mvp4",
        "mvp5_dir": run_dir / "mvp5",
    }


def run_pipeline(epub_path: Path, task_dir: Path | None = None) -> Path:
    if not epub_path.exists():
        raise FileNotFoundError(f"EPUB 文件不存在: {epub_path}")

    paths = build_paths(epub_path, task_dir=task_dir)
    paths["run_dir"].mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("开始执行统一流水线")
    print(f"输入 EPUB: {epub_path}")
    print(f"运行目录: {paths['run_dir']}")
    print("=" * 60)

    print("\n[提取] 提取文章")
    success = extract_articles_from_epub(
        str(epub_path),
        str(paths["mvp1_aggregate"]),
        str(paths["mvp1_dir"]),
    )
    if not success:
        raise RuntimeError("提取文章失败")

    print("\n[筛选] 筛选文章")
    success = filter_articles_by_length(
        str(paths["mvp1_dir"]),
        str(paths["mvp2_dir"]),
        min_length=2000,
    )
    if not success:
        raise RuntimeError("筛选文章失败")

    print("\n[清洗] 清洗格式")
    success = clean_articles(
        str(paths["mvp2_dir"]),
        str(paths["mvp3_dir"]),
    )
    if not success:
        raise RuntimeError("清洗格式失败")

    print("\n[翻译] 翻译文章")
    success = translate_articles(
        str(paths["mvp3_dir"]),
        str(paths["mvp4_dir"]),
        use_real_api=True,
    )
    if not success:
        diagnostics_file = paths["mvp4_dir"] / DIAGNOSTICS_FILENAME
        if diagnostics_file.exists():
            raise RuntimeError(f"翻译文章失败，诊断文件: {diagnostics_file}")
        raise RuntimeError("翻译文章失败")

    print("\n[合并] 合并 Word")
    output_file = output_file_for_epub(epub_path, paths["mvp5_dir"])
    build_document(paths["mvp4_dir"], output_file)
    if task_dir is not None:
        task_output = task_dir / "output.docx"
        task_output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(output_file, task_output)
        return task_output
    return output_file


def main() -> int:
    if len(sys.argv) > 1:
        epub_path = Path(sys.argv[1])
    else:
        epub_files = sorted(Path(".").glob("*.epub"))
        if not epub_files:
            print("请提供 EPUB 文件路径，或将 EPUB 放在当前目录下。")
            print("用法: python pipeline.py [epub文件路径]")
            return 1
        epub_path = epub_files[0]
        print(f"使用默认 EPUB: {epub_path}")

    try:
        output_file = run_pipeline(epub_path)
    except Exception as exc:
        print(f"\n流水线执行失败: {exc}")
        return 1

    print("\n统一流水线执行完成")
    print(f"最终 Word 输出: {output_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
