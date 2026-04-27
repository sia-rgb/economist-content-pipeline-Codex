#!/usr/bin/env python3
"""
经济学人文章翻译工具
将清洗后的英文文章转换为高质量中文口播逐字稿
使用DeepSeek API进行翻译
"""

import os
import sys
import re
import socket
import json
import threading
import uuid
from typing import Tuple, Optional, List
import time
import concurrent.futures
from datetime import datetime, timezone
from urllib.parse import urlparse
from console_utf8 import setup_console_utf8

setup_console_utf8()

# 尝试导入dotenv，不是必须的
try:
    from dotenv import load_dotenv
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False
    print("警告: python-dotenv 未安装，将使用环境变量或默认配置")

# 尝试导入DeepSeek
try:
    import openai
    DEEPSEEK_AVAILABLE = True
except ImportError:
    DEEPSEEK_AVAILABLE = False
    print("警告: openai 库未安装")

# 口播稿转换提示词
AUDIO_SCRIPT_PROMPT = """你是一位专业的《经济学人》中文版有声书播音员。请将以下英文文章完整翻译成适合中文听众收听的口播逐字稿。
要求：
1. 忠实原文，完整保留所有信息，不得删减、概括、合并或改写掉任何观点、案例、数据、人名、地名、机构名和细节。
2. 在不增删信息、不改变观点和逻辑顺序的前提下，改写为自然、清晰、适合中文听众收听的中文口语。
3. 将长难句拆成短句，方便听众一次听懂，避免复杂倒装和过长修饰。
4. 保留原文逻辑关系。在观点转换处可适当加入少量自然的口语连接词，如“首先”“换句话说”“值得注意的是”，但不得额外添加原文没有的信息或解释。
5. 数据、百分比、数字、年份、日期、货币和倍数，按中文口播习惯表达，但必须保证信息准确、完整，不得模糊化。
6. 人名、地名、机构名、书名、报告名、政策名等专有名词要准确处理；如无通行译法，可保留原文，或首次出现时采用“中文名（英文）”格式。
7. 按原文段落顺序自然分段；可为口播流畅略微调整断句，但不得打乱原文结构。
输出格式：
- 第一行必须严格写为：标题：中文标题。
- 空一行后开始正文。
- 只输出标题和正文，开头和结尾不要添加任何过渡语、资料来源说明或额外标记。原文如下："""

LONG_ARTICLE_THRESHOLD = 14000
TRANSLATION_CHUNK_SIZE = 8000
TRANSLATION_MAX_TOKENS = 2500
DIAGNOSTICS_FILENAME = "mvp4_diagnostics.json"
LLM_CALL_LOG_PATH = os.path.join("logs", "llm_call_log.jsonl")
LLM_CALL_LOG_LOCK = threading.Lock()


