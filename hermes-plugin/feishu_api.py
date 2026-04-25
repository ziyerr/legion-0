"""Feishu OpenAPI client for ProdMind.

Provides a minimal wrapper around the endpoints we need:
- tenant_access_token (with in-memory cache + auto-refresh)
- docx v1: create document + insert markdown-derived blocks
- im v1: send interactive card message

All public functions raise FeishuError on failure. Callers at the tool layer
catch and degrade gracefully so the main pipeline is never blocked.
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests


def _ensure_env_loaded() -> None:
    """Defensive: load ~/.hermes/.env if FEISHU creds are not already in env.

    Hermes normally exports these on process start, but offline utilities
    (one-off scripts, background syncs) may import this module without that
    bootstrap. Without it, the first API call raises "FEISHU_APP_ID not
    configured" even though the credentials exist on disk.
    """
    if os.environ.get("FEISHU_APP_ID"):
        return
    env_path = os.path.expanduser("~/.hermes/.env")
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and v and not os.environ.get(k):
                    os.environ[k] = v
    except Exception:
        pass


_ensure_env_loaded()


# ---------------------------------------------------------------------------
# Notification suppression
# ---------------------------------------------------------------------------
#
# Maintenance / ops scripts occasionally need to re-render or re-sync existing
# Feishu docs (e.g. reformat_lanling_prd.py) by calling save_research /
# create_prd / update_prd / evaluate_project. Without a suppression switch,
# every such re-run floods subscribed group chats with "system updates" —
# noise that has nothing to do with real product activity.
#
# The rule of thumb:
#   - System-level iterations (format tweaks, re-renders, migrations) = NO push
#   - Real product content changes (new research, new PRD, evaluation)  = push
#
# To opt into silent mode, export PRODMIND_SUPPRESS_NOTIFICATIONS=true before
# invoking the script, e.g.
#
#     PRODMIND_SUPPRESS_NOTIFICATIONS=true python3 maintenance_script.py
#
# Normal agent tool flow must NOT set this env var — it is an ops-only switch.
# Only high-level notification helpers (notify_project_channels) honour it;
# low-level API primitives (send_text_to_chat / send_card_message) stay
# unconditional so legitimate direct callers keep working.


def _should_suppress_notifications() -> bool:
    """Return True when PRODMIND_SUPPRESS_NOTIFICATIONS is set to a truthy value.

    Read dynamically from the environment on every call so maintenance scripts
    can toggle it at runtime without re-importing the module.
    """
    return os.environ.get("PRODMIND_SUPPRESS_NOTIFICATIONS", "").strip().lower() in (
        "true",
        "1",
        "yes",
    )


FEISHU_BASE = "https://open.feishu.cn"
TOKEN_REFRESH_BUFFER = 300  # refresh 5 minutes before expiry
REQUEST_TIMEOUT = 15

# Persistent state file for project → notification chat_id subscriptions.
PROJECT_CHANNELS_PATH = os.environ.get(
    "AICTO_PROJECT_CHANNELS",
    os.path.expanduser("~/.hermes/profiles/aicto/plugins/aicto/state/project_channels.json"),
)

# Hermes sessions index — used to infer current active Feishu chat.
HERMES_SESSIONS_PATH = os.path.expanduser("~/.hermes/sessions/sessions.json")


# Persistent state file for the auto-provisioned Bitable app.
# Overridable via env var for tests.
BITABLE_STATE_PATH = os.environ.get(
    "AICTO_BITABLE_STATE",
    os.path.expanduser("~/.hermes/profiles/aicto/plugins/aicto/state/bitable_state.json"),
)


class FeishuError(Exception):
    """Raised on any Feishu API failure (HTTP or business code)."""


# ---------------------------------------------------------------------------
# tenant_access_token cache
# ---------------------------------------------------------------------------

_cached_token: Optional[str] = None
_token_expires_at: float = 0.0


def _credentials() -> Tuple[str, str]:
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        raise FeishuError("FEISHU_APP_ID/FEISHU_APP_SECRET not configured")
    return app_id, app_secret


def get_tenant_access_token() -> str:
    """Return a cached tenant_access_token, refreshing if near expiry."""
    global _cached_token, _token_expires_at

    now = time.time()
    if _cached_token and now < _token_expires_at - TOKEN_REFRESH_BUFFER:
        return _cached_token

    app_id, app_secret = _credentials()
    resp = requests.post(
        f"{FEISHU_BASE}/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=REQUEST_TIMEOUT,
    )
    if not resp.ok:
        raise FeishuError(f"token HTTP {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    if data.get("code") != 0:
        raise FeishuError(f"token error {data.get('code')}: {data.get('msg')}")

    _cached_token = data["tenant_access_token"]
    _token_expires_at = now + int(data.get("expire", 7200))
    return _cached_token


def _auth_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {get_tenant_access_token()}",
        "Content-Type": "application/json; charset=utf-8",
    }


def _request(method: str, path: str, **kwargs) -> Dict[str, Any]:
    """Issue an authenticated request and return the parsed JSON body."""
    url = f"{FEISHU_BASE}{path}"
    headers = kwargs.pop("headers", {}) or {}
    headers.update(_auth_headers())
    resp = requests.request(
        method, url, headers=headers, timeout=REQUEST_TIMEOUT, **kwargs
    )
    if not resp.ok:
        raise FeishuError(f"{method} {path} HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if data.get("code") != 0:
        raise FeishuError(
            f"{method} {path} code={data.get('code')} msg={data.get('msg')}"
        )
    return data.get("data", {})


# ---------------------------------------------------------------------------
# Markdown -> docx block conversion
# ---------------------------------------------------------------------------

# Feishu docx block_type constants
BLOCK_TYPE_TEXT = 2
BLOCK_TYPE_H1 = 3
BLOCK_TYPE_H2 = 4
BLOCK_TYPE_H3 = 5
BLOCK_TYPE_H4 = 6
BLOCK_TYPE_H5 = 7
BLOCK_TYPE_H6 = 8
BLOCK_TYPE_BULLET = 12
BLOCK_TYPE_ORDERED = 13
BLOCK_TYPE_CODE = 14
BLOCK_TYPE_QUOTE = 15
BLOCK_TYPE_TODO = 17
BLOCK_TYPE_CALLOUT = 19
BLOCK_TYPE_DIVIDER = 22
BLOCK_TYPE_IMAGE = 27
BLOCK_TYPE_TABLE = 31
BLOCK_TYPE_TABLE_CELL = 32

_BLOCK_PROPERTY_KEY = {
    BLOCK_TYPE_TEXT: "text",
    BLOCK_TYPE_H1: "heading1",
    BLOCK_TYPE_H2: "heading2",
    BLOCK_TYPE_H3: "heading3",
    BLOCK_TYPE_H4: "heading4",
    BLOCK_TYPE_H5: "heading5",
    BLOCK_TYPE_H6: "heading6",
    BLOCK_TYPE_BULLET: "bullet",
    BLOCK_TYPE_ORDERED: "ordered",
    BLOCK_TYPE_CODE: "code",
    BLOCK_TYPE_QUOTE: "quote",
}

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_HIGHLIGHT_RE = re.compile(r"==(.+?)==")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _elements_from_inline(text: str) -> List[Dict[str, Any]]:
    """Convert a line of inline markdown into docx text_run elements.

    Very small parser: supports bold, italic, inline code, and links. Anything
    unmatched becomes plain text. This is enough for PM content (PRDs, reports).
    """
    if not text:
        return [{"text_run": {"content": "", "text_element_style": {}}}]

    # Tokenize by scanning for the earliest match of any inline pattern.
    segments: List[Tuple[str, Dict[str, Any]]] = []  # (content, style)
    remaining = text
    while remaining:
        matches = []
        for pattern, style in (
            (_BOLD_RE, {"bold": True}),
            (_ITALIC_RE, {"italic": True}),
            (_INLINE_CODE_RE, {"inline_code": True}),
            (_HIGHLIGHT_RE, {"background_color": 10}),
        ):
            m = pattern.search(remaining)
            if m:
                matches.append((m.start(), m.end(), m.group(1), style, None))
        link_match = _LINK_RE.search(remaining)
        if link_match:
            matches.append(
                (
                    link_match.start(),
                    link_match.end(),
                    link_match.group(1),
                    {},
                    link_match.group(2),
                )
            )

        if not matches:
            segments.append((remaining, {}))
            break

        matches.sort(key=lambda x: x[0])
        start, end, inner, style, link = matches[0]

        if start > 0:
            segments.append((remaining[:start], {}))
        seg_style = dict(style)
        if link:
            seg_style["link"] = {"url": link}
        segments.append((inner, seg_style))
        remaining = remaining[end:]

    elements: List[Dict[str, Any]] = []
    for content, style in segments:
        if not content:
            continue
        run: Dict[str, Any] = {"content": content}
        text_element_style: Dict[str, Any] = {}
        if style.get("bold"):
            text_element_style["bold"] = True
        if style.get("italic"):
            text_element_style["italic"] = True
        if style.get("inline_code"):
            text_element_style["inline_code"] = True
        if style.get("background_color"):
            text_element_style["background_color"] = style["background_color"]
        if "link" in style:
            text_element_style["link"] = style["link"]
        run["text_element_style"] = text_element_style
        elements.append({"text_run": run})

    if not elements:
        elements.append({"text_run": {"content": "", "text_element_style": {}}})
    return elements


def _build_block(block_type: int, inline_text: str) -> Dict[str, Any]:
    key = _BLOCK_PROPERTY_KEY[block_type]
    return {
        "block_type": block_type,
        key: {
            "elements": _elements_from_inline(inline_text),
            "style": {},
        },
    }


def _build_code_block(language: str, code: str) -> Dict[str, Any]:
    # language is unused (no enum mapping), but we keep the code verbatim.
    return {
        "block_type": BLOCK_TYPE_CODE,
        "code": {
            "elements": [
                {
                    "text_run": {
                        "content": code,
                        "text_element_style": {},
                    }
                }
            ],
            "style": {"language": 1, "wrap": True},
        },
    }


# Callout color mapping
_CALLOUT_PRESETS = {
    "note": {"emoji_id": "bulb", "background_color": 5, "border_color": 5},
    "warn": {"emoji_id": "fire", "background_color": 2, "border_color": 2},
    "tip": {"emoji_id": "star", "background_color": 4, "border_color": 4},
    "important": {"emoji_id": "pushpin", "background_color": 1, "border_color": 1},
    "success": {"emoji_id": "white_check_mark", "background_color": 4, "border_color": 4},
}


def _build_callout_blocks(callout_type: str, content_lines: List[str], new_id_fn) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Build a Callout block with child text blocks.

    Returns (callout_block, child_blocks) where child_blocks need to be added to descendants.
    """
    preset = _CALLOUT_PRESETS.get(callout_type, _CALLOUT_PRESETS["note"])

    child_blocks = []
    child_ids = []
    for line in content_lines:
        if not line.strip():
            continue
        child_id = new_id_fn()
        child_ids.append(child_id)
        child_blocks.append({
            "block_id": child_id,
            "block_type": BLOCK_TYPE_TEXT,
            "text": {
                "elements": _elements_from_inline(line.strip()),
                "style": {},
            },
        })

    if not child_blocks:
        child_id = new_id_fn()
        child_ids.append(child_id)
        child_blocks.append({
            "block_id": child_id,
            "block_type": BLOCK_TYPE_TEXT,
            "text": {
                "elements": [{"text_run": {"content": "", "text_element_style": {}}}],
                "style": {},
            },
        })

    callout_block = {
        "block_id": new_id_fn(),
        "block_type": BLOCK_TYPE_CALLOUT,
        "callout": {
            "emoji_id": preset["emoji_id"],
            "background_color": preset["background_color"],
            "border_color": preset["border_color"],
        },
        "children": child_ids,
    }

    return callout_block, child_blocks


