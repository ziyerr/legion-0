#!/usr/bin/env python3
"""
Legion Commander — 军团智慧中枢

功能（CC 原生通信替代后，Commander 专注独有价值）:
- 纠察巡查：用 LLM 分析指挥官行为，检测违规
- 战评复盘：提取执行经验，沉淀为战法/技能
- 度量聚合：统计各种事件指标
- 观察分析：定期分析 observations.jsonl，提取重复失败模式
- 政委广播：协议提醒
- GC：死亡 commander 检测、广播清理、邮箱清理
- 心跳：供外部检测存活

通信层已由 Claude Code 原生 SendMessage/useInboxPoller 接管。
"""

import json
import os
import sys
import time
import fcntl
import uuid
import hashlib
import threading
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

LEGION_DIR = Path(os.environ.get("LEGION_DIR", str(Path.home() / ".claude" / "legion")))
REGISTRY = LEGION_DIR / "registry.json"
BROADCAST = LEGION_DIR / "broadcast.jsonl"
HEARTBEAT_FILE = LEGION_DIR / "commander.heartbeat"
PROJECT_HASH = LEGION_DIR.name  # e.g. "6df23ccc"

# Mixed Legion runtime (legion_core.py) state, parallel to the legacy registry.
MIXED_DIR = LEGION_DIR / "mixed"
MIXED_REGISTRY = MIXED_DIR / "mixed-registry.json"
MIXED_INBOX_DIR = MIXED_DIR / "inbox"
MIXED_EVENTS = MIXED_DIR / "events.jsonl"
MIXED_RUNS_DIR = MIXED_DIR / "runs"

POLL_INTERVAL = 0.5  # seconds
HEARTBEAT_INTERVAL = 10  # 每 10 秒写一次心跳

# 线程安全锁（保护 ThreadPoolExecutor 线程中的 read-modify-write 操作）
_metrics_lock = threading.Lock()
_inspector_lock = threading.Lock()


# ── 颜色输出 ──
def log(msg, level="INFO"):
    colors = {"INFO": "\033[36m", "WARN": "\033[33m", "ERROR": "\033[31m", "OK": "\033[32m"}
    reset = "\033[0m"
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    color = colors.get(level, "")
    print(f"{color}[{ts}] [{level}] {msg}{reset}", flush=True)


# ── 原子 JSON 读写 ──
def read_json(path, default=None):
    """读取 JSON。配合 write_json 的 atomic rename，无需 flock。"""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default if default is not None else {}


