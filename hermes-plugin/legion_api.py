"""legion_api.py — AICTO 军团派单基础设施（P1.1 骨架）

复用 ProdMind 黄金标本（prodmind/hermes-plugin/tools.py:831-995）+ 改 from 字段为 'AICTO-CTO'，
新增 mailbox 协议字段（cto_context / appeal_id / appeal_count / priority）保持向后兼容。

本阶段实现的能力：
- discover_online_commanders()              扫描 directory.json + tmux 找在线指挥官
- send_to_commander(commander_id, payload)  双通道：inbox 强保障 + tmux 通知 best-effort
- _write_inbox_locked(commander_id, msg)    fcntl 锁原子写
- _tmux_alive / _tmux_send_keys             tmux 检测 / 一行通知
- mailbox_protocol_serialize                构造符合 ARCHITECTURE §5.3 协议的消息

不实现（推迟到 P1.4）：
- dispatch_to_legion_balanced 完整版（含负载均衡 / DAG 拓扑 / EngineerProfile 匹配）

路径白名单：所有 fs 操作仅触及 ~/.claude/legion/，符合 CTO-READ-ACCESS-SPEC §二·C 约束。
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ============================================================================
# 常量与异常
# ============================================================================

LEGION_ROOT = Path.home() / ".claude" / "legion"
LEGION_DIRECTORY = LEGION_ROOT / "directory.json"
TMUX_SESSION_PREFIX = "legion-"
SENDER_ID = "AICTO-CTO"

VALID_MSG_TYPES = ("task", "appeal", "appeal_response", "escalation")
VALID_PRIORITIES = ("high", "normal", "low")

# tmux 通知行硬上限（送 keys 用）。超过截断 + "..."，避免 shell 截断 / 转义。
TMUX_NOTIFY_MAX_LEN = 80


class LegionError(Exception):
    """legion_api 顶层异常 — 派单 / 写 inbox / tmux 操作失败时抛出。

    上游捕获后决定降级策略（重试 / 升级 / 飞书通知骏飞），本模块不自决。
    """


# ============================================================================
# 数据结构
# ============================================================================


@dataclass
class Commander:
    """一名在线指挥官的元数据快照。

    通过 discover_online_commanders() 构造；inbox_path 已展开为绝对路径，
    上层无需再拼。
    """

    legion_hash: str        # ~/.claude/legion/<hash>
    legion_project: str     # directory.json.legions[].project
    commander_id: str       # registry.json.teams[].id（如 "L1-麒麟军团"）
    task: str               # registry.json.teams[].task
    started_at: str         # registry.json.teams[].started
    tmux_alive: bool        # 通过 tmux list-sessions 判断
    tmux_session: str       # 实际 session name "legion-<hash>-<commander_id>"
    inbox_path: Path        # ~/.claude/legion/<hash>/team-<cid>/inboxes/<cid>.json

    def to_dict(self) -> Dict[str, Any]:
        return {
            "legion_hash": self.legion_hash,
            "legion_project": self.legion_project,
            "commander_id": self.commander_id,
            "task": self.task,
            "started_at": self.started_at,
            "tmux_alive": self.tmux_alive,
            "tmux_session": self.tmux_session,
            "inbox_path": str(self.inbox_path),
        }


# ============================================================================
# 内部 helpers
# ============================================================================


def _now_iso() -> str:
    """UTC ISO 8601（Z 后缀）— 与 mailbox 协议保留字段对齐。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _msg_id() -> str:
    """msg-<unix_ms> — 单进程内单调递增；与 ProdMind 命名风格保留对齐。"""
    return f"msg-{int(time.time() * 1000)}"


def _live_tmux_sessions() -> Optional[set]:
    """返回当前 tmux 会话名集合；命令失败返回 None。

    None 信号让上层选择"容忍策略"（默认认为 alive=True，避免误判离线导致漏发 inbox）。
    """
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return {line for line in result.stdout.strip().split("\n") if line}


def _inbox_path_for(legion_hash: str, commander_id: str) -> Path:
    """统一计算 inbox 路径 — 与 ProdMind 约定对齐。

    路径形如：~/.claude/legion/<hash>/team-<cid>/inboxes/<cid>.json
    （注意：不是 inbox.jsonl —— 那是军团 bootstrap 自维护的文件；
     ProdMind/AICTO 派单写的是独立的 inboxes/*.json，JSON 列表格式。）
    """
    return (
        LEGION_ROOT
        / legion_hash
        / f"team-{commander_id}"
        / "inboxes"
        / f"{commander_id}.json"
    )


