"""requirement_metadata_gate.py — AICTO 需求元数据硬门禁。

每一个进入 AICTO 的需求都必须先成为原子级 PRD 元数据：
- 基础元数据：需求 ID、标题、原子对象、验收标准
- 用户对齐：用户原始诉求、AIPM 设计思路、一致性判断、飞书确认记录
- 5W1H：Who / What / Why / When / Where / How
- 增删查改显算传：即使不涉及也必须显式写「无」

门禁失败时不进入技术方案、任务拆解、军团派单，避免 AICTO 基于残缺需求生成
看似完整但不可执行的方案。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple


NONE_MARKERS = {
    "无",
    "不涉及",
    "无需",
    "没有",
    "none",
    "n/a",
    "na",
    "not applicable",
}

UNKNOWN_MARKERS = {
    "待定",
    "待补",
    "todo",
    "tbd",
    "unknown",
    "未知",
    "不清楚",
    "以后再说",
    "<待补>",
    "?",
}

CONFLICT_OR_UNCONFIRMED_MARKERS = {
    "相悖",
    "冲突",
    "不一致",
    "背离",
    "未确认",
    "未探讨",
    "没探讨",
    "未和用户",
    "没有和用户",
    "未与用户",
    "没有与用户",
    "自作主张",
}


ATOMIC_METADATA = [
    {
        "key": "requirement_id",
        "label": "需求ID",
        "aliases": ["需求ID", "需求编号", "ID", "requirement_id", "req_id"],
        "hint": "稳定可追踪编号，例如 REQ-AICTO-001。",
    },
    {
        "key": "requirement_title",
        "label": "需求标题",
        "aliases": ["需求标题", "标题", "title", "requirement_title", "name"],
        "hint": "一句话描述原子需求，不把多个功能塞到同一条。",
    },
    {
        "key": "atomic_object",
        "label": "原子对象",
        "aliases": [
            "原子对象",
            "变更对象",
            "对象",
            "字段",
            "按钮",
            "页面",
            "接口",
            "atomic_object",
            "target",
            "scope",
        ],
        "hint": "明确到字段、按钮、页面、接口、任务或流程节点。",
    },
    {
        "key": "acceptance_criteria",
        "label": "验收标准",
        "aliases": ["验收标准", "验收", "acceptance", "acceptance_criteria", "then"],
        "hint": "可测试的 Given/When/Then 或等价验收条件。",
    },
]


USER_ALIGNMENT_METADATA = [
    {
        "key": "user_original_request",
        "label": "用户原始诉求",
        "aliases": [
            "用户原始诉求",
            "用户原话",
            "用户需求来源",
            "用户需求",
            "老板原话",
            "owner_request",
            "user_original_request",
            "user_requirement_source",
        ],
        "hint": "用户真实表达或可追溯来源，不能用 AIPM 推测替代。",
        "none_allowed": False,
    },
    {
        "key": "aipm_design_intent",
        "label": "AIPM设计思路",
        "aliases": [
            "AIPM设计思路",
            "AIPM设计方向",
            "PM设计思路",
            "产品设计思路",
            "设计依据",
            "aipm_design_intent",
            "design_rationale",
        ],
        "hint": "AIPM 对场景、方案方向、边界的设计解释。",
        "none_allowed": False,
    },
    {
        "key": "user_alignment_verdict",
        "label": "用户一致性判断",
        "aliases": [
            "用户一致性判断",
            "需求一致性",
            "用户对齐",
            "是否符合用户需求",
            "alignment",
            "user_alignment_verdict",
        ],
        "hint": "明确写已与用户诉求一致；如相悖/未确认，必须先让 AIPM 去飞书确认。",
        "none_allowed": False,
        "reject_conflict": True,
    },
    {
        "key": "feishu_user_confirmation",
        "label": "飞书用户确认记录",
        "aliases": [
            "飞书用户确认记录",
            "用户确认记录",
            "飞书确认",
            "确认链接",
            "飞书消息",
            "feishu_user_confirmation",
            "user_confirmation_ref",
        ],
        "hint": "飞书消息链接、会话 ID、文档链接或明确可追溯记录。",
        "none_allowed": False,
    },
]


FIVE_W_ONE_H = [
    {
        "key": "who",
        "label": "Who/谁",
        "aliases": ["who", "谁", "用户", "角色", "使用者", "干系人"],
        "hint": "谁触发、谁受影响、权限角色是什么。",
    },
    {
        "key": "what",
        "label": "What/做什么",
        "aliases": ["what", "做什么", "需求内容", "功能", "动作", "业务动作"],
        "hint": "要改变什么业务能力或系统行为。",
    },
    {
        "key": "why",
        "label": "Why/为什么",
        "aliases": ["why", "为什么", "目的", "价值", "问题", "背景"],
        "hint": "业务价值、问题来源、成功后解决什么。",
    },
    {
        "key": "when",
        "label": "When/何时",
        "aliases": ["when", "何时", "时机", "触发时机", "时间", "优先级", "截止"],
        "hint": "触发条件、使用时机、上线/优先级要求。",
    },
    {
        "key": "where",
        "label": "Where/哪里",
        "aliases": ["where", "哪里", "场景", "入口", "页面位置", "系统位置", "位置"],
        "hint": "发生在哪个产品、页面、模块、入口或系统边界。",
    },
    {
        "key": "how_business",
        "label": "How/业务流程",
        "aliases": ["how", "如何", "业务流程", "用户流程", "操作流程", "使用方式"],
        "hint": "用户/业务如何完成，不写技术实现细节。",
    },
]


CRUD_DISPLAY_COMPUTE_TRANSMIT = [
    {
        "key": "create",
        "label": "增",
        "aliases": ["增", "新增", "创建", "添加", "录入", "create", "add", "insert"],
        "hint": "新增什么数据/对象/状态；不涉及写「无」。",
    },
    {
        "key": "delete",
        "label": "删",
        "aliases": ["删", "删除", "移除", "作废", "delete", "remove"],
        "hint": "删除/撤销/作废什么；不涉及写「无」。",
    },
    {
        "key": "query",
        "label": "查",
        "aliases": ["查", "查询", "读取", "检索", "搜索", "列表", "read", "query", "list"],
        "hint": "谁能查什么、筛选/排序/分页/权限；不涉及写「无」。",
    },
    {
        "key": "update",
        "label": "改",
        "aliases": ["改", "修改", "编辑", "更新", "变更", "update", "edit"],
        "hint": "修改什么字段/状态/配置；不涉及写「无」。",
    },
    {
        "key": "display",
        "label": "显",
        "aliases": ["显", "显示", "展示", "呈现", "可见", "UI", "display", "render", "visibility"],
        "hint": "展示位置、字段文案、空态、错误态、权限可见性；不涉及写「无」。",
    },
    {
        "key": "compute",
        "label": "算",
        "aliases": ["算", "计算", "规则", "校验", "派生", "统计", "排序", "compute", "calculate", "rule"],
        "hint": "计算公式、校验规则、默认值、派生状态；不涉及写「无」。",
    },
    {
        "key": "transmit",
        "label": "传",
        "aliases": [
            "传",
            "传输",
            "传递",
            "接口",
            "同步",
            "事件",
            "消息",
            "集成",
            "api",
            "event",
            "webhook",
            "data_flow",
        ],
        "hint": "接口、事件、消息、上下游系统和数据流；不涉及写「无」。",
    },
]


ALL_DIMENSIONS = (
    ATOMIC_METADATA
    + USER_ALIGNMENT_METADATA
    + FIVE_W_ONE_H
    + CRUD_DISPLAY_COMPUTE_TRANSMIT
)
ATOMIC_METADATA_KEYS = {item["key"] for item in ATOMIC_METADATA}
NO_NONE_ALLOWED_KEYS = {
    item["key"]
    for item in ALL_DIMENSIONS
    if item.get("none_allowed") is False
}
CONFLICT_REJECT_KEYS = {
    item["key"]
    for item in ALL_DIMENSIONS
    if item.get("reject_conflict")
}
USER_ALIGNMENT_KEYS = {item["key"] for item in USER_ALIGNMENT_METADATA}


def run(args: Dict[str, Any], **kwargs) -> str:
    """Hermes tool entry."""
    action = (args.get("action") or "validate").strip()
    if action == "template":
        return json.dumps(_success(build_template(args)), ensure_ascii=False)
    if action != "validate":
        return json.dumps(
            {
                "error": f"unsupported action: {action}",
                "supported_actions": ["validate", "template"],
            },
            ensure_ascii=False,
        )
    return json.dumps(_success(validate(args)), ensure_ascii=False)


def validate(args: Dict[str, Any]) -> Dict[str, Any]:
    """校验 PRD/metadata 是否满足 AICTO 需求入口硬门禁。"""
    prd_markdown = args.get("prd_markdown") or args.get("prd_content") or ""
    metadata = args.get("requirement_metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    structured = _extract_structured_sections(metadata)
    markdown = _extract_markdown_sections(str(prd_markdown))
    resolved: Dict[str, Dict[str, Any]] = {}

    for dimension in ALL_DIMENSIONS:
        key = dimension["key"]
        value, source = _resolve_value(key, structured, markdown)
        status = _classify_value(value)
        if key in ATOMIC_METADATA_KEYS and status == "explicit_none":
            status = "unknown"
        if key in NO_NONE_ALLOWED_KEYS and status == "explicit_none":
            status = "unknown"
        if key in CONFLICT_REJECT_KEYS and status == "provided" and _is_conflict_or_unconfirmed(value or ""):
            status = "conflict_or_unconfirmed"
        resolved[key] = {
            "label": dimension["label"],
            "source": source,
            "value": value,
            "status": status,
            "hint": dimension["hint"],
        }

    missing_sections = [
        item["label"]
        for key, item in resolved.items()
        if item["status"] == "missing"
    ]
    blank_sections = [
        item["label"]
        for key, item in resolved.items()
        if item["status"] in {"blank", "unknown"}
    ]
    conflict_or_unconfirmed_sections = [
        item["label"]
        for key, item in resolved.items()
        if item["status"] == "conflict_or_unconfirmed"
    ]
    explicit_none_sections = [
        item["label"]
        for key, item in resolved.items()
        if item["status"] == "explicit_none"
    ]

    gate_status = (
        "pass"
        if not missing_sections and not blank_sections and not conflict_or_unconfirmed_sections
        else "fail"
    )
    clarification_request = _build_clarification_request(
        missing_sections=missing_sections,
        blank_sections=blank_sections,
        conflict_or_unconfirmed_sections=conflict_or_unconfirmed_sections,
        resolved=resolved,
    )
    requires_user_feishu_confirmation = _requires_user_feishu_confirmation(
        missing_sections=missing_sections,
        blank_sections=blank_sections,
        conflict_or_unconfirmed_sections=conflict_or_unconfirmed_sections,
        resolved=resolved,
    )

    return {
        "gate": "AICTO_REQUIREMENT_METADATA_GATE_V1",
        "gate_status": gate_status,
        "passes": gate_status == "pass",
        "blocking_downstream": gate_status != "pass",
        "metadata_contract": {
            "atomic_prd_required": True,
            "user_alignment_required": True,
            "no_omitted_dimensions": True,
            "explicit_none_required": "不涉及的维度必须写「无」；缺省、空白、待定都不通过。",
            "aipm_user_confirmation_required": (
                "如果 AIPM 设计与用户诉求相悖，或没有和用户探讨过相关需求，"
                "AIPM 必须先在飞书和用户确认需求场景、设计方向/思路/边界。"
            ),
            "applies_to": "所有进入 AICTO 的需求，包括字段、按钮、文案、规则、接口等小改动。",
        },
        "required_atomic_metadata": _dimension_labels(ATOMIC_METADATA),
        "required_user_alignment": _dimension_labels(USER_ALIGNMENT_METADATA),
        "required_5w1h": _dimension_labels(FIVE_W_ONE_H),
        "required_create_delete_query_update_display_compute_transmit": _dimension_labels(
            CRUD_DISPLAY_COMPUTE_TRANSMIT
        ),
        "missing_required_sections": missing_sections,
        "blank_or_unknown_sections": blank_sections,
        "conflict_or_unconfirmed_sections": conflict_or_unconfirmed_sections,
        "explicit_none_sections": explicit_none_sections,
        "requires_aipm_clarification": gate_status != "pass",
        "requires_user_feishu_confirmation": requires_user_feishu_confirmation,
        "aipm_clarification_protocol": _aipm_clarification_protocol(
            requires_user_feishu_confirmation=requires_user_feishu_confirmation,
        ),
        "sections": resolved,
        "clarification_request": clarification_request,
        "best_practice_template": build_template({})["markdown_template"],
    }


def evaluate_prd(
    *,
    prd_markdown: str,
    requirement_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Internal helper for design_tech_plan."""
    return validate(
        {
            "prd_markdown": prd_markdown,
            "requirement_metadata": requirement_metadata or {},
        }
    )