class LLMResponseParseError(Exception):
    """Raised when the API response shape cannot be parsed."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error_details(error: Exception) -> dict:
    details = {
        "error_type": type(error).__name__,
        "error_message": str(error),
    }

    for attr_name in ("status_code", "code", "type", "request_id"):
        attr_value = getattr(error, attr_name, None)
        if attr_value is not None:
            if isinstance(attr_value, (str, int, float, bool)):
                details[attr_name] = attr_value
            else:
                details[attr_name] = str(attr_value)

    response = getattr(error, "response", None)
    if response is not None:
        response_status = getattr(response, "status_code", None)
        response_text = getattr(response, "text", None)
        if response_status is not None:
            details["response_status_code"] = response_status
        if response_text:
            details["response_text_preview"] = str(response_text)[:500]

    return details


def _extract_http_status(error: Exception) -> Optional[int]:
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    response = getattr(error, "response", None)
    response_status = getattr(response, "status_code", None)
    if isinstance(response_status, int):
        return response_status

    return None


def _classify_llm_error(error: Exception, http_status: Optional[int]) -> str:
    if isinstance(error, LLMResponseParseError):
        return "parse_error"

    error_text = f"{type(error).__name__} {error}".lower()

    if "insufficient" in error_text and "balance" in error_text:
        return "insufficient_balance"
    if "quota" in error_text or "billing" in error_text:
        return "insufficient_balance"
    if "overloaded" in error_text or "capacity" in error_text or "busy" in error_text:
        return "overloaded"
    if "timeout" in error_text or "timed out" in error_text:
        return "timeout"
    if "connection" in error_text or "connect" in error_text:
        return "network_error"
    if "dns" in error_text or "name resolution" in error_text:
        return "network_error"

    if http_status in (401, 403):
        return "auth_error"
    if http_status == 402:
        return "insufficient_balance"
    if http_status == 400:
        if any(keyword in error_text for keyword in ("parameter", "max_tokens", "temperature", "messages", "model")):
            return "invalid_parameters"
        return "invalid_request"
    if http_status == 422:
        return "invalid_parameters"
    if http_status == 429:
        return "rate_limit"
    if http_status in (503, 529):
        return "overloaded"
    if isinstance(http_status, int) and http_status >= 500:
        return "server_error"

    return "unknown_error"


def _write_llm_call_log(record: dict) -> None:
    try:
        log_dir = os.path.dirname(LLM_CALL_LOG_PATH)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        with LLM_CALL_LOG_LOCK:
            with open(LLM_CALL_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _classify_error(error: Exception) -> str:
    status_code = getattr(error, "status_code", None)
    if status_code in (401, 403):
        return "auth"
    if status_code == 429:
        return "rate_limit"
    if isinstance(status_code, int) and status_code >= 500:
        return "server"
    if isinstance(status_code, int):
        return "api_response"

    error_text = f"{type(error).__name__} {error}".lower()
    if "timeout" in error_text or "timed out" in error_text:
        return "timeout"
    if "connection" in error_text or "connect" in error_text:
        return "network"
    if "dns" in error_text or "name resolution" in error_text:
        return "network"
    return "unknown"


def _write_diagnostics(diagnostics_path: str, diagnostics: dict) -> None:
    try:
        output_dir = os.path.dirname(diagnostics_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        with open(diagnostics_path, "w", encoding="utf-8") as f:
            json.dump(diagnostics, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"写入翻译诊断文件失败: {e}")


def _record_diagnostic(diagnostics: Optional[dict], diagnostics_path: Optional[str],
                       diagnostics_lock: Optional[object],
                       stage: str, **fields) -> None:
    if diagnostics is None or diagnostics_path is None or diagnostics_lock is None:
        return

    event = {
        "time": _utc_now_iso(),
        "stage": stage,
    }
    event.update(fields)

    with diagnostics_lock:
        diagnostics["events"].append(event)
        diagnostics["updated_at"] = event["time"]
        _write_diagnostics(diagnostics_path, diagnostics)


def _set_diagnostic_summary(diagnostics: Optional[dict], diagnostics_path: Optional[str],
                            diagnostics_lock: Optional[object], **fields) -> None:
    if diagnostics is None or diagnostics_path is None or diagnostics_lock is None:
        return

    with diagnostics_lock:
        diagnostics["summary"].update(fields)
        diagnostics["updated_at"] = _utc_now_iso()
        _write_diagnostics(diagnostics_path, diagnostics)

def load_config():
    """加载配置文件"""
    # 尝试加载 .env 文件
    if DOTENV_AVAILABLE:
        load_dotenv()
        print("已加载 .env 文件配置")

    # 获取API密钥
    api_key = os.getenv("DEEPSEEK_API_KEY")
    api_base = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    max_concurrent = _parse_max_concurrent(os.getenv("MAX_CONCURRENT"))

    return {
        "api_key": api_key,
        "api_base": api_base,
        "model": model,
        "max_concurrent": max_concurrent
    }


def _parse_max_concurrent(value: Optional[str]) -> int:
    """解析并发数配置，默认 6，非法值回退到默认值。"""
    default_value = 3

    if value is None:
        return default_value

    try:
        parsed = int(value)
        if parsed < 1:
            return default_value
        return parsed
    except (TypeError, ValueError):
        return default_value

def init_deepseek_client(config, diagnostics: Optional[dict] = None,
                         diagnostics_path: Optional[str] = None,
                         diagnostics_lock: Optional[object] = None):
    """初始化DeepSeek客户端"""
    if not DEEPSEEK_AVAILABLE:
        print("警告: openai 库未安装，无法使用真实API")
        _record_diagnostic(
            diagnostics, diagnostics_path, diagnostics_lock,
            "client_init",
            ok=False,
            category="dependency",
            reason="openai 库未安装",
        )
        return None

    if not config["api_key"]:
        print("警告: 未设置 DEEPSEEK_API_KEY，无法使用真实API")
        _record_diagnostic(
            diagnostics, diagnostics_path, diagnostics_lock,
            "client_init",
            ok=False,
            category="config",
            reason="未设置 DEEPSEEK_API_KEY",
        )
        return None

    try:
        client = openai.OpenAI(
            api_key=config["api_key"],
            base_url=config["api_base"]
        )
        print(f"DeepSeek客户端初始化成功，使用模型: {config['model']}")
        _record_diagnostic(
            diagnostics, diagnostics_path, diagnostics_lock,
            "client_init",
            ok=True,
            model=config["model"],
            api_base=config["api_base"],
        )
        return client
    except Exception as e:
        print(f"DeepSeek客户端初始化失败: {e}")
        _record_diagnostic(
            diagnostics, diagnostics_path, diagnostics_lock,
            "client_init",
            ok=False,
            category=_classify_error(e),
            **_error_details(e),
        )
        return None


def check_deepseek_connectivity(config, timeout: float = 5.0,
                                diagnostics: Optional[dict] = None,
                                diagnostics_path: Optional[str] = None,
                                diagnostics_lock: Optional[object] = None) -> bool:
    """
    在启动阶段做一次轻量网络自检，避免整批任务进入后才发现无法外连。

    只检查 TCP 连通性，不发起真实 API 请求。
    """
    api_base = config["api_base"]
    parsed = urlparse(api_base)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    if not host:
        print(f"警告: API地址格式无效: {api_base}")
        _record_diagnostic(
            diagnostics, diagnostics_path, diagnostics_lock,
            "network_preflight",
            ok=False,
            category="config",
            api_base=api_base,
            reason="API地址格式无效",
        )
        return False

    print(f"启动前网络自检: {host}:{port}")
    start_time = time.time()

    try:
        with socket.create_connection((host, port), timeout=timeout):
            print("网络自检通过: DeepSeek API端点可连接")
            _record_diagnostic(
                diagnostics, diagnostics_path, diagnostics_lock,
                "network_preflight",
                ok=True,
                api_base=api_base,
                host=host,
                port=port,
                elapsed_sec=round(time.time() - start_time, 3),
            )
            return True
    except OSError as e:
        elapsed = time.time() - start_time
        if getattr(e, "winerror", None) == 10013:
            print("网络自检失败: 当前环境禁止外连套接字连接（WinError 10013）")
            print("请检查 Codex 启动参数、系统防火墙或网络策略")
        else:
            print(f"网络自检失败: 无法连接 DeepSeek API端点: {e}")
        _record_diagnostic(
            diagnostics, diagnostics_path, diagnostics_lock,
            "network_preflight",
            ok=False,
            category="network",
            api_base=api_base,
            host=host,
            port=port,
            elapsed_sec=round(elapsed, 3),
            **_error_details(e),
        )
        return False

def read_mvp3_article(filepath: str) -> Tuple[Optional[str], Optional[str]]:
    """
    读取清洗后的文章文件

    Args:
        filepath: 文件路径

    Returns:
        tuple: (title, content) 或 (None, None) 如果读取失败
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # 清洗后格式: 第一行是标题，空一行后是正文
        lines = content.split('\n')
        if len(lines) < 2:
            print(f"文件格式错误: {filepath}")
            return None, None

        title = lines[0].strip()
        # 找到正文开始位置（跳过标题后的空行）
        body_start = 1
        while body_start < len(lines) and not lines[body_start].strip():
            body_start += 1

        if body_start >= len(lines):
            print(f"文件没有正文内容: {filepath}")
            return None, None

        body = '\n'.join(lines[body_start:])

        return title, body

    except Exception as e:
        print(f"读取文件失败 {filepath}: {e}")
        return None, None

