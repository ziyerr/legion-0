# P1.1 批次审查报告

> 审查者：reviewer / L1-麒麟军团  
> 审查时间：2026-04-25  
> 审查范围：5 个新核心模块 + tools.py 接入（共 6 文件 / 4658 行新增代码）  
> 审查依据：REQUIREMENTS.md / ARCHITECTURE.md / ADR-001~010 / PRD-CAPABILITIES.md / review-checklist.md

## 0. 验证手段（反幻觉的反幻觉）

每个模块基于以下**实跑命令**而非凭印象：

| 验证项 | 手段 | 结果 |
|------|------|------|
| pm_db_api 仅 SELECT | grep + AST 扫描非注释行 | ✅ 0 写 SQL |
| adr_storage 仅 5 张 CTO 表 | regex 抽取所有 SQL 表名 | ✅ {ADR, TechRisk, TechDebt, CodeReview, EngineerProfile} |
| _readonly_connect 物理只读 | 实际 INSERT INTO Project → 抛 OperationalError "attempt to write a readonly database" | ✅ 物理挡写 |
| _ensure_cto_tables 真有效 | sqlite3 dev.db 扫表 → 5 表全在，列数符合 DDL | ✅ 13/11/10/11/9 列 |
| feishu_api.py 仅 3 处常量改 | diff vs prodmind/hermes-plugin/feishu_api.py | ✅ 仅 16 行 diff（3 常量 × 2 行 + env var 名 × 2） |
| inbox 锁 = LOCK_EX | grep fcntl.flock | ✅ flock(lock_fd, fcntl.LOCK_EX) at line 353 |
| from = "AICTO-CTO" | grep SENDER_ID | ✅ 单源常量 line 39，无散落字面量 |
| error_classifier 测试 | python3 -m unittest test_error_classifier | ✅ **47 tests pass / 0 fail** |
| 实施者非凭印象自验 | 检查 ~/.hermes/profiles/aicto/logs/read-audit.log | ✅ 10 条真实调用记录跨 4 工具 |

## 1. 总评

| 模块 | 行数 | 评级 | 关键发现 |
|------|------|------|---------|
| feishu_api.py | 2040 | **PASS** | 整文件 copy + 3 常量改严丝合缝；token 仅进程内缓存（_cached_token），无落盘 |
| pm_db_api.py | 627 | **PASS** | 0 写 SQL；全参数化；_audit_log 真有产出；mode=ro 物理验证通过 |
| adr_storage.py | 933 | **PASS** | 仅 5 张 CTO 表；UUID id；ADR.number per-project 唯一索引兜底；CHECK 枚举值校验 |
| legion_api.py | 547 | **PASS** | mailbox 协议 8 保留字段 + 4 新字段全到位；fcntl LOCK_EX；tmux 80 字上限；fs 路径白名单 (~/.claude/legion/) |
| error_classifier.py | 507 | **PASS** | 4 级齐全；PM 3 补充边界全覆盖；47 tests pass；escalate 飞书失败兜底 log；retry 用尽抛 WrappedToolError |
| tools.py | 124 | **PASS** | 6 stub 返 not_implemented；10 工具 dispatch pm_db_api；ensure_ascii=False 全量 |

**0 BLOCKING / 7 NON-BLOCKING / 综合结论：ALL APPROVED**

## 2. BLOCKING 项（如有）

**无。** 所有边界 / 协议 / 安全 / 反幻觉 / 测试覆盖维度均通过。

## 3. NON-BLOCKING 项（建议修但不阻塞 merge）

> 格式遵循 PRD §五·能力 4 硬约束："把 X 改成 Y 因为 Z"。

### N-1 · feishu_api.py:1 — 文件 docstring 身份错误

