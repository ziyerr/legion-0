# 侦察搜索战法手册

经过验证的搜索模式，按场景分类。参谋不必每次从零摸索。

## 一、搜索策略矩阵

### 通用公式

```
"{核心关键词}" + {修饰词} + {过滤器}
```

修饰词按目的选择：
| 目的 | 修饰词 |
|------|--------|
| 找最佳实践 | best practice, recommended approach, production-ready |
| 找实现方案 | implementation, tutorial, how to, example |
| 找开源项目 | github, open source, library, framework |
| 找坑和风险 | pitfalls, gotchas, common mistakes, known issues |
| 找性能方案 | performance, optimization, benchmark, scalability |
| 找最新方案 | 2025, 2026, latest, modern |

过滤器：
| 平台 | 过滤器 |
|------|--------|
| GitHub | stars:>100, language:python/rust/typescript |
| Stack Overflow | votes:>10, is:answer, accepted:yes |
| npm | weekly downloads >10k |
| crates.io | downloads >1k |

## 二、按领域的搜索路径

### 前端 (React/TypeScript)

```
第 1 轮：方案搜索
  - "关键词 react component" site:github.com
  - "关键词 react hook implementation"
  - npm 搜索相关包，看 weekly downloads 和 last update

第 2 轮：质量验证
  - GitHub issues: "关键词 bug" / "关键词 breaking"
  - "关键词 react performance" / "关键词 react memory leak"
  - 查 bundle size: bundlephobia.com

第 3 轮：项目内部
  - Grep 现有代码中的同类实现
  - 查 package.json 是否已有相关依赖
  - git log 查历史上是否尝试过类似方案
```

### 后端 (Rust/Tauri)

```
第 1 轮：方案搜索
  - "关键词 rust" site:docs.rs 或 site:crates.io
  - "tauri 关键词 plugin" / "tauri 2 关键词"
  - crates.io 搜索，按 recent downloads 排序

第 2 轮：质量验证
  - crate 的 GitHub issues 数量和最近活跃度
  - "关键词 rust unsafe" / "关键词 rust panic"
  - 查 MSRV (Minimum Supported Rust Version) 是否兼容

第 3 轮：项目内部
  - Cargo.toml 已有依赖是否能复用
  - 查 gui/src-tauri/src/ 中已有的模式
  - Tauri 官方插件列表: tauri.app/plugin
```

### Python 脚本

```
第 1 轮：方案搜索
  - "关键词 python library" + "async" (本项目重度异步)
  - PyPI 搜索，看维护状态和 Python 版本支持
  - "关键词 python subprocess" / "关键词 asyncio"

第 2 轮：质量验证
  - "关键词 python memory" / "关键词 python slow"
  - 查是否有 C 依赖（影响跨平台部署）
  - 查是否支持 Python 3.10+（项目要求）

第 3 轮：项目内部
  - scripts/ 目录是否有同类脚本可复用
  - requirements.txt 已有依赖
  - 查 async_http_client.py / async_io.py 等基础设施
```

### AI/视频/音频（本项目核心领域）

```
第 1 轮：API 和服务
  - 即梦 API 文档: 查 jimeng_api_client.py 现有能力
  - CapCut Mate: 查 capcut-mate 服务端口 30000
  - Clipchamp TTS: 查 clipchamp_tts.py 支持的功能
  - 剪映/CapCut 草稿格式: 查 jianying_draft_gen_async.py

第 2 轮：替代方案
  - "关键词 API free tier" / "关键词 self-hosted"
  - Hugging Face 模型搜索
  - "关键词 ffmpeg" (视频处理的瑞士军刀)

第 3 轮：项目内部
  - config/prompts/ 已有的 prompt 模板
  - v2/skills/ 已有的 skill 实现
  - 查 .planning/ 中的设计决策
```

## 三、信息源优先级

```
1. 项目内部（战法库 > memory > .planning/ > git log）
   → 最高价值，前人踩过的坑不用再踩

2. 官方文档（Tauri/React/Python docs）
   → 权威但可能过时

3. GitHub 高星项目源码
   → 生产验证过的实现，可直接借鉴架构

4. Stack Overflow 高票回答
   → 踩坑经验丰富，但注意回答年份

5. 技术博客/教程
   → 参考思路但不盲信，很多博客代码不能直接用
```

## 四、反模式（不要做）

- **不要只看 README 就出报告** — 必须看 issues、PR、源码结构
- **不要只搜一次** — 至少从 2-3 个不同角度搜索
- **不要只看第一页结果** — 有价值的内容往往在第二三页
- **不要复制粘贴搜索结果** — 必须提炼为可操作的建议
- **不要忽略项目内部** — 战法库和现有代码往往比外部搜索更有价值
- **不要推荐没人维护的库** — 最后更新超过 1 年的库谨慎推荐

## 五、输出质量标准

好的侦察报告：
```
✅ "用 X 库的 Y 模块可以直接处理 Z，它的 A 方法支持我们需要的 B 格式"
✅ "GitHub issues #123 报告了 C 问题，影响我们的 D 场景，规避方案是 E"
✅ "项目已有 scripts/F.py 实现了类似功能，可以复用其 G 类"
```

差的侦察报告：
```
❌ "可以用 X 库" （太模糊）
❌ "网上有很多教程" （没有具体内容）
❌ "建议参考最佳实践" （等于没说）
```