def _build_todo_block(text: str, checked: bool = False) -> Dict[str, Any]:
    """Build a Todo/checkbox block."""
    return {
        "block_type": BLOCK_TYPE_TODO,
        "todo": {
            "elements": _elements_from_inline(text),
            "style": {
                "done": checked,
            },
        },
    }


# ---------------------------------------------------------------------------
# Mermaid rendering (Kroki) + Feishu image upload
# ---------------------------------------------------------------------------

KROKI_URL = "https://kroki.io/mermaid/png"

_MERMAID_BLOCK_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)


def _render_mermaid_to_png(mermaid_code: str) -> Optional[bytes]:
    """Render Mermaid code to PNG via Kroki API."""
    try:
        resp = requests.post(
            KROKI_URL,
            data=mermaid_code.encode("utf-8"),
            headers={"Content-Type": "text/plain"},
            timeout=15,
        )
        if resp.status_code == 200 and len(resp.content) > 100:
            return resp.content
    except Exception as e:
        print(f"[feishu_api] Mermaid render failed: {e}")
    return None


def _upload_image_to_feishu(
    image_bytes: bytes,
    file_name: str = "diagram.png",
    parent_type: str = "docx_image",
    parent_node: str = "",
) -> Optional[str]:
    """Upload an image to Feishu and return the file_token."""
    token = get_tenant_access_token()
    boundary = "----FormBoundary" + str(int(time.time()))

    parts: List[bytes] = []

    for field_name, field_value in [
        ("file_name", file_name),
        ("parent_type", parent_type),
        ("parent_node", parent_node),
        ("size", str(len(image_bytes))),
    ]:
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{field_name}"\r\n\r\n'.encode()
        )
        parts.append(f"{field_value}\r\n".encode())

    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'.encode()
    )
    parts.append(b"Content-Type: image/png\r\n\r\n")
    parts.append(image_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode())

    body_bytes = b"".join(parts)

    try:
        resp = requests.post(
            f"{FEISHU_BASE}/open-apis/drive/v1/medias/upload_all",
            data=body_bytes,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            timeout=30,
        )
        if resp.ok:
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("file_token")
            else:
                print(f"[feishu_api] image upload error: {data}")
        else:
            print(f"[feishu_api] image upload HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[feishu_api] image upload failed: {e}")
    return None


def _insert_mermaid_images(document_id: str, markdown: str) -> None:
    """Find mermaid code blocks in markdown, render to PNG, insert as images.

    Called after document creation/update. Each mermaid block is rendered via
    Kroki, uploaded to Feishu, and appended as an Image block (type 27) to the
    document root. If rendering or upload fails for any block, it is silently
    skipped (the mermaid source was already excluded from the code blocks, so
    there is no fallback text -- but this is acceptable since Kroki is highly
    reliable for valid Mermaid syntax).
    """
    matches = _MERMAID_BLOCK_RE.findall(markdown or "")
    if not matches:
        return

    for mermaid_code in matches:
        png_bytes = _render_mermaid_to_png(mermaid_code.strip())
        if not png_bytes:
            continue
        file_token = _upload_image_to_feishu(
            png_bytes,
            parent_type="docx_image",
            parent_node=document_id,
        )
        if not file_token:
            continue
        try:
            _request(
                "POST",
                f"/open-apis/docx/v1/documents/{document_id}/blocks/{document_id}/children",
                json={
                    "children": [
                        {
                            "block_type": BLOCK_TYPE_IMAGE,
                            "image": {"token": file_token},
                        }
                    ],
                    "index": -1,
                },
            )
        except Exception as e:
            print(f"[feishu_api] insert mermaid image block failed: {e}")


def _is_table_separator(line: str) -> bool:
    """Check if a line looks like a markdown table separator: | --- | --- |"""
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return False
    inner = stripped[1:-1]
    cells = [c.strip() for c in inner.split("|")]
    if not cells:
        return False
    for c in cells:
        if not re.match(r"^:?-{2,}:?$", c):
            return False
    return True


