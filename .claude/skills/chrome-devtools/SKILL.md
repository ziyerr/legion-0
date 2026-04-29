---
name: chrome-devtools
description: 浏览器实证验证协议。前端 UI 完成后、E2E 审计时、性能诊断时，通过 Chrome DevTools MCP 实际操作浏览器验证真实运行时（console/network/screenshot/performance）。看不到的东西不算完成——tsc 绿 ≠ 页面活。
---

# Chrome DevTools — 浏览器实证验证

## 核心原则

**UI 任务的终局验证必须是"真浏览器实际跑过"，而非 tsc / lint / 静态分析通过。**

`tsc --noEmit` 零报错只证明代码能编译；页面点开白屏、Console 红错、按钮不响应，这些只有浏览器能抓到。Chrome DevTools MCP 把"人工打开 Chrome 点一下"的动作结构化，让军团 agent 也能做 evidence-based 验证。

## 前置条件

本 skill 需要 Chrome DevTools MCP 运行：

```bash
# 用户级一次安装（所有项目生效）
claude mcp add --scope user chrome-devtools -- npx chrome-devtools-mcp@latest
```

无 MCP 时 skill 退化为"口头建议手动验证"，仍可用但失去自动化价值。

## 触发条件

以下场景**必须**用 chrome-devtools 验证：

| 场景 | 具体动作 | 为何必要 |
|------|---------|---------|
| **前端 UI 新功能完成** | 打开对应 route → 触发用户动作 → 截图 + 读 Console | tsc 不抓运行时 |
| **L/XL 级集成审计** | 走完核心用户旅程（注册→上传→付费→下载）+ 截 5 张关键页 | 集成验证者 skill 要求端到端 |
| **用户报"页面慢/卡"** | Performance tab 录 10s → 分析 LCP / TBT / long tasks | 肉眼"慢"太模糊 |
| **视觉回归担忧** | 改前后各截一张 → 对比 | 防设计样式意外破坏 |
| **JS 错误无法复现** | Console tab 监控 → 触发场景 → 收集 stack trace | 生产日志不一定有前端 error |
| **API 联调失败** | Network tab 看 request/response → 对照后端日志 | 前后端盲猜 debugging 低效 |

## 跳过场景

- **纯后端任务**（无 UI 改动）
- **单 hook/util 改动**（pytest / jest 已覆盖）
- **用户明确说"跳过验证"**
- **无头环境**（CI/远程机器无 Chrome，改用 Playwright headless 或截图服务）

## 使用流程

### 典型流程（前端功能完成后自检）

1. **启动服务**：`npm run dev` 在 `localhost:3000` 起前端，`uvicorn` 起后端
2. **调用 MCP**：告诉 chrome-devtools 打开目标 route，如 `/record`
3. **模拟用户动作**：click / type / scroll，复刻用户真实操作路径
4. **三层取证**：
   - Console logs：有无 red error、warning
   - Network panel：关键 API 是否 200、payload 正确
   - 截图：和设计稿/需求描述对比
5. **写入报告**：截图存 `.planning/<feature>/verification/`，Console/Network 结果写入审计报告

### 审计场景（L 级最终审计）

```
audit skill 部署 3 路验证者时：
  - 合规审计者 → 读 code
  - 红队攻击者 → API 层 poc
  - 集成验证者 → 【用 chrome-devtools 跑真浏览器 E2E】   ← 本 skill
```

集成验证者跑 5 个关键路径 + 截 5 张图 + 0 个 red console error 才算 PASS。

## 命令清单（MCP 常用）

| 意图 | Chrome DevTools MCP 动作 |
|-----|------------------------|
| 打开页面 | `navigate` to URL |
| 模拟点击 | `click` on selector |
| 输入文本 | `type` in element |
| 读 Console | `get_console_messages` |
| 读 Network | `list_network_requests` |
| 截图 | `take_screenshot` (PNG) |
| 性能录制 | `performance_start` → 触发动作 → `performance_stop` + `performance_analyze` |
| DOM 查询 | `querySelector` / `getOuterHTML` |
| 执行 JS | `evaluate_script` |

## 与其他 skill 协同

- **audit**：集成验证者路径优先跑 chrome-devtools，其次 pytest E2E
- **verification-before-completion**：本 skill 是它的具象实现（前端场景）
- **e2e-test**：Playwright 方案，和本 skill 互补（Playwright 适合写死 test case 跑 CI，本 skill 适合探索性验证）
- **ui-designer**：改完样式后必须 chrome-devtools 截图对比新旧

## 反模式

- ❌ **只截首页交差** — 必须截"用户会真正用的 5+ 个页面/状态"
- ❌ **看到红 Console 忽略** — 任何 error/warning 都要分析（哪怕是 React hydration warning）
- ❌ **截图不标注** — 每张图配一句"这里验证了什么"说明
- ❌ **依赖 chrome-devtools 跳过单测** — 它是最后一道防线，不是唯一防线（单测 + 集成 + 浏览器 三层共存）
- ❌ **手动点击同样的路径 5 遍** — 固化成 skill 里的命令序列，每次自动跑