def is_valid_translation_file(filepath: str, min_body_length: int = 50) -> bool:
    """
    对已存在的翻译结果做极简有效性校验。

    校验规则：
    1. 文件存在且非空
    2. 首行以“标题：”开头
    3. 正文存在且长度超过很低阈值
    """
    if not os.path.exists(filepath):
        return False

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        if not content.strip():
            return False

        lines = content.splitlines()
        if not lines:
            return False

        first_line = lines[0].strip()
        if not first_line.startswith("标题："):
            return False

        body_lines = [line.strip() for line in lines[1:] if line.strip()]
        body = "\n".join(body_lines)
        if len(body) < min_body_length:
            return False

        return True

    except Exception as e:
        print(f"校验翻译文件失败 {filepath}: {e}")
        return False


def _message_char_length(messages) -> int:
    """统计本次请求消息文本总字符数。"""
    total = 0
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            total += len(content)
    return total


def _message_preview(messages, limit: int = 300) -> str:
    """截取本次请求消息文本预览。"""
    parts = []
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str) and content:
            parts.append(content)
    return "\n".join(parts)[:limit]


def _usage_value(usage, field_name: str) -> Optional[int]:
    """兼容对象和字典两种 usage 结构。"""
    if usage is None:
        return None
    if isinstance(usage, dict):
        value = usage.get(field_name)
    else:
        value = getattr(usage, field_name, None)
    return value if isinstance(value, int) else None


def _log_request_metrics(log_label: str, messages, translated_text: Optional[str], response, max_tokens: int):
    """输出轻量的输入/输出长度日志，并标记是否接近输出上限。"""
    input_chars = _message_char_length(messages)
    output_chars = len(translated_text) if translated_text else 0
    usage = getattr(response, "usage", None)
    prompt_tokens = _usage_value(usage, "prompt_tokens")
    completion_tokens = _usage_value(usage, "completion_tokens")
    total_tokens = _usage_value(usage, "total_tokens")

    near_limit = False
    if completion_tokens is not None and max_tokens > 0:
        near_limit = completion_tokens >= int(max_tokens * 0.85)

    tokens_summary = (
        f" prompt_tokens={prompt_tokens} completion_tokens={completion_tokens} total_tokens={total_tokens}"
        if prompt_tokens is not None or completion_tokens is not None or total_tokens is not None
        else ""
    )
    print(
        f"  [METRICS] {log_label} input_chars={input_chars} output_chars={output_chars}"
        f"{tokens_summary} near_max_tokens={'YES' if near_limit else 'NO'}"
    )


def _response_choice_details(response) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """提取模型返回正文、停止原因和空内容原因。"""
    try:
        choices = response.get("choices") if isinstance(response, dict) else getattr(response, "choices", None)
        if not choices:
            return None, None, "no_choices"

        choice = choices[0]
        finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else getattr(choice, "finish_reason", None)
        message = choice.get("message") if isinstance(choice, dict) else getattr(choice, "message", None)
        if message is None:
            return None, finish_reason, "no_message"

        content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
        if content is None or content == "":
            return content, finish_reason, "empty_content"
        if isinstance(content, str) and content.strip() == "":
            return content, finish_reason, "cleaned_to_empty"
        return content, finish_reason, None
    except Exception as parse_error:
        raise LLMResponseParseError(str(parse_error)) from parse_error


def _business_failure_type(raw_output: str, cleaned_output: str,
                           finish_reason: Optional[str],
                           content_empty_reason: Optional[str]) -> Optional[str]:
    if finish_reason == "length" and len(raw_output) == 0:
        return "empty_length_failure"
    if content_empty_reason == "parse_error":
        return "parse_error"
    if content_empty_reason == "cleaned_to_empty":
        return "cleaned_to_empty"
    if content_empty_reason:
        return "empty_output"
    if len(raw_output) == 0:
        return "empty_output"
    if len(cleaned_output) == 0:
        return "cleaned_to_empty"
    return None


def _normalize_failure_type(error_type: str) -> str:
    if error_type in ("timeout", "rate_limit", "overloaded", "server_error", "parse_error",
                      "auth_error", "insufficient_balance", "invalid_parameters"):
        return error_type
    return "non_retryable_error"


def _is_retryable_failure(failure_type: Optional[str]) -> bool:
    return failure_type in {
        "empty_output",
        "cleaned_to_empty",
        "empty_length_failure",
        "timeout",
        "rate_limit",
        "overloaded",
        "server_error",
    }


def _retry_sleep_seconds(attempt_no: int) -> Optional[int]:
    if attempt_no == 1:
        return 2
    if attempt_no == 2:
        return 5
    return None