def _parse_table_row(line: str) -> List[str]:
    """Parse a markdown table row into a list of cell strings."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [c.strip() for c in stripped.split("|")]


# Content-aware table sizing constants. Tuned for Feishu docx body width.
_DOCX_MAX_TABLE_WIDTH = 900  # Typical docx page content width in pixels
_MIN_COL_WIDTH = 70          # Minimum per-column width to avoid collapsed cells
_MAX_COL_WIDTH = 420         # Cap per-column width to avoid one column eating the row
_CELL_HPADDING = 24          # Extra pixels per cell for padding/border


def _measure_cell_width(text: str) -> int:
    """Estimate rendered pixel width of a cell's longest line.

    Heuristic: CJK chars ~16px, ASCII chars ~8px, other ~12px. Takes the
    widest single line in the cell (so multi-line content doesn't over-
    estimate horizontal space).
    """
    if not text:
        return 0
    widest = 0
    for line in str(text).splitlines() or [""]:
        w = 0
        for ch in line:
            code = ord(ch)
            if code < 128:
                w += 8       # ASCII
            elif 0x4E00 <= code <= 0x9FFF or 0x3000 <= code <= 0x303F:
                w += 16      # CJK
            elif 0xFF00 <= code <= 0xFFEF:
                w += 16      # Fullwidth punctuation
            else:
                w += 12
        if w > widest:
            widest = w
    return widest


def _compute_column_widths(rows: List[List[str]], col_count: int) -> List[int]:
    """Compute per-column widths based on cell content.

    Algorithm:
      1. For each column, find the widest rendered cell (by _measure_cell_width).
      2. Add padding, clamp to [_MIN_COL_WIDTH, _MAX_COL_WIDTH].
      3. If total exceeds _DOCX_MAX_TABLE_WIDTH, scale down proportionally
         while preserving minimums (the excess is trimmed from the widest cols).
    """
    if col_count <= 0:
        return []

    raw: List[int] = []
    for ci in range(col_count):
        max_w = 0
        for row in rows:
            if ci < len(row):
                w = _measure_cell_width(row[ci])
                if w > max_w:
                    max_w = w
        raw.append(max(_MIN_COL_WIDTH, min(_MAX_COL_WIDTH, max_w + _CELL_HPADDING)))

    total = sum(raw)
    if total <= _DOCX_MAX_TABLE_WIDTH:
        return raw

    # Over budget: scale down but preserve minimum widths.
    # Compute scalable excess above minimum for each column and shrink proportionally.
    excess_per_col = [w - _MIN_COL_WIDTH for w in raw]
    total_excess = sum(excess_per_col)
    budget_excess = _DOCX_MAX_TABLE_WIDTH - (_MIN_COL_WIDTH * col_count)
    if budget_excess <= 0 or total_excess <= 0:
        return [_MIN_COL_WIDTH] * col_count
    scaled: List[int] = []
    for ex in excess_per_col:
        share = int(round(ex * budget_excess / total_excess))
        scaled.append(_MIN_COL_WIDTH + share)
    # Correct rounding drift
    diff = _DOCX_MAX_TABLE_WIDTH - sum(scaled)
    if diff != 0 and scaled:
        scaled[scaled.index(max(scaled))] += diff
    return scaled


def markdown_to_blocks(markdown: str) -> List[Dict[str, Any]]:
    """Parse markdown into flat docx blocks (no tables, no nested structure).

    For full rendering with tables, use markdown_to_descendants.
    """
    blocks: List[Dict[str, Any]] = []
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        stripped = line.lstrip()

        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            i += 1
            code_lines: List[str] = []
            while i < len(lines) and not lines[i].lstrip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            # Mermaid blocks are rendered as images in post-processing;
            # skip generating a code block so only the image appears.
            if lang.lower() == "mermaid":
                continue
            blocks.append(_build_code_block(lang, "\n".join(code_lines)))
            continue

        if not stripped:
            i += 1
            continue

        if stripped.startswith("###### "):
            blocks.append(_build_block(BLOCK_TYPE_H6, stripped[7:].strip()))
        elif stripped.startswith("##### "):
            blocks.append(_build_block(BLOCK_TYPE_H5, stripped[6:].strip()))
        elif stripped.startswith("#### "):
            blocks.append(_build_block(BLOCK_TYPE_H4, stripped[5:].strip()))
        elif stripped.startswith("### "):
            blocks.append(_build_block(BLOCK_TYPE_H3, stripped[4:].strip()))
        elif stripped.startswith("## "):
            blocks.append(_build_block(BLOCK_TYPE_H2, stripped[3:].strip()))
        elif stripped.startswith("# "):
            blocks.append(_build_block(BLOCK_TYPE_H1, stripped[2:].strip()))
        elif stripped.startswith("- [ ] ") or stripped.startswith("- [x] ") or stripped.startswith("- [X] "):
            checked = stripped[3] in ("x", "X")
            blocks.append(_build_todo_block(stripped[6:].strip(), checked))
        elif stripped.startswith("- ") or stripped.startswith("* "):
            blocks.append(_build_block(BLOCK_TYPE_BULLET, stripped[2:].strip()))
        elif re.match(r"^\d+\.\s+", stripped):
            content = re.sub(r"^\d+\.\s+", "", stripped)
            blocks.append(_build_block(BLOCK_TYPE_ORDERED, content))
        elif stripped.startswith("> "):
            blocks.append(_build_block(BLOCK_TYPE_QUOTE, stripped[2:].strip()))
        elif stripped in ("---", "***", "___"):
            blocks.append({"block_type": BLOCK_TYPE_DIVIDER, "divider": {}})
        else:
            blocks.append(_build_block(BLOCK_TYPE_TEXT, stripped))

        i += 1

    if not blocks:
        blocks.append(_build_block(BLOCK_TYPE_TEXT, ""))
    return blocks


def markdown_to_descendants(markdown: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Parse markdown into (children_id, descendants) for descendants API.

    Supports tables as real Feishu table blocks with nested cells.
    Returns (top_level_block_ids, flat_descendants_list).
    """
    children_id: List[str] = []
    descendants: List[Dict[str, Any]] = []
    id_counter = [0]
    # Stack of (indent_level, block) for tracking nested list items
    list_stack: List[Tuple[int, Dict[str, Any]]] = []

    def new_id() -> str:
        id_counter[0] += 1
        return f"b_{id_counter[0]}"

    def make_block(
        block_type: int,
        inline_text: str = "",
        *,
        indentation_level: Optional[int] = None,
    ) -> Dict[str, Any]:
        key = _BLOCK_PROPERTY_KEY.get(block_type)
        entry: Dict[str, Any] = {
            "block_id": new_id(),
            "block_type": block_type,
        }
        if key:
            style: Dict[str, Any] = {}
            # Ordered lists need sequence: "auto" for Feishu to render the
            # numbering. Without this, no 1. 2. 3. shows up.
            if block_type == BLOCK_TYPE_ORDERED:
                style["sequence"] = "auto"
            # NOTE: Do not set `indentation_level` here. The Feishu
            # create_document_block_descendant endpoint rejects it in two
            # distinct ways:
            #   * numeric string ("1")          -> 400 / 99992402 "field
            #     validation failed" ("options: [NoIndent, OneLevelIndent]")
            #   * enum literal ("OneLevelIndent" or "NoIndent") -> HTTP 200
            #     with business code 4000501 "open api operation and block
            #     not match"
            # The endpoint simply does not allow setting this field on
            # creation; it must be set via a follow-up update-block call.
            # Since deep list nesting has marginal visual value for PRD
            # content, we flatten all nested list items to level 0 and
            # keep the descendants insert path table-capable.
            # The `indentation_level` parameter is accepted for backward
            # compatibility but intentionally ignored.
            _ = indentation_level
            entry[key] = {
                "elements": _elements_from_inline(inline_text),
                "style": style,
            }
        return entry

    def make_text(inline_text: str) -> Dict[str, Any]:
        return make_block(BLOCK_TYPE_TEXT, inline_text)

    def make_divider() -> Dict[str, Any]:
        return {
            "block_id": new_id(),
            "block_type": BLOCK_TYPE_DIVIDER,
            "divider": {},
        }

    def make_code(lang: str, code: str) -> Dict[str, Any]:
        return {
            "block_id": new_id(),
            "block_type": BLOCK_TYPE_CODE,
            "code": {
                "elements": [
                    {
                        "text_run": {
                            "content": code,
                            "text_element_style": {},
                        }
                    }
                ],
                "style": {"language": 1, "wrap": True},
            },
        }

    def add_top(entry: Dict[str, Any]) -> None:
        children_id.append(entry["block_id"])
        descendants.append(entry)

    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        stripped = line.lstrip()

        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            i += 1
            code_lines: List[str] = []
            while i < len(lines) and not lines[i].lstrip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            # Mermaid blocks are rendered as images in post-processing;
            # skip generating a code block so only the image appears.
            if lang.lower() == "mermaid":
                continue
            add_top(make_code(lang, "\n".join(code_lines)))
            continue

        # Table detection: header row followed by separator row
        if stripped.startswith("|") and i + 1 < len(lines) and _is_table_separator(lines[i + 1]):
            header_cells = _parse_table_row(lines[i])
            col_count = len(header_cells)
            i += 2
            body_rows: List[List[str]] = []
            while i < len(lines):
                row_line = lines[i].strip()
                if not row_line.startswith("|"):
                    break
                row_cells = _parse_table_row(lines[i])
                while len(row_cells) < col_count:
                    row_cells.append("")
                row_cells = row_cells[:col_count]
                body_rows.append(row_cells)
                i += 1

            row_count = 1 + len(body_rows)
            all_rows = [header_cells] + body_rows

            # Compute content-aware column widths so tables fit the page
            # and each column's width reflects its content length.
            column_widths = _compute_column_widths(all_rows, col_count)

            # Build nested: table > cells > text
            table_block: Dict[str, Any] = {
                "block_id": new_id(),
                "block_type": BLOCK_TYPE_TABLE,
                "table": {
                    "property": {
                        "row_size": row_count,
                        "column_size": col_count,
                        "column_width": column_widths,
                        "header_row": True,
                    }
                },
                "children": [],
            }
            cell_blocks: List[Dict[str, Any]] = []
            text_blocks: List[Dict[str, Any]] = []
            for row in all_rows:
                for cell_text in row:
                    text_block = make_text(cell_text)
                    cell_block = {
                        "block_id": new_id(),
                        "block_type": BLOCK_TYPE_TABLE_CELL,
                        "table_cell": {},
                        "children": [text_block["block_id"]],
                    }
                    table_block["children"].append(cell_block["block_id"])
                    cell_blocks.append(cell_block)
                    text_blocks.append(text_block)

            children_id.append(table_block["block_id"])
            descendants.append(table_block)
            descendants.extend(cell_blocks)
            descendants.extend(text_blocks)
            continue

        # Callout detection: :::note / :::warn / :::tip / :::important / :::success
        if stripped.startswith(":::") and not stripped == ":::":
            callout_type = stripped[3:].strip().lower()
            if callout_type in _CALLOUT_PRESETS:
                i += 1
                callout_lines = []
                while i < len(lines) and not lines[i].strip().startswith(":::"):
                    callout_lines.append(lines[i])
                    i += 1
                if i < len(lines):
                    i += 1  # skip closing :::
                callout_block, child_blocks = _build_callout_blocks(
                    callout_type, callout_lines, new_id
                )
                children_id.append(callout_block["block_id"])
                descendants.append(callout_block)
                descendants.extend(child_blocks)
                continue

        if not stripped:
            i += 1
            continue

        # Heading: shift up so PRD subsections stay visually distinct.
        # Feishu's H5/H6 look identical to bold body text, so we never emit
        # them. We use H2/H3/H4 which are all visually prominent.
        #   # title → H2 (biggest body heading, rarely used)
        #   ## section → H3 (main sections — most common)
        #   ### subsection → H4 (sub-headings, still visibly a heading)
        #   #### and deeper → H4 (cap)
        heading_map = {
            "# ": BLOCK_TYPE_H2,
            "## ": BLOCK_TYPE_H3,
            "### ": BLOCK_TYPE_H4,
            "#### ": BLOCK_TYPE_H4,
            "##### ": BLOCK_TYPE_H4,
            "###### ": BLOCK_TYPE_H4,
        }
        matched_heading = False
        for prefix, block_type in sorted(heading_map.items(), key=lambda x: -len(x[0])):
            if stripped.startswith(prefix):
                add_top(make_block(block_type, stripped[len(prefix):].strip()))
                matched_heading = True
                break

        if matched_heading:
            i += 1
            continue

        # Todo detection: - [ ] or - [x] / - [X]
        if stripped.startswith("- [ ] ") or stripped.startswith("- [x] ") or stripped.startswith("- [X] "):
            checked = stripped[3] in ("x", "X")
            text = stripped[6:].strip()
            todo_block = _build_todo_block(text, checked)
            todo_block["block_id"] = new_id()
            children_id.append(todo_block["block_id"])
            descendants.append(todo_block)
            i += 1
            continue

        # Nested list detection: track indent level on the original line
        # (not stripped), allowing nested bullets/ordered items under ordered
        # parents. Format: "1. item" or "- item" or "* item".
        list_match = re.match(r"^(\s*)(\d+\.\s+|[-*]\s+)(.*)$", line)
        if list_match:
            indent_str, marker, item_text = list_match.groups()
            indent_level = len(indent_str) // 2  # 2 spaces per level
            is_ordered = marker.strip().endswith(".")
            block_type = BLOCK_TYPE_ORDERED if is_ordered else BLOCK_TYPE_BULLET
            item_block = make_block(
                block_type,
                item_text.strip(),
                indentation_level=indent_level,
            )

            if indent_level == 0 or not list_stack:
                add_top(item_block)
                # Reset list stack to this top-level item
                list_stack[:] = [(0, item_block)]
            else:
                # Pop stack to find parent at indent_level - 1
                while list_stack and list_stack[-1][0] >= indent_level:
                    list_stack.pop()
                if list_stack:
                    parent_level, parent_block = list_stack[-1]
                    parent_block.setdefault("children", []).append(item_block["block_id"])
                    descendants.append(item_block)
                else:
                    add_top(item_block)
                list_stack.append((indent_level, item_block))
            i += 1
            continue
        else:
            # Non-list line resets the stack
            list_stack.clear()

        if stripped.startswith("> "):
            add_top(make_block(BLOCK_TYPE_QUOTE, stripped[2:].strip()))
        elif stripped in ("---", "***", "___"):
            add_top(make_divider())
        else:
            add_top(make_text(stripped))

        i += 1

    if not children_id:
        add_top(make_text(""))

    return children_id, descendants