def build_template(args: Dict[str, Any]) -> Dict[str, Any]:
    """返回 AICTO 可接受的原子 PRD 模板。"""
    title = args.get("title") or "原子需求标题"
    req_id = args.get("requirement_id") or "REQ-YYYYMMDD-001"
    markdown = f"""# {title}

需求ID：{req_id}
需求标题：{title}
原子对象：<字段/按钮/页面/接口/任务/流程节点>
验收标准：Given <前置条件> / When <用户动作或系统事件> / Then <可验证结果>

## 用户对齐
用户原始诉求：<用户原话/需求来源，不允许用 AIPM 推测替代>
AIPM设计思路：<AIPM 对场景、设计方向、思路、边界的说明>
用户一致性判断：<已确认与用户诉求一致；如相悖/未确认，不得进入 AICTO>
飞书用户确认记录：<飞书消息链接/会话ID/文档链接>

## 5W1H
Who/谁：<用户角色/系统角色/影响对象>
What/做什么：<本原子需求要改变的业务能力>
Why/为什么：<业务价值/问题来源>
When/何时：<触发时机/优先级/上线要求>
Where/哪里：<产品/页面/模块/入口/系统边界>
How/业务流程：<用户或业务如何完成，不写技术实现>

## 增删查改显算传
增：无
删：无
查：无
改：无
显：无
算：无
传：无
"""
    return {
        "contract": "所有维度必须出现；不涉及写「无」；不能省略。",
        "markdown_template": markdown,
        "structured_template": {
            "requirement_id": req_id,
            "requirement_title": title,
            "atomic_object": "<字段/按钮/页面/接口/任务/流程节点>",
            "acceptance_criteria": "Given ... / When ... / Then ...",
            "user_original_request": "<用户原话/需求来源>",
            "aipm_design_intent": "<AIPM 对场景、设计方向、思路、边界的说明>",
            "user_alignment_verdict": "已确认与用户诉求一致",
            "feishu_user_confirmation": "<飞书消息链接/会话ID/文档链接>",
            "who": "<用户角色/系统角色/影响对象>",
            "what": "<业务动作>",
            "why": "<业务价值>",
            "when": "<触发时机>",
            "where": "<发生位置>",
            "how_business": "<业务流程>",
            "create": "无",
            "delete": "无",
            "query": "无",
            "update": "无",
            "display": "无",
            "compute": "无",
            "transmit": "无",
        },
    }


