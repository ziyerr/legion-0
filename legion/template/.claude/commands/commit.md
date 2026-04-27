---
description: 分析 staged 变更，生成 conventional commit 并提交
---

## 流程
1. 运行 `git status` 和 `git diff --cached`
2. 分析变更性质（feat/fix/refactor/docs/test/chore）
3. 确定作用范围 scope（从修改的目录推断）
4. 生成符合 Conventional Commits 规范的 message（subject + body 说明 why 而非 what）
5. 使用 HEREDOC 执行 commit，message 结尾必须带 Co-Authored-By：
   ```bash
   git commit -m "$(cat <<'EOF'
   <type>(<scope>): <subject>

   <body，说明 why 而非 what>

   Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
   EOF
   )"
   ```
6. 运行 `git status` 确认提交成功

## 禁止
- 不要自动 stage（用户应显式 `git add`）
- 不要 push
- 不要使用 `--no-verify` 或 `--amend`
- 不要在 message 中添加 "🤖 Generated with..." 除非用户显式要求