# ---------------------------------------------------------------------------
# docx v1 API helpers
# ---------------------------------------------------------------------------


def _insert_children(document_id: str, blocks: List[Dict[str, Any]]) -> None:
    """Append flat blocks as children of the document root. Chunks of <=50."""
    if not blocks:
        return
    path = (
        f"/open-apis/docx/v1/documents/{document_id}/blocks/{document_id}/children"
    )
    chunk_size = 50
    for offset in range(0, len(blocks), chunk_size):
        chunk = blocks[offset : offset + chunk_size]
        _request(
            "POST",
            path,
            json={"children": chunk, "index": -1},
        )


def _insert_descendants(
    document_id: str,
    children_id: List[str],
    descendants: List[Dict[str, Any]],
) -> None:
    """Insert a full descendants tree via the descendants API.

    Supports tables and other nested structures. Chunks automatically
    if the descendants list is very large.
    """
    if not children_id or not descendants:
        return

    path = (
        f"/open-apis/docx/v1/documents/{document_id}/blocks/{document_id}/descendant"
    )

    # Feishu limits descendants to ~1000 blocks per call. Chunk if needed,
    # but keep table structures intact (each table + its cells + texts go
    # together).
    # For simplicity, assume typical PRDs fit in one call.
    # If chunking is needed, split at table boundaries.
    max_per_call = 800
    if len(descendants) <= max_per_call:
        _request(
            "POST",
            path,
            json={
                "children_id": children_id,
                "index": -1,
                "descendants": descendants,
            },
        )
        return

    # Chunk while respecting structure: walk children_id and collect
    # all descendants reachable from each top-level block, then group.
    id_to_block = {d["block_id"]: d for d in descendants}

    def collect_subtree(block_id: str, out: List[Dict[str, Any]]) -> None:
        block = id_to_block.get(block_id)
        if not block:
            return
        out.append(block)
        for child_id in block.get("children", []):
            collect_subtree(child_id, out)

    current_top: List[str] = []
    current_desc: List[Dict[str, Any]] = []
    for top_id in children_id:
        subtree: List[Dict[str, Any]] = []
        collect_subtree(top_id, subtree)
        if current_desc and len(current_desc) + len(subtree) > max_per_call:
            _request(
                "POST",
                path,
                json={
                    "children_id": current_top,
                    "index": -1,
                    "descendants": current_desc,
                },
            )
            current_top = []
            current_desc = []
        current_top.append(top_id)
        current_desc.extend(subtree)

    if current_desc:
        _request(
            "POST",
            path,
            json={
                "children_id": current_top,
                "index": -1,
                "descendants": current_desc,
            },
        )