def write_json(path, data):
    """原子写入 JSON：写临时文件 → fsync → rename"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f'.tmp.{os.getpid()}.{threading.get_ident()}')
    with open(tmp_path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.rename(str(tmp_path), str(path))


def append_jsonl(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)


# ── 守护进程独占的可持久化证据面（patrol/retrospector/learning 连续性） ──
# Daemon 自有的 evidence 表 — 不染指 mixed/events.jsonl（那是 legion_core 持锁所有的）。
# 释放门 / 复盘官 / 后续分析可读这条流。每行带 schema_version + kind
# 鉴别字段，并包含 evidence_id / record_hash 供 release retrospective 引用。
DAEMON_EVIDENCE_FILE = LEGION_DIR / "daemon_evidence.jsonl"
DAEMON_EVIDENCE_SCHEMA = 1
DAEMON_EVIDENCE_MAX_LINES = 1000


def _record_evidence(kind, *, record=None, **details):
    """追加一条 daemon-owned evidence（同一文件，按 kind 鉴别）。

    kind 取值约定：
      - patrol_judgment / patrol_warning / patrol_violation / patrol_overturned
      - retrospective_started / retrospective_artifact_written
      - observation_pattern_detected / observation_tactic_suggested
      - protocol_proposal_added
      - mixed_commander_offline / commander_revived / commander_retired
    record 可传 discover_active_commanders() 单条记录，自动带上 cmd_id/source/role/provider。
    """
    payload = {
        "ts": datetime.now().isoformat(),
        "schema_version": DAEMON_EVIDENCE_SCHEMA,
        "evidence_id": f"daemon-{uuid.uuid4().hex[:12]}",
        "project_hash": PROJECT_HASH,
        "cwd": os.getcwd(),
        "kind": kind,
        "source_origin": "commander-daemon",
    }
    if isinstance(record, dict):
        payload["cmd_id"] = record.get("id")
        payload["commander_source"] = record.get("source")
        payload["role"] = record.get("role")
        payload["provider"] = record.get("provider")
        session = record.get("session")
        if session:
            payload["session"] = session
    payload.update(details)
    try:
        payload["record_hash"] = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
    except Exception:
        pass
    try:
        append_jsonl(DAEMON_EVIDENCE_FILE, payload)
    except Exception:
        pass  # evidence 写入不应影响主流程


def gc_daemon_evidence():
    """限定 daemon_evidence.jsonl 大小 — 保留最近 DAEMON_EVIDENCE_MAX_LINES 行。"""
    if not DAEMON_EVIDENCE_FILE.exists():
        return
    try:
        with open(DAEMON_EVIDENCE_FILE) as f:
            lines = f.readlines()
    except Exception:
        return
    if len(lines) <= DAEMON_EVIDENCE_MAX_LINES:
        return
    try:
        with open(DAEMON_EVIDENCE_FILE, "w") as f:
            f.writelines(lines[-DAEMON_EVIDENCE_MAX_LINES:])
        log(f"GC daemon_evidence: {len(lines)} -> {DAEMON_EVIDENCE_MAX_LINES} 行", "OK")
    except Exception:
        pass


def _record_observation(obs_type, details):
    """记录失败观察到 observations.jsonl（Harness 哲学核心）"""
    obs_file = Path.home() / ".claude" / "homunculus" / "observations.jsonl"
    obs_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        obs = {
            "ts": datetime.now().isoformat(),
            "type": obs_type,
            "source": "commander",
            **details
        }
        with open(obs_file, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(json.dumps(obs, ensure_ascii=False) + "\n")
            fcntl.flock(f, fcntl.LOCK_UN)
            # 大小检查：超过 5MB 自动归档
            try:
                if obs_file.stat().st_size > 5 * 1024 * 1024:
                    archive_dir = obs_file.parent / "archive"
                    archive_dir.mkdir(exist_ok=True)
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    import shutil
                    shutil.move(str(obs_file), str(archive_dir / f"observations-{ts}.jsonl"))
            except Exception:
                pass
    except Exception:
        pass  # 观察记录不应影响主流程


# ── 心跳 ──
def write_heartbeat():
    """写入心跳文件，供外部检测 Commander 存活"""
    HEARTBEAT_FILE.write_text(json.dumps({
        "pid": os.getpid(),
        "ts": datetime.now().isoformat(),
        "uptime_seconds": time.monotonic() - _start_time
    }))


# ── 初始化 ──
def init():
    LEGION_DIR.mkdir(parents=True, exist_ok=True)
    if not BROADCAST.exists():
        BROADCAST.touch()
    write_heartbeat()
    _record_evidence(
        "daemon_started",
        pid=os.getpid(),
        heartbeat_file=str(HEARTBEAT_FILE),
    )
    log("Commander 初始化完成", "OK")


# ── 混编/旧版 ID 与收件箱适配 ──
# 旧版纯 Claude 团队登记在 LEGION_DIR/registry.json 的 "teams" 列表中，session 命名
# legion-{PROJECT_HASH}-{tid}，收件箱在 LEGION_DIR/team-{tid}/inbox.jsonl。
# 混编 Legion (legion_core.py) 把指挥官登记在 mixed-registry.json 的 "commanders"
# 列表，session 命名 legion-mixed-{PROJECT_HASH}-{commander_id}，收件箱在
# MIXED_INBOX_DIR/{normalized_id}.jsonl，状态由 legion_core.py 持锁维护。
# Daemon 不应改写 mixed-registry.json，只读它来发现 L1/L2 指挥官并向其投递通知。

_MIXED_ACTIVE_STATUSES = {"launching", "commanding"}
_LEGACY_ACTIVE_STATUSES_EXCLUDED = {"completed", "failed"}


def _normalize_mixed_id(value: str) -> str:
    """复刻 legion_core.normalize_task_id：混编 inbox 文件名规则。"""
    safe = []
    for ch in value:
        if ch.isalnum() or ch in ("-", "_"):
            safe.append(ch)
        elif ch.isspace():
            safe.append("-")
    normalized = "".join(safe).strip("-_").lower()
    return normalized or value.lower()


def _read_mixed_commanders():
    """读取混编 registry 中的指挥官记录（不修改）。"""
    data = read_json(MIXED_REGISTRY, {"commanders": []})
    if not isinstance(data, dict):
        return []
    commanders = data.get("commanders", [])
    return commanders if isinstance(commanders, list) else []


def discover_active_commanders():
    """统一返回旧版 + 混编两侧的活跃指挥官。

    每条记录形如 {id, status, session, source, role, provider, raw}。
    旧版去重优先：如果一个 ID 在两侧都登记，以旧版条目为准。
    """
    seen = set()
    records = []

    legacy = read_json(REGISTRY, {"teams": []})
    for team in legacy.get("teams", []):
        tid = str(team.get("id", "")).strip()
        if not tid or not (tid.startswith("L1-") or tid.startswith("L2-")):
            continue
        if team.get("status") in _LEGACY_ACTIVE_STATUSES_EXCLUDED:
            continue
        seen.add(tid)
        records.append({
            "id": tid,
            "status": team.get("status"),
            "session": f"legion-{PROJECT_HASH}-{tid}",
            "source": "legacy",
            "role": "commander" if tid.startswith("L1-") else "branch-commander",
            "provider": team.get("provider"),
            "raw": team,
        })

    for cmdr in _read_mixed_commanders():
        cid = str(cmdr.get("id", "")).strip()
        if not cid or not (cid.startswith("L1-") or cid.startswith("L2-")):
            continue
        if cid in seen:
            continue
        if cmdr.get("status") not in _MIXED_ACTIVE_STATUSES:
            continue
        session = str(cmdr.get("session", "")).strip() or f"legion-mixed-{PROJECT_HASH}-{cid}"
        records.append({
            "id": cid,
            "status": cmdr.get("status"),
            "session": session,
            "source": "mixed",
            "role": cmdr.get("role"),
            "provider": cmdr.get("provider"),
            "raw": cmdr,
        })
        seen.add(cid)

    return records


def _commander_inbox_path(record):
    """指挥官实际投递路径：混编走 mixed/inbox，旧版走 team-{id}/inbox.jsonl。"""
    if record.get("source") == "mixed":
        return MIXED_INBOX_DIR / f"{_normalize_mixed_id(record['id'])}.jsonl"
    return LEGION_DIR / f"team-{record['id']}" / "inbox.jsonl"


def _commander_team_dir(record):
    """heartbeat.counter 与 gate.json 始终落在 team-{id}/，post-tool-use hook 也按
    CLAUDE_LEGION_TEAM_ID 写到这个目录，旧版/混编共享。"""
    return LEGION_DIR / f"team-{record['id']}"


def _commander_session(record):
    return record.get("session") or ""


def _build_message(record, *, sender, msg_type, priority, content, event=None, extras=None):
    """生成同时满足旧版 payload 渲染与混编 inbox 渲染的消息。"""
    payload = {"event": event or msg_type, "message": content}
    if extras:
        payload.update(extras)
    return {
        "id": f"msg-{uuid.uuid4().hex[:8]}",
        "ts": datetime.now().isoformat(),
        "from": sender,
        "to": record["id"],
        "type": msg_type,
        "priority": priority,
        "content": content,
        "payload": payload,
    }


def _deliver_inbox(record, message):
    """把消息追加到指挥官真正的收件箱（旧版或混编），加锁追加。"""
    inbox = _commander_inbox_path(record)
    inbox.parent.mkdir(parents=True, exist_ok=True)
    append_jsonl(inbox, message)


# ── 获取活跃 team 列表 ──
def get_active_teams():
    """返回旧版 + 混编两侧的活跃指挥官 ID（用于 stats / 概览）。"""
    return [r["id"] for r in discover_active_commanders()]


def _get_active_tmux_sessions():
    import subprocess
    try:
        result = subprocess.run(
            ["tmux", "ls", "-F", "#{session_name}"],
            capture_output=True, text=True, timeout=5
        )
    except Exception:
        return None  # tmux 不可用
    if not result.stdout.strip():
        return set()
    return set(result.stdout.strip().split("\n"))


def _session_claude_running(session_name):
    """session 存在且其顶层进程不是 shell（即 claude/codex 在跑）。"""
    import subprocess
    try:
        result = subprocess.run(
            ["tmux", "list-panes", "-t", session_name, "-F", "#{pane_current_command}"],
            capture_output=True, text=True, timeout=5
        )
    except Exception:
        return False
    current_cmd = result.stdout.strip().split("\n")[0] if result.stdout.strip() else ""
    return current_cmd not in ("zsh", "bash", "sh", "login", "")


def _session_child_alive(session_name):
    """session 存在，但 shell 之下没有任何子进程时返回 False（即 claude 已退）。"""
    import subprocess
    try:
        result = subprocess.run(
            ["tmux", "list-panes", "-t", session_name, "-F", "#{pane_pid}"],
            capture_output=True, text=True, timeout=5
        )
        shell_pid = result.stdout.strip().split("\n")[0] if result.stdout.strip() else ""
        if not shell_pid:
            return True  # 信息缺失，保守不判死
        child = subprocess.run(
            ["pgrep", "-P", shell_pid],
            capture_output=True, text=True, timeout=5
        )
        return bool(child.stdout.strip())
    except Exception:
        return True


def _broadcast_offline(dead_id, recipients):
    """向其它在线指挥官广播指定指挥官离线（按各自 inbox 路径投递）。"""
    for other in recipients:
        if other["id"] == dead_id:
            continue
        msg = _build_message(
            other,
            sender="commander",
            msg_type="notify",
            priority="normal",
            content=f"{dead_id} 已退役，从注册表移除。",
            event="commander_offline",
            extras={"offline_team": dead_id},
        )
        try:
            _deliver_inbox(other, msg)
        except Exception as e:
            log(f"退役广播投递失败 → {other['id']}: {e}", "WARN")


def gc_dead_commanders():
    """检测已死亡的指挥官（tmux session 不存在或进程已退），广播下线通知。

    旧版 registry.json：可直接从 teams 里移除已死条目。
    混编 mixed-registry.json：daemon 不持锁，不写回；只广播离线消息，
    真正的状态由 legion_core.py 的 reconcile/repair 路径回收。
    """
    active_sessions = _get_active_tmux_sessions()
    if active_sessions is None:
        return

    legacy = read_json(REGISTRY, {"teams": []})
    teams = legacy.get("teams", [])
    changed = False
    to_remove = []

    # 第一轮：旧版注册表里被误标 completed 但 session 还在跑的，复活
    for team in teams:
        tid = str(team.get("id", "")).strip()
        if not (tid.startswith("L1-") or tid.startswith("L2-")):
            continue
        if team.get("status") != "completed":
            continue
        session_name = f"legion-{PROJECT_HASH}-{tid}"
        if session_name in active_sessions and _session_claude_running(session_name):
            log(f"复活检测: {tid} 实际在线，status 从 completed 恢复为 commanding", "OK")
            team["status"] = "commanding"
            team.pop("completed", None)
            team.pop("exit_reason", None)
            changed = True
            _record_evidence(
                "commander_revived",
                cmd_id=tid,
                commander_source="legacy",
                session=session_name,
            )

    # 收集所有活跃指挥官（旧版 + 混编）作为广播池
    active_records = discover_active_commanders()

    # 第二轮：旧版指挥官的死亡检测（允许写回旧版 registry）
    for team in teams:
        tid = str(team.get("id", "")).strip()
        if not (tid.startswith("L1-") or tid.startswith("L2-")):
            continue
        if team.get("status") in _LEGACY_ACTIVE_STATUSES_EXCLUDED:
            continue

        session_name = f"legion-{PROJECT_HASH}-{tid}"
        if session_name not in active_sessions:
            log(f"死亡检测: {tid} 的 tmux session 不存在，将从注册表删除", "WARN")
            team["ended"] = datetime.now().isoformat()
            team["status"] = "completed"
            to_remove.append(tid)
            changed = True
            _broadcast_offline(tid, [r for r in active_records if r["id"] not in to_remove])
            _record_evidence(
                "commander_retired",
                cmd_id=tid,
                commander_source="legacy",
                session=session_name,
                cause="tmux_session_missing",
            )
            log(f"退役广播: {tid} → 已通知所有在线指挥官", "OK")
            continue

        if not _session_child_alive(session_name):
            log(f"死亡检测: {tid} 的 claude 进程已退出，将从注册表删除", "WARN")
            team["ended"] = datetime.now().isoformat()
            team["status"] = "completed"
            to_remove.append(tid)
            changed = True
            _broadcast_offline(tid, [r for r in active_records if r["id"] not in to_remove])
            _record_evidence(
                "commander_retired",
                cmd_id=tid,
                commander_source="legacy",
                session=session_name,
                cause="child_process_exited",
            )
            log(f"退役广播: {tid} → 已通知所有在线指挥官", "OK")

    if to_remove:
        legacy["teams"] = [t for t in teams if t.get("id") not in to_remove]
        log(f"注册表清理: 删除 {len(to_remove)} 个退役条目: {', '.join(to_remove)}", "OK")
    if changed:
        write_json(REGISTRY, legacy)

    # 第三轮：混编指挥官的死亡监控 — 仅广播，不改写混编 registry
    for record in active_records:
        if record.get("source") != "mixed":
            continue
        cid = record["id"]
        session_name = record["session"]
        is_dead = False
        if session_name not in active_sessions:
            log(f"混编死亡检测: {cid} session 不存在，等待 legion_core reconcile", "WARN")
            is_dead = True
        elif not _session_child_alive(session_name):
            log(f"混编死亡检测: {cid} 进程已退出，等待 legion_core reconcile", "WARN")
            is_dead = True
        if is_dead:
            survivors = [r for r in active_records if r["id"] != cid]
            _broadcast_offline(cid, survivors)
            _record_observation("mixed_commander_offline", {
                "commander_id": cid,
                "session": session_name,
                "provider": record.get("provider", ""),
            })
            _record_evidence(
                "mixed_commander_offline",
                record=record,
                cause=("session_missing" if session_name not in active_sessions else "child_process_exited"),
            )


def gc_broadcast():
    """清理 broadcast.jsonl：保留最近 200 行"""
    if not BROADCAST.exists():
        return
    try:
        with open(BROADCAST) as f:
            lines = f.readlines()
        if len(lines) > 200:
            with open(BROADCAST, "w") as f:
                f.writelines(lines[-200:])
            log(f"GC broadcast: {len(lines)} → 200 行", "OK")
    except Exception:
        pass


def _trim_jsonl(path, keep=100, label=""):
    """保留 jsonl 文件最后 keep 行；调整不调用 cursor 文件以外的状态。"""
    try:
        with open(path) as f:
            lines = f.readlines()
    except Exception:
        return
    if len(lines) <= keep:
        return
    try:
        with open(path, "w") as f:
            f.writelines(lines[-keep:])
        log(f"GC inbox: {label or path.name} {len(lines)} -> {keep} 行", "OK")
    except Exception:
        pass


def gc_inboxes():
    """清理已读消息：旧版 inbox.jsonl + 混编 inbox/*.jsonl 都裁尾，旧版 inboxes/*.json 删已读"""
    # 旧版 registry → team-*/inbox.*
    reg = read_json(REGISTRY, {"teams": []})
    for team in reg.get("teams", []):
        tid = team["id"]
        team_dir = LEGION_DIR / f"team-{tid}"

        inbox_path = team_dir / "inbox.jsonl"
        if inbox_path.exists():
            try:
                with open(inbox_path) as f:
                    inbox_lines = f.readlines()
                if len(inbox_lines) > 100:
                    with open(inbox_path, "w") as f:
                        f.writelines(inbox_lines[-100:])
                    cursor_path = team_dir / "inbox.cursor"
                    cursor_path.write_text("100")
                    log(f"GC inbox: {tid} inbox.jsonl {len(inbox_lines)} -> 100 行", "OK")
            except Exception:
                pass

        inboxes_dir = team_dir / "inboxes"
        if inboxes_dir.exists():
            import glob as _glob
            for inbox_file in _glob.glob(str(inboxes_dir / "*.json")):
                if inbox_file.endswith(".lock"):
                    continue
                try:
                    messages = read_json(inbox_file, [])
                    if not isinstance(messages, list):
                        continue
                    unread = [m for m in messages if not m.get("read", False)]
                    if len(unread) < len(messages):
                        write_json(inbox_file, unread)
                        cleaned = len(messages) - len(unread)
                        if cleaned > 0:
                            log(f"GC inbox: {Path(inbox_file).name} 清理 {cleaned} 已读消息", "OK")
                except Exception:
                    pass

    # 混编 inbox：仅做尾部裁剪。注意混编 inbox 由 legion_core 维护 cursor，
    # daemon 不重写 cursor，避免读端误读。
    if MIXED_INBOX_DIR.exists():
        for mixed_inbox in MIXED_INBOX_DIR.glob("*.jsonl"):
            _trim_jsonl(mixed_inbox, keep=200, label=f"mixed/{mixed_inbox.name}")