def _resolve_commander(commander_id: str) -> Tuple[str, str, bool]:
    """根据 commander_id 反查 (legion_hash, tmux_session, tmux_alive)。

    扫描 directory.json 所有 legion，匹配规则：legion 目录下含 team-<commander_id>/。
    与 discover_online_commanders 解耦：本函数对离线 commander 也能解析（只要 team 目录存在），
    用于 send_to_commander 给离线指挥官写 inbox（commander 上线后会读到）。

    Raises:
        LegionError: directory.json 不可读 / 0 匹配 / ≥2 匹配。
    """
    try:
        with open(LEGION_DIRECTORY, "r", encoding="utf-8") as f:
            directory = json.load(f)
    except Exception as e:
        raise LegionError(f"读 directory.json 失败：{e}") from e

    matches: List[str] = []
    for legion in directory.get("legions", []):
        legion_hash = legion.get("hash")
        if not legion_hash:
            continue
        team_dir = LEGION_ROOT / legion_hash / f"team-{commander_id}"
        if team_dir.exists():
            matches.append(legion_hash)

    if not matches:
        raise LegionError(
            f"未找到指挥官 {commander_id}（无 legion 目录含 team-{commander_id}）"
        )
    if len(matches) > 1:
        raise LegionError(
            f"指挥官 {commander_id} 在多个 legion 出现：{matches} —— "
            "需明确 legion_hash 消歧"
        )

    legion_hash = matches[0]
    session_name = f"{TMUX_SESSION_PREFIX}{legion_hash}-{commander_id}"
    live = _live_tmux_sessions()
    # tmux 命令失败时容忍：默认 alive=True，避免误判导致漏发通知
    tmux_alive = (session_name in live) if live is not None else True
    return legion_hash, session_name, tmux_alive


# ============================================================================
# 发现：discover_online_commanders
# ============================================================================


def discover_online_commanders() -> List[Commander]:
    """扫描所有 legion 找在线指挥官。

    步骤：
      1. 读 ~/.claude/legion/directory.json 列出所有 legion
      2. 对每个 legion 读其 registry.json，过滤 status='commanding' AND role='commander'
      3. 与 tmux list-sessions 比对得 tmux_alive

    Returns:
        按 (tmux_alive 优先, started_at 降序) 排列的 Commander 列表。
        directory.json 缺失或解析失败 → []；tmux 命令失败 → tmux_alive 默认 True。

    Raises:
        无 — 所有路径错误吃掉返回 []，给上游一个稳定信号。
    """
    try:
        with open(LEGION_DIRECTORY, "r", encoding="utf-8") as f:
            directory = json.load(f)
    except Exception:
        return []

    legions = directory.get("legions", [])
    if not legions:
        return []

    live = _live_tmux_sessions()
    tmux_lookup_ok = live is not None

    commanders: List[Commander] = []
    for legion in legions:
        legion_hash = legion.get("hash")
        if not legion_hash:
            continue
        registry_path = LEGION_ROOT / legion_hash / "registry.json"
        try:
            with open(registry_path, "r", encoding="utf-8") as f:
                registry = json.load(f)
        except Exception:
            continue

        for team in registry.get("teams", []):
            if team.get("status") != "commanding":
                continue
            if team.get("role") != "commander":
                continue
            cid = team.get("id", "")
            if not cid:
                continue
            session_name = f"{TMUX_SESSION_PREFIX}{legion_hash}-{cid}"
            tmux_alive = (
                (session_name in live) if tmux_lookup_ok else True
            )
            commanders.append(
                Commander(
                    legion_hash=legion_hash,
                    legion_project=legion.get("project", ""),
                    commander_id=cid,
                    task=team.get("task", ""),
                    started_at=team.get("started", ""),
                    tmux_alive=tmux_alive,
                    tmux_session=session_name,
                    inbox_path=_inbox_path_for(legion_hash, cid),
                )
            )

    commanders.sort(
        key=lambda c: (c.tmux_alive, c.started_at),
        reverse=True,
    )
    return commanders


# ============================================================================
# 协议：mailbox 序列化（ARCHITECTURE §5.3）
# ============================================================================