def _extract_doc_id(url_or_id: str) -> str:
    """Extract document_id from a Feishu URL or return as-is if already an ID.

    Supported URL patterns:
      https://xxx.feishu.cn/docx/XXXXX
      https://xxx.feishu.cn/docs/XXXXX
      https://xxx.feishu.cn/wiki/XXXXX
      https://xxx.larkoffice.com/docx/XXXXX
    """
    m = re.search(r"/(docx|docs|wiki)/([A-Za-z0-9]+)", url_or_id)
    if m:
        return m.group(2)
    return url_or_id.strip()


def _extract_block_text(block: dict, block_type: int) -> str:
    """Extract readable text from a single docx block.

    Converts Feishu block JSON into a simplified Markdown line. Handles
    text, headings (h1-h6), bullets, ordered lists, quotes, code, todos,
    tables (placeholder), and dividers.
    """
    type_key_map = {
        BLOCK_TYPE_TEXT: "text",
        BLOCK_TYPE_H1: "heading1",
        BLOCK_TYPE_H2: "heading2",
        BLOCK_TYPE_H3: "heading3",
        BLOCK_TYPE_H4: "heading4",
        BLOCK_TYPE_H5: "heading5",
        BLOCK_TYPE_H6: "heading6",
        BLOCK_TYPE_BULLET: "bullet",
        BLOCK_TYPE_ORDERED: "ordered",
        BLOCK_TYPE_CODE: "code",
        BLOCK_TYPE_QUOTE: "quote",
        BLOCK_TYPE_TODO: "todo",
    }

    key = type_key_map.get(block_type)
    if key:
        prop = block.get(key, {})
        elements = prop.get("elements", [])
        text_parts: List[str] = []
        for elem in elements:
            tr = elem.get("text_run", {})
            content = tr.get("content", "")
            if content:
                text_parts.append(content)
        text = "".join(text_parts)

        if block_type == BLOCK_TYPE_H1:
            return f"# {text}"
        if block_type == BLOCK_TYPE_H2:
            return f"## {text}"
        if block_type == BLOCK_TYPE_H3:
            return f"### {text}"
        if block_type in (BLOCK_TYPE_H4, BLOCK_TYPE_H5, BLOCK_TYPE_H6):
            return f"#### {text}"
        if block_type == BLOCK_TYPE_BULLET:
            return f"- {text}"
        if block_type == BLOCK_TYPE_ORDERED:
            return f"1. {text}"
        if block_type == BLOCK_TYPE_QUOTE:
            return f"> {text}"
        if block_type == BLOCK_TYPE_TODO:
            done = prop.get("style", {}).get("done", False)
            return f"- [{'x' if done else ' '}] {text}"
        return text

    if block_type == BLOCK_TYPE_TABLE:
        return "[table]"

    if block_type == BLOCK_TYPE_DIVIDER:
        return "---"

    return ""


def read_docx_content(document_id_or_url: str) -> str:
    """Read all content from a Feishu document and return simplified Markdown.

    Accepts either a Feishu URL (feishu.cn or larkoffice.com) or a raw
    document_id. Paginates through all blocks and converts each to a
    readable text line.
    """
    doc_id = _extract_doc_id(document_id_or_url)

    blocks: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
    while True:
        params: Dict[str, Any] = {"page_size": 500, "document_revision_id": -1}
        if page_token:
            params["page_token"] = page_token
        data = _request(
            "GET",
            f"/open-apis/docx/v1/documents/{doc_id}/blocks",
            params=params,
        )
        items = data.get("items", [])
        blocks.extend(items)
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
        if not page_token:
            break

    lines: List[str] = []
    for block in blocks:
        bt = block.get("block_type", 0)
        text = _extract_block_text(block, bt)
        if text:
            lines.append(text)

    return "\n".join(lines)


def _list_root_children(document_id: str) -> List[str]:
    """Return ordered block_ids under the root (excluding root itself)."""
    path = f"/open-apis/docx/v1/documents/{document_id}/blocks"
    block_ids: List[str] = []
    page_token: Optional[str] = None
    while True:
        params: Dict[str, Any] = {"page_size": 500, "document_revision_id": -1}
        if page_token:
            params["page_token"] = page_token
        data = _request("GET", path, params=params)
        for block in data.get("items", []):
            if block.get("block_id") == document_id:
                continue
            # Only direct children of root
            if block.get("parent_id") == document_id:
                block_ids.append(block["block_id"])
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
        if not page_token:
            break
    return block_ids


def _delete_root_children(document_id: str, count: int) -> None:
    if count <= 0:
        return
    path = (
        f"/open-apis/docx/v1/documents/{document_id}/blocks/"
        f"{document_id}/children/batch_delete"
    )
    # Feishu quirk: this sub-resource uses HTTP DELETE with a JSON body that
    # specifies the [start_index, end_index) range to remove from the parent.
    _request(
        "DELETE",
        path,
        json={"start_index": 0, "end_index": count},
    )


def _tenant_doc_url(document_id: str) -> str:
    """Build tenant-specific docx URL.

    Reads tenant subdomain from bitable_state.json (written when bitable app
    is initialized). Falls back to generic docs.feishu.cn if unavailable.
    """
    try:
        import re
        state = _load_bitable_state()
        if state and state.get("url"):
            m = re.match(r"https://([^/]+)/", state["url"])
            if m:
                return f"https://{m.group(1)}/docx/{document_id}"
    except Exception:
        pass
    return f"https://docs.feishu.cn/docx/{document_id}"


def _grant_doc_tenant_read(document_id: str) -> None:
    """Grant tenant-wide EDIT access on a docx so any enterprise member can edit.

    (2026-04-23) 用户要求：团队开发权限必须默认开启。升级 link_share_entity 从
    tenant_readable → tenant_editable，并把 manage_collaborator 从 can_view →
    can_edit 以允许协作者添加新协作者。函数名保留 _grant_doc_tenant_read 以
    不破坏调用方，实际行为是 edit 权限。

    Uses PATCH /open-apis/drive/v1/permissions/{token}/public. Silently ignores
    failures — permission grant is best-effort and must not block doc creation.
    """
    try:
        _request(
            "PATCH",
            f"/open-apis/drive/v1/permissions/{document_id}/public",
            params={"type": "docx"},
            json={
                "link_share_entity": "tenant_editable",
                "external_access_entity": "open",
                "security_entity": "anyone_can_view",
                "comment_entity": "anyone_can_edit",
                "share_entity": "anyone",
                "manage_collaborator_entity": "collaborator_can_edit",
                "view_entity": "anyone",
            },
        )
    except Exception as e:
        print(f"[feishu_api] Warning: failed to grant doc permissions: {e}")