def _call_deepseek_with_retry(client, model, messages,
                              log_label: str,
                              max_retries: int = 2,
                              retry_delay: float = 2.0,
                              diagnostics: Optional[dict] = None,
                              diagnostics_path: Optional[str] = None,
                              diagnostics_lock: Optional[object] = None,
                              filename: Optional[str] = None) -> Optional[str]:
    """执行单次 DeepSeek 请求，并统一处理重试与耗时日志。"""
    temperature = 0.3
    max_tokens = TRANSLATION_MAX_TOKENS
    input_chars = _message_char_length(messages)
    input_preview = _message_preview(messages)
    total_attempts = max_retries + 1

    for attempt in range(1, total_attempts + 1):
        request_id = uuid.uuid4().hex
        start_time_iso = _utc_now_iso()
        start_time = time.time()
        raw_output = None
        cleaned_output = ""
        finish_reason = None
        content_empty_reason = None

        try:
            print(f"  [API] {log_label} attempt {attempt}/{total_attempts} 开始")

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )

            try:
                translated_text, finish_reason, content_empty_reason = _response_choice_details(response)
            except Exception as parse_error:
                content_empty_reason = "parse_error"
                raise LLMResponseParseError(str(parse_error)) from parse_error

            raw_output = translated_text if isinstance(translated_text, str) else ""
            cleaned_output = raw_output.strip()
            end_time_iso = _utc_now_iso()
            elapsed = time.time() - start_time
            failure_type = _business_failure_type(raw_output, cleaned_output, finish_reason, content_empty_reason)
            business_status = "failed" if failure_type else "success"
            retryable = _is_retryable_failure(failure_type)
            final_attempt = business_status == "success" or not retryable or attempt >= total_attempts
            _write_llm_call_log({
                "request_id": request_id,
                "task_id": None,
                "article_id": filename,
                "model": model,
                "attempt_no": attempt,
                "max_retries": max_retries,
                "input_chars": input_chars,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "start_time": start_time_iso,
                "end_time": end_time_iso,
                "duration_ms": round(elapsed * 1000),
                "status": "success",
                "api_status": "success",
                "business_status": business_status,
                "failure_type": failure_type,
                "retryable": retryable,
                "final_attempt": final_attempt,
                "http_status": None,
                "error_type": None,
                "error_message": None,
                "retry_count": attempt - 1,
                "output_chars": len(translated_text) if translated_text else 0,
                "raw_output_chars": len(raw_output),
                "cleaned_output_chars": len(cleaned_output),
                "raw_output_preview": raw_output[:500],
                "finish_reason": finish_reason,
                "content_empty_reason": content_empty_reason,
                "input_preview": input_preview,
            })
            _log_request_metrics(log_label, messages, translated_text, response, max_tokens)
            print(f"  [API] {log_label} attempt {attempt}/{total_attempts} 成功，耗时: {elapsed:.2f}秒")
            _record_diagnostic(
                diagnostics, diagnostics_path, diagnostics_lock,
                "api_call",
                ok=business_status == "success",
                filename=filename,
                label=log_label,
                attempt=attempt,
                attempt_no=attempt,
                max_retries=max_retries,
                elapsed_sec=round(elapsed, 3),
                api_status="success",
                business_status=business_status,
                failure_type=failure_type,
                retryable=retryable,
                final_attempt=final_attempt,
                input_chars=input_chars,
                output_chars=len(translated_text) if translated_text else 0,
                raw_output_chars=len(raw_output),
                cleaned_output_chars=len(cleaned_output),
                finish_reason=finish_reason,
                content_empty_reason=content_empty_reason,
            )
            if business_status == "success":
                return translated_text

            if retryable and attempt < total_attempts:
                sleep_seconds = _retry_sleep_seconds(attempt)
                if sleep_seconds is not None:
                    print(f"  [API] {log_label} {sleep_seconds:.1f}秒后重试...")
                    time.sleep(sleep_seconds)
                continue

            return None

        except Exception as e:
            end_time_iso = _utc_now_iso()
            elapsed = time.time() - start_time
            http_status = _extract_http_status(e)
            error_type = _classify_llm_error(e, http_status)
            failure_type = _normalize_failure_type(error_type)
            retryable = _is_retryable_failure(failure_type)
            final_attempt = not retryable or attempt >= total_attempts
            _write_llm_call_log({
                "request_id": request_id,
                "task_id": None,
                "article_id": filename,
                "model": model,
                "attempt_no": attempt,
                "max_retries": max_retries,
                "input_chars": input_chars,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "start_time": start_time_iso,
                "end_time": end_time_iso,
                "duration_ms": round(elapsed * 1000),
                "status": "failed",
                "api_status": "failed",
                "business_status": "failed",
                "failure_type": failure_type,
                "retryable": retryable,
                "final_attempt": final_attempt,
                "http_status": http_status,
                "error_type": error_type,
                "error_message": str(e),
                "retry_count": attempt - 1,
                "output_chars": 0,
                "raw_output_chars": len(raw_output) if raw_output else 0,
                "cleaned_output_chars": len(cleaned_output),
                "raw_output_preview": raw_output[:500] if raw_output else "",
                "finish_reason": finish_reason,
                "content_empty_reason": content_empty_reason or ("parse_error" if isinstance(e, LLMResponseParseError) else None),
                "input_preview": input_preview,
            })
            print(f"  [API] {log_label} attempt {attempt}/{total_attempts} 失败，耗时: {elapsed:.2f}秒")
            print(f"DeepSeek API调用失败: {e}")
            _record_diagnostic(
                diagnostics, diagnostics_path, diagnostics_lock,
                "api_call",
                ok=False,
                filename=filename,
                label=log_label,
                attempt=attempt,
                attempt_no=attempt,
                max_retries=max_retries,
                elapsed_sec=round(elapsed, 3),
                api_status="failed",
                business_status="failed",
                failure_type=failure_type,
                retryable=retryable,
                final_attempt=final_attempt,
                category=_classify_error(e),
                raw_output_chars=len(raw_output) if raw_output else 0,
                cleaned_output_chars=len(cleaned_output),
                finish_reason=finish_reason,
                content_empty_reason=content_empty_reason or ("parse_error" if isinstance(e, LLMResponseParseError) else None),
                **_error_details(e),
            )

            if retryable and attempt < total_attempts:
                sleep_seconds = _retry_sleep_seconds(attempt)
                print(f"  [API] {log_label} {sleep_seconds:.1f}秒后重试...")
                time.sleep(sleep_seconds)

    return None


