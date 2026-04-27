# Deep Audit Plan — Legion-0 (2026-04-25)

## Goal
对 master 分支当前所有 modified + untracked 变更（tracked 1743+/-109 行；新增 9 个 skills、3 个 commander plan、新 AGENTS.md、新 .planning/、新测试、memory/builder-journal.md）进行**深度多维审计**，覆盖前次审计（02:22:34Z YES_WITH_WATCH）未触及或仅浅层覆盖的部分。

## 规模决策
非平凡任务 + 多专业领域 → 启用 4 路差异化 codex 审计 + 1 路 codex 运行时 verify。每路独立视角、独立 scope、独立验证方法，不重复同一动作。

## 分工

### Branch A — audit-static-quality (codex)
- **视角**：静态代码质量、bash/python 语法陷阱、本仓 tactics 已知坑
- **Scope**：
  - `install.sh`, `scripts/legion.sh`, `scripts/legion`, `scripts/legion-init.sh`
  - `scripts/legion_core.py`, `scripts/stack-verify.sh`, `scripts/hooks/post-tool-use.sh`
  - `tests/test_legion_core.py`, `tests/test_roundtable_skill.py`
- **必查项**：
  - `bash -n` / `shellcheck` 全过；python `-m py_compile` 全过
  - 已知坑：tactic-80f12f（bash local 在 case 分支必须包函数）、tactic-1abd3a（资源池 release null guard）、tactic-cbd061（破坏性清理先备份）
  - shadowed bindings、unused vars、未引用的 heredoc 变量
  - test 是否真的覆盖 R1-R17；mock 是否替代了真实集成
- **输出**：`inbox/audit-static-quality-report.md` 含 PASS/FAIL/WATCH 三选一裁决

### Branch B — audit-security-redteam (codex)
- **视角**：红队安全攻击面、命令注入、敏感信息回显、写入路径权限
- **Scope**：
  - `scripts/legion.sh`, `scripts/legion_core.py`, `scripts/legion-init.sh`
  - `scripts/hooks/post-tool-use.sh`, `scripts/stack-verify.sh`, `install.sh`
  - `.claude/commander/` `commander/` `memory/builder-journal.md`
- **必查项**：
  - heredoc / shell quoting 是否对用户输入做 injection 防护（commander name、task description、scope）
  - tmux send-keys 是否带未转义参数
  - 写入 `~/.claude/`、`/opt/homebrew/bin/legion` 是否会覆盖既有非 Legion 文件（hooks 合并幂等）
  - hooks 注入面：post-tool-use 是否能被恶意工具输出攻击
  - tactic-1f3c41（禁止回显 secret）、tactic-580e80（定时任务/插件加载路径同等扫描）
  - prompt injection 入口：mixed inbox / events.jsonl / readiness 报告
- **输出**：`inbox/audit-security-redteam-report.md`

### Branch C — audit-integration-contract (codex)
- **视角**：模块间契约、生命周期、并发/超时、回归覆盖
- **Scope**：
  - `scripts/legion.sh`, `scripts/legion_core.py`, `scripts/hooks/post-tool-use.sh`
  - `scripts/legion-init.sh`, `tests/test_legion_core.py`
  - `README.md`, `AGENTS.md`, `.planning/STATE.md|REQUIREMENTS.md|DECISIONS.md`
- **必查项**：
  - `legion.sh` ↔ `legion_core.py` 的 CLI 契约：mixed status/inbox/msg/broadcast/readiness/campaign 参数与 schema 对齐
  - `host_convened` / `branch_commander_*` / `commander_*` 事件 schema 是否一致
  - `lifecycle=campaign` L2 disband 触发条件（completed + no retain_context）
  - readiness handshake parent-scoped 过滤是否正确（防止历史 L2 计入本届 roster）
  - tmux 会话生命周期：session not alive → planned → relaunch 路径
  - R1-R17 每条是否有对应 regression test；`tests/test_legion_core.py` 1298 行覆盖度评估
  - tactic-af6bcc（API 探针）、tactic-c57407（文件重组同步引用）
- **输出**：`inbox/audit-integration-contract-report.md`

### Branch D — audit-reversibility-and-skills (codex)
- **视角**：不可逆/破坏性操作、新增 skills 安全合规
- **Scope**：
  - `install.sh`, `scripts/legion.sh`, `scripts/legion-init.sh`, `scripts/legion`
  - `.claude/skills/{ai-tob-research,chrome-devtools,claw-roundtable-skill,e2e-test,prompt-optimizer,safe-exec,self-improving-agent,skill-creator,ui-ux-designer}/`
  - `.agents/` `skills/`
- **必查项**：
  - `legion 0`/`legion h`/`legion view` 写入 `~/.claude/scripts/`、`~/.claude/agents/`、`~/.claude/skills/`、`/opt/homebrew/bin/legion` 是否破坏用户既有 customizations（hooks merge/agents merge/skills overwrite policy）
  - install.sh 是否做备份；是否有 `rm -rf` / 覆盖未提交代码
  - 新增 skills 自身：是否符合 SKILL.md 规范、是否引入命令执行风险（`self-improving-agent` 自动改代码、`safe-exec` 反讽地不安全、`chrome-devtools` MCP 权限、`skill-creator` 写文件路径）
  - skill scripts/hooks 是否会绕过 Quality Gate
  - `.claude/skills/generated/` 自动生成内容来源/审核
- **输出**：`inbox/audit-reversibility-skills-report.md`

### Branch E — verify-runtime (codex, depends on A+B+C+D)
- **视角**：运行时实证（不依赖代码阅读）
- **必查项**：
  - `bash -n` 全部 modified scripts
  - `python -m py_compile scripts/legion_core.py`
  - `python -m pytest tests/test_legion_core.py` 实跑
  - `legion.sh mixed status / inbox / events tail` 跑通
  - `legion.sh mixed campaign --dry-run` 用一个最小 plan
  - `bash scripts/stack-verify.sh detect` 退出码 0
  - `bash scripts/legion.sh host --dry-run` 退出码 0
- **输出**：`inbox/verify-runtime-report.md` 含每条命令的 stdout/stderr/exit code

## 收敛
4 路 audit + 1 路 verify 完成后，L1 汇总产出 `inbox/deep-audit-summary.md`：
- 严重度分级：CRITICAL（阻塞 commit）/ HIGH（必须修）/ MEDIUM（建议修）/ LOW（记录）
- 三选一最终裁决：PASS / YES_WITH_WATCH / FAIL
- 任一 audit 报 FAIL → 整体 FAIL

## 不做的事
- 不修代码（审计阶段，纯只读）
- 不做主观品味建议（abstraction 偏好等）
- 不重复前次 02:22:34Z 已覆盖的 7-file shellcheck 浅层结论