def create_docx(title: str, markdown_content: str) -> Dict[str, str]:
    """Create a new Feishu docx, insert content, and grant tenant read access.

    Uses the descendants API to properly render tables, nested structures,
    and all markdown block types.

    Returns {"document_id", "url"}.
    """
    data = _request(
        "POST",
        "/open-apis/docx/v1/documents",
        json={"title": title or "Untitled", "folder_token": ""},
    )
    document = data.get("document", {})
    document_id = document.get("document_id")
    if not document_id:
        raise FeishuError("create docx: missing document_id in response")

    children_id, descendants = markdown_to_descendants(markdown_content or "")
    try:
        _insert_descendants(document_id, children_id, descendants)
    except Exception as e:
        print(f"[feishu_api] descendants insert failed: {e}")
        # Retry: strip callout blocks (may be unsupported), keep tables
        stripped_children = []
        stripped_descendants = []
        callout_child_ids = set()
        for d in descendants:
            if d.get("block_type") == BLOCK_TYPE_CALLOUT:
                # Collect callout's children IDs to also skip
                for cid in d.get("children", []):
                    callout_child_ids.add(cid)
                continue
            if d.get("block_id") in callout_child_ids:
                continue
            stripped_descendants.append(d)
        for cid in children_id:
            if any(d.get("block_id") == cid and d.get("block_type") == BLOCK_TYPE_CALLOUT for d in descendants):
                continue
            stripped_children.append(cid)
        try:
            if stripped_children:
                _insert_descendants(document_id, stripped_children, stripped_descendants)
                print(f"[feishu_api] retry without callouts succeeded")
            else:
                raise Exception("no blocks left after stripping callouts")
        except Exception as e2:
            print(f"[feishu_api] retry also failed, falling back to flat: {e2}")
            blocks = markdown_to_blocks(markdown_content or "")
            _insert_children(document_id, blocks)

    # Render any mermaid code blocks as images and append to the document
    _insert_mermaid_images(document_id, markdown_content or "")

    # Grant tenant-wide read access so users can actually open the doc
    _grant_doc_tenant_read(document_id)

    return {
        "document_id": document_id,
        "url": _tenant_doc_url(document_id),
    }


def update_docx(document_id: str, markdown_content: str) -> Dict[str, str]:
    """Replace the body of an existing docx with new markdown content."""
    if not document_id:
        raise FeishuError("update docx: document_id is required")

    existing = _list_root_children(document_id)
    if existing:
        _delete_root_children(document_id, len(existing))

    children_id, descendants = markdown_to_descendants(markdown_content or "")
    try:
        _insert_descendants(document_id, children_id, descendants)
    except Exception as e:
        print(f"[feishu_api] descendants insert failed: {e}")
        stripped_children = []
        stripped_descendants = []
        callout_child_ids = set()
        for d in descendants:
            if d.get("block_type") == BLOCK_TYPE_CALLOUT:
                for cid in d.get("children", []):
                    callout_child_ids.add(cid)
                continue
            if d.get("block_id") in callout_child_ids:
                continue
            stripped_descendants.append(d)
        for cid in children_id:
            if any(d.get("block_id") == cid and d.get("block_type") == BLOCK_TYPE_CALLOUT for d in descendants):
                continue
            stripped_children.append(cid)
        try:
            if stripped_children:
                _insert_descendants(document_id, stripped_children, stripped_descendants)
                print(f"[feishu_api] retry without callouts succeeded")
            else:
                raise Exception("no blocks left after stripping callouts")
        except Exception as e2:
            print(f"[feishu_api] retry also failed, falling back to flat: {e2}")
            blocks = markdown_to_blocks(markdown_content or "")
            _insert_children(document_id, blocks)

    # Render any mermaid code blocks as images and append to the document
    _insert_mermaid_images(document_id, markdown_content or "")

    return {
        "document_id": document_id,
        "url": _tenant_doc_url(document_id),
    }


# ---------------------------------------------------------------------------
# Evaluation markdown rendering
# ---------------------------------------------------------------------------


_LAYER1_QUESTION_LABELS = {
    "real_user_identified": "1. 真实用户已识别 (Real user identified)",
    "concrete_pain": "2. 具体痛点 (Concrete pain)",
    "status_quo": "3. 当前替代方案 (Status quo)",
    "willingness_to_pay": "4. 付费意愿 (Willingness to pay)",
    "observation_over_survey": "5. 观察优于问卷 (Observation over survey)",
    "narrowest_wedge": "6. 最小楔子 (Narrowest wedge)",
    "ten_raving_fans": "7. 10 个狂热粉丝 (Ten raving fans)",
    "sales_friction": "8. 销售摩擦 (Sales friction)",
    "retention_signal": "9. 留存信号 (Retention signal)",
    "founder_fit": "10. 创始人匹配 (Founder fit)",
}

_LAYER3_DIMENSION_LABELS = {
    "company_purpose": "Company Purpose（公司使命）",
    "problem": "Problem（问题）",
    "solution": "Solution（解决方案）",
    "why_now": "Why Now（时机）",
    "market_size": "Market Size（市场规模）",
    "competition": "Competition（竞争格局）",
    "product": "Product（产品状态）",
    "business_model": "Business Model（商业模式）",
    "team": "Team（团队）",
    "financials": "Financials / Runway（财务）",
}