def _split_long_content(content: str, chunk_size: int = TRANSLATION_CHUNK_SIZE) -> List[str]:
    """按段落优先分块，过长段落再按句子拆分。"""
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", content) if paragraph.strip()]
    if not paragraphs:
        return [content.strip()] if content.strip() else []

    chunks = []
    current_parts = []
    current_length = 0

    def flush_current():
        nonlocal current_parts, current_length
        if current_parts:
            chunks.append("\n\n".join(current_parts).strip())
            current_parts = []
            current_length = 0

    def append_piece(piece: str):
        nonlocal current_parts, current_length
        piece = piece.strip()
        if not piece:
            return

        separator_length = 2 if current_parts else 0
        if current_parts and current_length + separator_length + len(piece) > chunk_size:
            flush_current()

        current_parts.append(piece)
        current_length += separator_length + len(piece)

    def split_oversized_paragraph(paragraph: str) -> List[str]:
        sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?。！？])\s+", paragraph) if sentence.strip()]
        if len(sentences) <= 1:
            return [paragraph[i:i + chunk_size] for i in range(0, len(paragraph), chunk_size)]

        pieces = []
        sentence_group = []
        sentence_group_length = 0

        for sentence in sentences:
            separator_length = 1 if sentence_group else 0
            if sentence_group and sentence_group_length + separator_length + len(sentence) > chunk_size:
                pieces.append(" ".join(sentence_group).strip())
                sentence_group = [sentence]
                sentence_group_length = len(sentence)
                continue

            if len(sentence) > chunk_size:
                if sentence_group:
                    pieces.append(" ".join(sentence_group).strip())
                    sentence_group = []
                    sentence_group_length = 0
                pieces.extend(sentence[i:i + chunk_size] for i in range(0, len(sentence), chunk_size))
                continue

            sentence_group.append(sentence)
            sentence_group_length += separator_length + len(sentence)

        if sentence_group:
            pieces.append(" ".join(sentence_group).strip())

        return pieces

    for paragraph in paragraphs:
        if len(paragraph) > chunk_size:
            flush_current()
            for piece in split_oversized_paragraph(paragraph):
                append_piece(piece)
            flush_current()
            continue

        append_piece(paragraph)

    flush_current()
    return chunks


def _translate_title_only(client, model, title: str,
                          max_retries: int = 2,
                          retry_delay: float = 2.0,
                          diagnostics: Optional[dict] = None,
                          diagnostics_path: Optional[str] = None,
                          diagnostics_lock: Optional[object] = None,
                          filename: Optional[str] = None) -> Optional[str]:
    """为长文分块翻译路径单独翻译标题。"""
    messages = [
        {"role": "system", "content": "你是一位专业的《经济学人》中文版有声书播音员。"},
        {"role": "user", "content": f"请准确翻译下面这篇《经济学人》文章标题，译成自然、清晰、适合中文听众收听的中文标题。不要添加任何说明，不要输出“标题：”，只输出中文标题。\n\n{title}"}
    ]
    translated_title = _call_deepseek_with_retry(
        client, model, messages, "title", max_retries=max_retries, retry_delay=retry_delay,
        diagnostics=diagnostics, diagnostics_path=diagnostics_path,
        diagnostics_lock=diagnostics_lock, filename=filename
    )
    return translated_title.strip() if translated_title else None


def _translate_chunk_body(client, model, title: str, chunk: str, chunk_index: int, total_chunks: int,
                          max_retries: int = 2,
                          retry_delay: float = 2.0,
                          diagnostics: Optional[dict] = None,
                          diagnostics_path: Optional[str] = None,
                          diagnostics_lock: Optional[object] = None,
                          filename: Optional[str] = None) -> Optional[str]:
    """翻译长文正文分块，避免重复输出标题和附加说明。"""
    messages = [
        {"role": "system", "content": "你是一位专业的《经济学人》中文版有声书播音员。"},
        {
            "role": "user",
            "content": (
                f"下面是同一篇长文章的第 {chunk_index}/{total_chunks} 段正文，原标题是：{title}\n"
                "请只翻译这一段正文，保持忠实原文、自然清晰、适合中文听众收听的口语表达。\n"
                "不得删减、概括或补充信息；要保留数据、专有名词和逻辑关系。\n"
                "不要添加标题、序号、说明、总结或任何额外标记，只输出这一段翻译后的正文。\n\n"
                f"{chunk}"
            )
        }
    ]
    translated_chunk = _call_deepseek_with_retry(
        client, model, messages, f"chunk {chunk_index}/{total_chunks}",
        max_retries=max_retries, retry_delay=retry_delay,
        diagnostics=diagnostics, diagnostics_path=diagnostics_path,
        diagnostics_lock=diagnostics_lock, filename=filename
    )
    return translated_chunk.strip() if translated_chunk else None


