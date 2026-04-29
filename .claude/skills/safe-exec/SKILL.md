---
name: safe-exec
description: 不可逆操作的安全执行协议。触发条件命中高风险命令清单时，强制进入容器化验证模式或 dry-run 降级，避免破坏性操作直接命中真实数据。
---

# Safe Exec — 不可逆操作防护

## 触发条件（命中任一即触发）

执行下列命令或其变体时**必须**进入 safe-exec 流程：

- `rm -rf <path>`（任何递归删除）
- `git push --force` / `git push -f` / `git push --force-with-lease`
- `git reset --hard`
- `git clean -fd`
- `git branch -D` / `git checkout -- .` / `git restore .`
- `DROP TABLE` / `DROP DATABASE` / `TRUNCATE`
- `gh repo delete` / `gh release delete`
- `find <path> -delete` / `find <path> -exec rm`
- `chmod -R 000` / `chown -R`（递归权限变更）
- `dd if=... of=/dev/sdX`
- `docker system prune -a` / `docker volume rm`
- 对 production 数据库的 `UPDATE`/`DELETE`（无 `WHERE`）
- 对共享存储的 `mv`/`cp` 覆盖现有文件
- 任何涉及 `/Users/<user>/` 根级的删除/移动

## 协议：容器化验证模式（首选）

### Step 1: 构建验证容器
```dockerfile
# ~/.claude/skills/safe-exec/Dockerfile.template
FROM alpine:latest
WORKDIR /workspace
# 按需 mount 数据集，默认无内容
```

### Step 2: 容器内预演（只读挂载）
```bash
docker build -f Dockerfile.template -t safe-exec-sandbox .
docker run --rm -v $(pwd):/workspace:ro safe-exec-sandbox sh -c "<dangerous-command>"
```

**关键**：宿主挂载用 `:ro` 只读模式，验证行为不影响真实数据。

### Step 3: 比对结果
- 容器输出 ≠ 预期 → **中止**，报告指挥官
- 容器输出 = 预期 → 进入 Step 4

### Step 4: 宿主执行（需用户显式 CONFIRM）
向用户展示：完整命令 + 容器预演输出 + 影响文件列表。用户回复 `CONFIRM` 才执行。

## 降级：dry-run 模式（Docker 不可用时）

| 原命令 | dry-run 变体 |
|--------|------------|
| `rm -rf X` | `find X -type f \| head -20`（查看将删的文件） |
| `git push --force` | `git push --dry-run --force` |
| `git reset --hard` | `git status && git log -5`（确认要丢弃的提交） |
| `git clean -fd` | `git clean -fdn`（n 即 dry-run） |
| `find X -delete` | `find X -print` |
| `DROP TABLE X` | `SELECT COUNT(*) FROM X`（查看将丢的数据） |
| `chown -R u:g X` | `find X -not -user u`（查看将变更的文件数） |

展示 dry-run 输出后，用户回复 `CONFIRM` 才真正执行。

## 使用协议

1. **声明意图**：agent 进入触发条件 → 先文字声明"这是高风险操作，进入 safe-exec 协议"
2. **git snapshot**：所有操作前必须有可回滚的 git 提交（除非操作本身在 git 之外）
3. **优先容器**：Docker 可用走容器化验证；不可用走 dry-run
4. **自治模式**：用户不在场时 → 必须 dry-run 验证 → 输出无害再执行；任何不确定 → 暂停等待
5. **常规模式**：必须用户 `CONFIRM` 才执行真实命令

## 反模式

- ❌ 未预演直接执行
- ❌ 以"上次成功过"为由跳过协议
- ❌ 把 `--force` 当成默认选项
- ❌ 在 `/Users/` 根级使用任何递归命令不经 safe-exec
- ❌ 自治模式下省略 dry-run 步骤

## 例外（无需触发）

- `rm <single-file>` 非递归 / `rm /tmp/xxx` 明确临时路径
- 项目内 `target/` `node_modules/` `dist/` 清理
- `git reset --soft HEAD~1`（可恢复）
- `git checkout -- <file>`（git 追踪可恢复）
- 已经是 dry-run 的命令
- 只读的 `ls` / `find -print` / `git status`

## 集成点

- 其他 skill 引用：`详见 ~/.claude/skills/safe-exec/SKILL.md`
- 项目 CLAUDE.md 引用：`@~/.claude/skills/safe-exec/SKILL.md`
- 与 implement agent 的 degradation-policy 联动：safe-exec 验证后确认不可降级再 fallback