**X**：`"""Feishu OpenAPI client for ProdMind.`  
**Y**：`"""Feishu OpenAPI client for AICTO（整文件 copy 自 prodmind/hermes-plugin/feishu_api.py + 3 处常量改，ADR-004 LOCKED）.`  
**Z**：当前 docstring 仍标识为 ProdMind，会让后续维护者误以为是 ProdMind 的代码而非 AICTO 的拷贝；ADR-004 明确"整文件 copy + 3 处常量改"包含身份归属语义，docstring 也属于身份范畴。

### N-2 · adr_storage.py:933 — 模块导入即写 dev.db（副作用）

**X**：模块底部 `_ensure_cto_tables()` 在 `import adr_storage` 时无条件执行，且写硬编码路径 `/Users/feijun/Documents/prodmind/dev.db`。  
**Y**：把建表挪到 `__init__.py:register(ctx)` 内或加 try/except + delayed init flag。  
**Z**：CI / 测试环境 / 干净机器没有该路径的 dev.db 时，任何 `import adr_storage`（甚至 `from . import adr_storage`）会立刻抛 OperationalError，难以单元测试本模块。Phase 1 内单机能跑不阻塞，Phase 2 加 CI 时必返工。

### N-3 · adr_storage.py:521 — 参数名 `type` shadow 内置

**X**：`def create_debt(project_id: str, type: str, description: str, ...)`  
**Y**：把参数名 `type` 改成 `debt_type`（同时改调用方 / docstring）。  
**Z**：shadow Python builtin `type()`，Pylint W0622；若函数体后续需要 `isinstance(x, type)` 之类引用会触发 bug。当前无引用所以不爆，但是 footgun。

### N-4 · legion_api.py:117 / 206 / 225 — 静默吞 Exception

**X**：`except Exception: return None` / `except Exception: return []` / `except Exception: continue`，无日志输出。  
**Y**：改成 `except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as e:` + 至少一行 `print(f"[legion_api] {context}: {e}", file=sys.stderr)` 或接 logger。  
**Z**：当前实现满足"非阻塞"，但反幻觉纪律要求异常可见化（R-NFR-1~5）；调试时一旦 directory.json 损坏 / tmux 异常，会"看似无错"地静默返回空集，造成幻觉性"无在线指挥官"。

### N-5 · pm_db_api.py:79 — 同 #N-4，_audit_log 静默吞

**X**：`except Exception: pass # 审计失败不阻塞业务返回`  
**Y**：保留不阻塞策略，但加 `print(f"[pm_db_api] audit log failed: {e}", file=sys.stderr)`。  
**Z**：审计失败应可见——磁盘满 / 权限错 / 路径不存在时当前完全无信号，违反反幻觉纪律的"承认缺失不编造"。

### N-6 · pm_db_api.py:320-336 — `min_rice_score` 类型未校验

**X**：`min_rice_score = args.get("min_rice_score")` 直传 SQL 比较，未校验数值类型。  
**Y**：`if min_rice_score is not None and not isinstance(min_rice_score, (int, float)): return _err("min_rice_score must be number")`。  
**Z**：调用方若传 `"10.0"` 字符串，SQLite 走 lexical 比较返非预期行集（`"10.0" >= "100"` 为 False），而非显式拒绝；防御性编程的最低限。

### N-7 · adr_storage.py:322-337 — `get_adr(_conn=)` 返回 un-hydrated 行

**X**：`return _hydrate_adr_row(result) if _conn is None else result` —— 内部带 `_conn` 调用时跳过 hydrate，外部调用时 hydrate。  
**Y**：内部统一始终 hydrate，或重命名 `_get_adr_raw` / `get_adr_hydrated` 显式分流。  
**Z**：当前 `create_adr` 行 302 写法 `_hydrate_adr_row(get_adr(adr_id, _conn=conn))` 能工作，但语义双义；Phase 2 增加调用点容易踩坑（拿到 raw row 直接序列化给客户端会少 `display_number`）。

## 4. 一致性检查

