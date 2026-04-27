---
description: 对 GitHub PR 进行代码审查，输出结构化反馈
---

## 输入
PR 编号或 URL

## 流程
1. `gh pr view <PR>` 查看元信息
2. `gh pr diff <PR>` 查看全部变更
3. `gh pr view <PR> --comments` 查看已有评论
4. 按三维度审查：
   - **Correctness**：逻辑/边界/错误处理
   - **Security**：注入/权限/敏感数据
   - **Testing**：测试覆盖/可验证性
5. 输出结构化反馈：

```
## Review

### Strengths
- [优点 1]

### Concerns
- [file:line] [问题描述] — [建议]

### Blockers
- [必须修复项]

### Suggestions
- [可选改进]
```

6. 不自动 approve/merge，只输出审查

## 禁止
- 不要自动 `gh pr merge`
- 不要自动 `gh pr review --approve`
