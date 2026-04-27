---
name: evaluate_quality必须检查完整性
description: 所有 skill 的 evaluate_quality 不能只检查"已有产物的质量"，必须同时检查"产物数 vs 预期数"，失败项直接 score=0
type: tactic
---

## 问题模式（同一个 bug 在 4 个层面出现）

1. **tts_narration**: 1/32 音频但 score=1.0（只检查已有文件质量）
2. **video_poll**: 15/16 视频但 score=1.0（g014 失败被忽略）
3. **自愈路径**: quality.passed=True 就自愈为 COMPLETED（不查 manifest）
4. **DAG checkpoint API**: 返回缓存的 manifest 值（不实时计算）

## 统一修复

13 个 skill 的 evaluate_quality 全部加入完整性检查：
```python
manifest = self.get_work_manifest(inp.project_id, inp.episode)
failed_items = [m for m in manifest if m.status == "failed"]
if failed_items:
    score = 0.0  # 明确失败 → 强制触发重做
elif actual < expected:
    penalty = (1 - actual/expected) * 1.5  # 缺失 → 按比例扣分
```

自愈路径增加 manifest 完整性校验。API 改为实时计算 manifest。

## 铁律

"产物存在" ≠ "产物完整"。评分 = min(质量分, 完整性分)。
