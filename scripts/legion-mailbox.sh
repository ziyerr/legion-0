#!/bin/bash
# ============================================================================
# [DEPRECATED] legion-mailbox.sh — 已被 Claude Code 原生通信替代
# ============================================================================
# 此文件的功能已由 Claude Code 内置的 teammateMailbox.ts 接管:
# - writeToMailbox() → SendMessage 工具
# - readMailbox() → useInboxPoller (1s 自动轮询)
# - markMessagesAsRead() → 自动标记
#
# 如果旧代码仍在 source 此文件，提供空壳兼容:
# ============================================================================

# 空壳函数（向后兼容）
mailbox_send() { echo "[DEPRECATED] 请使用 SendMessage 工具" >&2; }
mailbox_send_json() { echo "[DEPRECATED] 请使用 SendMessage 工具" >&2; }
mailbox_read() { echo '[]'; }
mailbox_read_unread() { echo '[]'; }
mailbox_unread_count() { echo "0"; }
mailbox_broadcast() { echo "0"; }
mailbox_mark_read() { :; }
mailbox_mark_all_read() { :; }
mailbox_clear() { :; }
mailbox_display() { echo "(已迁移到 CC 原生通信)"; }
mailbox_inject_xml() { :; }
mailbox_list_inboxes() { :; }

echo "[legion-mailbox] 已废弃，通信已由 CC SendMessage/useInboxPoller 接管" >&2
