"""review_code.py — 能力 4：代码审查（10 项 + BLOCKING 硬 gate + appeal 协议）

P1.6 核心入口实现。tools.py 仅 dispatch 到本模块的 ``run`` 函数。

5 步推理链（详见 ARCHITECTURE.md §1 / RECON-HISTORY 8.4）：
  1. 拉 PR diff（subprocess gh pr diff）
     - 失败 → tech 级（PR 不存在 / 权限不足 / gh CLI 未安装）
     - PR diff 过长（> 80K 字符）→ 截取关键文件 + warning
  2. 拉 tech_plan / PRD 上下文（如 tech_plan_id 给定）
     - adr_storage.list_adrs(project_id)
     - best-effort 拉 PRD 验收（pm_db_api.get_pm_context_for_tech_plan）
  3. LLM 10 项审查（强制三态 status / "X→Y 因 Z" 文案 / scope 单维度）
  4. 评论密度兜底
     - 单 PR ≤ 5 评论（超出按 severity 截断 + 聚合 warning）
     - 单文件 ≤ 2 BLOCKING（超出转 refactor 建议）
  5. 写 CodeReview 表 + 飞书 BLOCKING 卡片（如 BLOCKING > 0）

关键约束（硬纪律）：
- 每项 status ∈ {PASS, BLOCKING, NON-BLOCKING}
- BLOCKING 文案必须含"把 X 改成 Y 因为 Z"格式（LLM prompt + 后处理正则校验）
- 单 PR ≤ 5 评论 / 单文件 ≤ 2 BLOCKING（超出按 severity 排序截断）
- _ReviewCodeError 继承 WrappedToolError（防 B-1 第五轮）
- 全程 retry_with_backoff 包裹 LLM 调用
- 飞书卡片失败不阻塞主流程（warning 即可）
- senior_review_verdict 字段 Phase 1 留空，骏飞手动填（KR：BLOCKING 准确率 ≥90%）

参考：
- .planning/phase1/specs/REQUIREMENTS.md §1.5 R-FN-4.1 ~ 4.12
- .planning/phase1/specs/ARCHITECTURE.md §1（数据流）+ §5.4（CodeReview 表）
- .planning/phase1/specs/PHASE-PLAN.md §7
- .planning/phase1/recon/PRD-CAPABILITIES.md 能力 4
- .planning/phase1/recon/RECON-HISTORY.md §8.4（评论密度算法）
- .dispatch/inbox/pm-clarification-20250425-1505.md R-OPEN-3（appeal 1 次升级）+
  R-OPEN-10（KR 分子分母）
- design_tech_plan.py（_invoke_llm / _extract_content / _parse_llm_json 复用）
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from . import adr_storage, design_tech_plan, error_classifier, feishu_api, pm_db_api


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

PROMPT_PATH: pathlib.Path = (
    pathlib.Path(__file__).parent / "templates" / "code-review-prompt.md"
)
"""LLM prompt 模板（避免硬编码到 .py）。"""

# 10 项审查清单（PRD 字面，逐字保留 — 顺序固定，program 用作权威表）
CHECKLIST_ITEMS: List[Tuple[int, str]] = [
    (1, "架构一致"),
    (2, "可读性"),
    (3, "安全"),
    (4, "测试"),
    (5, "错误处理"),
    (6, "复杂度"),
    (7, "依赖"),
    (8, "性能"),
    (9, "跨军团冲突"),
    (10, "PRD 一致"),
]

ALLOWED_STATUS: set = {"PASS", "BLOCKING", "NON-BLOCKING"}

# scope 别名 → checklist 维度名（小写归一化匹配）
SCOPE_ALIASES: Dict[str, str] = {
    "all": "all",
    "architecture": "架构一致",
    "架构": "架构一致",
    "架构一致": "架构一致",
    "readability": "可读性",
    "可读性": "可读性",
    "security": "安全",
    "安全": "安全",
    "test": "测试",
    "tests": "测试",
    "测试": "测试",
    "error": "错误处理",
    "error_handling": "错误处理",
    "错误处理": "错误处理",
    "complexity": "复杂度",
    "复杂度": "复杂度",
    "dependency": "依赖",
    "dependencies": "依赖",
    "依赖": "依赖",
    "performance": "性能",
    "perf": "性能",
    "性能": "性能",
    "conflict": "跨军团冲突",
    "cross_legion": "跨军团冲突",
    "跨军团冲突": "跨军团冲突",
    "prd": "PRD 一致",
    "prd_consistency": "PRD 一致",
    "prd 一致": "PRD 一致",
}

# PR diff 字符上限（送 LLM 前截断，避免 context 爆掉）
PR_DIFF_CHAR_LIMIT: int = 80000

# 评论密度上限（PRD §五·能力 4）
MAX_COMMENTS_PER_PR: int = 5
MAX_BLOCKING_PER_FILE: int = 2

# 「X → Y 因 Z」文案校验关键词（必须同时含「改成/换成」+「因」/「因为」）
_BLOCKING_FORMAT_KEYWORDS_AB: Tuple[str, ...] = ("改成", "换成", "替换", "改为")
_BLOCKING_FORMAT_KEYWORDS_REASON: Tuple[str, ...] = ("因为", "因", "由于")

# Severity 排序：BLOCKING > NON-BLOCKING > PASS（用于截断时保留高 severity）
_STATUS_SEVERITY: Dict[str, int] = {"BLOCKING": 2, "NON-BLOCKING": 1, "PASS": 0}

# Appeal 升级阈值（R-OPEN-3：默认 1 次 appeal 即升级骏飞）
APPEAL_ESCALATION_THRESHOLD: int = 1


# ---------------------------------------------------------------------------
# 异常类（继承 WrappedToolError，防 B-1：retry 用 .level 短路）
# ---------------------------------------------------------------------------


class _ReviewCodeError(error_classifier.WrappedToolError):
    """本模块专用异常，继承 WrappedToolError 让 retry_with_backoff 走 .level 短路。

    防 B-1（第五轮固化）：照 design_tech_plan / breakdown_tasks /
    dispatch_balanced / kickoff_project 修复方案，继承 WrappedToolError 让
    retry 走 level 短路 → 技术级正常 3 次重试。
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
    """review_code 主入口（5 步推理链）。

    返回 JSON 字符串（与其他 AICTO 工具风格一致），所有错误用 4 级分类。
    """
    started_at = time.monotonic()
    warnings: List[str] = []

    # ---- 入参校验（intent 级失败立即返）----
    pr_url = args.get("pr_url")
    tech_plan_id = args.get("tech_plan_id")
    scope_raw = args.get("scope") or "all"

    if not pr_url or not isinstance(pr_url, str):
        return _fail(
            "pr_url is required (string)",
            level=error_classifier.LEVEL_INTENT,
            elapsed=time.monotonic() - started_at,
        )

    # 简单校验 PR URL 格式（github.com/owner/repo/pull/N）
    pr_meta = _parse_pr_url(pr_url)
    if not pr_meta.get("owner") or not pr_meta.get("repo") or not pr_meta.get("number"):
        return _fail(
            f"pr_url must be a valid GitHub PR URL "
            f"(https://github.com/<owner>/<repo>/pull/<n>); got {pr_url!r}",
            level=error_classifier.LEVEL_INTENT,
            elapsed=time.monotonic() - started_at,
        )

    # 归一化 scope
    scope_canonical = _normalize_scope(scope_raw)
    if scope_canonical is None:
        return _fail(
            f"unknown scope {scope_raw!r}; allowed: all / "
            f"{','.join(sorted(set(SCOPE_ALIASES.values())))}",
            level=error_classifier.LEVEL_INTENT,
            elapsed=time.monotonic() - started_at,
        )

    # ---- Step 1：拉 PR diff ----
    try:
        pr_diff_full, pr_title = _step1_fetch_pr_diff(pr_url)
    except _ReviewCodeError as e:
        # 技术级：可能是 gh CLI 临时超时 — retry 由 _step1 内部 retry 接管，到这里说明用尽
        if e.level in (error_classifier.LEVEL_PERMISSION, error_classifier.LEVEL_UNKNOWN):
            error_classifier.escalate_to_owner(
                e.level, e, {"phase": "step1_fetch_pr_diff", "pr_url": pr_url}
            )
        return _fail(
            f"step1_fetch_pr_diff: {e}",
            level=e.level,
            elapsed=time.monotonic() - started_at,
        )
    except Exception as e:  # noqa: BLE001
        level = error_classifier.classify(e)
        if level in (error_classifier.LEVEL_PERMISSION, error_classifier.LEVEL_UNKNOWN):
            error_classifier.escalate_to_owner(
                level, e, {"phase": "step1_fetch_pr_diff", "pr_url": pr_url}
            )
        return _fail(
            f"step1_fetch_pr_diff: {e}",
            level=level,
            elapsed=time.monotonic() - started_at,
        )

    # PR diff 大小裁剪
    pr_diff_for_llm, diff_truncated = _truncate_pr_diff(pr_diff_full)
    if diff_truncated:
        warnings.append(
            f"PR diff 过长（{len(pr_diff_full)} 字符），已截断到前 "
            f"{PR_DIFF_CHAR_LIMIT} 字符送 LLM 审查；如需完整审查请人工补做"
        )

    # ---- Step 2：拉 tech_plan / PRD 上下文（best-effort） ----
    project_id: Optional[str] = tech_plan_id  # tech_plan_id 沿用 design_tech_plan 约定 = project_id
    tech_plan_context: str = "（无 tech_plan_id；架构一致维度仅做结构性检查）"
    prd_context: str = "（无 PRD 上下文；PRD 一致维度仅做形式检查）"

    if tech_plan_id:
        try:
            adrs = adr_storage.list_adrs(tech_plan_id) or []
            tech_plan_context = _summarize_adrs_for_review(adrs)
            if not adrs:
                warnings.append(
                    f"tech_plan_id={tech_plan_id} 对应 0 条 ADR；架构一致维度可能不准"
                )
        except Exception as e:  # noqa: BLE001
            # ADR 读失败 → warning，不阻塞
            warnings.append(f"tech_plan ADR 读取失败：{e}（架构一致维度可能不准）")
            tech_plan_context = f"（ADR 读取失败：{e}）"

        # 尝试拉 PRD 上下文（best-effort；project_id 可能不是真实 PM Project.id）
        try:
            prd_context = _try_load_prd_context(tech_plan_id)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"PRD 上下文拉取失败：{e}（PRD 一致维度可能不准）")

    # ---- Step 3：LLM 10 项审查 ----
    try:
        llm_result = _step3_llm_review(
            pr_url=pr_url,
            pr_number=pr_meta.get("number") or "",
            pr_title=pr_title or "",
            pr_diff=pr_diff_for_llm,
            tech_plan_context=tech_plan_context,
            prd_context=prd_context,
            scope=scope_canonical,
        )
    except _ReviewCodeError as e:
        if e.level in (error_classifier.LEVEL_PERMISSION, error_classifier.LEVEL_UNKNOWN):
            error_classifier.escalate_to_owner(
                e.level, e, {"phase": "step3_llm_review", "pr_url": pr_url}
            )
        return _fail(
            f"step3_llm_review: {e}",
            level=e.level,
            elapsed=time.monotonic() - started_at,
        )
    except error_classifier.WrappedToolError as e:
        # retry 用尽
        error_classifier.escalate_to_owner(
            e.level, e, {"phase": "step3_llm_review", "pr_url": pr_url}
        )
        return _fail(
            f"step3_llm_review exhausted: {e}",
            level=e.level,
            elapsed=time.monotonic() - started_at,
        )
    except Exception as e:  # noqa: BLE001
        level = error_classifier.classify(e)
        error_classifier.escalate_to_owner(
            level, e, {"phase": "step3_llm_review", "pr_url": pr_url}
        )
        return _fail(
            f"step3_llm_review: {e}",
            level=level,
            elapsed=time.monotonic() - started_at,
        )

    # ---- Step 4：评论密度兜底 + 文案校验 ----
    checklist_normalized = _normalize_checklist(llm_result.get("checklist") or [])
    checklist_after_format, format_warnings = _enforce_blocking_format(
        checklist_normalized
    )
    warnings.extend(format_warnings)

    checklist_after_per_file, per_file_warnings = _enforce_per_file_blocking_cap(
        checklist_after_format
    )
    warnings.extend(per_file_warnings)

    checklist_final, density_warnings = _enforce_pr_comment_cap(
        checklist_after_per_file
    )
    warnings.extend(density_warnings)

    blocking_count = sum(1 for it in checklist_final if it["status"] == "BLOCKING")
    non_blocking_count = sum(
        1 for it in checklist_final if it["status"] == "NON-BLOCKING"
    )
    comments_total = blocking_count + non_blocking_count
    overall_summary = llm_result.get("overall_summary") or ""

    # ---- Step 5a：写 CodeReview 表 ----
    code_review_id: Optional[str] = None
    review_write_error: Optional[str] = None
    # 没有 project_id 也写一行（用占位 'no-project-id'），避免 KR 度量丢失
    review_project_id = project_id or "no-project-id"
    try:
        review_row = adr_storage.create_review(
            project_id=review_project_id,
            pr_url=pr_url,
            commit_sha=None,  # Phase 1 不抠 sha；Phase 2 可从 gh pr view --json 拉
            checklist=checklist_final,
            blocker_count=blocking_count,
            suggestion_count=non_blocking_count,
            appeal_status="none",
            reviewer="AICTO",
        )
        code_review_id = review_row.get("id") if review_row else None
    except Exception as e:  # noqa: BLE001
        review_write_error = f"{type(e).__name__}: {e}"
        warnings.append(f"CodeReview 表写入失败：{review_write_error}（KR 度量可能丢失）")

    # ---- Step 5b：飞书 BLOCKING 卡片（仅当 blocking_count > 0） ----
    appeal_card_message_id: Optional[str] = None
    appeal_card_error: Optional[str] = None
    appeal_card: Optional[Dict[str, Any]] = None
    if blocking_count > 0:
        appeal_card = build_appeal_card(
            pr_url=pr_url,
            pr_number=pr_meta.get("number") or "",
            pr_title=pr_title or "",
            checklist=checklist_final,
            blocking_count=blocking_count,
            code_review_id=code_review_id,
        )
        target_chat_id = (
            os.environ.get("AICTO_FEISHU_CHAT_ID", "").strip()
            or os.environ.get("AICTO_PM_FEISHU_CHAT_ID", "").strip()
        )
        if not target_chat_id:
            appeal_card_error = "AICTO_FEISHU_CHAT_ID env not set; appeal card not sent"
            warnings.append(appeal_card_error)
        else:
            try:
                send_result = feishu_api.send_card_message(
                    target_chat_id, appeal_card
                )
                # send_card_message 返回的是 data 部分（dict）；message_id 在 data.message_id
                if isinstance(send_result, dict):
                    msg = send_result.get("message_id") or (
                        (send_result.get("data") or {}).get("message_id")
                    )
                    appeal_card_message_id = msg
            except Exception as e:  # noqa: BLE001
                appeal_card_error = f"{type(e).__name__}: {e}"
                warnings.append(
                    f"飞书 BLOCKING 卡片发送失败：{appeal_card_error}（不阻塞主流程）"
                )

    # ---- 返回 ----
    elapsed = time.monotonic() - started_at
    return _success(
        {
            "pr_url": pr_url,
            "pr_number": pr_meta.get("number"),
            "pr_title": pr_title or None,
            "scope": scope_canonical,
            "checklist": checklist_final,
            "blocking_count": blocking_count,
            "non_blocking_count": non_blocking_count,
            "comments_total": comments_total,
            "overall_summary": overall_summary,
            "code_review_id": code_review_id,
            "appeal_card_message_id": appeal_card_message_id,
            "appeal_card_error": appeal_card_error,
            "appeal_card": appeal_card,  # 供调用方人工 inspect / 测试断言
            "tech_plan_id": tech_plan_id,
            "project_id": project_id,
            "review_write_error": review_write_error,
            "warnings": warnings or None,
            "elapsed_seconds": round(elapsed, 2),
        }
    )


