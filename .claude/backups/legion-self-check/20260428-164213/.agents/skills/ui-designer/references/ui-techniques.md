# UI Design Techniques Reference（UI 设计师工具箱）

UI 设计师在输出视觉规范时可按需使用以下技术。根据需求复杂度选择。

---

## 1. 视觉层级（Visual Hierarchy）

**适用场景：** 页面信息多，需要引导用户视线。

**执行方法：**
1. 确定页面的 1 个主焦点（用户第一眼看什么）
2. 通过大小/颜色/对比/间距建立 3 级信息层级：
   - L1 主信息：最大字号 + 主色 + 最多空间
   - L2 辅助信息：中等字号 + 次要色
   - L3 补充信息：最小字号 + 灰色
3. 验证：遮住 L2/L3 只看 L1，是否能理解页面核心

**本项目适配：**
- L1 用 --color-accent-ink (#2c3e50) + 24px+
- L2 用 --color-primary-600 (#495057) + 16px
- L3 用 --color-primary-400 (#adb5bd) + 14px

---

## 2. 格式塔原则（Gestalt Principles）

**适用场景：** 组件排列和分组。

**核心原则：**
- **接近性**：相关的元素靠近放置（间距 8px），不相关的拉开（间距 24px+）
- **相似性**：同类元素用同样的视觉样式（颜色/大小/形状）
- **闭合性**：用卡片/边框/背景色划分区域
- **连续性**：对齐！左对齐是默认，居中只用于标题

**本项目适配：**
- 卡片区分用 --color-bg-card + border-radius: 12px + box-shadow
- 区域间距用 --spacing-xl (32px)
- 组件间距用 --spacing-md (16px)

---

## 3. 状态设计（State Design）

**适用场景：** 任何交互组件。

**必须覆盖的状态：**
| 状态 | 视觉变化 | 说明 |
|------|---------|------|
| default | 基础样式 | 常态 |
| hover | 微亮/微暗 + cursor:pointer | 鼠标悬停 |
| active/pressed | 更深 + 微缩 | 点击瞬间 |
| focused | outline 或 ring | 键盘焦点 |
| disabled | opacity: 0.5 + cursor:not-allowed | 不可用 |
| loading | spinner 或 skeleton | 等待中 |
| empty | 空状态插图 + 引导文案 | 无数据 |
| error | 红色边框 + 错误文案 | 出错 |
| success | 绿色反馈 | 操作成功 |

**本项目适配：**
- hover 用 --gradient-primary-hover
- error 用 --color-accent-cinnabar
- success 用 --color-accent-bamboo
- loading 用 --animation-pulse

---

## 4. 响应式布局策略

**适用场景：** 桌面应用（Tauri），窗口可调大小。

**断点策略（本项目）：**
| 窗口宽度 | 布局 | 说明 |
|---------|------|------|
| ≥1440px | 全展开 | 侧边栏 + 主区域 + 详情面板 |
| 1024-1439px | 收缩 | 侧边栏折叠为图标 |
| <1024px | 最小 | 底部 Tab 替代侧边栏 |

**CSS 实现：**
```css
@media (max-width: 1439px) { .sidebar { width: 64px; } }
@media (max-width: 1023px) { .sidebar { display: none; } }
```

---

## 5. 配色决策树

**适用场景：** 不确定某个元素用什么颜色时。

```
这是用户操作的主按钮？
  → 是 → --gradient-primary (墨色渐变)
  → 否 → 这是状态信息？
    → 成功 → --color-accent-bamboo (竹绿)
    → 错误 → --color-accent-cinnabar (朱砂)
    → 警告 → --color-warning-500 (琥珀)
    → 信息 → --color-accent-stone (石青)
    → 否 → 这是背景？
      → 页面底 → --color-bg-app (宣纸米黄)
      → 卡片 → --color-bg-card (卡片纸张)
      → 侧边栏 → --gradient-sidebar
      → 否 → 这是文字？
        → 主要 → --color-accent-ink (墨色)
        → 次要 → --color-primary-500 (灰墨)
        → 辅助 → --color-primary-400 (淡灰)
```

---

## 6. 组件复用检查

**适用场景：** 设计新功能前必做。

**执行步骤：**
1. 读 `knowledge/COMPONENT_INVENTORY.md`
2. 在现有组件中找是否有可复用的
3. 找到 → 标注"基于: {组件名}"，只定义差异
4. 找不到 → 标注"新建"，输出完整规范

**原则：** 能复用就复用。新建组件意味着维护成本增加。

---

## 7. 间距系统（Spacing System）

**本项目间距规范（8px 基准）：**
| 名称 | 值 | 用途 |
|------|-----|------|
| xs | 4px | 图标与文字间 |
| sm | 8px | 紧凑元素间 |
| md | 16px | 标准组件间 |
| lg | 24px | 区块间 |
| xl | 32px | 大区域间 |
| 2xl | 48px | 页面级间距 |

**铁律：所有间距必须是 4 的倍数。禁止 5px、7px、13px 等非规则值。**

---

## 8. 动效原则

**适用场景：** 状态变化、页面切换、元素出现/消失。

| 场景 | 时长 | 曲线 | 示例 |
|------|------|------|------|
| hover 反馈 | 150ms | ease | 按钮变色 |
| 展开/收起 | 200ms | ease-out | 面板展开 |
| 页面切换 | 300ms | ease-in-out | 路由变化 |
| 入场动画 | 400ms | ease-out | 卡片渐入 |
| 数据刷新 | 200ms | ease | 数字变化 |

**铁律：动效不超过 400ms。超过就是慢，用户会等不及。**

---

## 9. 无障碍基础（Accessibility）

**最低要求：**
- 颜色对比度 ≥ 4.5:1（WCAG AA）
- 所有可点击元素 ≥ 44x44px（触摸友好）
- 图标旁有文字标签（或 aria-label）
- focus 状态可见（键盘导航）

---

## 10. 设计验收清单

每次输出设计规范前，对照检查：
- [ ] 使用了 variables.css 中的设计变量（无硬编码颜色）
- [ ] 覆盖了所有交互状态（hover/active/disabled/loading/empty/error）
- [ ] 间距是 4 的倍数
- [ ] 与现有页面风格一致（参考 PAGE_STYLES.md）
- [ ] 优先复用现有组件（参考 COMPONENT_INVENTORY.md）
- [ ] 动效时长 ≤ 400ms
- [ ] 颜色对比度 ≥ 4.5:1
- [ ] 图标用 lucide-react

---

# 高级设计方法论（融合自通用 UI/UX 知识库）

以下方法论从通用设计实践中提取，适用于复杂功能设计。

---

## 11. Nielsen 十大可用性启发式

设计验收和审查时的通用检查框架：

| # | 原则 | 本项目应用 |
|---|------|-----------|
| 1 | **系统状态可见性** | DAG 节点实时状态、进度条、loading spinner |
| 2 | **系统与现实匹配** | 用"场景""角色""道具"等影视行业术语 |
| 3 | **用户控制和自由** | 支持撤销、返回、取消操作 |
| 4 | **一致性和标准** | 统一使用 variables.css 设计系统 |
| 5 | **错误预防** | 危险操作前弹确认框（ConfirmDialog） |
| 6 | **识别而非回忆** | 用图标+文字标签，不依赖用户记忆 |
| 7 | **灵活性和效率** | 常用功能提供快捷路径 |
| 8 | **简约设计** | 水墨留白风格，不堆砌信息 |
| 9 | **帮助恢复错误** | 错误信息说明原因+解决方案（ErrorDisplay） |
| 10 | **帮助文档** | 复杂功能提供 tooltip 说明 |

---

## 12. 组件设计五原则

新建或修改组件时遵循：

1. **一致性** — 相同功能使用相同组件，禁止为同一目的创造新变体
2. **可预测性** — 用户能预期组件行为（按钮点了会怎样）
3. **高效性** — 减少操作步骤（如默认值、自动填充）
4. **容错性** — 预防错误 > 恢复错误（disabled 状态、输入验证）
5. **即时反馈** — 操作后 200ms 内给予视觉反馈

---

## 13. 渐进式披露（Progressive Disclosure）

**适用场景：** 功能多但不想一次性展示全部。

**策略：**
- 首屏只展示 3-5 个核心操作
- 次要功能放在"更多"菜单或折叠面板
- 高级设置隐藏在独立面板中
- 用户操作越深入，展示越多细节

**本项目应用：**
- ProjectWorkspace 左侧 Tab 切换各功能模块（渐进）
- StoryboardEditor 默认展示分镜，详情折叠

---

## 14. Atomic Design（原子化设计）

从最小单元向上组合：

```
Atoms（原子）→ Molecules（分子）→ Organisms（组织）→ Templates → Pages
  按钮           搜索框            导航栏           布局骨架     完整页面
  标签           卡片头部          侧边栏           内容模板     带数据的页面
  输入框         列表项            功能面板
```

**本项目已有的原子：**
- 原子：按钮、标签、输入框、图标（lucide-react）
- 分子：AssetPreview、ErrorDisplay、ConfirmDialog
- 组织：AssetGrid、PipelinePanel、AudioManager
- 页面：22 个 pages

设计新功能时，先检查已有原子/分子是否可组合，不要直接设计页面级。

---

## 15. Design Thinking 五步法

处理复杂/模糊需求时的思考框架：

```
1. 共情(Empathize) — 目标用户是谁？他在什么场景下用？
2. 定义(Define)    — 核心问题是什么？（一句话）
3. 构思(Ideate)    — 至少想 3 种方案再选
4. 原型(Prototype) — 输出 ASCII 线框图（我们不用 Figma）
5. 测试(Test)      — 对照验收标准和 Nielsen 十大启发式检查
```

**注意：** 在军团体系中，步骤 1-2 由产品参谋完成（模块定义表）。UI 设计师从步骤 3 开始。