def gc_tmp_files():
    """清理残留的 .tmp.* 文件（write_json 崩溃残留）"""
    now = time.time()
    cleaned = 0
    recovered = 0
    for tmp_path in LEGION_DIR.rglob("*.tmp.*"):
        if not tmp_path.is_file():
            continue
        try:
            age = now - tmp_path.stat().st_mtime
            if age < 60:
                continue
            # name 形如 "foo.tmp.12345.67890"，原始文件是 "foo.json"
            name = tmp_path.name
            idx = name.find(".tmp.")
            if idx < 0:
                continue
            base_name = name[:idx] + ".json"
            target_path = tmp_path.parent / base_name
            if target_path.exists():
                tmp_path.unlink()
                cleaned += 1
            else:
                os.rename(str(tmp_path), str(target_path))
                recovered += 1
        except Exception:
            pass
    if cleaned or recovered:
        log(f"GC tmp: 清理 {cleaned} 个, 恢复 {recovered} 个残留 tmp 文件", "OK")

# ── 政委广播：按工具调用次数向在线指挥官重申核心协议 ──
COMMISSAR_TOOL_CALL_INTERVAL = 50  # 每 50 次工具调用广播一次
_commissar_last_seen = {}  # {cmd_id: last_counter_when_broadcast}

def commissar_broadcast():
    """政委按工具调用次数广播。覆盖旧版 + 混编两侧的活跃指挥官（L1/L2 都收）。

    工具调用计数器始终落在 LEGION_DIR/team-{id}/heartbeat.counter（由
    post-tool-use hook 按 CLAUDE_LEGION_TEAM_ID 写入），混编与旧版共用。
    """
    global _commissar_last_seen

    active = discover_active_commanders()
    # 政委只对真正在跑的（commanding）指挥官播报，避免对刚 launching 的造成噪声
    active = [r for r in active if r.get("status") == "commanding"]
    if not active:
        return

    for record in active:
        cmd_id = record["id"]
        counter_file = _commander_team_dir(record) / "heartbeat.counter"
        try:
            counter = int(counter_file.read_text().strip())
        except (FileNotFoundError, ValueError, NotADirectoryError):
            continue

        last = _commissar_last_seen.get(cmd_id, 0)
        if counter <= last:
            continue

        last_boundary = last // COMMISSAR_TOOL_CALL_INTERVAL
        curr_boundary = counter // COMMISSAR_TOOL_CALL_INTERVAL
        if curr_boundary <= last_boundary:
            _commissar_last_seen[cmd_id] = counter
            continue

        body = (
            f"【政委广播 — 第{counter}次工具调用检查点】\n"
            "⚠️ Spec 驱动 + 上下文保鲜：\n"
            "- 中型+任务 → 维护 .planning/ 目录（REQUIREMENTS/DECISIONS/STATE）\n"
            "- 决策写入 DECISIONS.md 标记 LOCKED，执行阶段不可推翻\n"
            "- 对话变长时 /compact + 读 STATE.md 恢复\n"
            "⚠️ 结构化任务 + 原子提交：\n"
            "- 给 teammate 用 XML 格式（action/verify/done/commit）\n"
            "- 每个 task 完成就 git commit，不攒一堆\n"
            "⚠️ 两阶段审计（必须贴验证输出）：\n"
            "- 1.规格符合性 2.cargo check+tsc --noEmit\n"
            "其他：worktree隔离 | 参谋外部调研 | 消息ACK | 情报响应"
        )
        msg = _build_message(
            record,
            sender="政委",
            msg_type="notify",
            priority="normal",
            content=body,
            event="protocol_reminder",
            extras={"tool_call_counter": counter, "source": record.get("source", "legacy")},
        )
        try:
            _deliver_inbox(record, msg)
        except Exception as e:
            log(f"政委广播投递失败 → {cmd_id}: {e}", "WARN")
            continue
        _commissar_last_seen[cmd_id] = counter
        log(f"政委广播 → {cmd_id} ({record.get('source','?')}, 第{counter}次工具调用)", "OK")


# ── 纠察：智能行为监察，用 LLM 判断指挥官是否偏离协议 ──
INSPECTOR_INTERVAL_SECONDS = 120  # 每 2 分钟巡查一次
_inspector_last_check = {}  # {cmd_id: last_check_counter}
_inspector_history = {}  # {cmd_id: [recent_snapshots]}  滑动窗口
INSPECTOR_MEMORY_FILE = LEGION_DIR / "inspector_memory.json"


def _load_inspector_memory():
    """加载纠察记忆：历史判断 + 误判记录"""
    return read_json(INSPECTOR_MEMORY_FILE, {
        "judgments": [],   # 历史判断记录
        "overturned": [],  # 被推翻的误判
        "patterns": {}     # 学到的模式 {pattern_key: {count, last_seen, adjust}}
    })


def _save_inspector_memory(memory):
    write_json(INSPECTOR_MEMORY_FILE, memory)


def _record_judgment(cmd_id, verdict, reason, screen_summary):
    """记录纠察判断（线程安全）"""
    with _inspector_lock:
        memory = _load_inspector_memory()
        record = {
            "ts": datetime.now().isoformat(),
            "cmd_id": cmd_id,
            "verdict": verdict,
            "reason": reason,
            "screen_summary": screen_summary[:300],
            "overturned": False
        }
        memory["judgments"].append(record)
        # 只保留最近 50 条
        memory["judgments"] = memory["judgments"][-50:]
        _save_inspector_memory(memory)


