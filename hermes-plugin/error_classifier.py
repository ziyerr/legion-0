"""error_classifier.py — 4 级错误分类 + 重试调度（ADR-006 LOCKED）

四级分类：
- ``tech``      技术级：网络抖动 / 5xx / 429 / db locked / LLM context — 自动指数退避重试
- ``permission`` 权限级：401/403 永久 / readonly db 写挡 / git push reject / feishu_app_lock — 升级骏飞
- ``intent``    意图级：UNIQUE / FOREIGN KEY / required missing / LLM 永久拒答 / "我无法判断" — 给 PM 候选选项
- ``unknown``   未知级：以上都不命中 — 保守升级 + 完整 stack

参考：
- ARCHITECTURE.md §6（4 级判定矩阵）
- REQUIREMENTS.md §4.5（R-NFR-19~22）
- ADR-006（4 级分类 LOCKED）
- pm-clarification-20250425-1505.md R-OPEN-2（PM 补充 3 个边界）

设计纪律：
- 关键词匹配大小写不敏感（input 一律转 lower 后比对）
- 多级关键词同时命中时按 ``technical < permission < intent`` 取靠后一级（更保守）
- escalate 失败（飞书未配置 / token 失效 / 网络断）→ 写本地 escalation.log 兜底
- retry_with_backoff 仅对技术级错误重试，遇非技术级立即抛
- Phase 1 同步 sleep；async 调用方需自行换 asyncio.sleep
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

# ---------------------------------------------------------------------------
# Public level constants
# ---------------------------------------------------------------------------

LEVEL_TECH: str = "tech"
LEVEL_PERMISSION: str = "permission"
LEVEL_INTENT: str = "intent"
LEVEL_UNKNOWN: str = "unknown"

# Conservatism order — 多级同时命中时，靠后一级胜出（更保守）
_LEVEL_PRIORITY: List[str] = [LEVEL_TECH, LEVEL_PERMISSION, LEVEL_INTENT]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Mutable on purpose — tests may patch this to a temp path.
_ESCALATION_LOG_PATH: Path = (
    Path.home() / ".hermes" / "profiles" / "aicto" / "logs" / "escalation.log"
)

_OWNER_NAME: str = "张骏飞"
_ENV_OWNER_USER_ID: str = "AICTO_OWNER_FEISHU_USER_ID"  # 张骏飞 user_id (open_id)
_ENV_OWNER_CHAT_ID: str = "AICTO_FEISHU_CHAT_ID"        # AICTO 工作群 chat_id
_ENV_PM_CHAT_ID: str = "AICTO_PM_FEISHU_CHAT_ID"        # 私聊 PM 的 chat_id


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class WrappedToolError(Exception):
    """工具层包装异常，携带 4 级分类信息。

    用法：
        raise WrappedToolError("飞书 token 失效", level=LEVEL_PERMISSION)

    classify(WrappedToolError(...)) 直接返回其 level（不再做关键词匹配）。
    """

    def __init__(
        self,
        message: str,
        level: str = LEVEL_UNKNOWN,
        *,
        original: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message)
        self.level: str = level if level in {
            LEVEL_TECH, LEVEL_PERMISSION, LEVEL_INTENT, LEVEL_UNKNOWN
        } else LEVEL_UNKNOWN
        self.original: Optional[BaseException] = original

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"WrappedToolError(level={self.level!r}, message={self.args[0]!r})"


# ---------------------------------------------------------------------------
# Keyword tables (all lowercased; substring match)
# ---------------------------------------------------------------------------

# 权限级：永久权限拒绝 / 写挡 / 资源锁
_PERMISSION_KEYWORDS: List[str] = [
    "attempt to write a readonly database",  # CTO 误写 PM 表（dev.db mode=ro）
    "readonly database",
    "feishu_app_lock",
    "feishu app lock",
    "git push rejected",
    "git push reject",
    "non-fast-forward",
    "permission denied",
    "forbidden",
    "unauthorized",
    "401",
    "403",
]

# 意图级：业务约束 / 输入校验 / LLM 永久拒答 / "我无法判断"
_INTENT_KEYWORDS: List[str] = [
    "我无法",                     # 覆盖 "我无法判断" / "我无法继续" 等 LLM 拒答口径
    "cannot determine",
    "unable to determine",
    "unique constraint",
    "foreign key",
    "required field",
    "missing required",
    "validation error",
    "invalid argument",
    "policy refusal",
    "policy violation",
]

# 技术级：网络 / 5xx / 429 / db lock / LLM 暂时性
_TECH_KEYWORDS: List[str] = [
    # 网络异常类型名（lowercased）
    "connectionerror",
    "connecttimeout",
    "readtimeout",
    "timeouterror",
    # 网络异常描述
    "timeout",
    "timed out",
    "connection refused",
    "connection reset",
    "network is unreachable",
    "name resolution",
    # HTTP 5xx
    "500",
    "502",
    "503",
    "504",
    "5xx",
    "internal server error",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
    # Rate limit
    "429",
    "rate limit",
    "rate-limit",
    "too many requests",
    # DB transient
    "database is locked",
    "db is locked",
    "sqlite_busy",
    "deadlock",
    # LLM 暂时性
    "context length",
    "context window",
    "max_tokens",
    "model overloaded",
    "model is currently overloaded",
    "service is busy",
]

_LEVEL_KEYWORDS: Dict[str, List[str]] = {
    LEVEL_TECH: _TECH_KEYWORDS,
    LEVEL_PERMISSION: _PERMISSION_KEYWORDS,
    LEVEL_INTENT: _INTENT_KEYWORDS,
}


# ---------------------------------------------------------------------------
# Public API: classify
# ---------------------------------------------------------------------------

def classify(exception_or_msg: Union[BaseException, str, Any]) -> str:
    """把异常或错误消息分到 4 级（tech / permission / intent / unknown）。

    - exception_or_msg 接受 ``BaseException`` 实例或任意可 ``str()`` 的值。
    - 关键词匹配大小写不敏感。
    - 多级同时命中时按 ``_LEVEL_PRIORITY`` 取靠后一级（更保守）。
    - ``WrappedToolError`` 直接返回其 ``level``，不再做关键词匹配。
    """
    # Short-circuit: WrappedToolError 自带 level，直接信任
    if isinstance(exception_or_msg, WrappedToolError):
        return exception_or_msg.level or LEVEL_UNKNOWN

    if isinstance(exception_or_msg, BaseException):
        exc_type_name = type(exception_or_msg).__name__
        message = str(exception_or_msg)
        text = (exc_type_name + " " + message).lower()
        # 内置网络异常 → 默认 tech，但允许 permission/intent 关键词覆盖
        if isinstance(exception_or_msg, (ConnectionError, TimeoutError)):
            for level in (LEVEL_INTENT, LEVEL_PERMISSION):
                if _match_any(text, _LEVEL_KEYWORDS[level]):
                    return level
            return LEVEL_TECH
    else:
        text = str(exception_or_msg).lower()

    matched: List[str] = []
    if _match_any(text, _TECH_KEYWORDS):
        matched.append(LEVEL_TECH)
    if _match_any(text, _PERMISSION_KEYWORDS):
        matched.append(LEVEL_PERMISSION)
    if _match_any(text, _INTENT_KEYWORDS):
        matched.append(LEVEL_INTENT)

    if not matched:
        return LEVEL_UNKNOWN

    # 多级命中时取最靠后一级（最保守）
    for level in reversed(_LEVEL_PRIORITY):
        if level in matched:
            return level
    return LEVEL_UNKNOWN


def _match_any(text: str, keywords: List[str]) -> bool:
    return any(kw in text for kw in keywords)


# ---------------------------------------------------------------------------
# Retry with exponential backoff (tech-level only)
# ---------------------------------------------------------------------------

def retry_with_backoff(
    func: Callable[..., Any],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    **kwargs: Any,
) -> Any:
    """对技术级错误做指数退避重试。

    - 默认 max_retries=3，base_delay=1.0 → 退避序列 1s/2s/4s。
    - 仅技术级错误重试；非技术级（permission/intent/unknown）立即抛出。
    - 用尽重试仍失败 → 包装为 ``WrappedToolError(level=LEVEL_UNKNOWN)`` 抛出，
      上游可捕获并 escalate_to_owner（unknown 含完整 stack）。
    - 同步 ``time.sleep``；async 调用方需自行用 ``asyncio.sleep`` 实现。
    """
    if not callable(func):
        raise TypeError("retry_with_backoff: func must be callable")
    if max_retries < 1:
        raise ValueError("retry_with_backoff: max_retries must be >= 1")
    if base_delay < 0:
        raise ValueError("retry_with_backoff: base_delay must be >= 0")

    last_exc: Optional[BaseException] = None

    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except WrappedToolError as e:
            if e.level != LEVEL_TECH:
                raise
            last_exc = e
        except BaseException as e:  # noqa: BLE001 — intentional broad catch
            level = classify(e)
            if level != LEVEL_TECH:
                # 非技术级错误立即上抛，不重试
                raise
            last_exc = e

        # 不在最后一次尝试后 sleep（白白等）
        if attempt < max_retries - 1:
            delay = base_delay * (2 ** attempt)
            time.sleep(delay)

    # 全部重试用尽 — 包装为 unknown 让上游升级
    assert last_exc is not None
    raise WrappedToolError(
        f"retry_with_backoff exhausted after {max_retries} attempts: {last_exc}",
        level=LEVEL_UNKNOWN,
        original=last_exc,
    )


# ---------------------------------------------------------------------------
# Escalation paths (permission / unknown level → 升级骏飞)
# ---------------------------------------------------------------------------

def _format_owner_mention() -> str:
    """构造 ``<at user_id="xxx">张骏飞</at>``，无 user_id 时降级为 ``@张骏飞``。"""
    owner_id = os.environ.get(_ENV_OWNER_USER_ID, "").strip()
    if owner_id:
        return f'<at user_id="{owner_id}">{_OWNER_NAME}</at>'
    return f"@{_OWNER_NAME}"


def _truncate_json(obj: Any, limit: int = 500) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        s = str(obj)
    if len(s) > limit:
        return s[:limit] + "...（截断）"
    return s


def _format_escalation_text(
    level: str,
    exception_or_msg: Any,
    context: Dict[str, Any],
) -> str:
    mention = _format_owner_mention()

    if isinstance(exception_or_msg, BaseException):
        err_desc = f"{type(exception_or_msg).__name__}: {exception_or_msg}"
        try:
            stack = "".join(
                traceback.format_exception(
                    type(exception_or_msg),
                    exception_or_msg,
                    exception_or_msg.__traceback__,
                )
            )
        except Exception:  # noqa: BLE001
            stack = ""
    else:
        err_desc = str(exception_or_msg)
        stack = ""

    lines: List[str] = [
        f"{mention} 程小远遇到 [{level}] 级错误，需要你介入：",
        f"错误：{err_desc}",
    ]
    if context:
        lines.append(f"上下文：{_truncate_json(context)}")

    if level == LEVEL_UNKNOWN and stack:
        snippet = stack.strip().splitlines()[-10:]
        lines.append("Stack（末 10 行）：")
        lines.extend(snippet)

    return "\n".join(lines)


def _write_escalation_log(payload: Dict[str, Any]) -> bool:
    """Append a JSON line to escalation.log. Return True on success."""
    try:
        _ESCALATION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _ESCALATION_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        return True
    except OSError as e:
        print(
            f"[error_classifier] escalation log write failed: {e}",
            file=sys.stderr,
        )
        return False


def _try_send_feishu_text(chat_id: str, text: str) -> Optional[str]:
    """Try to send via feishu_api.send_text_to_chat. Return error string on failure, None on success."""
    if not chat_id:
        return f"chat_id empty (env not set)"
    try:
        # 延迟相对导入：feishu_api 可能尚未实现（占位期）
        from . import feishu_api  # type: ignore
    except ImportError as e:
        return f"ImportError: {e}"
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__} on import: {e}"

    try:
        feishu_api.send_text_to_chat(chat_id, text)
        return None
    except Exception as e:  # noqa: BLE001 — 飞书 API 失败兜底到 log
        return f"{type(e).__name__}: {e}"


def escalate_to_owner(
    level: str,
    exception_or_msg: Any,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """升级骏飞（飞书 @张骏飞）。失败兜底写本地 ``escalation.log``。

    Args:
        level: 4 级之一（permission / unknown 最常用，tech 重试失败也走此处）
        exception_or_msg: Exception 实例或 str
        context: 可选业务上下文（project_id / tool_name / args 摘要等）

    Returns:
        ``{"escalated": True, "level": ..., "sent_via_feishu": bool,
           "log_path": "...", "feishu_error": str|None}``
    """
    context = context or {}
    text = _format_escalation_text(level, exception_or_msg, context)
    chat_id = os.environ.get(_ENV_OWNER_CHAT_ID, "").strip()

    feishu_err = _try_send_feishu_text(chat_id, text)
    sent_via_feishu = feishu_err is None

    # 审计落盘 — 即使飞书发送成功也写日志（留痕）
    log_payload: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": "escalate_to_owner",
        "level": level,
        "error": str(exception_or_msg),
        "error_type": type(exception_or_msg).__name__
        if isinstance(exception_or_msg, BaseException)
        else "str",
        "context": context,
        "sent_via_feishu": sent_via_feishu,
        "feishu_error": feishu_err,
        "text": text,
    }
    log_written = _write_escalation_log(log_payload)

    return {
        "escalated": True,
        "level": level,
        "sent_via_feishu": sent_via_feishu,
        "log_written": log_written,
        "log_path": str(_ESCALATION_LOG_PATH),
        "feishu_error": feishu_err,
    }


# ---------------------------------------------------------------------------
# Intent-level: give PM candidate options
# ---------------------------------------------------------------------------

def give_options_to_pm(
    question: str,
    options: List[str],
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """意图级错误 — 给 PM 候选选项。

    Phase 1：通过飞书私聊 PM（``AICTO_PM_FEISHU_CHAT_ID``）发送文本。
    无 chat_id / 飞书失败 → 兜底写 ``escalation.log``。
    返回结构化 dict 供工具层序列化为 ``{"error": ..., "level": "intent", "options": ...}``。

    Args:
        question: 给 PM 的提问（"PRD 没有指定数据库类型，请选择"）
        options:  候选项列表（≥2 项，文档级要求 2~3 项）
        context:  可选业务上下文（prd_id / tool_name 等）

    Raises:
        ValueError: options 数量不足 2 或类型非法
    """
    if not isinstance(options, list):
        raise ValueError("give_options_to_pm: options 必须是 list")
    if len(options) < 2:
        raise ValueError("give_options_to_pm: options 至少 2 个候选")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("give_options_to_pm: question 不能为空")

    context = context or {}
    pm_chat_id = os.environ.get(_ENV_PM_CHAT_ID, "").strip()

    lines: List[str] = [
        f"程小远需要 PM 决策：{question}",
        "候选选项：",
    ]
    for i, opt in enumerate(options, 1):
        lines.append(f"  {i}. {opt}")
    if context:
        lines.append(f"上下文：{_truncate_json(context)}")
    text = "\n".join(lines)

    feishu_err = _try_send_feishu_text(pm_chat_id, text)
    sent_via_feishu = feishu_err is None

    log_payload: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": "give_options_to_pm",
        "question": question,
        "options": options,
        "context": context,
        "sent_via_feishu": sent_via_feishu,
        "feishu_error": feishu_err,
        "text": text,
    }
    log_written = _write_escalation_log(log_payload)

    return {
        "asked_pm": True,
        "question": question,
        "options": options,
        "sent_via_feishu": sent_via_feishu,
        "log_written": log_written,
        "feishu_error": feishu_err,
    }


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------

__all__ = [
    "LEVEL_TECH",
    "LEVEL_PERMISSION",
    "LEVEL_INTENT",
    "LEVEL_UNKNOWN",
    "WrappedToolError",
    "classify",
    "retry_with_backoff",
    "escalate_to_owner",
    "give_options_to_pm",
]
