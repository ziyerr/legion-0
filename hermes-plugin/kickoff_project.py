"""kickoff_project.py — 能力 0：项目启动自动化（8 步串联）

P1.5 核心入口实现。tools.py 仅 dispatch 到本模块的 ``run`` 函数。

8 步串联（详见 ARCHITECTURE.md §1 / PHASE-PLAN §6 / REQUIREMENTS §1.1 / PRD-CAPABILITIES 能力 0）：
  1. mkdir ~/Documents/<project>           # 本地 fs
  2. git init                              # 本地 fs（subprocess）
  3. POST 8642 /api/tools/create_project   # ProdMind HTTP 调用 ◄── ADR-008
  4. INSERT INTO ADR (number=1)            # _cto_own_connect 写 prodmind/dev.db ◄── ADR-002
  5. legion.sh l1+1 → 拉军团（subprocess）  # ◄── 失败兜底 discover_online_commanders
  6. 写 mailbox 协议（验证构造）            # legion_api.mailbox_protocol_serialize
  7. 派首批任务到军团 inbox                  # dispatch_to_legion_balanced（占位 task）
  8. send_card_message AICTO 群             # 飞书启动卡片（5 字段 + 3 按钮）

关键约束（硬纪律）：
- R-FN-0.6 SLA：≤30 秒完成 8 步（埋点 elapsed_seconds）
- R-FN-0.5 4 级错误分类：
  * 技术级（mkdir 权限 / git fail / HTTP 5xx）→ 自动重试 3 次
  * 权限级（git push 拒绝 / dev.db readonly）→ 升级骏飞
  * 意图级（project 已存在 / 缺参数）→ 给 PM 选项
  * 未知级 → 升级骏飞
- 降级策略：
  * PM 8642 不在线 → 本地记录 + 飞书 @PM 手动补建（不阻塞）
  * legion.sh 失败 → 找现有空闲军团兜底（不阻塞）
  * 飞书发卡片失败 → warning 记录但仍返成功（不阻塞）
- step_results 8 步全部记录（status / 时间戳 / 关键产出）
- _KickoffProjectError 继承 WrappedToolError（防 B-1）

测试时 mock 全部副作用：HTTP / subprocess(legion.sh) / send_card_message / dispatch_to_legion_balanced。
真实 mkdir / git init 可写入 ~/Documents/AICTO_kickoff_test/，运行后必须清理。

参考：
- .planning/phase1/specs/REQUIREMENTS.md §1.1（R-FN-0.1 ~ 0.6）
- .planning/phase1/specs/ARCHITECTURE.md §1（数据流图 — kickoff 8 步）
- .planning/phase1/specs/PHASE-PLAN.md §6
- .planning/phase1/recon/PRD-CAPABILITIES.md 能力 0（含 ASCII mock）
- .planning/phase1/decisions/ADR-008（PM HTTP 协议 LOCKED）
- .dispatch/inbox/pm-clarification-20250425-1505.md R-OPEN-8（HTTP endpoint）
- .dispatch/inbox/pm-clarification-20250425-1515-chatid.md（默认 chat_id）
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import (
    adr_storage,
    dispatch_balanced,
    error_classifier,
    feishu_api,
    legion_api,
)


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

KICKOFF_SLA_SECONDS: float = 30.0
"""R-FN-0.6 SLA：≤30 秒完成 8 步。"""

DEFAULT_AICTO_CHAT_ID: str = "oc_1d531eb5d70e3a415f728260f1bf7a7a"
"""R-OPEN-9 PM 答复：AICTO 群 chat_id 默认值（统一汇报）。"""

ENV_AICTO_CHAT_ID: str = "AICTO_FEISHU_CHAT_ID"

PRODMIND_CREATE_PROJECT_URL: str = "http://localhost:8642/api/tools/create_project"
"""ADR-008 LOCKED 的 PM HTTP 端点（kickoff 第 3 步）。"""

PRODMIND_HTTP_TIMEOUT_SECONDS: float = 5.0
"""PM HTTP 调用超时（保守值，避免 30s SLA 被单步拖死）。"""

LEGION_SCRIPT_PATH: str = "/Users/feijun/.claude/scripts/legion.sh"
"""legion.sh 全路径（kickoff 第 5 步 subprocess 调用）。"""

LEGION_SUBPROCESS_TIMEOUT: float = 15.0
"""legion.sh subprocess 超时（保守值）。"""

VALID_PRIORITIES = ("P0", "P1", "P2")

# project_name 白名单（防 path traversal — fix S-1 reviewer-p1-5 / 2026-04-25）
# 允许：英文 / 数字 / 下划线 / 连字符 / CJK 中文，长度 1-64
# 禁止：/ \ .. 控制字符 — 防止 ~/Documents/<name> 拼接逃逸
_PROJECT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_一-鿿][A-Za-z0-9_一-鿿\-]{0,63}$")


# ---------------------------------------------------------------------------
# 异常类（继承 WrappedToolError，防 B-1：retry 用 .level 短路）
# ---------------------------------------------------------------------------


class _KickoffProjectError(error_classifier.WrappedToolError):
    """本模块专用异常，继承 WrappedToolError 让 retry_with_backoff 走 .level 短路。

    防 B-1（reviewer-p1-2 / 2026-04-25）：原 design_tech_plan 继承 Exception →
    retry 用 classify() 关键词匹配返回 LEVEL_UNKNOWN → 立即抛不重试 →
    R-NFR-19 / ADR-006 技术级重试 3 次实质失效。本模块照 design_tech_plan /
    breakdown_tasks / dispatch_balanced 修复方案，继承 WrappedToolError 让
    retry 走 level 短路。
    """

    def __init__(
        self,
        message: str,
        level: str = error_classifier.LEVEL_UNKNOWN,
    ) -> None:
        super().__init__(message, level=level)


# ---------------------------------------------------------------------------
# Public entry — tools.py 调用此函数
# ---------------------------------------------------------------------------


def run(args: Dict[str, Any], **kwargs) -> str:
    """kickoff_project 主入口（8 步串联）。

    返回 JSON 字符串（与其他 AICTO 工具风格一致），所有错误用 4 级分类。
    """
    started_at = time.monotonic()
    warnings: List[str] = []
    step_results: Dict[str, Any] = {}

    # ---- 入参校验（intent 级失败立即返）----
    project_name = args.get("project_name")
    if not project_name or not isinstance(project_name, str) or not project_name.strip():
        return _fail(
            "project_name is required (non-empty string)",
            level=error_classifier.LEVEL_INTENT,
            elapsed=time.monotonic() - started_at,
            step_failed="0_validate_args",
        )
    project_name = project_name.strip()

    # path traversal 防御（fix S-1 reviewer-p1-5 / 2026-04-25）
    # CTO 写权力大于 design_tech_plan，必须双层防御（plugin schema + 这里 runtime）
    if not _PROJECT_NAME_PATTERN.match(project_name):
        return _fail(
            f"project_name {project_name!r} 含非法字符或超长，仅允许 [A-Za-z0-9_一-鿿-] 长度 1-64，禁 / \\ .. 控制字符",
            level=error_classifier.LEVEL_INTENT,
            elapsed=time.monotonic() - started_at,
            step_failed="0_validate_args",
        )

    description = args.get("description") or ""
    priority = args.get("priority") or "P1"
    if priority not in VALID_PRIORITIES:
        return _fail(
            f"priority must be one of {VALID_PRIORITIES}, got {priority!r}",
            level=error_classifier.LEVEL_INTENT,
            elapsed=time.monotonic() - started_at,
            step_failed="0_validate_args",
        )

    target_chat_id = (
        args.get("target_chat_id")
        or os.environ.get(ENV_AICTO_CHAT_ID)
        or DEFAULT_AICTO_CHAT_ID
    )
    expected_legion_skill = args.get("expected_legion_skill") or ""

    # ---- Step 1：创建项目目录 ----
    git_path = os.path.expanduser(f"~/Documents/{project_name}")
    try:
        s1 = _step1_mkdir(git_path)
    except _KickoffProjectError as e:
        step_results["1_mkdir"] = _step_failed(e, started_at)
        if e.level in (error_classifier.LEVEL_PERMISSION, error_classifier.LEVEL_UNKNOWN):
            error_classifier.escalate_to_owner(
                e.level, e, {"phase": "step1_mkdir", "git_path": git_path}
            )
        return _fail(
            str(e),
            level=e.level,
            elapsed=time.monotonic() - started_at,
            step_failed="1_mkdir",
            step_results=step_results,
        )
    except Exception as e:  # noqa: BLE001
        level = error_classifier.classify(e)
        step_results["1_mkdir"] = _step_failed(e, started_at, level=level)
        if level in (error_classifier.LEVEL_PERMISSION, error_classifier.LEVEL_UNKNOWN):
            error_classifier.escalate_to_owner(
                level, e, {"phase": "step1_mkdir", "git_path": git_path}
            )
        return _fail(
            f"step1_mkdir: {e}",
            level=level,
            elapsed=time.monotonic() - started_at,
            step_failed="1_mkdir",
            step_results=step_results,
        )
    step_results["1_mkdir"] = s1

    # ---- Step 2：git init ----
    try:
        s2 = _step2_git_init(git_path)
    except _KickoffProjectError as e:
        step_results["2_git_init"] = _step_failed(e, started_at)
        if e.level in (error_classifier.LEVEL_PERMISSION, error_classifier.LEVEL_UNKNOWN):
            error_classifier.escalate_to_owner(
                e.level, e, {"phase": "step2_git_init", "git_path": git_path}
            )
        return _fail(
            str(e),
            level=e.level,
            elapsed=time.monotonic() - started_at,
            step_failed="2_git_init",
            step_results=step_results,
        )
    except Exception as e:  # noqa: BLE001
        level = error_classifier.classify(e)
        step_results["2_git_init"] = _step_failed(e, started_at, level=level)
        if level in (error_classifier.LEVEL_PERMISSION, error_classifier.LEVEL_UNKNOWN):
            error_classifier.escalate_to_owner(
                level, e, {"phase": "step2_git_init", "git_path": git_path}
            )
        return _fail(
            f"step2_git_init: {e}",
            level=level,
            elapsed=time.monotonic() - started_at,
            step_failed="2_git_init",
            step_results=step_results,
        )
    step_results["2_git_init"] = s2

    # ---- Step 3：HTTP 调 PM create_project（降级容忍）----
    s3, project_id = _step3_create_pm_project(
        project_name=project_name,
        description=description,
        warnings=warnings,
    )
    step_results["3_prodmind_project"] = s3

    # ---- Step 4：写 ADR-0001 ----
    try:
        s4, adr_id, adr_display_number = _step4_write_adr(
            project_id=project_id,
            project_name=project_name,
            description=description,
            priority=priority,
            expected_legion_skill=expected_legion_skill,
        )
    except _KickoffProjectError as e:
        step_results["4_adr_0001"] = _step_failed(e, started_at)
        if e.level in (error_classifier.LEVEL_PERMISSION, error_classifier.LEVEL_UNKNOWN):
            error_classifier.escalate_to_owner(
                e.level, e, {"phase": "step4_write_adr", "project_id": project_id}
            )
        return _fail(
            str(e),
            level=e.level,
            elapsed=time.monotonic() - started_at,
            step_failed="4_adr_0001",
            step_results=step_results,
        )
    except Exception as e:  # noqa: BLE001
        level = error_classifier.classify(e)
        step_results["4_adr_0001"] = _step_failed(e, started_at, level=level)
        if level in (error_classifier.LEVEL_PERMISSION, error_classifier.LEVEL_UNKNOWN):
            error_classifier.escalate_to_owner(
                level, e, {"phase": "step4_write_adr", "project_id": project_id}
            )
        return _fail(
            f"step4_write_adr: {e}",
            level=level,
            elapsed=time.monotonic() - started_at,
            step_failed="4_adr_0001",
            step_results=step_results,
        )
    step_results["4_adr_0001"] = s4

    # ---- Step 5：拉军团（legion.sh l1+1，失败兜底 discover）----
    s5, legion_commander_id = _step5_provision_legion(
        project_name=project_name,
        expected_skill=expected_legion_skill,
        git_path=git_path,
        warnings=warnings,
    )
    step_results["5_legion"] = s5
    if not legion_commander_id:
        # 拉军团 + 兜底都失败 → 整体失败（无法派任务）
        return _fail(
            "step5_provision_legion: 无法拉起新军团且无在线空闲军团兜底",
            level=error_classifier.LEVEL_TECH,
            elapsed=time.monotonic() - started_at,
            step_failed="5_legion",
            step_results=step_results,
        )

    # ---- Step 6：建通讯（mailbox 协议构造，验证合法性）----
    try:
        s6 = _step6_build_mailbox(
            project_id=project_id,
            project_name=project_name,
            legion_commander_id=legion_commander_id,
        )
    except _KickoffProjectError as e:
        step_results["6_mailbox"] = _step_failed(e, started_at)
        # fix W-1 reviewer-p1-5：与 step 1/2/4 一致，permission/unknown 自动升级骏飞
        if e.level in (error_classifier.LEVEL_PERMISSION, error_classifier.LEVEL_UNKNOWN):
            error_classifier.escalate_to_owner(
                e.level, e, {"phase": "step6_mailbox",
                             "project_id": project_id,
                             "legion_commander_id": legion_commander_id}
            )
        return _fail(
            str(e),
            level=e.level,
            elapsed=time.monotonic() - started_at,
            step_failed="6_mailbox",
            step_results=step_results,
        )
    except Exception as e:  # noqa: BLE001
        level = error_classifier.classify(e)
        step_results["6_mailbox"] = _step_failed(e, started_at, level=level)
        return _fail(
            f"step6_build_mailbox: {e}",
            level=level,
            elapsed=time.monotonic() - started_at,
            step_failed="6_mailbox",
            step_results=step_results,
        )
    step_results["6_mailbox"] = s6

    # ---- Step 7：派首批任务（占位 task）----
    s7, initial_tasks = _step7_dispatch_initial(
        project_id=project_id,
        project_name=project_name,
        expected_skill=expected_legion_skill,
        warnings=warnings,
    )
    step_results["7_initial_tasks"] = s7

    # ---- Step 8：飞书启动卡片 ----
    s8, feishu_card_message_id = _step8_send_kickoff_card(
        project_name=project_name,
        git_path=git_path,
        legion_commander_id=legion_commander_id,
        adr_id=adr_id,
        adr_display_number=adr_display_number,
        project_id=project_id,
        target_chat_id=target_chat_id,
        warnings=warnings,
    )
    step_results["8_feishu_card"] = s8

    # ---- 返回 ----
    elapsed = time.monotonic() - started_at
    if elapsed > KICKOFF_SLA_SECONDS:
        warnings.append(
            f"SLA breach: elapsed={elapsed:.1f}s 超过 {KICKOFF_SLA_SECONDS:.0f}s "
            "（R-FN-0.6 验收）"
        )

    return _success(
        {
            "project_id": project_id,
            "git_path": git_path,
            "legion_commander_id": legion_commander_id,
            "adr_id": adr_id,
            "adr_display_number": adr_display_number,
            "initial_tasks": initial_tasks,
            "feishu_card_message_id": feishu_card_message_id,
            "elapsed_seconds": round(elapsed, 2),
            "sla_compliant": elapsed <= KICKOFF_SLA_SECONDS,
            "step_results": step_results,
            "warnings": warnings or None,
        }
    )


# ---------------------------------------------------------------------------
# Step 1: mkdir
# ---------------------------------------------------------------------------


def _step1_mkdir(git_path: str) -> Dict[str, Any]:
    """创建项目目录。

    存在已有目录 → intent 级（"project directory already exists"，给 PM 选项）。
    其他 OSError → permission（PermissionError）/ tech 级。
    """
    started = time.monotonic()
    if os.path.exists(git_path):
        raise _KickoffProjectError(
            f"project directory already exists: {git_path} "
            "（请改用其他名字或先删除已有目录）",
            level=error_classifier.LEVEL_INTENT,
        )
    try:
        os.makedirs(git_path, exist_ok=False)
    except FileExistsError as e:
        # race 兜底
        raise _KickoffProjectError(
            f"project directory already exists: {git_path}",
            level=error_classifier.LEVEL_INTENT,
        ) from e
    except PermissionError as e:
        raise _KickoffProjectError(
            f"mkdir permission denied: {git_path}: {e}",
            level=error_classifier.LEVEL_PERMISSION,
        ) from e
    except OSError as e:
        raise _KickoffProjectError(
            f"mkdir failed: {git_path}: {e}",
            level=error_classifier.LEVEL_TECH,
        ) from e

    return {
        "status": "success",
        "git_path": git_path,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "ts": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Step 2: git init（带 retry）
# ---------------------------------------------------------------------------


def _step2_git_init(git_path: str) -> Dict[str, Any]:
    """git init 项目目录（subprocess + retry 1 次重试）。

    技术级失败：subprocess returncode != 0（非 permission）/ TimeoutExpired。
    权限级：PermissionError / git push rejected 等关键词。
    """
    started = time.monotonic()

    def _do_git_init() -> str:
        try:
            result = subprocess.run(
                ["git", "init"],
                cwd=git_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except FileNotFoundError as e:
            raise _KickoffProjectError(
                f"git binary not found: {e}",
                level=error_classifier.LEVEL_PERMISSION,
            ) from e
        except subprocess.TimeoutExpired as e:
            raise _KickoffProjectError(
                f"git init timeout: {e}",
                level=error_classifier.LEVEL_TECH,
            ) from e
        except OSError as e:
            raise _KickoffProjectError(
                f"git init OSError: {e}",
                level=error_classifier.LEVEL_TECH,
            ) from e

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            level = error_classifier.classify(stderr) or error_classifier.LEVEL_TECH
            if level == error_classifier.LEVEL_UNKNOWN:
                # subprocess 失败默认 tech（可重试）
                level = error_classifier.LEVEL_TECH
            raise _KickoffProjectError(
                f"git init returncode={result.returncode}: {stderr}",
                level=level,
            )
        return result.stdout or ""

    # retry_with_backoff（tech 级 3 次重试）
    stdout = error_classifier.retry_with_backoff(_do_git_init, max_retries=3, base_delay=0.5)

    return {
        "status": "success",
        "git_path": git_path,
        "stdout_excerpt": (stdout.strip()[:200] if isinstance(stdout, str) else ""),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "ts": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Step 3: HTTP create_project on PM 8642（降级容忍）
# ---------------------------------------------------------------------------


def _step3_create_pm_project(
    *,
    project_name: str,
    description: str,
    warnings: List[str],
) -> Tuple[Dict[str, Any], str]:
    """调 ProdMind 8642 /api/tools/create_project（ADR-008 LOCKED）。

    PM 不在线 / 5xx → 降级：本地 logs 记录 + 飞书 @PM 手动补建（不阻塞）。
    返回 (step_record, project_id)；降级时 project_id 用临时 UUID。
    """
    started = time.monotonic()

    try:
        import requests  # 懒加载（部署侧 requests 由 hermes venv 提供）
    except ImportError as e:
        warnings.append(f"step3 requests 模块缺失，PM HTTP 跳过：{e}")
        return _step3_degraded(
            project_name=project_name,
            description=description,
            reason=f"requests 模块缺失：{e}",
            started=started,
        )

    body = {"name": project_name, "description": description or ""}

    def _do_post() -> Dict[str, Any]:
        # 降级关键：连接失败（PM 离线）→ ConnectionError → 走兜底
        # 5xx → tech 级，重试
        try:
            resp = requests.post(
                PRODMIND_CREATE_PROJECT_URL,
                json=body,
                timeout=PRODMIND_HTTP_TIMEOUT_SECONDS,
            )
        except requests.exceptions.ConnectionError as e:
            # 显式标记 connection refused → tech 级（让 retry 短路 / 上层降级）
            raise _KickoffProjectError(
                f"ProdMind connection refused: {e}",
                level=error_classifier.LEVEL_TECH,
            ) from e
        except requests.exceptions.Timeout as e:
            raise _KickoffProjectError(
                f"ProdMind HTTP timeout: {e}",
                level=error_classifier.LEVEL_TECH,
            ) from e
        except requests.exceptions.RequestException as e:
            raise _KickoffProjectError(
                f"ProdMind HTTP request error: {e}",
                level=error_classifier.LEVEL_TECH,
            ) from e

        if resp.status_code >= 500:
            raise _KickoffProjectError(
                f"ProdMind HTTP {resp.status_code}: {resp.text[:200]}",
                level=error_classifier.LEVEL_TECH,
            )
        if resp.status_code == 404:
            # endpoint 未挂载 → 降级（视为 PM 不在线一种）
            raise _KickoffProjectError(
                f"ProdMind endpoint 404 (not deployed): "
                f"{PRODMIND_CREATE_PROJECT_URL}",
                level=error_classifier.LEVEL_TECH,
            )
        if resp.status_code >= 400:
            raise _KickoffProjectError(
                f"ProdMind HTTP {resp.status_code}: {resp.text[:200]}",
                level=error_classifier.LEVEL_INTENT,
            )

        try:
            return resp.json()
        except ValueError as e:
            raise _KickoffProjectError(
                f"ProdMind 响应非法 JSON: {e}",
                level=error_classifier.LEVEL_TECH,
            ) from e

    # tech 级失败 retry 3 次；用尽 / 非 tech → 降级
    try:
        payload = error_classifier.retry_with_backoff(
            _do_post, max_retries=3, base_delay=0.5
        )
    except error_classifier.WrappedToolError as e:
        # 用尽重试或非 tech 级 — 降级（不抛，避免阻塞 8 步）
        return _step3_degraded(
            project_name=project_name,
            description=description,
            reason=str(e),
            started=started,
        )
    except Exception as e:  # noqa: BLE001
        # 兜底：任何其他异常都降级（PM 离线常态）
        return _step3_degraded(
            project_name=project_name,
            description=description,
            reason=f"{type(e).__name__}: {e}",
            started=started,
        )

    project_id = (
        payload.get("projectId") if isinstance(payload, dict) else None
    )
    if not project_id:
        warnings.append(
            "step3 PM 返回缺 projectId，降级为本地临时 UUID（PM 需手动补建）"
        )
        return _step3_degraded(
            project_name=project_name,
            description=description,
            reason="PM 返回缺 projectId 字段",
            started=started,
        )

    return (
        {
            "status": "success",
            "project_id": project_id,
            "endpoint": PRODMIND_CREATE_PROJECT_URL,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "ts": _now_iso(),
        },
        project_id,
    )


def _step3_degraded(
    *,
    project_name: str,
    description: str,
    reason: str,
    started: float,
) -> Tuple[Dict[str, Any], str]:
    """PM 不在线 / 失败 → 降级：本地记录 + 飞书 @PM 手动补建。"""
    project_id = f"local-{uuid.uuid4()}"
    log_dir = Path.home() / ".hermes" / "profiles" / "aicto" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "kickoff_pm_degraded.log"

    record = {
        "ts": _now_iso(),
        "kind": "kickoff_pm_degraded",
        "project_name": project_name,
        "description": description,
        "local_project_id": project_id,
        "reason": reason,
        "endpoint": PRODMIND_CREATE_PROJECT_URL,
    }
    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        log_written = True
    except OSError:
        log_written = False

    # best-effort 通知 PM（飞书 send_text_to_chat — 失败吞掉，不阻塞）
    pm_chat_id = os.environ.get("AICTO_PM_FEISHU_CHAT_ID", "").strip()
    pm_notified = False
    if pm_chat_id:
        try:
            feishu_api.send_text_to_chat(
                pm_chat_id,
                f"@张小飞 程小远 kickoff 第 3 步降级：PM HTTP 不在线（{reason[:200]}），"
                f"已本地占位 project_id={project_id}（{project_name}），"
                "请上线 ProdMind 后手动补建 Project 行并对齐 ID。",
            )
            pm_notified = True
        except Exception:  # noqa: BLE001 — best-effort
            pm_notified = False

    return (
        {
            "status": "degraded",
            "local_project_id": project_id,
            "local_record_path": str(log_path),
            "log_written": log_written,
            "pm_notified": pm_notified,
            "reason": reason,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "ts": _now_iso(),
        },
        project_id,
    )


# ---------------------------------------------------------------------------
# Step 4: 写 ADR-0001
# ---------------------------------------------------------------------------


def _step4_write_adr(
    *,
    project_id: str,
    project_name: str,
    description: str,
    priority: str,
    expected_legion_skill: str,
) -> Tuple[Dict[str, Any], str, str]:
    """写一条 ADR-0001 记录项目启动决策。

    Returns:
        (step_record, adr_id, adr_display_number)
    """
    started = time.monotonic()

    alternatives = [
        {
            "name": "立即启动并复用现有军团",
            "pros": "时间最短，无需等新军团 spawn",
            "cons": "现有军团可能与新项目技术栈不完全匹配",
            "chosen": False,
        },
        {
            "name": "等 PM PRD 评审完后再启动",
            "pros": "避免空转，技术栈选型更准",
            "cons": "PRD 评审可能拖几天，错过时间窗口",
            "chosen": False,
        },
        {
            "name": "8 步自动化串联立即启动 + 占位首批任务",
            "pros": "并行推进：军团就位 + 等 PRD；30s 内可见进度",
            "cons": "占位 task 不算实工作，需等 PRD 后 design_tech_plan 接力",
            "chosen": True,
        },
    ]

    rationale_parts = [f"基于 PM 触发：{description or '（未提供 description）'}"]
    if priority:
        rationale_parts.append(f"优先级 {priority}")
    if expected_legion_skill:
        rationale_parts.append(f"期望军团技能 = {expected_legion_skill}")
    rationale_parts.append(
        "决策方案：8 步自动化（mkdir / git init / PM 项目条目 / ADR / 拉军团 / "
        "mailbox / 派占位任务 / 飞书启动卡片），SLA ≤30s。"
    )
    rationale = "\n".join(rationale_parts)

    # fix W-2 reviewer-p1-5：sqlite locked 退避重试（PM R-OPEN-2 明确 tech 级 3 次重试）
    def _create_adr_inner():
        return adr_storage.create_adr(
            project_id=project_id,
            title="ADR-0001：项目启动决策记录",
            decision=f"启动项目 {project_name}（kickoff 8 步串联）",
            rationale=rationale,
            alternatives_considered=alternatives,
            decided_by="AICTO",
        )

    adr = error_classifier.retry_with_backoff(_create_adr_inner, max_retries=3, base_delay=1.0)

    return (
        {
            "status": "success",
            "adr_id": adr["id"],
            "adr_display_number": adr["display_number"],
            "project_id": project_id,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "ts": _now_iso(),
        },
        adr["id"],
        adr["display_number"],
    )


# ---------------------------------------------------------------------------
# Step 5: 拉军团（legion.sh l1+1，失败兜底 discover）
# ---------------------------------------------------------------------------


def _step5_provision_legion(
    *,
    project_name: str,
    expected_skill: str,
    git_path: str,
    warnings: List[str],
) -> Tuple[Dict[str, Any], Optional[str]]:
    """拉军团：legion.sh l1+1 <project_name>；失败兜底 discover_online_commanders.

    Returns:
        (step_record, legion_commander_id 或 None — None 表示完全失败)
    """
    started = time.monotonic()

    # 5a. 先试 legion.sh
    try:
        result = subprocess.run(
            ["bash", LEGION_SCRIPT_PATH, "l1+1", project_name],
            capture_output=True,
            text=True,
            timeout=LEGION_SUBPROCESS_TIMEOUT,
            cwd=git_path,
        )
        legion_sh_ok = result.returncode == 0
        legion_sh_stderr = (result.stderr or "").strip()[:300]
        legion_sh_stdout = (result.stdout or "").strip()[:300]
    except subprocess.TimeoutExpired as e:
        legion_sh_ok = False
        legion_sh_stderr = f"TimeoutExpired: {e}"
        legion_sh_stdout = ""
    except FileNotFoundError as e:
        legion_sh_ok = False
        legion_sh_stderr = f"FileNotFoundError: {e}"
        legion_sh_stdout = ""
    except OSError as e:
        legion_sh_ok = False
        legion_sh_stderr = f"OSError: {e}"
        legion_sh_stdout = ""

    if legion_sh_ok:
        # 解析 legion.sh 输出找 commander_id；通常 l1+1 默认创建 "L1-<project>" 或类似
        # legion.sh stdout 不一定标准化 — 兜底用 discover 找新创建的
        commanders = legion_api.discover_online_commanders()
        # 优先匹配 legion_project == project_name 的 commander
        chosen = None
        for c in commanders:
            if c.legion_project == project_name:
                chosen = c
                break
        if chosen is None and commanders:
            # fallback：取最新 started_at 的在线 commander
            chosen = commanders[0]

        if chosen:
            return (
                {
                    "status": "success",
                    "legion_commander_id": chosen.commander_id,
                    "legion_project": chosen.legion_project,
                    "tmux_session": chosen.tmux_session,
                    "tmux_alive": chosen.tmux_alive,
                    "method": "legion.sh l1+1",
                    "stdout_excerpt": legion_sh_stdout,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "ts": _now_iso(),
                },
                chosen.commander_id,
            )
        # legion.sh 成功但 discover 找不到 — 走兜底
        warnings.append(
            f"step5 legion.sh succeeded but discover found no commander; falling back."
        )

    else:
        warnings.append(
            f"step5 legion.sh failed: {legion_sh_stderr}; falling back to "
            "discover_online_commanders for idle legion."
        )

    # 5b. 兜底：discover 现有空闲军团
    try:
        commanders = legion_api.discover_online_commanders()
    except Exception as e:  # noqa: BLE001
        commanders = []
        warnings.append(f"step5 discover_online_commanders 失败：{e}")

    # 期望技能匹配（best-effort）+ alive 优先
    chosen_fallback = None
    if expected_skill and commanders:
        skill_lower = expected_skill.lower()
        # 简单子串匹配 commander_id 或 legion_project
        for c in commanders:
            blob = f"{c.commander_id} {c.legion_project}".lower()
            if skill_lower in blob:
                chosen_fallback = c
                break

    if chosen_fallback is None and commanders:
        # discover 已按 (alive, started) 排序 — 取首个
        chosen_fallback = commanders[0]

    if chosen_fallback is None:
        return (
            {
                "status": "failed",
                "method": "legion.sh + discover fallback",
                "legion_sh_ok": legion_sh_ok,
                "legion_sh_stderr": legion_sh_stderr,
                "online_legion_count": 0,
                "reason": "无新拉起军团且无空闲在线军团兜底",
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "ts": _now_iso(),
            },
            None,
        )

    return (
        {
            "status": "degraded" if not legion_sh_ok else "success",
            "legion_commander_id": chosen_fallback.commander_id,
            "legion_project": chosen_fallback.legion_project,
            "tmux_session": chosen_fallback.tmux_session,
            "tmux_alive": chosen_fallback.tmux_alive,
            "method": (
                "discover fallback (existing idle legion)"
                if not legion_sh_ok
                else "legion.sh + discover"
            ),
            "legion_sh_stderr": (None if legion_sh_ok else legion_sh_stderr),
            "online_legion_count": len(commanders),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "ts": _now_iso(),
        },
        chosen_fallback.commander_id,
    )


# ---------------------------------------------------------------------------
# Step 6: 建通讯（mailbox 协议构造）
# ---------------------------------------------------------------------------


def _step6_build_mailbox(
    *,
    project_id: str,
    project_name: str,
    legion_commander_id: str,
) -> Dict[str, Any]:
    """构造 mailbox 协议消息（验证合法性，不实际写 inbox）。

    R-FN-3.9：复用 legion_api.mailbox_protocol_serialize 不自构造，保证向后兼容。
    实际派单在 step 7 走 dispatch_to_legion_balanced（含双通道 inbox + tmux）。
    """
    started = time.monotonic()

    msg = legion_api.mailbox_protocol_serialize(
        payload=f"项目 {project_name} 启动，等待首批任务",
        msg_type="task",
        to=legion_commander_id,
        summary=f"AICTO 项目启动: {project_name}",
        cto_context={
            "project_id": project_id,
            "phase": "kickoff",
            "project_name": project_name,
        },
        priority="normal",
    )

    return {
        "status": "success",
        "msg_id": msg["id"],
        "msg_type": msg["type"],
        "from": msg["from"],
        "to": msg["to"],
        "summary": msg["summary"],
        "has_cto_context": "cto_context" in msg,
        "priority": msg.get("priority"),
        "note": "协议构造验证通过；实际派单由 step7 走 dispatch_to_legion_balanced",
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "ts": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Step 7: 派首批任务（占位 task）
# ---------------------------------------------------------------------------


def _step7_dispatch_initial(
    *,
    project_id: str,
    project_name: str,
    expected_skill: str,
    warnings: List[str],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """派 1 个 placeholder task 到军团（等 PM PRD 后接 design_tech_plan）。

    调用 dispatch_to_legion_balanced（含双通道 inbox + tmux），失败 → warning + deferred。
    Phase 1 占位任务：tech_stack_link=['planning']，可由 dispatch 启发式选军团。
    """
    started = time.monotonic()

    placeholder_tasks = [
        {
            "id": f"T-init-{uuid.uuid4().hex[:8]}",
            "title": f"等待 PM 提供 {project_name} PRD 后启动 design_tech_plan",
            "description": (
                f"项目 {project_name} 启动占位任务。"
                "等 PM 完成 PRD 评审后，CTO 将调用 design_tech_plan 落 ADR + 飞书技术方案文档；"
                "随后调 breakdown_tasks 拆分实战任务，再 dispatch_to_legion_balanced 派单。"
                "本任务无需军团动手，只需 acknowledge 并 standby。"
            ),
            "depends_on": [],
            "size": "S",
            "tech_stack_link": ["planning"] + (
                [expected_skill] if expected_skill else []
            ),
            "acceptance_gwt": {
                "given": f"军团已就位（{project_name} 项目目录 + git + ADR-0001 已落地）",
                "when": "PM 完成 PRD 并通知 CTO",
                "then": "CTO 触发 design_tech_plan → breakdown_tasks → dispatch；"
                        "军团从 standby 进入实战",
            },
            "suggested_legion": None,
        }
    ]

    try:
        raw = dispatch_balanced.run(
            {"tasks": placeholder_tasks, "project_id": project_id}
        )
        result = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        warnings.append(f"step7 dispatch_to_legion_balanced 调用异常：{e}")
        return (
            {
                "status": "degraded",
                "reason": f"dispatch invoke error: {e}",
                "tasks_attempted": len(placeholder_tasks),
                "tasks_assigned": 0,
                "tasks_deferred": len(placeholder_tasks),
                "initial_tasks": placeholder_tasks,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "ts": _now_iso(),
            },
            placeholder_tasks,
        )

    if not result.get("success"):
        # dispatch 内部失败 — 不阻塞 kickoff（占位任务可后续重派）
        warnings.append(
            f"step7 dispatch failed: {result.get('error') or 'unknown'}"
        )
        return (
            {
                "status": "degraded",
                "reason": f"dispatch returned failure: {result.get('error')}",
                "dispatch_level": result.get("level"),
                "tasks_attempted": len(placeholder_tasks),
                "tasks_assigned": 0,
                "tasks_deferred": len(placeholder_tasks),
                "initial_tasks": placeholder_tasks,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "ts": _now_iso(),
            },
            placeholder_tasks,
        )

    assignments = result.get("assignments") or []
    deferred = result.get("deferred") or []

    return (
        {
            "status": "success",
            "tasks_attempted": len(placeholder_tasks),
            "tasks_assigned": len(assignments),
            "tasks_deferred": len(deferred),
            "assignments": assignments,
            "deferred": deferred,
            "online_legion_count": result.get("online_legion_count"),
            "initial_tasks": placeholder_tasks,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "ts": _now_iso(),
        },
        placeholder_tasks,
    )


# ---------------------------------------------------------------------------
# Step 8: 飞书启动卡片
# ---------------------------------------------------------------------------


def _step8_send_kickoff_card(
    *,
    project_name: str,
    git_path: str,
    legion_commander_id: str,
    adr_id: str,
    adr_display_number: str,
    project_id: str,
    target_chat_id: str,
    warnings: List[str],
) -> Tuple[Dict[str, Any], Optional[str]]:
    """构造并发送 PRD-CAPABILITIES 能力 0 启动卡片。

    R-FN-0.4：5 字段 + 3 操作按钮。失败 → warning + status=degraded（不阻塞）。
    """
    started = time.monotonic()

    if not target_chat_id:
        warnings.append(
            "step8 飞书 chat_id 为空（AICTO_FEISHU_CHAT_ID 未配置且无传入），跳过卡片"
        )
        return (
            {
                "status": "degraded",
                "reason": "chat_id 为空，跳过发送",
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "ts": _now_iso(),
            },
            None,
        )

    card = build_kickoff_card(
        project_name=project_name,
        git_path=git_path,
        legion_commander_id=legion_commander_id,
        adr_id=adr_id,
        adr_display_number=adr_display_number,
        project_id=project_id,
    )

    try:
        resp = feishu_api.send_card_message(target_chat_id, card)
    except Exception as e:  # noqa: BLE001 — 飞书失败不阻塞
        warnings.append(f"step8 飞书 send_card_message 失败：{e}")
        return (
            {
                "status": "degraded",
                "reason": f"send_card_message error: {e}",
                "card_dict": card,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "ts": _now_iso(),
            },
            None,
        )

    # 飞书返回 {data: {message_id: ...}, ...} 或直接 {message_id: ...}
    message_id = None
    if isinstance(resp, dict):
        # 兼容两种风格
        message_id = resp.get("message_id")
        if not message_id and isinstance(resp.get("data"), dict):
            message_id = resp["data"].get("message_id")

    return (
        {
            "status": "success",
            "feishu_message_id": message_id,
            "chat_id": target_chat_id,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "ts": _now_iso(),
        },
        message_id,
    )


# ---------------------------------------------------------------------------
# 卡片构造（公开 API，测试也单独验证 dict schema）
# ---------------------------------------------------------------------------


def build_kickoff_card(
    *,
    project_name: str,
    git_path: str,
    legion_commander_id: str,
    adr_id: str,
    adr_display_number: str,
    project_id: str,
) -> Dict[str, Any]:
    """构造 PRD-CAPABILITIES 能力 0 启动卡片 dict。

    5 字段：项目名 / Path / Legion / ADR / 状态文案
    3 按钮：[查看 ADR]（primary）/ [加入军团群]（default）/ [暂停项目]（danger）
    button.value 必须 json.dumps（飞书协议怪癖）。
    template = "green"（PRD-CAPABILITIES 配色）。
    """
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"🚀 项目启动：{project_name}",
            },
            "template": "green",
        },
        "elements": [
            {
                "tag": "div",
                "fields": [
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**项目名**\n{project_name}",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**Path**\n`{git_path}`",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": (
                                f"**Legion**\n{legion_commander_id} (就位)"
                            ),
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**ADR**\n{adr_display_number} 已记录",
                        },
                    },
                ],
            },
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "**状态**：等 PM 发 PRD 启动首批任务",
                },
            },
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "查看 ADR"},
                        "type": "primary",
                        "value": json.dumps(
                            {
                                "action": "view_adr",
                                "adr_id": adr_id,
                                "adr_display_number": adr_display_number,
                                "project_id": project_id,
                            },
                            ensure_ascii=False,
                        ),
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "加入军团群"},
                        "type": "default",
                        "value": json.dumps(
                            {
                                "action": "join_legion",
                                "legion_commander_id": legion_commander_id,
                                "project_id": project_id,
                            },
                            ensure_ascii=False,
                        ),
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "暂停项目"},
                        "type": "danger",
                        "value": json.dumps(
                            {
                                "action": "pause_project",
                                "project_id": project_id,
                                "project_name": project_name,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
            },
        ],
    }


# ---------------------------------------------------------------------------
# 公共辅助
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _step_failed(
    e: BaseException,
    started_at: float,
    *,
    level: Optional[str] = None,
) -> Dict[str, Any]:
    """构造失败的 step_record。"""
    if level is None:
        if isinstance(e, error_classifier.WrappedToolError):
            level = e.level
        else:
            level = error_classifier.classify(e)
    return {
        "status": "failed",
        "error": f"{type(e).__name__}: {e}",
        "level": level,
        "elapsed_seconds": round(time.monotonic() - started_at, 3),
        "ts": _now_iso(),
    }


def _success(payload: Dict[str, Any]) -> str:
    return json.dumps({"success": True, **payload}, ensure_ascii=False)


def _fail(
    message: str,
    *,
    level: str,
    elapsed: float,
    step_failed: Optional[str] = None,
    step_results: Optional[Dict[str, Any]] = None,
) -> str:
    body: Dict[str, Any] = {
        "error": message,
        "level": level,
        "elapsed_seconds": round(elapsed, 2),
    }
    if step_failed:
        body["step_failed"] = step_failed
    if step_results is not None:
        body["step_results"] = step_results
    return json.dumps(body, ensure_ascii=False)


__all__ = [
    "run",
    "build_kickoff_card",
    "KICKOFF_SLA_SECONDS",
    "DEFAULT_AICTO_CHAT_ID",
    "PRODMIND_CREATE_PROJECT_URL",
    "LEGION_SCRIPT_PATH",
    "_KickoffProjectError",
]