# ---------------------------------------------------------------------------
# Step 1: 拉 PR diff
# ---------------------------------------------------------------------------


_PR_URL_REGEX = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)/?",
    re.IGNORECASE,
)


def _parse_pr_url(pr_url: str) -> Dict[str, Optional[str]]:
    """解析 GitHub PR URL → {owner, repo, number}。失败返 {}。"""
    m = _PR_URL_REGEX.match(pr_url.strip())
    if not m:
        return {}
    return {
        "owner": m.group("owner"),
        "repo": m.group("repo"),
        "number": m.group("number"),
    }


def _step1_fetch_pr_diff(pr_url: str) -> Tuple[str, Optional[str]]:
    """用 gh CLI 拉 PR diff + title。

    Returns:
        (diff_text, pr_title)

    Raises:
        _ReviewCodeError(tech): gh CLI 临时失败 / PR 不存在
        _ReviewCodeError(permission): gh CLI 鉴权失败 / 未安装
    """
    def _do_diff() -> str:
        try:
            result = subprocess.run(
                ["gh", "pr", "diff", pr_url],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except FileNotFoundError as e:
            # gh CLI 未安装 — 永久权限级，不要重试
            raise _ReviewCodeError(
                f"gh CLI 未安装或不在 PATH：{e}（请先 `brew install gh && gh auth login`）",
                level=error_classifier.LEVEL_PERMISSION,
            )
        except subprocess.TimeoutExpired as e:
            raise _ReviewCodeError(
                f"gh pr diff 超时：{e}",
                level=error_classifier.LEVEL_TECH,
            )

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            # 鉴权失败 / 找不到 PR → 不可重试
            stderr_lower = stderr.lower()
            if (
                "authentication" in stderr_lower
                or "401" in stderr_lower
                or "403" in stderr_lower
                or "could not resolve" in stderr_lower
                or "not found" in stderr_lower
            ):
                raise _ReviewCodeError(
                    f"gh pr diff 失败（永久错误，不重试）：{stderr or 'unknown'}",
                    level=error_classifier.LEVEL_PERMISSION,
                )
            # 其他错误归 tech，让 retry 重试
            raise _ReviewCodeError(
                f"gh pr diff 失败（returncode={result.returncode}）：{stderr or 'no stderr'}",
                level=error_classifier.LEVEL_TECH,
            )
        return result.stdout or ""

    diff = error_classifier.retry_with_backoff(_do_diff, max_retries=3, base_delay=1.0)

    # 拉 PR title（best-effort，失败不阻塞）
    pr_title: Optional[str] = None
    try:
        title_proc = subprocess.run(
            ["gh", "pr", "view", pr_url, "--json", "title", "-q", ".title"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if title_proc.returncode == 0:
            pr_title = (title_proc.stdout or "").strip() or None
    except Exception:  # noqa: BLE001
        pr_title = None

    return diff, pr_title


def _truncate_pr_diff(diff_full: str) -> Tuple[str, bool]:
    """PR diff 过长时按文件块截断到 PR_DIFF_CHAR_LIMIT。

    简化版：保留前 N 字符 + 提示尾部已省略；若刚好超出几行则不截。
    """
    if not diff_full:
        return ("", False)
    if len(diff_full) <= PR_DIFF_CHAR_LIMIT:
        return (diff_full, False)

    head = diff_full[:PR_DIFF_CHAR_LIMIT]
    # 在最后一个 'diff --git' 之前截，避免半个文件
    last_diff_marker = head.rfind("\ndiff --git ")
    if last_diff_marker > PR_DIFF_CHAR_LIMIT // 2:
        head = head[:last_diff_marker]
    return (
        head + f"\n\n…（diff 过长已截断；原始 {len(diff_full)} 字符，仅含前 {len(head)}）",
        True,
    )


# ---------------------------------------------------------------------------
# Step 2: tech_plan / PRD 上下文
# ---------------------------------------------------------------------------


def _summarize_adrs_for_review(adrs: List[Dict[str, Any]]) -> str:
    """把 ADR list 浓缩成行列表（送 LLM 审查 architecture 维度用）。"""
    if not adrs:
        return "（无 ADR 历史）"
    lines: List[str] = ["项目历史 ADR（架构决策记录，按编号升序）："]
    for adr in adrs[:20]:
        title = (adr.get("title") or "").replace("\n", " ")
        decision = (adr.get("decision") or "").replace("\n", " ")
        if len(decision) > 200:
            decision = decision[:200] + "..."
        lines.append(
            f"  - {adr.get('display_number') or 'ADR-?'}: {title} | "
            f"status={adr.get('status')} | decision={decision}"
        )
    if len(adrs) > 20:
        lines.append(f"  - …（共 {len(adrs)} 条，仅显示前 20）")
    return "\n".join(lines)


def _try_load_prd_context(project_id: str) -> str:
    """尝试用 project_id 拉 PRD + UserStories 摘要（best-effort）。

    如果 project_id 不是真实 PM Project.id（如直传的 ad-hoc），返回空提示。
    """
    if not project_id:
        return "（无 project_id）"
    try:
        raw = pm_db_api.get_pm_context_for_tech_plan({"project_id": project_id})
        payload = json.loads(raw)
        if "error" in payload:
            return f"（PM context 拉取失败：{payload.get('error')}）"
        prd = payload.get("prd") or {}
        stories = payload.get("user_stories") or []
        lines: List[str] = []
        title = prd.get("title")
        if title:
            lines.append(f"PRD 标题：{title}")
        if stories:
            lines.append("UserStories（验收标准摘要）：")
            for s in stories[:10]:
                ac = (s.get("acceptanceCriteria") or "").replace("\n", " ")
                if len(ac) > 200:
                    ac = ac[:200] + "..."
                lines.append(
                    f"  - asA={s.get('asA')} iWant={s.get('iWant')} "
                    f"AC={ac or '（未填）'}"
                )
        return "\n".join(lines) if lines else "（PM context 为空）"
    except Exception as e:  # noqa: BLE001
        return f"（PM context 异常：{e}）"


# ---------------------------------------------------------------------------
# Step 3: LLM 10 项审查
# ---------------------------------------------------------------------------


def _normalize_scope(scope_raw: str) -> Optional[str]:
    """归一化 scope 入参为权威维度名 / "all"；非法返 None。"""
    if scope_raw is None:
        return "all"
    key = str(scope_raw).strip().lower()
    if not key:
        return "all"
    return SCOPE_ALIASES.get(key)


def _load_prompt_template() -> str:
    if not PROMPT_PATH.exists():
        raise _ReviewCodeError(
            f"prompt template missing: {PROMPT_PATH}",
            level=error_classifier.LEVEL_UNKNOWN,
        )
    return PROMPT_PATH.read_text(encoding="utf-8")


def _build_messages(
    *,
    pr_url: str,
    pr_number: str,
    pr_title: str,
    pr_diff: str,
    tech_plan_context: str,
    prd_context: str,
    scope: str,
) -> List[Dict[str, Any]]:
    template = _load_prompt_template()
    rendered = (
        template.replace("{{PR_URL}}", pr_url)
        .replace("{{PR_NUMBER}}", pr_number or "?")
        .replace("{{PR_TITLE}}", pr_title or "（未拉到 title）")
        .replace("{{PR_DIFF}}", pr_diff or "（PR diff 为空）")
        .replace("{{TECH_PLAN_CONTEXT}}", tech_plan_context or "（无）")
        .replace("{{PRD_CONTEXT}}", prd_context or "（无）")
        .replace("{{SCOPE}}", scope or "all")
    )
    return [
        {
            "role": "system",
            "content": (
                "你是程小远，云智 OPC 团队的 AI CTO。严格按用户消息中的契约输出 JSON。"
                "不要任何 markdown 围栏。不要任何解释性前后缀。"
            ),
        },
        {"role": "user", "content": rendered},
    ]


def _step3_llm_review(
    *,
    pr_url: str,
    pr_number: str,
    pr_title: str,
    pr_diff: str,
    tech_plan_context: str,
    prd_context: str,
    scope: str,
) -> Dict[str, Any]:
    """发给 LLM → 解 JSON → 返回 dict（带 retry 包裹）。

    复用 design_tech_plan._invoke_llm / _extract_content / _parse_llm_json。
    """
    messages = _build_messages(
        pr_url=pr_url,
        pr_number=pr_number,
        pr_title=pr_title,
        pr_diff=pr_diff,
        tech_plan_context=tech_plan_context,
        prd_context=prd_context,
        scope=scope,
    )

    def _do_call() -> Dict[str, Any]:
        response = design_tech_plan._invoke_llm(messages)
        content = design_tech_plan._extract_content(response)
        try:
            return design_tech_plan._parse_llm_json(content)
        except design_tech_plan._DesignTechPlanError as e:
            # 把 design_tech_plan 的异常重新包成本模块的异常（保留 .level）
            raise _ReviewCodeError(str(e), level=e.level)

    return error_classifier.retry_with_backoff(_do_call, max_retries=3, base_delay=2.0)


# ---------------------------------------------------------------------------
# Step 4: 评论密度兜底 + 文案校验
# ---------------------------------------------------------------------------


def _normalize_checklist(raw: List[Any]) -> List[Dict[str, Any]]:
    """LLM 输出的 checklist 兜底：补齐 10 项 / 修非法 status / 截断 comment。

    顺序固定为 CHECKLIST_ITEMS 顺序（item=1..10）。
    """
    by_item: Dict[int, Dict[str, Any]] = {}
    by_name: Dict[str, Dict[str, Any]] = {}

    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        item_no = entry.get("item")
        name = entry.get("name") or ""
        if isinstance(item_no, int) and 1 <= item_no <= 10:
            by_item[item_no] = entry
        elif isinstance(name, str) and name.strip():
            by_name[name.strip()] = entry

    out: List[Dict[str, Any]] = []
    for item_no, name in CHECKLIST_ITEMS:
        entry = by_item.get(item_no) or by_name.get(name) or {}
        status = str(entry.get("status") or "").strip().upper()
        if status not in ALLOWED_STATUS:
            # 非法 status 兜底为 PASS（保守）
            status = "PASS"
        comment = entry.get("comment") or ""
        if not isinstance(comment, str):
            comment = str(comment)
        # comment 过长截断
        if len(comment) > 1500:
            comment = comment[:1500] + "...（截断）"
        out.append(
            {
                "item": item_no,
                "name": name,
                "status": status,
                "comment": comment.strip(),
            }
        )
    return out


def _has_blocking_format(comment: str) -> bool:
    """检测 BLOCKING 文案是否含 "X→Y 因 Z" 关键词组合。

    放宽匹配：含「改成/换成/替换/改为」之一 + 含「因/因为/由于」之一 即认为合规。
    """
    if not comment:
        return False
    has_ab = any(kw in comment for kw in _BLOCKING_FORMAT_KEYWORDS_AB)
    has_reason = any(kw in comment for kw in _BLOCKING_FORMAT_KEYWORDS_REASON)
    return has_ab and has_reason


def _enforce_blocking_format(
    checklist: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """BLOCKING 文案不合规 → reformat（自动加"把 ... 改成 ... 因为 ..."骨架）。

    R-FN-4.5：BLOCKING 必须含 "把 X 改成 Y 因为 Z" 格式。
    实现策略：检测不合规的 BLOCKING → 把原 comment 包进模板 + 加 warning。
    """
    out: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for item in checklist:
        if item["status"] == "BLOCKING" and not _has_blocking_format(item["comment"]):
            original = item["comment"] or "（无具体描述）"
            reformatted = (
                f"[文案需重写] 程小远未给出"
                f"\"把 X 改成 Y 因为 Z\"格式的明确指令；原文：{original} "
                f"— 建议把当前实现改成符合规约的实现因为 BLOCKING 必须给出可执行修复方案"
            )
            new_item = dict(item)
            new_item["comment"] = reformatted
            new_item["format_warning"] = True
            out.append(new_item)
            warnings.append(
                f"item {item['item']} ({item['name']}) BLOCKING 文案不合规，已 reformat"
            )
        else:
            out.append(item)
    return out, warnings


def _extract_files_from_comment(comment: str) -> List[str]:
    """从 BLOCKING comment 里 grep 出涉及的文件路径（best-effort）。

    匹配常见模式：a/path/to/file.py 或 path/to/file.py 或 file.py:line
    用于"单文件 ≤ 2 BLOCKING"统计 — 若无法识别则归并到伪文件 "<unknown>"。
    """
    if not comment:
        return []
    # 简单正则：匹配 path/to/file.ext (.py/.ts/.tsx/.js/.go/.rs/.md/.yml/.json/.sh ...)
    file_pattern = re.compile(
        r"(?:^|[\s\(\[\"'`])"
        r"((?:[a-zA-Z0-9_\-./]+/)+[a-zA-Z0-9_\-]+\.[a-zA-Z]{1,5})"
        r"(?:[:\s\)\]\"'`]|$)"
    )
    matches = file_pattern.findall(comment)
    return list(set(matches)) if matches else []


def _enforce_per_file_blocking_cap(
    checklist: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """单文件 BLOCKING ≤ 2：超出转 NON-BLOCKING + 聚合 refactor 提示。

    PRD §五·能力 4：单文件 ≤ 2 BLOCKING（超出建议整体 refactor）。

    策略：
      - 统计每个文件出现在多少个 BLOCKING comment 里
      - 若某文件 BLOCKING 数 > 2，把第 3 起的 BLOCKING 转为 NON-BLOCKING + comment 加聚合提示
      - 超过 2 BLOCKING 的文件附在 warning 里供调用方知晓
    """
    file_blocking_count: Dict[str, int] = {}
    out: List[Dict[str, Any]] = []
    warnings: List[str] = []
    files_over_cap: set = set()

    # 第一遍：构建当前 BLOCKING 项的 file 列表
    blocking_indices: List[int] = []
    blocking_files_per_item: List[List[str]] = []
    for idx, item in enumerate(checklist):
        if item["status"] == "BLOCKING":
            blocking_indices.append(idx)
            blocking_files_per_item.append(_extract_files_from_comment(item["comment"]))
        else:
            blocking_files_per_item.append([])

    # 第二遍：累计计数 + 标记需降级的 BLOCKING
    indices_to_demote: set = set()
    # 按 checklist 顺序累计（item 1 → 10）
    for idx in blocking_indices:
        files = blocking_files_per_item[idx]
        if not files:
            continue
        # 任一文件超过 cap → 该 BLOCKING 降级
        for f in files:
            file_blocking_count[f] = file_blocking_count.get(f, 0) + 1
            if file_blocking_count[f] > MAX_BLOCKING_PER_FILE:
                indices_to_demote.add(idx)
                files_over_cap.add(f)

    for idx, item in enumerate(checklist):
        if idx in indices_to_demote:
            new_item = dict(item)
            new_item["status"] = "NON-BLOCKING"
            files_in_comment = blocking_files_per_item[idx]
            file_repr = ", ".join(sorted(files_in_comment)) or "（多处）"
            new_item["comment"] = (
                f"[聚合：见整体 refactor 建议] 文件 {file_repr} 出现 "
                f"> {MAX_BLOCKING_PER_FILE} 个 BLOCKING，"
                f"建议整体 refactor 后重审。原 BLOCKING 文案：{item['comment']}"
            )
            new_item["aggregated_due_to_per_file_cap"] = True
            out.append(new_item)
        else:
            out.append(item)

    if files_over_cap:
        warnings.append(
            f"以下文件 BLOCKING 数 > {MAX_BLOCKING_PER_FILE}，"
            f"超出部分已聚合为整体 refactor 建议：{sorted(files_over_cap)}"
        )

    return out, warnings


def _enforce_pr_comment_cap(
    checklist: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """单 PR 评论 ≤ 5（BLOCKING + NON-BLOCKING 总数）：超出按 severity 排序，截掉低 severity。

    实现策略：
      - 找出所有 status != PASS 的项（已是评论）
      - 按 severity 排序（BLOCKING > NON-BLOCKING）
      - 保留 top 5；其余转 PASS + comment 加聚合提示
      - 维度顺序保留（不打乱 item 1..10 顺序）
    """
    comment_indices: List[int] = []
    for idx, item in enumerate(checklist):
        if item["status"] in ("BLOCKING", "NON-BLOCKING"):
            comment_indices.append(idx)

    if len(comment_indices) <= MAX_COMMENTS_PER_PR:
        return list(checklist), []

    # 按 (severity 降序, item 升序) 排序，挑前 N
    ranked = sorted(
        comment_indices,
        key=lambda i: (-_STATUS_SEVERITY[checklist[i]["status"]], checklist[i]["item"]),
    )
    keep_indices = set(ranked[:MAX_COMMENTS_PER_PR])
    drop_indices = set(ranked[MAX_COMMENTS_PER_PR:])

    out: List[Dict[str, Any]] = []
    for idx, item in enumerate(checklist):
        if idx in drop_indices:
            new_item = dict(item)
            new_item["status"] = "PASS"
            new_item["comment"] = (
                f"[聚合：见整体 refactor 建议] 评论密度截断（单 PR ≤ "
                f"{MAX_COMMENTS_PER_PR}）— 原 status={item['status']}，原 comment："
                f"{item['comment']}"
            )
            new_item["aggregated_due_to_pr_cap"] = True
            out.append(new_item)
        else:
            out.append(item)

    warnings = [
        f"单 PR 评论 > {MAX_COMMENTS_PER_PR}，按 severity 排序保留 top "
        f"{MAX_COMMENTS_PER_PR}，其余 {len(drop_indices)} 条已转 PASS + 聚合提示"
    ]
    return out, warnings


# ---------------------------------------------------------------------------
# 飞书 Appeal 卡片
# ---------------------------------------------------------------------------


def build_appeal_card(
    *,
    pr_url: str,
    pr_number: str,
    pr_title: str,
    checklist: List[Dict[str, Any]],
    blocking_count: int,
    code_review_id: Optional[str],
) -> Dict[str, Any]:
    """构造 BLOCKING Appeal 飞书卡片（4 字段 + 3 操作按钮）。

    PRD §五·能力 4 ASCII mock：
      字段：PR 编号 / 标题 / BLOCKING 内容（前 3 条）/ 修复要求
      按钮：[军团接受 BLOCKING] / [军团 appeal] / [@骏飞仲裁]

    每个 button.value 是 json.dumps({action, code_review_id, pr_url, ...})，
    供未来飞书卡片回调机制（Phase 2）解析使用。
    """
    blockings = [it for it in checklist if it["status"] == "BLOCKING"]
    # 取前 3 条详细列出，避免卡片超长
    top3 = blockings[:3]
    elements: List[Dict[str, Any]] = []

    elements.append(
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**PR #{pr_number}**：{pr_title or '（未拉到 title）'}\n"
                f"链接：[{pr_url}]({pr_url})\n"
                f"**BLOCKING 数：{blocking_count}**",
            },
        }
    )
    elements.append({"tag": "hr"})

    blocking_lines: List[str] = ["**BLOCKING 详情（前 3 条）：**"]
    for i, b in enumerate(top3, 1):
        # 控制单条长度，避免卡片爆 size
        comment = b.get("comment") or ""
        if len(comment) > 300:
            comment = comment[:300] + "..."
        blocking_lines.append(f"{i}. [{b['name']}] {comment}")
    if blocking_count > 3:
        blocking_lines.append(f"…（共 {blocking_count} 条 BLOCKING，仅展示前 3）")
    elements.append(
        {
            "tag": "div",
            "text": {"tag": "lark_md", "content": "\n".join(blocking_lines)},
        }
    )
    elements.append({"tag": "hr"})

    elements.append(
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    "**修复要求**：见上述明确指令（每条 BLOCKING 须含「把 X 改成 Y 因为 Z」格式）。\n"
                    "BLOCKING 硬 gate — 军团必须停 + 修 + 重 PR；如不同意可点 [军团 appeal]。"
                ),
            },
        }
    )

    # 3 按钮
    common_value: Dict[str, Any] = {
        "code_review_id": code_review_id,
        "pr_url": pr_url,
        "pr_number": pr_number,
    }

    elements.append(
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "✅ 军团接受 BLOCKING"},
                    "type": "primary",
                    "value": json.dumps(
                        {**common_value, "action": "accept_blocking"},
                        ensure_ascii=False,
                    ),
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "🔁 军团 appeal"},
                    "type": "default",
                    "value": json.dumps(
                        {**common_value, "action": "appeal"},
                        ensure_ascii=False,
                    ),
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "🚨 @骏飞仲裁"},
                    "type": "danger",
                    "value": json.dumps(
                        {**common_value, "action": "escalate_to_owner"},
                        ensure_ascii=False,
                    ),
                },
            ],
        }
    )

    card: Dict[str, Any] = {
        "config": {"wide_screen_mode": True, "enable_forward": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"⚠️ BLOCKING — PR #{pr_number}",
            },
            "template": "red",
        },
        "elements": elements,
    }
    return card