def mailbox_protocol_serialize(
    payload: str,
    msg_type: str = "task",
    *,
    to: str = "",
    summary: str = "",
    cto_context: Optional[Dict[str, Any]] = None,
    appeal_id: Optional[str] = None,
    appeal_count: Optional[int] = None,
    priority: Optional[str] = None,
) -> Dict[str, Any]:
    """构造符合 ARCHITECTURE §5.3 的消息字典。

    保留字段（不动现有 schema，向后兼容老 commander）：
      id / from / to / type / payload / timestamp / read / summary

    新增字段（仅在传值时写入，老 commander 忽略）：
      cto_context / appeal_id / appeal_count / priority

    Args:
        payload: 派单正文（明文文本）。可能很长，上层确保走 inbox 不走 tmux。
        msg_type: task / appeal / appeal_response / escalation。
        to: 目标 commander_id（写入 to 字段）。
        summary: ≤一行简介，缺省时拼 "AICTO 派发: <to>"。
        cto_context: 派单时附加 {tech_plan_id, adr_links, feishu_doc_url}。
        appeal_id / appeal_count: appeal 类型消息上下文。
        priority: high / normal / low。

    Raises:
        LegionError: msg_type 或 priority 非法。
    """
    if msg_type not in VALID_MSG_TYPES:
        raise LegionError(
            f"非法 msg_type={msg_type!r}（合法值：{VALID_MSG_TYPES}）"
        )
    if priority is not None and priority not in VALID_PRIORITIES:
        raise LegionError(
            f"非法 priority={priority!r}（合法值：{VALID_PRIORITIES}）"
        )

    msg: Dict[str, Any] = {
        "id": _msg_id(),
        "from": SENDER_ID,
        "to": to,
        "type": msg_type,
        "payload": payload,
        "timestamp": _now_iso(),
        "read": False,
        "summary": summary or f"AICTO 派发: {to}",
    }

    # 新增字段：仅在传值时写入（老 commander 不存在这些 key 也不会报错）
    if cto_context is not None:
        msg["cto_context"] = cto_context
    if appeal_id is not None:
        msg["appeal_id"] = appeal_id
    if appeal_count is not None:
        msg["appeal_count"] = appeal_count
    if priority is not None:
        msg["priority"] = priority

    return msg


# ============================================================================
# inbox 写入：fcntl LOCK_EX 排他锁
# ============================================================================