def _build_evaluation_markdown(
    project_name: str, evaluation_data: Dict[str, Any]
) -> str:
    """Render a three-layer evaluation into structured Markdown.

    evaluation_data expected keys: layer1 (dict), layer2 (dict), layer3 (dict),
    overallScore, recommendation, blockingConcerns, nextValidation, reasoning,
    updatedAt (optional).
    """
    layer1 = evaluation_data.get("layer1") or {}
    layer2 = evaluation_data.get("layer2") or {}
    layer3 = evaluation_data.get("layer3") or {}
    overall = evaluation_data.get("overallScore")
    recommendation = evaluation_data.get("recommendation") or ""
    blocking = evaluation_data.get("blockingConcerns") or []
    next_validation = evaluation_data.get("nextValidation") or []
    reasoning = evaluation_data.get("reasoning") or ""
    updated_at = evaluation_data.get("updatedAt") or ""

    lines: List[str] = []
    lines.append(f"# {project_name} - 三层方法论评估报告")
    lines.append("")
    lines.append(
        "> 评估框架：YC Desirability (Layer 1) + Lean Startup 三不确定性 (Layer 2) "
        "+ Sequoia 10 维度 (Layer 3)"
    )
    lines.append("")
    if updated_at:
        lines.append(f"**最近更新**：{updated_at}")
        lines.append("")

    # Header scorecard
    lines.append("## 总览")
    lines.append("")
    lines.append("| 项目 | 分值 |")
    lines.append("|------|------|")
    if overall is not None:
        lines.append(f"| 综合得分 | {overall} / 10 |")
    l1_score = layer1.get("score")
    if l1_score is not None:
        lines.append(f"| Layer 1 Desirability | {l1_score} / 10 |")
    if layer2:
        des = (layer2.get("desirability") or {}).get("score")
        via = (layer2.get("viability") or {}).get("score")
        fea = (layer2.get("feasibility") or {}).get("score")
        if des is not None:
            lines.append(f"| Layer 2 Desirability | {des} / 10 |")
        if via is not None:
            lines.append(f"| Layer 2 Viability | {via} / 10 |")
        if fea is not None:
            lines.append(f"| Layer 2 Feasibility | {fea} / 10 |")
    l3_score = layer3.get("score")
    if l3_score is not None:
        lines.append(f"| Layer 3 Sequoia 平均 | {l3_score} / 10 |")
    lines.append(f"| 最终建议 | **{recommendation}** |")
    lines.append("")

    # Blocking concerns
    if blocking:
        lines.append("## 阻塞性风险")
        lines.append("")
        for item in blocking:
            lines.append(f"- {item}")
        lines.append("")

    # Layer 1
    lines.append("## Layer 1 — YC Desirability 10 追问")
    lines.append("")
    lines.append(
        "> 出处：Y Combinator Office Hours / Paul Graham《How to Get Startup Ideas》"
    )
    lines.append("")
    if l1_score is not None:
        lines.append(f"**Layer 1 平均分**：{l1_score} / 10")
        weakest = layer1.get("weakest_question")
        if weakest:
            lines.append(f"**最弱环节**：{_LAYER1_QUESTION_LABELS.get(weakest, weakest)}")
        lines.append("")
    lines.append("| 问题 | 分数 | 答案 | 证据来源 |")
    lines.append("|------|------|------|----------|")
    for q in layer1.get("questions") or []:
        if not isinstance(q, dict):
            continue
        qid = q.get("id", "")
        label = _LAYER1_QUESTION_LABELS.get(qid, qid)
        score = q.get("score", "")
        answer = (q.get("answer") or "").replace("\n", " ").replace("|", "\\|")
        evidence = (q.get("evidence_source") or "").replace("\n", " ").replace("|", "\\|")
        lines.append(f"| {label} | {score} | {answer} | {evidence} |")
    lines.append("")
    l1_reco = layer1.get("recommendation")
    if l1_reco:
        lines.append(f"**Layer 1 结论**：{l1_reco}")
        lines.append("")

    # Layer 2
    lines.append("## Layer 2 — Lean Startup 三不确定性")
    lines.append("")
    lines.append(
        "> 出处：Eric Ries《The Lean Startup》 — Desirability / Viability / Feasibility"
    )
    lines.append("")
    for key, title in [
        ("desirability", "Desirability（产品假设：用户要这个东西）"),
        ("viability", "Viability（商业假设：能赚钱）"),
        ("feasibility", "Feasibility（技术假设：能做出来）"),
    ]:
        section = layer2.get(key) or {}
        score = section.get("score", "")
        lines.append(f"### {title}")
        lines.append("")
        lines.append(f"- **得分**：{score} / 10")
        lines.append(f"- **核心假设 (Hypothesis)**：{section.get('hypothesis', '')}")
        lines.append(f"- **验证实验 (Experiment)**：{section.get('experiment', '')}")
        lines.append(f"- **成功标准 (Success Criteria)**：{section.get('success_criteria', '')}")
        lines.append("")
    riskiest = layer2.get("riskiest_assumption")
    if riskiest:
        lines.append(f"**最高风险假设**：{riskiest}")
        lines.append("")

    # Layer 3
    lines.append("## Layer 3 — Sequoia 10 维度（融资视角）")
    lines.append("")
    lines.append("> 出处：Sequoia Capital Pitch Deck Template")
    lines.append("")
    lines.append("| 维度 | 分数 | 依据 |")
    lines.append("|------|------|------|")
    for d in layer3.get("dimensions") or []:
        if not isinstance(d, dict):
            continue
        name = d.get("name", "")
        label = _LAYER3_DIMENSION_LABELS.get(name, name)
        score = d.get("score", "")
        note = (d.get("reasoning") or "").replace("\n", " ").replace("|", "\\|")
        lines.append(f"| {label} | {score} | {note} |")
    lines.append("")
    biggest_gap = layer3.get("biggest_gap")
    if biggest_gap:
        lines.append(
            f"**最大短板**：{_LAYER3_DIMENSION_LABELS.get(biggest_gap, biggest_gap)}"
        )
        lines.append("")

    # Next validation
    if next_validation:
        lines.append("## 下一步验证清单")
        lines.append("")
        for idx, item in enumerate(next_validation, 1):
            lines.append(f"{idx}. {item}")
        lines.append("")

    # Overall reasoning
    if reasoning:
        lines.append("## 综合分析")
        lines.append("")
        lines.append(reasoning)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# im v1: interactive card message
# ---------------------------------------------------------------------------


def send_card_message(chat_id: str, card: Dict[str, Any]) -> Dict[str, Any]:
    """Send an interactive card to a chat. Returns the message data payload."""
    if not chat_id:
        raise FeishuError("send_card: chat_id is required")
    path = "/open-apis/im/v1/messages?receive_id_type=chat_id"
    return _request(
        "POST",
        path,
        json={
            "receive_id": chat_id,
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        },
    )


# ---------------------------------------------------------------------------
# Bitable v1 — minimal record create/update used by Phase 4
# ---------------------------------------------------------------------------


def bitable_create_record(
    app_token: str, table_id: str, fields: Dict[str, Any]
) -> Dict[str, Any]:
    path = f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    return _request("POST", path, json={"fields": fields})


def bitable_update_record(
    app_token: str, table_id: str, record_id: str, fields: Dict[str, Any]
) -> Dict[str, Any]:
    path = (
        f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}"
    )
    return _request("PUT", path, json={"fields": fields})


# ---------------------------------------------------------------------------
# Bitable v1 — auto-provisioning: create app + tables on first use
# ---------------------------------------------------------------------------


def bitable_create_app(name: str, folder_token: str = "") -> Dict[str, str]:
    """Create a new Bitable app under the bot's space.

    Returns {"app_token", "url"}.
    """
    data = _request(
        "POST",
        "/open-apis/bitable/v1/apps",
        json={"name": name or "ProdMind", "folder_token": folder_token or ""},
    )
    app = data.get("app", {}) if isinstance(data, dict) else {}
    app_token = app.get("app_token")
    if not app_token:
        raise FeishuError("create bitable app: missing app_token in response")
    url = app.get("url") or f"https://feishu.cn/base/{app_token}"
    return {"app_token": app_token, "url": url}


def bitable_create_table(
    app_token: str,
    table_name: str,
    fields: List[Dict[str, Any]],
    default_view_name: str = "",
) -> str:
    """Create a new table inside an existing Bitable app. Returns table_id.

    `fields` must be a list of {"field_name": str, "type": int} dicts. The
    first entry becomes the primary (index) field and should be a Text field.
    """
    if not app_token:
        raise FeishuError("create bitable table: app_token is required")
    if not fields:
        raise FeishuError("create bitable table: at least one field is required")

    path = f"/open-apis/bitable/v1/apps/{app_token}/tables"
    body = {
        "table": {
            "name": table_name,
            "default_view_name": default_view_name or table_name,
            "fields": fields,
        }
    }
    data = _request("POST", path, json=body)
    table_id = data.get("table_id") if isinstance(data, dict) else None
    if not table_id:
        raise FeishuError(
            f"create bitable table '{table_name}': missing table_id in response"
        )
    return table_id


# Schema of the ProdMind Bitable — kept as data so tests and ensure_initialized
# share the same definition. All SingleSelect fields are represented as Text
# to avoid managing options on first provision.
BITABLE_APP_NAME = "AICTO 技术决策档案"

_BITABLE_PROJECTS_FIELDS = [
    {"field_name": "项目名称", "type": 1},
    {"field_name": "状态", "type": 1},
    {"field_name": "创建时间", "type": 5},
    {"field_name": "评估分数", "type": 2},
    {"field_name": "推荐", "type": 1},
    {"field_name": "PRD链接", "type": 1},
    {"field_name": "最近活动", "type": 1},
]

_BITABLE_RESEARCH_FIELDS = [
    {"field_name": "项目名称", "type": 1},
    {"field_name": "类型", "type": 1},
    {"field_name": "标题", "type": 1},
    {"field_name": "创建时间", "type": 5},
    {"field_name": "内容摘要", "type": 1},
]

_BITABLE_RISKS_FIELDS = [
    {"field_name": "项目名称", "type": 1},
    {"field_name": "风险描述", "type": 1},
    {"field_name": "概率", "type": 1},
    {"field_name": "影响", "type": 1},
    {"field_name": "缓解措施", "type": 1},
]