def translate_with_deepseek(client, model, title: str, content: str,
                            max_retries: int = 2, retry_delay: float = 2.0,
                            diagnostics: Optional[dict] = None,
                            diagnostics_path: Optional[str] = None,
                            diagnostics_lock: Optional[object] = None,
                            filename: Optional[str] = None) -> Optional[str]:
    """
    使用DeepSeek API翻译文章

    Args:
        client: DeepSeek客户端
        model: 模型名称
        title: 文章标题
        content: 文章内容
        max_retries: 最大重试次数
        retry_delay: 基础重试等待时间（秒）

    Returns:
        str: 翻译后的中文口播稿，失败返回None
    """
    full_text = f"{title}\n\n{content}"
    title_preview = title[:50] + "..." if len(title) > 50 else title

    print(f"正在调用DeepSeek API翻译文章: {title_preview}")

    if len(full_text) <= LONG_ARTICLE_THRESHOLD:
        translated_text = _call_deepseek_with_retry(
            client,
            model,
            [
                {"role": "system", "content": "你是一位专业的《经济学人》中文版有声书播音员。"},
                {"role": "user", "content": AUDIO_SCRIPT_PROMPT + full_text}
            ],
            "full article",
            max_retries=max_retries,
            retry_delay=retry_delay,
            diagnostics=diagnostics,
            diagnostics_path=diagnostics_path,
            diagnostics_lock=diagnostics_lock,
            filename=filename
        )
        if translated_text:
            print(f"翻译完成，长度: {len(translated_text)} 字符")
        return translated_text

    chunks = _split_long_content(content)
    if not chunks:
        print("长文分块失败: 未能生成有效正文分块")
        return None

    print(f"检测到超长文章，启用分块翻译: 正文 {len(content)} 字符，切分为 {len(chunks)} 块")

    translated_title = _translate_title_only(
        client, model, title, max_retries=max_retries, retry_delay=retry_delay,
        diagnostics=diagnostics, diagnostics_path=diagnostics_path,
        diagnostics_lock=diagnostics_lock, filename=filename
    )
    if not translated_title:
        print("长文分块翻译失败: 标题翻译失败")
        return None

    translated_chunks = []
    total_chunks = len(chunks)

    for chunk_index, chunk in enumerate(chunks, 1):
        print(f"  [CHUNK] 正在翻译第 {chunk_index}/{total_chunks} 块，长度: {len(chunk)} 字符")
        translated_chunk = _translate_chunk_body(
            client, model, title, chunk, chunk_index, total_chunks,
            max_retries=max_retries, retry_delay=retry_delay,
            diagnostics=diagnostics, diagnostics_path=diagnostics_path,
            diagnostics_lock=diagnostics_lock, filename=filename
        )
        if not translated_chunk:
            print(f"长文分块翻译失败: 第 {chunk_index}/{total_chunks} 块翻译失败")
            return None
        translated_chunks.append(translated_chunk)

    translated_text = f"标题：{translated_title}\n\n" + "\n\n".join(translated_chunks)
    print(f"分块翻译完成，长度: {len(translated_text)} 字符")
    return translated_text

def mock_translate(title: str, content: str) -> str:
    """
    模拟翻译（用于测试或API不可用时）

    Args:
        title: 文章标题
        content: 文章内容

    Returns:
        str: 模拟翻译结果
    """
    print(f"使用模拟翻译: {title[:50]}...")

    # 简单的模拟翻译 - 在实际使用中应替换为真实API调用
    mock_title = f"【模拟翻译】{title}"
    mock_content = f"（这里是英文文章的中文口播稿模拟版本，实际应使用DeepSeek API生成）\n\n原文标题: {title}\n\n原文内容预览: {content[:200]}...\n\n（完整文章需要真实API翻译）"

    result = f"标题：{mock_title}\n\n{mock_content}"
    return result

def save_mvp4_article(filepath: str, translated_text: str):
    """
    保存翻译后的文章

    Args:
        filepath: 输出文件路径
        translated_text: 翻译后的文本
    """
    try:
        # 确保输出目录存在
        output_dir = os.path.dirname(filepath)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
            print(f"创建输出目录: {output_dir}")

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(translated_text)

        print(f"已保存: {os.path.basename(filepath)}")
        return True

    except Exception as e:
        print(f"保存文件失败 {filepath}: {e}")
        return False

