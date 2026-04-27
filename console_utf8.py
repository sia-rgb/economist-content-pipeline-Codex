#!/usr/bin/env python3
"""
控制台 UTF-8 初始化工具。

目标：
1. 在 Windows 控制台中将输入/输出 code page 切到 UTF-8。
2. 将 Python 标准流重设为 UTF-8，避免 print 中文时出现乱码。
"""

import os
import sys
import ctypes


def _set_windows_console_code_page():
    """在 Windows 控制台中启用 UTF-8 code page。"""
    if os.name != "nt":
        return

    try:
        kernel32 = ctypes.windll.kernel32
        utf8_code_page = 65001
        kernel32.SetConsoleCP(utf8_code_page)
        kernel32.SetConsoleOutputCP(utf8_code_page)
    except Exception:
        # 控制台不可用或当前环境不支持时，保持静默降级。
        pass


def _reconfigure_text_stream(stream):
    """将文本流重设为 UTF-8。"""
    if stream is None:
        return

    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def setup_console_utf8():
    """初始化当前进程的控制台与标准流编码。"""
    _set_windows_console_code_page()
    _reconfigure_text_stream(sys.stdout)
    _reconfigure_text_stream(sys.stderr)
    _reconfigure_text_stream(sys.stdin)