def _success(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(payload)
    payload.setdefault("success", True)
    return payload


def _dimension_labels(dimensions: Iterable[Dict[str, Any]]) -> List[str]:
    return [d["label"] for d in dimensions]


def _resolve_value(
    key: str,
    structured: Dict[str, str],
    markdown: Dict[str, str],
) -> Tuple[Optional[str], str]:
    if key in structured:
        return structured[key], "requirement_metadata"
    if key in markdown:
        return markdown[key], "prd_markdown"
    return None, "missing"


def _extract_structured_sections(metadata: Dict[str, Any]) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    alias_map = _alias_map()

    def _walk(obj: Any):
        if not isinstance(obj, dict):
            return
        for raw_key, raw_value in obj.items():
            dim = _match_alias(str(raw_key), alias_map)
            if dim:
                sections[dim] = _stringify_value(raw_value)
            if isinstance(raw_value, dict):
                _walk(raw_value)

    _walk(metadata)
    return sections


def _extract_markdown_sections(text: str) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    alias_map = _alias_map()
    current_key: Optional[str] = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        key_part, value_part, has_delimiter = _split_key_value(stripped)
        dim = _match_alias(key_part, alias_map) if key_part else None
        if dim and has_delimiter:
            sections[dim] = value_part.strip()
            current_key = dim
            continue

        heading_dim = _match_alias(stripped, alias_map)
        if heading_dim:
            sections.setdefault(heading_dim, "")
            current_key = heading_dim
            continue

        if current_key and not _looks_like_new_section(stripped, alias_map):
            previous = sections.get(current_key, "")
            sections[current_key] = (previous + "\n" + stripped).strip()

    # 如果 markdown 只有 H1，也把它作为标题兜底，但需求标题字段仍建议显式写。
    if "requirement_title" not in sections:
        title = _first_h1(text)
        if title:
            sections["requirement_title"] = title

    return sections


def _split_key_value(line: str) -> Tuple[str, str, bool]:
    normalized_line = line
    for delimiter in ("：", ":"):
        if delimiter in normalized_line:
            before, after = normalized_line.split(delimiter, 1)
            return _clean_key(before), after, True
    return _clean_key(normalized_line), "", False


def _looks_like_new_section(line: str, alias_map: Dict[str, str]) -> bool:
    key_part, _, has_delimiter = _split_key_value(line)
    return has_delimiter and bool(_match_alias(key_part, alias_map))


def _first_h1(text: str) -> Optional[str]:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped.lstrip("#").strip()
            if title:
                return title
    return None


def _classify_value(value: Optional[str]) -> str:
    if value is None:
        return "missing"
    compact = _compact(value)
    if not compact:
        return "blank"
    if _is_unknown(value):
        return "unknown"
    if _is_explicit_none(value):
        return "explicit_none"
    return "provided"


def _is_explicit_none(value: str) -> bool:
    compact = _compact(value)
    return any(
        compact == marker or compact.startswith(marker)
        for marker in (_compact(m) for m in NONE_MARKERS)
    )


def _is_unknown(value: str) -> bool:
    compact = _compact(value)
    return any(marker in compact for marker in (_compact(m) for m in UNKNOWN_MARKERS))


def _is_conflict_or_unconfirmed(value: str) -> bool:
    compact = _compact(value)
    return any(
        marker in compact
        for marker in (_compact(m) for m in CONFLICT_OR_UNCONFIRMED_MARKERS)
    )


def _compact(value: str) -> str:
    remove_chars = set("，。,.;；:：、`*_#<>\\/-")
    return "".join(
        ch
        for ch in value.strip().lower()
        if not ch.isspace() and ch not in remove_chars
    )


def _clean_key(key: str) -> str:
    cleaned = key.strip()
    cleaned = re.sub(r"^#{1,6}\s*", "", cleaned)
    cleaned = re.sub(r"^[-*+]\s*", "", cleaned)
    cleaned = re.sub(r"^\d+[.)、]\s*", "", cleaned)
    cleaned = cleaned.strip("*`[]()（） \t")
    return cleaned


def _normalize_alias(value: str) -> str:
    return re.sub(r"[\s_\-：:（）()/#*`]+", "", _clean_key(value).lower())


def _alias_map() -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for dimension in ALL_DIMENSIONS:
        mapping[_normalize_alias(dimension["key"])] = dimension["key"]
        mapping[_normalize_alias(dimension["label"])] = dimension["key"]
        for alias in dimension["aliases"]:
            mapping[_normalize_alias(alias)] = dimension["key"]
    return mapping


def _match_alias(raw_key: str, alias_map: Dict[str, str]) -> Optional[str]:
    normalized = _normalize_alias(raw_key)
    if not normalized:
        return None
    if normalized in alias_map:
        return alias_map[normalized]
    for alias, dimension_key in alias_map.items():
        if len(alias) >= 2 and normalized.startswith(alias):
            return dimension_key
    return None


def _stringify_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "\n".join(_stringify_value(item) for item in value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _build_clarification_request(
    *,
    missing_sections: List[str],
    blank_sections: List[str],
    conflict_or_unconfirmed_sections: List[str],
    resolved: Dict[str, Dict[str, Any]],
) -> List[str]:
    requests: List[str] = []
    for label in missing_sections:
        hint = _hint_by_label(label, resolved)
        requests.append(f"请补充「{label}」：{hint} 不涉及也必须写「无」。")
    for label in blank_sections:
        hint = _hint_by_label(label, resolved)
        requests.append(f"「{label}」不能空白/待定：{hint} 不涉及请写「无」。")
    for label in conflict_or_unconfirmed_sections:
        hint = _hint_by_label(label, resolved)
        requests.append(
            f"「{label}」显示与用户诉求相悖或尚未确认：{hint}。"
            "AIPM 必须先在飞书中和用户确认需求场景、设计方向/思路/边界。"
        )
    return requests


def _requires_user_feishu_confirmation(
    *,
    missing_sections: List[str],
    blank_sections: List[str],
    conflict_or_unconfirmed_sections: List[str],
    resolved: Dict[str, Dict[str, Any]],
) -> bool:
    if conflict_or_unconfirmed_sections:
        return True
    bad_labels = set(missing_sections) | set(blank_sections)
    for key in USER_ALIGNMENT_KEYS:
        item = resolved.get(key) or {}
        if item.get("label") in bad_labels:
            return True
    return False


def _aipm_clarification_protocol(
    *,
    requires_user_feishu_confirmation: bool,
) -> Dict[str, Any]:
    required_actions = [
        "AIPM 读取用户原始表达和已有 PRD，不得用产品猜测替代用户事实。",
        "AIPM 补齐原子 PRD 元数据、5W1H、增删查改显算传。",
        "AIPM 更新 PRD 后重新提交 AICTO；AICTO 门禁通过前不进入技术方案或军团派发。",
    ]
    if requires_user_feishu_confirmation:
        required_actions.insert(
            1,
            "AIPM 必须在飞书中和用户确认需求场景、设计方向/思路/边界，并留下可追溯确认记录。",
        )
    return {
        "next_owner": "AIPM",
        "aicto_state": "blocked_waiting_aipm_clarification",
        "aipm_required_actions": required_actions,
        "user_confirmation_questions": [
            "这个需求真实要解决的用户场景是什么？",
            "AIPM 当前设计方向是否符合你的原始诉求？",
            "本次需求的边界是什么，哪些明确不做？",
            "验收时你会看哪些行为、数据、页面或结果？",
        ],
        "aicto_boundary": "AICTO 只阻断、提问、给技术约束；不替 AIPM 改 PRD，不替用户做产品确认。",
    }


def _hint_by_label(label: str, resolved: Dict[str, Dict[str, Any]]) -> str:
    for item in resolved.values():
        if item["label"] == label:
            return item["hint"]
    return "补齐元数据"