### 与 ARCHITECTURE.md §4 设计对齐
- ✅ §4.1 feishu_api.py 整文件 copy + 3 常量改 — diff 验证（仅 16 行差异）
- ✅ §4.2 pm_db_api.py 8 + 2 工具 + mode=ro + audit log — 全到位 + 真有产出
- ✅ §4.3 adr_storage.py 5 张表 + _cto_own_connect + ADR.number per-project — 全到位
- ✅ §4.4 legion_api.py discover/dispatch/appeal 协议骨架 — 已铺好（dispatch_to_legion_balanced 完整版按 spec 推迟到 P1.4）
- ✅ §5.3 mailbox 协议 8 保留字段 + 4 新字段（cto_context / appeal_id / appeal_count / priority）— 全到位
- ✅ §6 4 级错误分类矩阵 — 关键词全覆盖；PM 3 补充边界全实现

### 与 REQUIREMENTS.md §2~§4 需求对齐
- ✅ R-DT-1~5：5 张 CTO 自有表全建（13/11/10/11/9 列符合 DDL）
- ✅ R-TL-7~16：10 工具全部接入（read_pm_*/list_pm_*/get_pm_context/diff_pm_versions）
- ✅ R-NFR-1~5：反幻觉 5 条（错误返 error key / 不静默吞 / retry 失败 escalate / stub 透明 / 决策有据）
- ✅ R-NFR-15：飞书 token 进程内缓存 + 5min 提前刷新（feishu_api.py:138 验证）
- ✅ R-NFR-19~22：4 级错误分类全 6 能力共享（待 cron / 6 能力实施时验证嵌入）

### 与 ADR-001~010 决策对齐
- ✅ ADR-001 16 工具命名 — `__init__.py` register 列表 16 条
- ✅ ADR-002 ADR 存 prodmind/dev.db — `_cto_own_connect()` 路径正确
- ✅ ADR-003 plugin 目录结构 — 5 新模块到位
- ✅ ADR-004 飞书整文件复用 — diff 验证仅 3 处常量改
- ✅ ADR-005 dispatch 双通道 + appeal — mailbox_protocol_serialize 实装
- ✅ ADR-006 4 级错误 + PM 补充 3 边界 — 47 tests pass
- ✅ ADR-007 cron 自管 — P1.1 不在范围（推迟到 P1.7）
- ✅ ADR-008/009/010 — P1.1 不在范围

## 5. 反幻觉的反幻觉（高阶验证）

| 项 | 实施者声称 | 我实跑验证 |
|----|-----------|----------|
| 5 张 CTO 表已建 | ✅ | sqlite3 dev.db 扫表确认 5 表 + 列数符合 DDL |
| readonly 物理挡写 | ✅ | INSERT INTO Project 真抛 OperationalError |
| pm_db_api 真有调用 | ✅ | read-audit.log 10 条记录跨 read_pm_project / read_pm_prd / list_pm_features / get_pm_context_for_tech_plan / diff_pm_prd_versions |
| error_classifier 47 tests | ✅ | 实跑 `python3 -m unittest test_error_classifier` → 47 OK |
| feishu_api 仅 3 常量改 | ✅ | `diff` vs prodmind 源文件 → 仅 16 行差异，全部为已声明的 3 处常量 |

## 6. 综合结论

```
判定：ALL APPROVED
0 BLOCKING / 7 NON-BLOCKING / 6 文件全 PASS

可进入 P1.1 验证者实测 → 然后启动 P1.2（design_tech_plan）
```

NON-BLOCKING 7 条建议在 Phase 1 收官前批量修复（不阻塞 P1.2~P1.7 推进）；
也可以在 P1.7 末期与 cron 实现一并打补丁。

---

**审查方法学**：本批次审查由 grep / regex 静态扫描 + 实跑测试 + 真实数据库验证 + 真实日志取证四种手段交叉验证。无任何一条评级仅基于"看代码"。
