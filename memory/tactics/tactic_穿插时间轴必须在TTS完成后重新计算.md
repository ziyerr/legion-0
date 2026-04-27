---
name: 穿插时间轴必须在TTS完成后重新计算
description: narration_interleave 的产出依赖 tts_narration 的完整音频集，TTS 重跑后穿插必须重新计算，否则旁白覆盖率极低
type: tactic
---

## 问题

泼辣大小姐单集项目中，穿插时间轴在 TTS 只有 1 条音频时就计算完成了。之后 TTS 重跑生成了 32 条音频，但穿插时间轴没有重新计算（被自愈机制标记为 COMPLETED），导致 232 秒的视频里只有 4.2 秒有旁白。

## 根因链

1. tts_narration 的 manifest 只检查"是否存在任何音频"而非"覆盖率" → 1/32 就标记完成
2. narration_interleave 在 TTS 不完整时执行 → 只放置 1 条旁白
3. TTS 重跑后，自愈机制检测到 interleave 产物存在 → 标记 COMPLETED
4. 下游基于 1 条旁白的穿插方案生成草稿 → 视频几乎无旁白

## 修复

1. tts_narration 的 evaluate_quality 和 get_work_manifest 改为按旁白条目逐项展开，检查覆盖率
2. 所有 skill 的 evaluate_quality 统一加完整性检查（实际产物数 vs 预期数）
3. 自愈机制增加 manifest 完整性校验（manifest_completed < manifest_total 不自愈）
4. DAG checkpoint API 改为实时计算 manifest（不依赖缓存）

## 教训

"产物存在"不等于"产物完整"。质量检查必须包含完整性维度。