def _check_overturned():
    """检查是否有判断被用户推翻（gate approve 了 violation）（线程安全）"""
    with _inspector_lock:
        memory = _load_inspector_memory()
        judgments = memory.get("judgments", [])

        for j in judgments:
            if j.get("verdict") != "violation" or j.get("overturned"):
                continue
            cmd_id = j.get("cmd_id", "")
            # gate.json 不区分 L1/L2、旧版/混编，统一在 LEGION_DIR/team-{id}/。
            gate_file = LEGION_DIR / f"team-{cmd_id}" / "gate.json"
            if gate_file.exists():
                try:
                    gate = json.loads(gate_file.read_text())
                    if gate.get("status") == "approved":
                        # 被推翻了
                        j["overturned"] = True
                        overturn_record = {
                            "ts": datetime.now().isoformat(),
                            "cmd_id": cmd_id,
                            "original_reason": j.get("reason", ""),
                            "screen_summary": j.get("screen_summary", "")
                        }
                        memory.setdefault("overturned", []).append(overturn_record)
                        memory["overturned"] = memory["overturned"][-20:]

                        # 提取模式：什么类型的行为被误判了
                        pattern_key = j.get("reason", "")[:50]
                        patterns = memory.setdefault("patterns", {})
                        if pattern_key not in patterns:
                            patterns[pattern_key] = {"count": 0, "adjust": "降低严厉度"}
                        patterns[pattern_key]["count"] += 1
                        patterns[pattern_key]["last_seen"] = datetime.now().isoformat()

                        record_metric("violations_overturned", cmd_id)
                        _record_evidence(
                            "patrol_overturned",
                            cmd_id=cmd_id,
                            commander_source="shared",
                            original_reason=j.get("reason", "")[:200],
                            screen_summary=j.get("screen_summary", "")[:200],
                        )
                        log(f"纠察自适应: 判断被推翻 ({cmd_id}): {j.get('reason','')[:60]}", "WARN")
                except Exception:
                    pass

        _save_inspector_memory(memory)


def _get_inspector_context():
    """生成纠察的自适应上下文（注入到 prompt 中）"""
    memory = _load_inspector_memory()
    overturned = memory.get("overturned", [])
    patterns = memory.get("patterns", {})

    if not overturned and not patterns:
        return ""

    lines = ["\n⚠️ 纠察自适应记忆（从历史误判中学到的）："]

    if overturned:
        lines.append(f"历史上有 {len(overturned)} 次判断被用户推翻（误判），以下是教训：")
        for o in overturned[-5:]:  # 最近 5 次
            lines.append(f"  - 误判了 {o.get('cmd_id','')}: \"{o.get('original_reason','')[:80]}\"")
            lines.append(f"    当时屏幕: {o.get('screen_summary','')[:100]}")

    if patterns:
        lines.append("学到的模式（遇到类似场景时降低严厉度）：")
        for pattern, info in sorted(patterns.items(), key=lambda x: -x[1].get("count", 0))[:5]:
            lines.append(f"  - \"{pattern}\" — 被误判 {info['count']} 次，应该 {info['adjust']}")

    lines.append("请根据以上经验调整你的判断，避免重复误判。")
    return "\n".join(lines)

def inspector_patrol():
    """纠察巡查：抓取指挥官屏幕，用 LLM 判断是否违规。

    旧版只看 L1 的 status==commanding；新版扩展为 L1+L2，旧版+混编全部巡视，
    session 名按记录里的 source 选择 legion-/legion-mixed- 前缀。
    """
    global _inspector_last_check, _inspector_history
    import subprocess as sp

    # 先检查是否有历史判断被用户推翻（自适应学习）
    _check_overturned()

    active = [r for r in discover_active_commanders() if r.get("status") == "commanding"]
    if not active:
        return

    for record in active:
        cmd_id = record["id"]
        session_name = _commander_session(record)
        if not session_name:
            continue

        counter_file = _commander_team_dir(record) / "heartbeat.counter"
        try:
            counter = int(counter_file.read_text().strip())
        except (FileNotFoundError, ValueError, NotADirectoryError):
            continue

        last = _inspector_last_check.get(cmd_id, 0)
        # 至少间隔 20 次工具调用才巡查一次（避免频繁）
        if counter - last < 20:
            continue

        try:
            result = sp.run(
                ["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-150"],
                capture_output=True, text=True, timeout=5
            )
            screen = result.stdout.strip()
        except Exception:
            continue

        if not screen or len(screen) < 50:
            continue

        if cmd_id not in _inspector_history:
            _inspector_history[cmd_id] = []
        _inspector_history[cmd_id].append({
            "counter": counter,
            "screen": screen[-2000:]
        })
        if len(_inspector_history[cmd_id]) > 3:
            _inspector_history[cmd_id].pop(0)

        _inspector_last_check[cmd_id] = counter

        if len(_inspector_history[cmd_id]) < 2:
            continue

        task_desc = str(record["raw"].get("task", "")) if isinstance(record.get("raw"), dict) else ""
        _inspect_with_llm(record, task_desc, _inspector_history[cmd_id])