# ---------------------------------------------------------------------------
# Appeal 协议（内部分支；Phase 1 提供同步处理函数，Phase 2 接飞书卡片回调）
# ---------------------------------------------------------------------------


def appeal_handler(args: Dict[str, Any], **kwargs) -> str:
    """处理军团对某 BLOCKING 的 appeal（顶层工具，但不计入 16 工具清单）。

    输入：
      code_review_id (str, 必填) — review_code 输出的 CodeReview.id
      appeal_reason (str, 必填) — 军团给出的 appeal 理由
      appealer (str, 可选) — 军团名（如 "L1-麒麟军团"）

    处理：
      1. 读 CodeReview 行，校验存在
      2. LLM 评估 appeal 合理性（retract / maintain）
      3. retract：UPDATE CodeReview SET appeal_status='retracted'
      4. maintain：UPDATE appeal_status='maintained' + 升级骏飞（R-OPEN-3 默认 1 次即升级）

    返回：
      {"success": True, "verdict": "retracted|maintained", "reasoning": "...",
       "code_review_id": "...", "elapsed_seconds": ..., "warnings": [...]}
    """
    started_at = time.monotonic()
    warnings: List[str] = []

    code_review_id = args.get("code_review_id")
    appeal_reason = args.get("appeal_reason")
    appealer = args.get("appealer") or "未指定军团"

    if not code_review_id or not isinstance(code_review_id, str):
        return _fail(
            "code_review_id is required (string)",
            level=error_classifier.LEVEL_INTENT,
            elapsed=time.monotonic() - started_at,
        )
    if not appeal_reason or not isinstance(appeal_reason, str):
        return _fail(
            "appeal_reason is required (string)",
            level=error_classifier.LEVEL_INTENT,
            elapsed=time.monotonic() - started_at,
        )

    # 读 CodeReview 行（直接 sqlite，不写 adr_storage 新方法）
    review_row = _fetch_code_review(code_review_id)
    if review_row is None:
        return _fail(
            f"CodeReview not found: {code_review_id}",
            level=error_classifier.LEVEL_INTENT,
            elapsed=time.monotonic() - started_at,
        )
    checklist = review_row.get("checklist") or []
    blockings = [it for it in checklist if (it.get("status") == "BLOCKING")]

    # LLM 评估 appeal 合理性
    try:
        verdict, reasoning = _llm_assess_appeal(
            checklist=checklist,
            blockings=blockings,
            appeal_reason=appeal_reason,
            appealer=appealer,
            pr_url=review_row.get("pr_url") or "",
        )
    except _ReviewCodeError as e:
        # 评估失败 → unknown 升级，保守维持原 BLOCKING
        error_classifier.escalate_to_owner(
            error_classifier.LEVEL_UNKNOWN,
            e,
            {"phase": "llm_assess_appeal", "code_review_id": code_review_id},
        )
        return _fail(
            f"appeal LLM 评估失败：{e}（已升级骏飞，请人工裁决）",
            level=error_classifier.LEVEL_UNKNOWN,
            elapsed=time.monotonic() - started_at,
        )
    except Exception as e:  # noqa: BLE001
        level = error_classifier.classify(e)
        error_classifier.escalate_to_owner(
            level, e, {"phase": "llm_assess_appeal", "code_review_id": code_review_id}
        )
        return _fail(
            f"appeal LLM 评估失败：{e}",
            level=level,
            elapsed=time.monotonic() - started_at,
        )

    # 写 appeal_status
    new_status = "retracted" if verdict == "retracted" else "maintained"
    try:
        adr_storage.update_appeal_status(code_review_id, new_status)
    except Exception as e:  # noqa: BLE001
        warnings.append(f"appeal_status 更新失败：{e}")

    # maintained → 升级骏飞（R-OPEN-3：默认 1 次即升级）
    escalation_result: Optional[Dict[str, Any]] = None
    if new_status == "maintained":
        try:
            escalation_result = error_classifier.escalate_to_owner(
                error_classifier.LEVEL_PERMISSION,  # 维度：CTO/军团决策权冲突 → 升级人
                f"军团 {appealer} appeal 被维持（pr={review_row.get('pr_url')}），"
                f"请仲裁。LLM 维持理由：{reasoning}",
                {
                    "phase": "appeal_maintained",
                    "code_review_id": code_review_id,
                    "appealer": appealer,
                    "appeal_reason": appeal_reason,
                    "pr_url": review_row.get("pr_url"),
                    "blocking_count": len(blockings),
                },
            )
            # 同步把 appeal_status 升级到 'escalated'
            try:
                adr_storage.update_appeal_status(code_review_id, "escalated")
            except Exception as ex:  # noqa: BLE001
                warnings.append(f"appeal_status 升级到 escalated 失败：{ex}")
        except Exception as e:  # noqa: BLE001
            warnings.append(f"escalate_to_owner 失败：{e}")

    elapsed = time.monotonic() - started_at
    return _success(
        {
            "verdict": new_status,
            "reasoning": reasoning,
            "code_review_id": code_review_id,
            "appealer": appealer,
            "escalation": escalation_result,
            "warnings": warnings or None,
            "elapsed_seconds": round(elapsed, 2),
        }
    )