def _load_bitable_state() -> Optional[Dict[str, Any]]:
    if not os.path.exists(BITABLE_STATE_PATH):
        return None
    try:
        with open(BITABLE_STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _save_bitable_state(state: Dict[str, Any]) -> None:
    parent = os.path.dirname(BITABLE_STATE_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(BITABLE_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _state_is_valid(state: Optional[Dict[str, Any]]) -> bool:
    if not state or not isinstance(state, dict):
        return False
    if not state.get("app_token"):
        return False
    tables = state.get("tables") or {}
    return bool(tables.get("projects"))


def bitable_ensure_initialized() -> Dict[str, Any]:
    """Load or provision the ProdMind Bitable app.

    On first call: creates a new Bitable app "ProdMind 项目管理" plus the
    three predefined tables, then persists the resulting ids to
    `BITABLE_STATE_PATH`.

    On subsequent calls: returns the cached state from disk without hitting
    the network. The projects table id is the minimum viable state; research
    and risks tables are provisioned in the same call but are not strictly
    required for the core sync path.

    Returns a dict shaped like::

        {
          "app_token": "...",
          "url": "https://.../base/...",
          "tables": {"projects": "...", "research": "...", "risks": "..."},
          "created_at": "2026-04-10T..."
        }

    Raises FeishuError on any provisioning failure.
    """
    cached = _load_bitable_state()
    if _state_is_valid(cached):
        return cached  # type: ignore[return-value]

    app_info = bitable_create_app(BITABLE_APP_NAME)
    app_token = app_info["app_token"]
    app_url = app_info["url"]

    tables: Dict[str, str] = {}
    tables["projects"] = bitable_create_table(
        app_token,
        "项目总览",
        _BITABLE_PROJECTS_FIELDS,
        default_view_name="全部项目",
    )
    tables["research"] = bitable_create_table(
        app_token,
        "调研记录",
        _BITABLE_RESEARCH_FIELDS,
        default_view_name="全部记录",
    )
    tables["risks"] = bitable_create_table(
        app_token,
        "风险清单",
        _BITABLE_RISKS_FIELDS,
        default_view_name="全部风险",
    )

    state = {
        "app_token": app_token,
        "url": app_url,
        "tables": tables,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _save_bitable_state(state)
    return state


# ---------------------------------------------------------------------------
# Notification channels — project → Feishu chat_ids
# ---------------------------------------------------------------------------


def _load_project_channels() -> Dict[str, List[str]]:
    """Load project → chat_id subscription mapping from disk."""
    try:
        if os.path.exists(PROJECT_CHANNELS_PATH):
            with open(PROJECT_CHANNELS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}


def _save_project_channels(channels: Dict[str, List[str]]) -> None:
    """Persist project → chat_id subscription mapping to disk."""
    os.makedirs(os.path.dirname(PROJECT_CHANNELS_PATH), exist_ok=True)
    with open(PROJECT_CHANNELS_PATH, "w", encoding="utf-8") as f:
        json.dump(channels, f, ensure_ascii=False, indent=2)


def subscribe_project_channel(project_id: str, chat_id: str) -> bool:
    """Register a chat to receive notifications for a project. Idempotent."""
    if not project_id or not chat_id:
        return False
    channels = _load_project_channels()
    existing = channels.get(project_id, [])
    if chat_id not in existing:
        existing.append(chat_id)
        channels[project_id] = existing
        _save_project_channels(channels)
        return True
    return False


def get_project_channels(project_id: str) -> List[str]:
    """Return list of chat_ids subscribed to a project."""
    return _load_project_channels().get(project_id, [])


def get_current_feishu_chat() -> Optional[str]:
    """Infer the currently-active Feishu chat from Hermes sessions.

    Reads sessions.json and returns the chat_id of the most recently updated
    Feishu session. Used to auto-subscribe a project when it's created in
    a specific group chat.

    Returns None if no feishu session exists or sessions.json unavailable.
    """
    try:
        if not os.path.exists(HERMES_SESSIONS_PATH):
            return None
        with open(HERMES_SESSIONS_PATH, "r", encoding="utf-8") as f:
            sessions = json.load(f)
        if not isinstance(sessions, dict):
            return None

        best_chat: Optional[str] = None
        best_time: str = ""
        for key, session in sessions.items():
            if not isinstance(session, dict):
                continue
            origin = session.get("origin") or {}
            if origin.get("platform") != "feishu":
                continue
            chat_id = origin.get("chat_id")
            if not chat_id:
                continue
            # Prefer last_activity_at; fall back to updated_at / created_at
            ts = (
                session.get("last_activity_at")
                or session.get("updated_at")
                or session.get("created_at")
                or ""
            )
            if ts > best_time:
                best_time = ts
                best_chat = chat_id
        return best_chat
    except Exception:
        return None


def send_text_to_chat(chat_id: str, text: str) -> None:
    """Send a plain text message to a Feishu chat. Raises on failure."""
    # Check if text contains <at> tags — if so, use post format for @mentions
    if "<at " in text:
        _send_post_with_mentions(chat_id, text)
        return
    _request(
        "POST",
        "/open-apis/im/v1/messages",
        params={"receive_id_type": "chat_id"},
        json={
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}),
        },
    )


def _send_post_with_mentions(chat_id: str, text: str) -> None:
    """Send a post (rich text) message that supports @mentions.

    Parses <at user_id="xxx">name</at> tags into Feishu post format.
    """
    import re as _re

    # Split text into segments: plain text and @mention tags
    at_pattern = _re.compile(r'<at user_id="([^"]+)">([^<]+)</at>')
    parts = at_pattern.split(text)

    # parts = [text_before, user_id, name, text_after, user_id, name, ...]
    content_line: list = []
    i = 0
    while i < len(parts):
        if i % 3 == 0:
            # Plain text segment
            plain = parts[i]
            if plain:
                content_line.append({"tag": "text", "text": plain})
        elif i % 3 == 1:
            # user_id
            user_id = parts[i]
            user_name = parts[i + 1] if i + 1 < len(parts) else ""
            content_line.append({"tag": "at", "user_id": user_id, "user_name": user_name})
            i += 1  # skip the name part
        i += 1

    post_content = {
        "zh_cn": {
            "content": [content_line],
        },
    }

    _request(
        "POST",
        "/open-apis/im/v1/messages",
        params={"receive_id_type": "chat_id"},
        json={
            "receive_id": chat_id,
            "msg_type": "post",
            "content": json.dumps(post_content),
        },
    )


def notify_project_channels(
    project_id: str,
    message: str,
    *,
    also_current: bool = True,
) -> List[str]:
    """Send a text notification to all chats subscribed to a project.

    If ``also_current`` is True and the current Feishu session's chat_id is
    not yet subscribed, auto-subscribe it and include it in the notification.

    Returns the list of chat_ids that received the message. Returns an empty
    list (and logs to stderr) when PRODMIND_SUPPRESS_NOTIFICATIONS is set —
    see :func:`_should_suppress_notifications` for details.
    """
    # Respect the ops-level suppression switch used by maintenance scripts.
    if _should_suppress_notifications():
        import sys

        preview = (message or "").replace("\n", " ")[:60]
        print(
            f"[prodmind] notification suppressed for project {project_id}: {preview}...",
            file=sys.stderr,
        )
        return []

    chats = set(get_project_channels(project_id))

    if also_current:
        current = get_current_feishu_chat()
        if current:
            if current not in chats:
                subscribe_project_channel(project_id, current)
            chats.add(current)

    sent: List[str] = []
    for chat_id in chats:
        try:
            send_text_to_chat(chat_id, message)
            sent.append(chat_id)
        except Exception as e:
            print(
                f"[feishu_api] notify_project_channels: failed to send to {chat_id}: {e}"
            )
    return sent



# ---------------------------------------------------------------------------
# Message resource (video/image/file) download
# ---------------------------------------------------------------------------

def download_message_resource(
    message_id: str,
    file_key: str,
    dest_path,
    file_type: str = "file",
) -> int:
    """Stream a message resource (video/image/file) to dest_path.

    Feishu API: GET /open-apis/im/v1/messages/{message_id}/resources/{file_key}
    Returns the byte count written.
    """
    token = get_tenant_access_token()
    url = (
        f"{FEISHU_BASE}/open-apis/im/v1/messages/{message_id}"
        f"/resources/{file_key}"
    )
    r = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        params={"type": file_type},
        stream=True,
        timeout=REQUEST_TIMEOUT,
    )
    if not r.ok:
        raise FeishuError(
            f"download_message_resource HTTP {r.status_code}: "
            f"{r.text[:300]}"
        )
    size = 0
    with open(dest_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)
                size += len(chunk)
    return size