def translate_articles(input_dir: str, output_dir: str, use_real_api: bool = True):
    """
    翻译目录中的所有文章

    Args:
        input_dir: 输入目录（docs/mvp3）
        output_dir: 输出目录（docs/mvp4）
        use_real_api: 是否使用真实API
    """
    # 加载配置
    config = load_config()
    max_concurrent = config["max_concurrent"]

    print("=" * 60)
    print("开始翻译文章...")
    print(f"输入目录: {input_dir}")
    print(f"输出目录: {output_dir}")
    print(f"使用真实API: {use_real_api}")
    print(f"使用{max_concurrent}并发翻译")
    print("=" * 60)

    # 确保输出目录存在
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"创建输出目录: {output_dir}")

    diagnostics_path = os.path.join(output_dir, DIAGNOSTICS_FILENAME)
    diagnostics_lock = threading.Lock()
    diagnostics = {
        "created_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "input_dir": input_dir,
        "output_dir": output_dir,
        "use_real_api": use_real_api,
        "config": {
            "api_base": config["api_base"],
            "model": config["model"],
            "max_concurrent": max_concurrent,
            "api_key_present": bool(config["api_key"]),
            "api_key_length": len(config["api_key"]) if config["api_key"] else 0,
            "deepseek_available": DEEPSEEK_AVAILABLE,
            "dotenv_available": DOTENV_AVAILABLE,
        },
        "events": [],
        "summary": {},
    }
    _write_diagnostics(diagnostics_path, diagnostics)
    print(f"翻译诊断文件: {diagnostics_path}")

    # 初始化DeepSeek客户端
    client = None
    if use_real_api and not DEEPSEEK_AVAILABLE:
        _record_diagnostic(
            diagnostics, diagnostics_path, diagnostics_lock,
            "dependency_check",
            ok=False,
            category="dependency",
            reason="openai 库未安装",
        )

    if use_real_api and DEEPSEEK_AVAILABLE:
        if not check_deepseek_connectivity(
            config,
            diagnostics=diagnostics,
            diagnostics_path=diagnostics_path,
            diagnostics_lock=diagnostics_lock,
        ):
            print("错误: 启动前网络自检失败，无法执行真实翻译")
            _set_diagnostic_summary(
                diagnostics, diagnostics_path, diagnostics_lock,
                status="failed",
                reason="network_preflight_failed",
            )
            return False

    if use_real_api and DEEPSEEK_AVAILABLE:
        client = init_deepseek_client(
            config,
            diagnostics=diagnostics,
            diagnostics_path=diagnostics_path,
            diagnostics_lock=diagnostics_lock,
        )
        if not client:
            print("错误: 无法初始化真实API客户端，无法执行真实翻译")
            _set_diagnostic_summary(
                diagnostics, diagnostics_path, diagnostics_lock,
                status="failed",
                reason="client_init_failed",
            )
            return False

    # 收集所有.txt文件
    txt_files = []
    for filename in os.listdir(input_dir):
        if filename.endswith('.txt'):
            txt_files.append(filename)

    if not txt_files:
        print("错误: 输入目录中没有.txt文件")
        _set_diagnostic_summary(
            diagnostics, diagnostics_path, diagnostics_lock,
            status="failed",
            reason="no_input_txt_files",
        )
        return False

    print(f"找到 {len(txt_files)} 个文章文件")

    def article_attempt_summary(filename: str) -> dict:
        with diagnostics_lock:
            api_events = [
                event for event in diagnostics["events"]
                if event.get("stage") == "api_call" and event.get("filename") == filename
            ]

        success_events = [event for event in api_events if event.get("business_status") == "success"]
        failed_events = [event for event in api_events if event.get("business_status") == "failed"]
        last_failure = failed_events[-1] if failed_events else {}
        retry_success = any((event.get("attempt_no") or event.get("attempt") or 1) > 1 for event in success_events)

        return {
            "retry_success": retry_success,
            "last_failure_type": last_failure.get("failure_type"),
        }

    # 定义处理单个文件的函数
    def process_single_article(filename):
        """处理单篇文章"""
        input_path = os.path.join(input_dir, filename)
        output_path = os.path.join(output_dir, filename)

        print(f"\n处理文件: {filename}")

        if os.path.exists(output_path):
            if is_valid_translation_file(output_path):
                print(f"  [SKIP] {filename} already exists and is valid")
                _record_diagnostic(
                    diagnostics, diagnostics_path, diagnostics_lock,
                    "article_skip",
                    ok=True,
                    filename=filename,
                    reason="已存在有效翻译文件",
                )
                return {"ok": True, "filename": filename, "skipped": True, "retry_success": False}
            print(f"  [RETRY] {filename} 已存在但校验失败，将重新翻译")

        # 读取文章
        title, content = read_mvp3_article(input_path)
        if title is None or content is None:
            print(f"  [!] 读取失败")
            _record_diagnostic(
                diagnostics, diagnostics_path, diagnostics_lock,
                "article_read",
                ok=False,
                filename=filename,
                reason="读取文章失败",
            )
            return {"ok": False, "filename": filename, "failure_type": "non_retryable_error"}

        print(f"  标题: {title[:50]}..." if len(title) > 50 else f"  标题: {title}")
        print(f"  正文长度: {len(content)} 字符")

        # 翻译文章
        if use_real_api:
            if not client:
                print(f"  [!] 真实翻译不可用")
                _record_diagnostic(
                    diagnostics, diagnostics_path, diagnostics_lock,
                    "article_translate",
                    ok=False,
                    filename=filename,
                    category="config",
                    reason="真实翻译不可用",
                )
                return {"ok": False, "filename": filename, "failure_type": "non_retryable_error"}
            translated_text = translate_with_deepseek(
                client,
                config["model"],
                title,
                content,
                diagnostics=diagnostics,
                diagnostics_path=diagnostics_path,
                diagnostics_lock=diagnostics_lock,
                filename=filename,
            )
        else:
            translated_text = mock_translate(title, content)

        if translated_text is None:
            print(f"  [!] 翻译失败")
            attempt_summary = article_attempt_summary(filename)
            _record_diagnostic(
                diagnostics, diagnostics_path, diagnostics_lock,
                "article_translate",
                ok=False,
                filename=filename,
                reason="翻译函数返回None",
                failure_type=attempt_summary.get("last_failure_type"),
            )
            return {
                "ok": False,
                "filename": filename,
                "failure_type": attempt_summary.get("last_failure_type") or "non_retryable_error",
            }

        # 保存翻译结果
        success = save_mvp4_article(output_path, translated_text)
        if success:
            print(f"  [+] 翻译成功")
            attempt_summary = article_attempt_summary(filename)
            _record_diagnostic(
                diagnostics, diagnostics_path, diagnostics_lock,
                "article_translate",
                ok=True,
                filename=filename,
                output_chars=len(translated_text),
                retry_success=attempt_summary.get("retry_success", False),
            )
            return {
                "ok": True,
                "filename": filename,
                "skipped": False,
                "retry_success": attempt_summary.get("retry_success", False),
            }
        else:
            print(f"  [!] 保存失败")
            _record_diagnostic(
                diagnostics, diagnostics_path, diagnostics_lock,
                "article_save",
                ok=False,
                filename=filename,
                reason="保存翻译文章失败",
            )
            return {"ok": False, "filename": filename, "failure_type": "non_retryable_error"}

    # 使用配置项控制并发处理
    print(f"\n开始{max_concurrent}并发翻译...")
    success_files = 0
    failed_files = 0
    initial_success_files = 0
    retry_success_files = 0
    empty_output_failed_files = 0
    failed_articles = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        # 提交所有任务
        futures = {}
        for filename in txt_files:
            future = executor.submit(process_single_article, filename)
            futures[future] = filename

        # 收集结果
        for future in concurrent.futures.as_completed(futures):
            filename = futures[future]
            try:
                result = future.result(timeout=120)  # 每篇最长120秒
                if result and result.get("ok"):
                    success_files += 1
                    if not result.get("skipped"):
                        if result.get("retry_success"):
                            retry_success_files += 1
                        else:
                            initial_success_files += 1
                else:
                    failed_files += 1
                    failure_type = result.get("failure_type") if isinstance(result, dict) else None
                    failed_articles.append({
                        "filename": filename,
                        "failure_type": failure_type or "non_retryable_error",
                    })
                    if failure_type in ("empty_output", "cleaned_to_empty", "empty_length_failure"):
                        empty_output_failed_files += 1
            except concurrent.futures.TimeoutError:
                print(f"  [TIMEOUT] 任务超时（120秒）")
                _record_diagnostic(
                    diagnostics, diagnostics_path, diagnostics_lock,
                    "article_timeout",
                    ok=False,
                    filename=filename,
                    category="timeout",
                    timeout_sec=120,
                )
                failed_files += 1
                failed_articles.append({
                    "filename": filename,
                    "failure_type": "timeout",
                })
            except Exception as e:
                print(f"  [ERROR] 任务异常: {e}")
                _record_diagnostic(
                    diagnostics, diagnostics_path, diagnostics_lock,
                    "article_exception",
                    ok=False,
                    filename=filename,
                    category=_classify_error(e),
                    **_error_details(e),
                )
                failed_files += 1
                failed_articles.append({
                    "filename": filename,
                    "failure_type": "non_retryable_error",
                })

    total_files = len(txt_files)

    print("=" * 60)
    print("翻译完成!")
    print(f"总文件数: {total_files}")
    print(f"成功翻译: {success_files}")
    print(f"初次成功: {initial_success_files}")
    print(f"重试后成功: {retry_success_files}")
    print(f"处理失败: {failed_files}")
    print(f"空输出失败: {empty_output_failed_files}")
    failure_categories = {}
    for event in diagnostics["events"]:
        if event.get("ok") is False:
            category = event.get("category") or event.get("stage") or "unknown"
            failure_categories[category] = failure_categories.get(category, 0) + 1

    _set_diagnostic_summary(
        diagnostics, diagnostics_path, diagnostics_lock,
        status="succeeded" if success_files > 0 else "failed",
        total_files=total_files,
        success_files=success_files,
        initial_success_files=initial_success_files,
        retry_success_files=retry_success_files,
        failed_files=failed_files,
        empty_output_failed_files=empty_output_failed_files,
        failed_articles=failed_articles,
        failure_categories=failure_categories,
    )

    if success_files > 0:
        print(f"\n翻译后的文件已保存到: {output_dir}")
        print("前3个翻译文件示例:")
        success_files_list = [f for f in os.listdir(output_dir) if f.endswith('.txt')][:3]
        for i, f in enumerate(success_files_list, 1):
            filepath = os.path.join(output_dir, f)
            try:
                with open(filepath, 'r', encoding='utf-8') as file:
                    content = file.read()
                lines = content.split('\n')
                title_preview = lines[0] if lines else "无标题"
                print(f"  {i}. {f}")
                print(f"      标题预览: {title_preview[:50]}..." if len(title_preview) > 50 else f"      标题: {title_preview}")
            except:
                print(f"  {i}. {f} (读取失败)")

    return success_files > 0