def _fetch_code_review(code_review_id: str) -> Optional[Dict[str, Any]]:
    """直接从 CodeReview 表拉一行（adr_storage 没暴露 get_review，这里直查）。"""
    import sqlite3 as _sqlite

    try:
        conn = _sqlite.connect(adr_storage.PRODMIND_DB_PATH)
        conn.row_factory = _sqlite.Row
        try:
            row = conn.execute(
                'SELECT * FROM "CodeReview" WHERE "id" = ?', (code_review_id,)
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            # hydrate checklist_json
            raw = d.get("checklist_json")
            if raw:
                try:
                    d["checklist"] = json.loads(raw)
                except (TypeError, ValueError):
                    d["checklist"] = None
            else:
                d["checklist"] = None
            return d
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return None


def _llm_assess_appeal(
    *,
    checklist: List[Dict[str, Any]],
    blockings: List[Dict[str, Any]],
    appeal_reason: str,
    appealer: str,
    pr_url: str,
) -> Tuple[str, str]:
    """LLM 评估 appeal 是否合理。返回 (verdict, reasoning)。

    verdict ∈ {retracted, maintained}。
    """
    blocking_lines = "\n".join(
        f"  - [{b.get('name')}] {b.get('comment')}" for b in blockings
    )
    user_msg = (
        f"军团 {appealer} 对你（程小远）刚才给的 BLOCKING 提了 appeal。\n\n"
        f"PR: {pr_url}\n\n"
        f"原 BLOCKING 列表：\n{blocking_lines or '（空）'}\n\n"
        f"军团 appeal 理由：\n{appeal_reason}\n\n"
        "请判断这个 appeal 是否合理：\n"
        "- 如果军团有充分技术理由 → verdict=retracted（你收回 BLOCKING）\n"
        "- 如果军团理由不成立 → verdict=maintained（维持 BLOCKING，会升级骏飞仲裁）\n\n"
        "严格输出 JSON（不要 markdown 围栏，不要解释前后缀）：\n"
        '{"verdict": "retracted|maintained", "reasoning": "≤200字理由"}'
    )
    messages = [
        {
            "role": "system",
            "content": (
                "你是程小远，云智 OPC 团队的 AI CTO。处理军团对 BLOCKING 的 appeal。"
                "保守原则：模糊时维持 BLOCKING（让骏飞仲裁），不轻易收回。"
                "严格输出 JSON。"
            ),
        },
        {"role": "user", "content": user_msg},
    ]

    def _do_call() -> Dict[str, Any]:
        response = design_tech_plan._invoke_llm(messages)
        content = design_tech_plan._extract_content(response)
        try:
            return design_tech_plan._parse_llm_json(content)
        except design_tech_plan._DesignTechPlanError as e:
            raise _ReviewCodeError(str(e), level=e.level)

    result = error_classifier.retry_with_backoff(_do_call, max_retries=3, base_delay=2.0)
    verdict = str(result.get("verdict") or "").strip().lower()
    if verdict not in ("retracted", "maintained"):
        verdict = "maintained"  # 保守兜底
    reasoning = str(result.get("reasoning") or "").strip() or "（无 reasoning）"
    return verdict, reasoning


# ---------------------------------------------------------------------------
# BLOCKING 超时检测接口（供 P1.7 daily_brief 调用）
# ---------------------------------------------------------------------------


def find_stale_blocking_reviews(stale_hours: float = 24.0) -> List[Dict[str, Any]]:
    """扫描 24h 内未处理（appeal_status='none' 且 blocker_count>0）的 CodeReview。

    R-FN-4.6：军团忽略 BLOCKING = 执行纪律违规，自动升级骏飞。
    本函数仅返回候选列表，是否实际升级由 daily_brief 调度。
    """
    import sqlite3 as _sqlite
    from datetime import datetime, timedelta, timezone

    threshold = datetime.now(timezone.utc) - timedelta(hours=stale_hours)
    threshold_iso = threshold.strftime("%Y-%m-%dT%H:%M:%S")

    try:
        conn = _sqlite.connect(adr_storage.PRODMIND_DB_PATH)
        conn.row_factory = _sqlite.Row
        try:
            rows = conn.execute(
                'SELECT * FROM "CodeReview" '
                'WHERE "blocker_count" > 0 '
                '  AND "appeal_status" = ? '
                '  AND "reviewed_at" < ? '
                'ORDER BY "reviewed_at" DESC',
                ("none", threshold_iso),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------------------
# 公共辅助（与 design_tech_plan / breakdown_tasks 风格一致）
# ---------------------------------------------------------------------------


def _success(payload: Dict[str, Any]) -> str:
    return json.dumps({"success": True, **payload}, ensure_ascii=False)


def _fail(message: str, *, level: str, elapsed: float) -> str:
    return json.dumps(
        {
            "error": message,
            "level": level,
            "elapsed_seconds": round(elapsed, 2),
        },
        ensure_ascii=False,
    )


__all__ = [
    "run",
    "appeal_handler",
    "build_appeal_card",
    "find_stale_blocking_reviews",
    "CHECKLIST_ITEMS",
    "ALLOWED_STATUS",
    "MAX_COMMENTS_PER_PR",
    "MAX_BLOCKING_PER_FILE",
    "APPEAL_ESCALATION_THRESHOLD",
]
