---
description: 基于当前分支创建 GitHub Pull Request
---

## 流程
1. 检查当前分支 `git branch --show-current`
2. 运行 `git log base..HEAD --oneline` 查看所有 commit
3. 运行 `git diff base...HEAD` 分析所有变更
4. 确认分支已 push：`git push -u origin HEAD`
5. 生成 PR 标题（<70 字符）
6. 生成 PR body，使用标准模板：

```
## Summary
- [1-3 个 bullet point 说明核心变更]

## Test Plan
- [ ] [测试项 1]
- [ ] [测试项 2]
```

7. 运行 `gh pr create --title "..." --body "..."`（使用 HEREDOC）
8. 返回 PR URL

## 禁止
- 不要 force push
- 不要在 main/master 分支直接创建
- 不要提交包含 .env / credentials 的 diff