def _write_inbox_to_path(inbox_file: Path, message: Dict[str, Any]) -> Path:
    """带 fcntl.LOCK_EX 排他锁的 inbox.json 追加写入（原子操作）。

    锁文件独立于 inbox json（inbox + ".lock"），避免 inbox 文件本身被锁污染；
    finally 块确保解锁；inbox 不存在或 JSON 解析失败时初始化为 []。

    Args:
        inbox_file: 完整 inbox 路径，本函数负责 mkdir 父目录。
        message: 已通过 mailbox_protocol_serialize 构造的消息字典。

    Returns:
        实际写入的 inbox 路径（与传入一致）。
    """
    inbox_file = Path(inbox_file)
    inbox_dir = inbox_file.parent
    inbox_dir.mkdir(parents=True, exist_ok=True)
    lock_file = inbox_file.with_suffix(inbox_file.suffix + ".lock")

    with open(lock_file, "w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            try:
                with open(inbox_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                if not isinstance(existing, list):
                    existing = []
            except Exception:
                # 不存在 / 损坏 / 非 JSON list → 初始化为空列表
                existing = []
            existing.append(message)
            with open(inbox_file, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    return inbox_file


def _write_inbox_locked(commander_id: str, message: Dict[str, Any]) -> Path:
    """fcntl 锁写入 commander 的 inbox.json（高层入口，含路径解析）。

    路径：~/.claude/legion/<hash>/team-<commander_id>/inboxes/<commander_id>.json
    其中 <hash> 通过 _resolve_commander 反查 directory.json 确定。

    Raises:
        LegionError: commander_id 0/≥2 匹配，或写入 IO 失败。
    """
    legion_hash, _session, _alive = _resolve_commander(commander_id)
    inbox_file = _inbox_path_for(legion_hash, commander_id)
    try:
        return _write_inbox_to_path(inbox_file, message)
    except Exception as e:
        raise LegionError(
            f"写入 inbox 失败 ({inbox_file}): {e}"
        ) from e


# ============================================================================
# tmux 操作（仅用于"通知行"，不发派单内容）
# ============================================================================


def _tmux_alive(commander: Commander) -> bool:
    """检测目标 commander 的 tmux 会话是否存在。

    tmux 命令失败时回退到 commander 自身已记录的 tmux_alive（避免双重 spawn）。
    """
    live = _live_tmux_sessions()
    if live is None:
        return commander.tmux_alive
    return commander.tmux_session in live


def _tmux_send_keys(commander: Commander, text: str) -> None:
    """对 commander session 发一行通知（仅通知，不发 payload 正文）。

    text 长度上限 TMUX_NOTIFY_MAX_LEN（80）字符；超出截断 + "..."。
    任何 send-keys 调用失败抛 LegionError，由上游决定如何降级。
    """
    if not text:
        return
    if len(text) > TMUX_NOTIFY_MAX_LEN:
        text = text[: TMUX_NOTIFY_MAX_LEN - 3] + "..."
    try:
        result = subprocess.run(
            [
                "tmux",
                "send-keys",
                "-t",
                commander.tmux_session,
                text,
                "Enter",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as e:
        raise LegionError(f"tmux send-keys 异常：{e}") from e
    if result.returncode != 0:
        raise LegionError(
            f"tmux send-keys 失败 (rc={result.returncode}) "
            f"stderr={result.stderr.strip()}"
        )


# ============================================================================
# 双通道派发：send_to_commander
# ============================================================================


def send_to_commander(
    commander_id: str,
    payload: str,
    msg_type: str = "task",
    *,
    summary: str = "",
    cto_context: Optional[Dict[str, Any]] = None,
    appeal_id: Optional[str] = None,
    appeal_count: Optional[int] = None,
    priority: Optional[str] = None,
) -> Dict[str, Any]:
    """双通道派发：inbox 强保障 + tmux 通知 best-effort。

    流程：
      1. _resolve_commander 反查 (legion_hash, tmux_session, tmux_alive)
      2. mailbox_protocol_serialize 构造消息
      3. _write_inbox_to_path 原子写 inbox（失败抛 LegionError）
      4. 若 tmux 在线，_tmux_send_keys 发一行通知（"@<cid> AICTO 派任务，inbox/<id> 查看"）
         tmux 通知失败不抛（best-effort），返回 tmux_notified=False。

    纪律：
      - payload 走 inbox（可能很长），tmux 只发通知（≤80 字符）—— 团长强约束。
      - 离线 commander：仍写 inbox，commander 上线后读到。

    Returns:
        {
          "message_id": "msg-...",
          "inbox_path": "/abs/path/.../inboxes/<cid>.json",
          "tmux_session": "legion-<hash>-<cid>",
          "tmux_notified": True|False,
        }

    Raises:
        LegionError: commander 解析失败 / inbox 写入失败 / msg_type 非法。
    """
    legion_hash, tmux_session, tmux_is_alive = _resolve_commander(commander_id)

    message = mailbox_protocol_serialize(
        payload=payload,
        msg_type=msg_type,
        to=commander_id,
        summary=summary,
        cto_context=cto_context,
        appeal_id=appeal_id,
        appeal_count=appeal_count,
        priority=priority,
    )

    inbox_file = _inbox_path_for(legion_hash, commander_id)
    try:
        inbox_path = _write_inbox_to_path(inbox_file, message)
    except Exception as e:
        # inbox 是强保障通道；失败必须抛出，上游决定升级骏飞 / 重试
        raise LegionError(
            f"写入 inbox 失败 ({inbox_file}): {e}"
        ) from e

    tmux_notified = False
    if tmux_is_alive:
        notify_line = (
            f"@{commander_id} AICTO 派任务，inbox/{message['id']} 查看"
        )
        try:
            # 临时构造 Commander 视图给 _tmux_send_keys（只用 tmux_session 字段）
            _tmux_send_keys(
                Commander(
                    legion_hash=legion_hash,
                    legion_project="",
                    commander_id=commander_id,
                    task="",
                    started_at="",
                    tmux_alive=True,
                    tmux_session=tmux_session,
                    inbox_path=inbox_file,
                ),
                notify_line,
            )
            tmux_notified = True
        except LegionError:
            # tmux 通知是 best-effort —— 失败不抛，inbox 已经落地
            tmux_notified = False

    return {
        "message_id": message["id"],
        "inbox_path": str(inbox_path),
        "tmux_session": tmux_session,
        "tmux_notified": tmux_notified,
    }


__all__ = [
    "Commander",
    "LegionError",
    "SENDER_ID",
    "VALID_MSG_TYPES",
    "VALID_PRIORITIES",
    "discover_online_commanders",
    "mailbox_protocol_serialize",
    "send_to_commander",
    # 下划线开头但供测试 / 上层调用方按 spec 导入
    "_write_inbox_locked",
    "_tmux_alive",
    "_tmux_send_keys",
]