def main():
    """主函数"""
    print("经济学人文章翻译工具")
    print("=" * 60)

    # 检查依赖
    if not DEEPSEEK_AVAILABLE:
        print("提示: 要使用真实DeepSeek API，请安装 openai 库:")
        print("pip install openai")

    if not DOTENV_AVAILABLE:
        print("提示: 要使用.env文件配置，请安装 python-dotenv 库:")
        print("pip install python-dotenv")

    # 路径配置
    input_dir = "docs/mvp3"
    output_dir = "docs/mvp4"

    # 检查输入目录
    if not os.path.exists(input_dir):
        print(f"错误: 输入目录不存在: {input_dir}")
        print("请先运行 pipeline.py 生成清洗后的文章文件")
        return 1

    # 检查是否有文章文件
    txt_files = [f for f in os.listdir(input_dir) if f.endswith('.txt')]
    if not txt_files:
        print(f"错误: 输入目录中没有.txt文件: {input_dir}")
        return 1

    print(f"输入目录中有 {len(txt_files)} 个文章文件")

    # 询问是否使用真实API
    use_real_api = True
    if not DEEPSEEK_AVAILABLE:
        print("错误: openai 库未安装，无法执行真实翻译")
        print("如需测试模拟翻译，请显式修改脚本调用参数")
        return 1
    else:
        config = load_config()
        if not config["api_key"]:
            print("错误: 未设置 DEEPSEEK_API_KEY 环境变量，无法执行真实翻译")
            print("请复制 .env.template 为 .env 并填写您的API密钥")
            print("或设置环境变量: export DEEPSEEK_API_KEY=your_key")
            print("如需测试模拟翻译，请显式修改脚本调用参数")
            return 1

    # 执行翻译
    success = translate_articles(input_dir, output_dir, use_real_api)

    if not success:
        print("\n警告: 没有成功翻译任何文件")
        return 1

    print("\n完成! 翻译文件已生成")
    return 0

if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)
