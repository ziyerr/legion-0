# AICTO — STATE

> 顶层 STATE 快照。详细子状态见各模块 `.planning/<module>/STATE.md`。
> 历史 Phase 0 快照已被本版覆盖；如需追溯参考 git history 1faa52e 之前。

## 当前阶段
**Phase 1 · 已完成 + 4 个治理模块就位**（2026-04-27）

P1.0 → P1.7 全部交付，6 大核心能力工具上线；其后追加 4 个组织治理/运维模块（CTO 运行模型、军团系统维护、多项目组合视图、需求元数据门禁）。
当前 hermes-plugin 注册 **24 个工具**，全量单测 **138/138 PASS**（Hermes venv 运行）。
最新 commit `1a31c4d feat: add AICTO legion collaboration governance` 已推送到 GitHub origin/master。

## 已完成

### Phase 1 核心交付（commit 链）
| 阶段 | 主题 | Commit | 状态 |
|------|------|--------|------|
| P1.0 | spec + plugin 骨架 + 16 工具注册 + SOUL.md 程小远化 | `1faa52e` | ✅ |
| P1.1 | feishu_api / pm_db_api / adr_storage / legion_api / error_classifier 5 模块共 4658 行；47/47 单测；mode=ro 物理挡写验证 | `db801a8` | ✅ |
| P1.2 | design_tech_plan（6 步推理链 + ADR 自动写入 + 飞书 doc）1049 行；KR4 平均 60.9s（SLA 300s）；9/9 验证 PASS | `9eadcbb` | ✅ |
| P1.3 | breakdown_tasks（方案 → 任务 DAG）1007 行；9+9 验证 PASS；B-1 防回归 | `072c3d8` | ✅ |
| P1.4 | dispatch_to_legion_balanced（智能调度）716 行；10+7 验证 PASS；B-1 第三轮固化 | `c8525b6` | ✅ |
| P1.5 | kickoff_project（项目启动 8 步）1287 行；15 单测 PASS；S-1+W-1+W-2 修复 | `57b4299` | ✅ |
| P1.6 | review_code（10 项审查 + 硬 gate）1294 行；83 单测 PASS；B-1 第五轮固化 | `bcdd8c3` | ✅ |
| P1.7 | daily_brief + cron + 14 NON-BLOCKING 修复；106/106 单测 PASS；B-1 第六轮 | `cfe5e95` | ✅ |

### Phase 1 后追加的治理 / 运维模块（commit `1a31c4d`）
| 模块 | 工具 | 关键产出 | 子 STATE |
|------|------|---------|----------|
| CTO 专业运行模型 | `cto_operating_model` | 能力矩阵 / 运行手册 / 权威来源 / 证据门 + 独立 `cto_memory_*.jsonl` 长期记忆；强制 `legion_command_center` 关键确认动作带 evidence；`docs/AICTO-OPERATING-MODEL.md` 固化契约 | `cto-operating-model/STATE.md` |
| 军团系统维护 | `legion_system_maintenance` | scan / follow_up_active / record_summary / ack_status / escalate_overdue_acks；真实扫描 31 项目 / 25 在线 commander / 43 active / 23 attention 任务；4 条 CTO 跟进指令全部 ACK | `legion-maintenance/STATE.md` |
| 多项目组合管理 | `legion_portfolio_status` + `dispatch_to_legion_balanced` 项目过滤 | PM 项目 × Legion 军团组合态；默认按归属过滤 + `allow_cross_project_borrow` 显式开关；6 PM 项目 / 9 active / 3 online | `multiproject/STATE.md` |
| 需求元数据门禁 + AIPM/AICTO 协作 | `requirement_metadata_gate` + `aipm_cto_collaboration` | 在 LLM/ADR/飞书副作用前阻断；用户对齐元数据 + 冲突/未确认探测；AIPM 澄清请求 + AICTO 验收交付协议 | `requirement-metadata-gate/STATE.md` |

### 关键决策日志
- `.planning/phase1/decisions/DECISIONS.md`：ADR-001 ~ ADR-010 全部 🔒 LOCKED（PM 已于 2026-04-25 答复 R-OPEN 12 项）
- 各模块 DECISIONS.md：cto-operating-model / legion-maintenance / multiproject / requirement-metadata-gate

## 进行中
无。Phase 1 主线已收敛，下一波动作等用户/PM 派单。

## 待完成（无重大功能缺口，只剩文档/部署收尾）

### 文档收尾
- 顶层 README / docs 同步更新到 24 工具 + 4 治理模块的真相
- `.planning/phase1/STATE.md` 老旧子文件含历史阶段记录，可考虑归档至 `archive/`（非阻塞）

### 部署/接入收尾
- AICTO 飞书 bot **已建（app_id `cli_a9495f70ddb85cc5`）但未拉入任何群** —— 后续上线触发点是「PM 第一次正式向 AICTO 派单到飞书群」
- profile `aicto` running on 8644，daily_brief cron 已随 gateway 启动；首次 18:00 触发结果待观测后归档

### 工作目录卫生
- 工作树存在多份 `<name> 2.py` 副本（macOS Finder 复制残留），需要清理；属于杂务非阻塞

## 上线状态
**Profile `aicto` running on port 8644**（独立 HERMES_HOME = `/Users/feijun/.hermes/profiles/aicto`）。

- ✅ Plugin `aicto 1.0.0` enabled / 24 工具注册 / 反幻觉 hook 已 load
- ✅ default profile（PM/张小飞 8642）零影响 —— profile 隔离生效
- ✅ Hermes profile list：default running 8642 / ai-hr / aicto running 8644
- ⚠️ AICTO 飞书 bot 已建未入群，等 PM 首单触发上线
- ✅ CTO 独立长期记忆：`/Users/feijun/.hermes/profiles/aicto/plugins/aicto/state/cto_memory.jsonl`

## 下一步触发点
1. PM 在飞书群正式向 AICTO 派出第一个 PRD（触发 design_tech_plan 真实链路 + 元数据门禁）
2. 用户决定文档归档/清理动作（顶层 README 更新 + `<name> 2.py` 副本清除）
3. Phase 2 蓝图启动（PRD §Phase 2/3：EngineerProfile / 跨项目技术债盘点 / 度量埋点）

## 纪律提醒
继承用户 2026-04-23 「生产系统零影响」硬约束 —— profile 隔离已落地，PM 8642 完全不受 AICTO 启停影响。任何把 AICTO 接入新 profile 或共享状态的动作仍需先在 worktree 验证。