def _call_claude(prompt, max_tokens=200):
    """通过 claude CLI 调用 LLM，复用 Claude Code 自身的认证"""
    import subprocess as sp
    try:
        result = sp.run(
            ["claude", "-p", prompt, "--max-turns", "1"],
            capture_output=True, text=True, timeout=90
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception as e:
        log(f"claude CLI 调用失败: {e}", "WARN")
        return None


def _inspect_with_llm(record, task_desc, snapshots):
    """用 claude CLI 分析指挥官行为；record 同时携带 source/role 信息。"""
    cmd_id = record["id"]
    role_desc = "L1 指挥官" if cmd_id.startswith("L1-") else "L2 分支指挥官"
    combined = "\n---快照分隔---\n".join([
        f"[第{s['counter']}次工具调用时的屏幕]\n{s['screen']}" for s in snapshots
    ])

    prompt = f"""你是军团纠察官。分析以下 {role_desc} {cmd_id} 的行为快照。

你必须按以下步骤分析（不可跳过）：

**步骤 1：识别用户下达的任务**
从屏幕中找到用户（❯ 后面的输入）最近下达的任务是什么。用一句话概括。

**步骤 2：判断任务规模**
- 小任务：改几行代码、修一个 bug、加一个小配置 → 指挥官自己做合理
- 中任务：涉及 3-5 个文件的功能修改 → 指挥官可以自己做，也可以派人
- 大任务：全链路检查、跨模块重构、新架构设计、涉及 5+ 文件 → 必须派 teammate

**步骤 3：检查指挥官行为是否匹配任务规模**
- 大任务但指挥官自己在读大量代码/做大量分析 → warning 或 violation
- 小/中任务指挥官自己做 → normal
- 指挥官已经创建了 teammate → normal
- 指挥官在做审计（cargo check / tsc）→ normal
- 指挥官在和用户对话 → normal

**步骤 4：判定**
- violation 仅限：大规模任务完全不派人，从头到尾自己干
- 宁可误放，不可误抓
{_get_inspector_context()}

行为快照（从旧到新）：
{combined}

请输出 JSON（不要其他内容）：
{{
  "user_task": "用户下达的任务（一句话）",
  "task_scale": "small|medium|large",
  "has_teammates": true/false,
  "verdict": "normal|warning|violation",
  "reason": "一句话说明判断依据",
  "suggestion": "如果有问题，建议指挥官怎么做"
}}"""

    try:
        result_text = _call_claude(prompt)
        if not result_text:
            return

        # 解析 JSON
        import re
        json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if not json_match:
            return
        result = json.loads(json_match.group())

        verdict = result.get("verdict", "normal")
        reason = result.get("reason", "")
        suggestion = result.get("suggestion", "")

        # 记录所有判断（用于自适应学习）
        screen_summary = snapshots[-1]["screen"][-300:] if snapshots else ""
        _record_judgment(cmd_id, verdict, reason, screen_summary)

        user_task = result.get("user_task", "未识别")
        task_scale = result.get("task_scale", "?")

        if verdict == "normal":
            _record_evidence(
                "patrol_judgment",
                record=record,
                verdict="normal",
                task_scale=task_scale,
                user_task=user_task[:120],
                reason=reason[:200],
            )
            log(f"纠察巡查 {cmd_id}: 正常 [{task_scale}] {user_task[:40]} — {reason}")
            return

        if verdict == "warning":
            # 检查连续 warning 次数 → 累计升级
            memory = _load_inspector_memory()
            recent = [j for j in memory.get("judgments", [])[-10:]
                      if j.get("cmd_id") == cmd_id and j.get("verdict") == "warning"]
            consecutive_warnings = len(recent)

            if consecutive_warnings >= 2:
                # 连续 2 次 warning 未改正 → 升级为 violation
                log(f"纠察升级: {cmd_id} 连续 {consecutive_warnings} 次 warning 未改正 → 执法", "ERROR")
                verdict = "violation"
                reason = f"连续 {consecutive_warnings} 次提醒未改正: {reason}"
                # 继续走下面的 violation 处理
            else:
                content = (
                    f"【纠察提醒 {consecutive_warnings+1}/2】{reason}\n"
                    f"建议：{suggestion}\n"
                    "⚠️ 再次提醒未改正将自动升级为执法（冻结操作）"
                )
                msg = _build_message(
                    record,
                    sender="纠察",
                    msg_type="notify",
                    priority="normal",
                    content=content,
                    event="inspector_warning",
                    extras={"warning_count": consecutive_warnings + 1, "max_warnings": 2},
                )
                try:
                    _deliver_inbox(record, msg)
                except Exception as e:
                    log(f"纠察提醒投递失败 → {cmd_id}: {e}", "WARN")
                log(f"纠察提醒 ({consecutive_warnings+1}/2) → {cmd_id}: {reason}", "WARN")
                record_metric("warnings_issued", cmd_id)
                _record_evidence(
                    "patrol_warning",
                    record=record,
                    warning_count=consecutive_warnings + 1,
                    max_warnings=2,
                    reason=reason[:200],
                    suggestion=suggestion[:200],
                    user_task=user_task[:120],
                    task_scale=task_scale,
                )
                return  # warning 处理完毕，不走 violation

        elif verdict == "violation":
            pass  # fall through to violation handling below

        # violation handling (reached from direct violation or escalated warning)
        if verdict == "violation":
            # gate.json 在 LEGION_DIR/team-{id}/ 是旧版/混编共享的执法面。
            gate_file = _commander_team_dir(record) / "gate.json"
            write_json(gate_file, {
                "status": "blocked",
                "reason": f"纠察暂停：{reason}。{suggestion}",
                "blocked_by": "执法",
                "blocked_at": datetime.now().isoformat(),
                "commander_source": record.get("source", "legacy"),
                "session": _commander_session(record),
            })
            content = (
                f"⛔【纠察执法】{reason}\n要求：{suggestion}\n"
                f"你的操作已被暂停。纠正后由用户或上级解除：legion.sh gate {cmd_id} approve"
            )
            msg = _build_message(
                record,
                sender="纠察",
                msg_type="notify",
                priority="urgent",
                content=content,
                event="inspector_violation",
                extras={
                    "reason": reason,
                    "suggestion": suggestion,
                    "source": record.get("source", "legacy"),
                },
            )
            try:
                _deliver_inbox(record, msg)
            except Exception as e:
                log(f"纠察执法投递失败 → {cmd_id}: {e}", "WARN")
            record_metric("violations_issued", cmd_id)
            _record_evidence(
                "patrol_violation",
                record=record,
                reason=reason[:200],
                suggestion=suggestion[:200],
                user_task=user_task[:120],
                task_scale=task_scale,
                gate_file=str(gate_file),
            )
            log(f"纠察暂停 → {cmd_id}: {reason}", "ERROR")

    except Exception as e:
        log(f"纠察分析异常: {e}", "WARN")


# ── 战评官：任务完成后提取经验 → 项目 memory + 全局战法库 ──
REVIEW_INTERVAL_SECONDS = 120
_review_checked = set()  # 已复盘的 cmd_id（避免重复）
TACTICS_DIR = Path(os.path.expanduser("~/.claude/memory/tactics"))
TACTICS_DIR.mkdir(parents=True, exist_ok=True)
MAX_GLOBAL_TACTICS = 50
MAX_PROJECT_MEMORY = 30


def _detect_task_completion():
    """检测哪些 L1 指挥官刚完成任务（旧版+混编都看）。

    返回列表，每项是 discover_active_commanders() 风格的 record（带 session/source）。
    完成判定：
      - 旧版 registry 中状态已是 completed → 收回
      - 仍 commanding/launching 但屏幕出现完成信号 → 收回
      - 混编侧 status==completed 不会被 daemon 直接看到（daemon 只读 mixed-registry），
        所以混编只看屏幕信号；这是有意的 — 真正的完成由 legion_core 持锁回收。
    """
    import subprocess as sp

    completed = []
    seen = set()

    # 第一轮：旧版 registry 里已经标记 completed 的 L1
    legacy = read_json(REGISTRY, {"teams": []})
    for team in legacy.get("teams", []):
        cmd_id = str(team.get("id", "")).strip()
        if not cmd_id.startswith("L1-") or cmd_id in _review_checked or cmd_id in seen:
            continue
        if team.get("status") == "completed":
            completed.append({
                "id": cmd_id,
                "status": "completed",
                "session": f"legion-{PROJECT_HASH}-{cmd_id}",
                "source": "legacy",
                "role": "commander",
                "provider": team.get("provider"),
                "raw": team,
            })
            seen.add(cmd_id)

    # 第二轮：仍在跑的 L1（旧版+混编），抓屏幕看是否打出完成信号
    for record in discover_active_commanders():
        cmd_id = record["id"]
        if not cmd_id.startswith("L1-") or cmd_id in _review_checked or cmd_id in seen:
            continue
        session_name = _commander_session(record)
        if not session_name:
            continue
        try:
            result = sp.run(
                ["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-30"],
                capture_output=True, text=True, timeout=5
            )
            screen = result.stdout
        except Exception:
            continue
        completion_signals = ["审计通过", "任务完成", "全部完成", "已完成所有", "审计结果：通过"]
        if any(sig in screen for sig in completion_signals):
            completed.append(record)
            seen.add(cmd_id)

    return completed


def after_action_review():
    """战评官：对完成任务的指挥官提取经验（旧版+混编都覆盖）。"""
    completed = _detect_task_completion()
    if not completed:
        return

    for record in completed:
        cmd_id = record["id"]
        if cmd_id in _review_checked:
            continue
        _review_checked.add(cmd_id)

        session_name = _commander_session(record)
        if not session_name:
            continue

        # 抓取最近屏幕（尽量多）
        import subprocess as sp
        try:
            result = sp.run(
                ["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-200"],
                capture_output=True, text=True, timeout=5
            )
            screen = result.stdout.strip()[-4000:]  # 最后 4000 字符
        except Exception:
            continue

        if len(screen) < 100:
            continue

        log(f"战评官启动 → {cmd_id} ({record.get('source','?')})", "OK")
        _record_evidence(
            "retrospective_started",
            record=record,
            screen_excerpt=screen[-400:],
        )
        _extract_learnings(cmd_id, screen, record=record)


def _extract_learnings(cmd_id, screen, *, record=None):
    """用 claude CLI 提取经验，分类写入项目 memory 或全局战法。

    record 可选 — 如有，evidence/memory 写入会带上 source/role/provider，便于
    后续复盘官区分混编 vs 旧版指挥官输出。
    """
    # 读取现有战法标题列表（避免重复）
    existing_tactics = []
    for tf in TACTICS_DIR.glob("*.md"):
        try:
            content = tf.read_text()
            for line in content.split("\n"):
                if line.startswith("summary:"):
                    existing_tactics.append(line.replace("summary:", "").strip())
        except Exception:
            pass

    # 读取项目 memory 列表
    project_memory_dir = None
    try:
        import subprocess as sp
        result = sp.run(["pwd"], capture_output=True, text=True, timeout=2)
        cwd = result.stdout.strip()
        # 推断项目 memory 路径
        safe_path = cwd.replace("/", "-")
        if safe_path.startswith("-"):
            safe_path = safe_path[1:]
        project_memory_dir = Path(os.path.expanduser(f"~/.claude/projects/-{safe_path}/memory"))
    except Exception:
        pass

    existing_project_memory = []
    if project_memory_dir and project_memory_dir.exists():
        for mf in project_memory_dir.glob("*.md"):
            if mf.name != "MEMORY.md":
                existing_project_memory.append(mf.stem)

    prompt = f"""你是军团战评官。分析以下 L1 指挥官 {cmd_id} 完成任务后的屏幕记录，提取有价值的经验。

屏幕记录：
{screen}

已有全局战法（避免重复）：
{chr(10).join(f'- {t}' for t in existing_tactics[:20]) if existing_tactics else '无'}

已有项目 memory 条目：
{chr(10).join(f'- {m}' for m in existing_project_memory[:20]) if existing_project_memory else '无'}

判断标准：
- 只提取非显而易见的、经过实战验证的经验
- 区分"项目特有"和"跨项目通用"
- 如果没有值得记录的经验，返回空
- 不要和已有条目重复

输出 JSON（不要其他内容）：
{{
  "project_learnings": [
    {{"topic": "简短主题", "content": "经验内容，2-3句话", "domain": "领域标签"}}
  ],
  "global_tactics": [
    {{"summary": "一句话概括", "detail": "具体经验，含步骤或注意事项", "domain": "领域标签如 rust/typescript/python/architecture"}}
  ],
  "generated_skills": [
    {{
      "name": "技能名（英文kebab-case，如 check-tauri-sync）",
      "description": "写给模型看：什么时候应该触发这个技能（不是描述它做什么）",
      "pattern": "tool-wrapper|generator|reviewer|inversion|pipeline（Google ADK 5大设计模式之一）",
      "scope": "global 或 project",
      "skill_md": "SKILL.md 的完整内容（YAML frontmatter + markdown 指令）",
      "scripts": {{"脚本文件名.sh": "脚本内容"}},
      "references": {{"参考文件名.md": "参考内容（可选）"}},
      "gotchas": "Claude 使用此技能时容易犯的错误（最高价值内容）"
    }}
  ]
}}

generated_skills 规则（遵循 Claude Code Skills + Google ADK 最佳实践）：
- 只有当某个操作**反复出现且可以自动化**时才生成技能
- skill_md 必须包含 YAML frontmatter（name/description/pattern）+ markdown 指令
- description 写给模型看：描述"什么时候触发"而不是"做什么"
- pattern 必须标注为以下 5 种设计模式之一：
  * tool-wrapper：包装工具/API/库的使用方式和最佳实践
  * generator：模板填充，保证输出结构一致
  * reviewer：审阅检查，对前序输出做结构化质量评价
  * inversion：阶段门控，先问清需求再执行（苏格拉底式）
  * pipeline：多步骤顺序执行，带 checkpoint
- 生产中模式通常组合使用：inversion+generator / generator+reviewer / pipeline+reviewer
- gotchas 是最高价值内容：记录 Claude 常犯的错误和陷阱
- scripts 里放可执行脚本，references 放参考文档（按需读取，不一次性加载）
- SKILL.md 控制在 500 行以内，详细内容放 references
- 大部分情况 generated_skills 应该是空数组

如果没有值得记录的，返回：{{"project_learnings": [], "global_tactics": [], "generated_skills": []}}"""

    try:
        result_text = _call_claude(prompt)
        if not result_text:
            return

        import re
        json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if not json_match:
            return
        result = json.loads(json_match.group())

        project_count = 0
        tactic_count = 0
        skill_count = 0

        # 写入项目 memory
        for learning in result.get("project_learnings", []):
            if _write_project_memory(learning, cmd_id, project_memory_dir, record=record):
                project_count += 1

        # 写入全局战法
        for tactic in result.get("global_tactics", []):
            if _write_global_tactic(tactic, cmd_id, record=record):
                tactic_count += 1

        # 生成技能
        for skill in result.get("generated_skills", []):
            if _write_generated_skill(skill, cmd_id, record=record):
                skill_count += 1

        if project_count or tactic_count or skill_count:
            _record_evidence(
                "retrospective_artifact_written",
                record=record,
                cmd_id=cmd_id,
                project_learnings=project_count,
                global_tactics=tactic_count,
                generated_skills=skill_count,
            )

    except Exception as e:
        log(f"战评官分析异常: {e}", "WARN")


def analyze_observations():
    """分析 observations.jsonl，提取失败模式，自动生成战法"""
    obs_file = Path.home() / ".claude" / "homunculus" / "observations.jsonl"
    if not obs_file.exists():
        return

    # 读最近 50 条（不全量分析，避免 token 浪费）
    try:
        with open(obs_file) as f:
            lines = f.readlines()
        recent = lines[-50:] if len(lines) > 50 else lines
    except Exception:
        return

    if len(recent) < 5:
        return  # 数据不够，跳过

    # 统计失败类型分布
    from collections import Counter
    type_counts = Counter()
    for line in recent:
        try:
            obs = json.loads(line.strip())
            type_counts[obs.get("type", "unknown")] += 1
        except Exception:
            pass

    if not type_counts:
        return

    # 找到重复出现的失败模式（≥3次 = 值得分析）
    recurring = {t: c for t, c in type_counts.items() if c >= 3}
    if not recurring:
        return

    log(f"观察分析: 发现 {len(recurring)} 种重复失败模式: {dict(recurring)}", "OK")

    # 用 LLM 分析重复模式并建议战法
    sample_obs = []
    for line in recent:
        try:
            obs = json.loads(line.strip())
            if obs.get("type") in recurring:
                sample_obs.append(obs)
        except Exception:
            pass

    if len(sample_obs) < 3:
        return

    # 限制样本量
    sample_text = json.dumps(sample_obs[:10], ensure_ascii=False, indent=2)

    prompt = f"""分析以下重复出现的失败观察记录，提取模式：

失败类型分布: {dict(recurring)}

样本记录:
{sample_text[:3000]}

请输出 JSON（不要其他内容）：
{{
  "patterns": [
    {{
      "type": "失败类型",
      "count": 次数,
      "root_cause": "根因分析",
      "suggestion": "建议的防范措施"
    }}
  ],
  "should_create_tactic": true/false,
  "tactic_summary": "如果值得创建战法，一句话总结"
}}"""

    result_text = _call_claude(prompt)
    if not result_text:
        return

    try:
        import re
        json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if not json_match:
            return
        result = json.loads(json_match.group())
    except Exception:
        return

    patterns = result.get("patterns", [])
    for p in patterns:
        log(f"观察模式: {p.get('type')} ×{p.get('count')} — {p.get('root_cause', '')[:60]}", "OK")
        record_metric("observation_patterns_found")
        _record_evidence(
            "observation_pattern_detected",
            pattern_type=p.get("type"),
            count=p.get("count"),
            root_cause=str(p.get("root_cause", ""))[:200],
            suggestion=str(p.get("suggestion", ""))[:200],
        )

    # 如果建议创建战法，记录到度量（实际战法创建由战评官的 _extract_learnings 处理）
    if result.get("should_create_tactic"):
        log(f"观察分析建议创建战法: {result.get('tactic_summary', '')[:80]}", "OK")
        record_metric("observation_tactic_suggested")
        _record_evidence(
            "observation_tactic_suggested",
            tactic_summary=str(result.get("tactic_summary", ""))[:200],
            recurring_types=dict(recurring),
        )

    _record_observation("analysis_completed", {
        "patterns_found": len(patterns),
        "recurring_types": dict(recurring),
        "tactic_suggested": result.get("should_create_tactic", False)
    })


def _write_project_memory(learning, cmd_id, memory_dir, *, record=None):
    """写入项目 memory；返回 True 表示落盘成功（用于 evidence 计数）。"""
    if not memory_dir or not memory_dir.exists():
        return False

    topic = learning.get("topic", "").strip()
    content = learning.get("content", "").strip()
    domain = learning.get("domain", "general")
    if not topic or not content:
        return False

    # 检查容量
    existing = list(memory_dir.glob("tactic_*.md"))
    if len(existing) >= MAX_PROJECT_MEMORY:
        # 不淘汰，只是不写入（项目 memory 有其他条目占位）
        log(f"战评官: 项目 memory 已满 ({MAX_PROJECT_MEMORY})，跳过", "WARN")
        return False

    safe_topic = topic.replace(" ", "_").replace("/", "_")[:30]
    filename = f"tactic_{safe_topic}.md"
    filepath = memory_dir / filename

    source_meta = cmd_id
    if isinstance(record, dict) and record.get("source"):
        source_meta = f"{cmd_id} ({record.get('source')}/{record.get('provider') or '?'})"

    entry = f"""---
name: {topic}
description: {content[:80]}
type: project
domain: {domain}
---

{content}

来源: {source_meta} · {datetime.now().strftime('%Y-%m-%d')}
"""
    filepath.write_text(entry)
    record_metric("tactics_generated", cmd_id)
    log(f"战评官 → 项目 memory: {topic}", "OK")
    return True


def _write_global_tactic(tactic, cmd_id, *, record=None):
    """写入全局战法库；返回 True 表示落盘成功。"""
    summary = tactic.get("summary", "").strip()
    detail = tactic.get("detail", "").strip()
    domain = tactic.get("domain", "general")
    if not summary or not detail:
        return False

    # 检查容量，满了时淘汰 score=0 的
    existing = list(TACTICS_DIR.glob("*.md"))
    if len(existing) >= MAX_GLOBAL_TACTICS:
        _evict_tactics()
        existing = list(TACTICS_DIR.glob("*.md"))
        if len(existing) >= MAX_GLOBAL_TACTICS:
            log("战评官: 全局战法库已满且无可淘汰条目，跳过", "WARN")
            return False

    tactic_id = f"tactic-{uuid.uuid4().hex[:6]}"
    filename = f"{tactic_id}.md"
    filepath = TACTICS_DIR / filename

    source_meta = cmd_id
    commander_source = "legacy"
    if isinstance(record, dict):
        commander_source = record.get("source") or "legacy"
        if record.get("source"):
            source_meta = f"{cmd_id} ({record.get('source')}/{record.get('provider') or '?'})"

    entry = f"""---
id: {tactic_id}
domain: {domain}
score: 0
created: {datetime.now().strftime('%Y-%m-%d')}
last_cited: never
source: {source_meta}
commander_source: {commander_source}
summary: {summary}
---

{detail}
"""
    filepath.write_text(entry)
    log(f"战评官 → 全局战法: [{domain}] {summary}", "OK")
    return True


def _evict_tactics():
    """淘汰 score=0 的战法条目"""
    candidates = []
    for tf in TACTICS_DIR.glob("*.md"):
        try:
            content = tf.read_text()
            score = 0
            for line in content.split("\n"):
                if line.startswith("score:"):
                    score = int(line.split(":")[1].strip())
                    break
            if score == 0:
                candidates.append(tf)
        except Exception:
            pass

    # 按文件修改时间排序，最老的先淘汰
    candidates.sort(key=lambda f: f.stat().st_mtime)
    for c in candidates[:5]:  # 每次最多淘汰 5 个
        c.unlink()
        log(f"战评官淘汰战法: {c.name}", "WARN")


def cite_tactic(tactic_id):
    """参谋引用战法时调用，score +1"""
    for tf in TACTICS_DIR.glob("*.md"):
        content = tf.read_text()
        if f"id: {tactic_id}" in content:
            today = datetime.now().strftime('%Y-%m-%d')
            # 更新 score 和 last_cited
            lines = content.split("\n")
            new_lines = []
            for line in lines:
                if line.startswith("score:"):
                    old_score = int(line.split(":")[1].strip())
                    new_lines.append(f"score: {old_score + 1}")
                elif line.startswith("last_cited:"):
                    new_lines.append(f"last_cited: {today}")
                else:
                    new_lines.append(line)
            tf.write_text("\n".join(new_lines))
            return True
    return False


# ── 技能生成与管理 ──
GLOBAL_SKILLS_DIR = Path(os.path.expanduser("~/.claude/skills/generated"))
GLOBAL_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
MAX_GLOBAL_SKILLS = 30
MAX_PROJECT_SKILLS = 20


def _get_project_skills_dir():
    """获取当前项目的技能目录"""
    try:
        import subprocess as sp
        result = sp.run(["pwd"], capture_output=True, text=True, timeout=2)
        cwd = result.stdout.strip()
        safe_path = cwd.replace("/", "-")
        if safe_path.startswith("-"):
            safe_path = safe_path[1:]
        d = Path(os.path.expanduser(f"~/.claude/projects/-{safe_path}/skills"))
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        return None



def _write_generated_skill(skill, cmd_id, *, record=None):
    """战评官生成技能：按 Claude Code 官方 SKILL.md 规范，生成目录结构化的 skill。

    返回 True 表示落盘成功（用于 evidence 计数）。
    """
    name = skill.get("name", "").strip()
    description = skill.get("description", "").strip()
    pattern = skill.get("pattern", "tool-wrapper").strip()
    scope = skill.get("scope", "project").strip()
    skill_md = skill.get("skill_md", "").strip()
    scripts = skill.get("scripts", {})
    references = skill.get("references", {})
    gotchas = skill.get("gotchas", "").strip()

    if not name or not skill_md:
        return False

    # 根据 scope 选择父目录
    if scope == "global":
        parent_dir = Path(os.path.expanduser("~/.claude/skills"))
    else:
        project_skills = _get_project_skills_dir()
        if project_skills:
            # 项目 skill 放在 .claude/skills/ 下（Claude Code 能自动发现）
            parent_dir = Path(os.getcwd()) / ".claude" / "skills"
        else:
            parent_dir = Path(os.path.expanduser("~/.claude/skills"))
    parent_dir.mkdir(parents=True, exist_ok=True)

    skill_dir = parent_dir / name

    # 检查容量（统计同级 skill 目录数）
    max_skills = MAX_GLOBAL_SKILLS if scope == "global" else MAX_PROJECT_SKILLS
    existing = [d for d in parent_dir.iterdir() if d.is_dir() and (d / "SKILL.md").exists()]
    if len(existing) >= max_skills:
        _evict_skills_from_dir(parent_dir)
        existing = [d for d in parent_dir.iterdir() if d.is_dir() and (d / "SKILL.md").exists()]
        if len(existing) >= max_skills:
            log(f"战评官: 技能库已满 ({max_skills})，跳过", "WARN")
            return False

    # 验证脚本语法
    import subprocess as sp
    for script_name, script_content in scripts.items():
        if script_name.endswith(".sh"):
            try:
                result = sp.run(["bash", "-n"], input=script_content, capture_output=True, text=True, timeout=5)
                if result.returncode != 0:
                    log(f"战评官: 技能 {name}/{script_name} 语法错误，丢弃: {result.stderr[:100]}", "WARN")
                    return False
            except Exception:
                return False

    # 创建目录结构
    skill_dir.mkdir(parents=True, exist_ok=True)

    # 写入 SKILL.md（如果 LLM 没生成 frontmatter，补充一个）
    if not skill_md.startswith("---"):
        skill_md = f"""---
name: {name}
description: {description}
pattern: {pattern}
---

{skill_md}"""

    # 追加 gotchas 到 SKILL.md
    if gotchas:
        skill_md += f"\n\n## Gotchas\n\n{gotchas}\n"

    # 追加 references 导航
    if references:
        skill_md += "\n\n## References\n\n"
        for ref_name in references:
            skill_md += f"- [{ref_name}](references/{ref_name})\n"

    (skill_dir / "SKILL.md").write_text(skill_md)

    # 写入 scripts/
    if scripts:
        (skill_dir / "scripts").mkdir(exist_ok=True)
        for script_name, script_content in scripts.items():
            script_path = skill_dir / "scripts" / script_name
            script_path.write_text(script_content)
            script_path.chmod(0o755)

    # 写入 references/
    if references:
        (skill_dir / "references").mkdir(exist_ok=True)
        for ref_name, ref_content in references.items():
            (skill_dir / "references" / ref_name).write_text(ref_content)

    # 注册到 meta（用于 score 追踪和淘汰）
    meta_file = parent_dir / "_skills_meta.json"
    meta = read_json(meta_file, {"skills": {}})
    commander_source = "legacy"
    provider = None
    if isinstance(record, dict):
        commander_source = record.get("source") or "legacy"
        provider = record.get("provider")
    meta["skills"][name] = {
        "description": description,
        "pattern": pattern,
        "scope": scope,
        "source": cmd_id,
        "commander_source": commander_source,
        "provider": provider,
        "created": datetime.now().isoformat(),
        "score": 0
    }
    write_json(meta_file, meta)

    record_metric("skills_generated", cmd_id)
    log(f"战评官 → 新技能 [{scope}]: {name}/ (SKILL.md + {len(scripts)} scripts + {len(references)} refs)", "OK")
    return True


def cite_skill(skill_name):
    """军团使用技能时 score +1（查项目和全局两个 meta）"""
    search_dirs = []
    # 项目 .claude/skills/
    try:
        import subprocess as sp
        result = sp.run(["pwd"], capture_output=True, text=True, timeout=2)
        cwd = result.stdout.strip()
        search_dirs.append(Path(cwd) / ".claude" / "skills")
    except Exception:
        pass
    # 全局
    search_dirs.append(Path(os.path.expanduser("~/.claude/skills")))

    for skills_dir in search_dirs:
        meta_file = skills_dir / "_skills_meta.json"
        meta = read_json(meta_file, {"skills": {}})
        if skill_name in meta.get("skills", {}):
            meta["skills"][skill_name]["score"] = meta["skills"][skill_name].get("score", 0) + 1
            meta["skills"][skill_name]["last_cited"] = datetime.now().isoformat()
            write_json(meta_file, meta)
            return True
    return False


def _evict_skills_from_dir(parent_dir):
    """淘汰指定目录中 score=0 的技能（目录结构）"""
    meta_file = parent_dir / "_skills_meta.json"
    meta = read_json(meta_file, {"skills": {}})
    to_remove = []

    for name, info in meta.get("skills", {}).items():
        if info.get("score", 0) == 0:
            to_remove.append(name)

    to_remove.sort(key=lambda n: meta["skills"][n].get("created", ""))

    import shutil
    for name in to_remove[:5]:
        skill_dir = parent_dir / name
        if skill_dir.is_dir():
            shutil.rmtree(skill_dir)
        # 兼容旧格式（平铺文件）
        for ext in (".sh", ".md"):
            f = parent_dir / f"{name}{ext}"
            if f.exists():
                f.unlink()
        del meta["skills"][name]
        log(f"战评官淘汰技能: {name}", "WARN")

    write_json(meta_file, meta)


# ── 度量体系：追踪效率/合规/质量指标 ──
METRICS_FILE = LEGION_DIR / "metrics.json"


def _load_metrics():
    return read_json(METRICS_FILE, {
        "tasks_completed": 0,
        "total_tool_calls": 0,
        "warnings_issued": 0,
        "violations_issued": 0,
        "violations_overturned": 0,
        "audits_passed": 0,
        "audits_failed": 0,
        "recon_performed": 0,
        "recon_skipped": 0,
        "skills_generated": 0,
        "tactics_generated": 0,
        "by_commander": {}
    })


def _save_metrics(m):
    write_json(METRICS_FILE, m)


def record_metric(key, cmd_id=None, increment=1):
    """记录一个度量指标（线程安全）"""
    with _metrics_lock:
        m = _load_metrics()
        m[key] = m.get(key, 0) + increment
        if cmd_id:
            if cmd_id not in m["by_commander"]:
                m["by_commander"][cmd_id] = {}
            m["by_commander"][cmd_id][key] = m["by_commander"][cmd_id].get(key, 0) + increment
        _save_metrics(m)


def metrics_summary():
    """生成度量摘要"""
    m = _load_metrics()
    total_tasks = m.get("tasks_completed", 0)
    total_warnings = m.get("warnings_issued", 0)
    overturned = m.get("violations_overturned", 0)
    violations = m.get("violations_issued", 0)
    audit_pass = m.get("audits_passed", 0)
    audit_fail = m.get("audits_failed", 0)
    recon = m.get("recon_performed", 0)
    recon_skip = m.get("recon_skipped", 0)

    accuracy = f"{((violations - overturned) / violations * 100):.0f}%" if violations > 0 else "N/A"
    audit_rate = f"{(audit_pass / (audit_pass + audit_fail) * 100):.0f}%" if (audit_pass + audit_fail) > 0 else "N/A"
    recon_rate = f"{(recon / (recon + recon_skip) * 100):.0f}%" if (recon + recon_skip) > 0 else "N/A"

    return (f"任务: {total_tasks} | 纠察准确率: {accuracy} | "
            f"审计通过率: {audit_rate} | 侦察执行率: {recon_rate}")


# ── 协议自进化：战评官提出协议修改建议 ──
PROTOCOL_PROPOSALS_FILE = LEGION_DIR / "protocol_proposals.json"


def propose_protocol_change():
    """基于度量数据和历史模式，提出协议优化建议"""
    m = _load_metrics()
    memory = _load_inspector_memory()
    proposals = read_json(PROTOCOL_PROPOSALS_FILE, {"proposals": [], "applied": []})

    # 只有积累够数据才分析
    total_warnings = m.get("warnings_issued", 0)
    total_violations = m.get("violations_issued", 0)
    overturned = m.get("violations_overturned", 0)

    if total_warnings + total_violations < 5:
        return  # 数据不足

    issues = []

    # 检测1: 纠察误判率过高
    if total_violations > 0 and overturned / total_violations > 0.5:
        issues.append("纠察误判率超过50%，建议放宽 violation 判定标准")

    # 检测2: 侦察被大量跳过
    recon = m.get("recon_performed", 0)
    recon_skip = m.get("recon_skipped", 0)
    if recon + recon_skip > 5 and recon_skip / (recon + recon_skip) > 0.7:
        issues.append("侦察被跳过率超过70%，建议降低侦察强制性或优化参谋输出格式")

    # 检测3: 审计失败率过高
    audit_pass = m.get("audits_passed", 0)
    audit_fail = m.get("audits_failed", 0)
    if audit_pass + audit_fail > 5 and audit_fail / (audit_pass + audit_fail) > 0.5:
        issues.append("审计失败率超过50%，建议在执行阶段加入更多中间验证")

    if not issues:
        return

    # 用 LLM 生成具体建议
    issues_text = "\n".join(f"- {i}" for i in issues)
    prompt = f"""你是军团协议优化顾问。根据以下度量异常，提出具体的协议修改建议：

度量异常：
{issues_text}

当前度量：
{json.dumps(m, ensure_ascii=False, indent=2)}

已有协议修改提案（避免重复）：
{json.dumps([p.get('summary','') for p in proposals.get('proposals', [])[-5:]], ensure_ascii=False)}

输出 JSON（不要其他内容）：
{{
  "proposals": [
    {{"summary": "一句话建议", "detail": "具体修改方案", "severity": "low|medium|high"}}
  ]
}}
如果无需修改，返回 {{"proposals": []}}"""

    result_text = _call_claude(prompt)
    if not result_text:
        return

    try:
        import re
        match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if not match:
            return
        result = json.loads(match.group())
        new_proposals = result.get("proposals", [])
        if new_proposals:
            for p in new_proposals:
                p["ts"] = datetime.now().isoformat()
                p["status"] = "pending"
                p["proposal_id"] = f"prop-{uuid.uuid4().hex[:8]}"
            proposals["proposals"].extend(new_proposals)
            proposals["proposals"] = proposals["proposals"][-20:]  # 最多保留20条
            write_json(PROTOCOL_PROPOSALS_FILE, proposals)
            log(f"协议自进化: 提出 {len(new_proposals)} 条优化建议", "OK")
            for p in new_proposals:
                _record_evidence(
                    "protocol_proposal_added",
                    proposal_id=p.get("proposal_id"),
                    summary=str(p.get("summary", ""))[:200],
                    severity=p.get("severity"),
                    triggering_issues=issues,
                )
    except Exception as e:
        log(f"协议自进化异常: {e}", "WARN")


# ── 技能组合推荐：根据任务类型推荐 pattern 组合 ──
SKILL_COMBOS = {
    "新功能": "inversion + generator + reviewer（先细化需求→模板生成→审阅）",
    "bug修复": "systematic-debugging + reviewer（四阶段排障→审阅）",
    "重构": "pipeline + reviewer + git-worktree（分步执行+检查点+分支隔离）",
    "优化": "inversion + pipeline + reviewer（先问清目标→分步优化→审阅）",
    "集成": "tool-wrapper + pipeline + reviewer（包装API→串联步骤→审阅）",
    "测试": "test-driven-development + reviewer（红绿重构→审阅）",
}


def recommend_skill_combo(task_description):
    """根据任务描述推荐技能组合"""
    desc_lower = task_description.lower()
    for keyword, combo in SKILL_COMBOS.items():
        if keyword in desc_lower:
            return combo
    return None


# ── 主循环 ──
_start_time = time.monotonic()


def _safe_call(func, name):
    """安全调用函数，捕获异常并记录"""
    try:
        func()
    except Exception as e:
        log(f"{name}异常: {e}", "WARN")


def main():
    global _start_time
    _start_time = time.monotonic()

    init()
    log("=" * 50)
    log("Legion Commander 智慧中枢启动", "OK")
    log(f"轮询间隔: {POLL_INTERVAL}s")
    log("=" * 50)

    gc_counter = 0
    heartbeat_counter = 0
    stats_counter = 0
    commissar_counter = 0
    inspector_counter = 0
    review_counter = 0
    obs_analysis_counter = 0
    protocol_counter = 0

    # 异步 LLM 调用线程池（inspector/reviewer 不阻塞主循环）
    llm_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="llm")
    _pending_futures = []

    while True:
        try:
            # 心跳：每 20 轮（10s）
            heartbeat_counter += 1
            if heartbeat_counter >= 20:
                write_heartbeat()
                heartbeat_counter = 0

            # GC：每 60 轮（30s）
            gc_counter += 1
            if gc_counter >= 60:
                gc_broadcast()
                gc_inboxes()
                gc_tmp_files()
                gc_dead_commanders()
                gc_daemon_evidence()
                gc_counter = 0

            # 政委广播：和 GC 同频检查（每 30s），只有工具调用计数器跨越边界才真正广播
            commissar_counter += 1
            if commissar_counter >= 60:
                commissar_broadcast()
                commissar_counter = 0

            # 纠察巡查：每 240 轮（120s = 2分钟）
            inspector_counter += 1
            if inspector_counter >= int(INSPECTOR_INTERVAL_SECONDS / POLL_INTERVAL):
                # 清理已完成的 futures
                _pending_futures = [f for f in _pending_futures if not f.done()]
                if len(_pending_futures) < 2:  # 限制并发 LLM 调用数
                    future = llm_executor.submit(_safe_call, inspector_patrol, "纠察巡查")
                    _pending_futures.append(future)
                else:
                    log("跳过纠察巡查: LLM 调用队列满", "WARN")
                inspector_counter = 0

            # 战评官：每 240 轮（120s = 2分钟）
            review_counter += 1
            if review_counter >= int(REVIEW_INTERVAL_SECONDS / POLL_INTERVAL):
                _pending_futures = [f for f in _pending_futures if not f.done()]
                if len(_pending_futures) < 2:
                    future = llm_executor.submit(_safe_call, after_action_review, "战评官")
                    _pending_futures.append(future)
                else:
                    log("跳过战评: LLM 调用队列满", "WARN")
                obs_analysis_counter += 1
                if obs_analysis_counter >= 5:  # 每 5 次战评周期（约 10 分钟）分析一次
                    _pending_futures = [f for f in _pending_futures if not f.done()]
                    if len(_pending_futures) < 2:
                        future = llm_executor.submit(_safe_call, analyze_observations, "观察分析")
                        _pending_futures.append(future)
                    obs_analysis_counter = 0
                review_counter = 0

            # 统计：每 120 轮（60s）
            stats_counter += 1
            if stats_counter >= 120:
                teams = get_active_teams()
                uptime = int(time.monotonic() - _start_time)
                ms = metrics_summary()
                log(f"状态: {len(teams)} teams | uptime {uptime}s")
                log(f"度量: {ms}")
                stats_counter = 0

            # 协议自进化：每 3600 轮（30 分钟）分析度量异常并提出优化建议
            protocol_counter += 1
            if protocol_counter >= 3600:
                try:
                    propose_protocol_change()
                except Exception as e:
                    log(f"协议自进化异常: {e}", "WARN")
                protocol_counter = 0

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            log("Commander 收到终止信号，退出", "WARN")
            llm_executor.shutdown(wait=False)
            break
        except Exception as e:
            log(f"错误: {e}", "ERROR")
            time.sleep(1)


if __name__ == "__main__":
    main()
