# 中国大学生数学建模本地 MCP 核心：Phase 0 架构与 M1a/M1b 规格

- 日期：2026-07-17
- 状态：按 M1a/M1b 修订，提交最终审查
- 阶段：Phase 0，仅架构和第一阶段规格
- M1 推荐架构：单仓库、单发行物、单服务器进程的模块化单体
- 首个可运行检查点：M1a 功能垂直切片
- 首个可信兼容基线：M1b 可信化加固

## 1. 文档目的

本文定义一个面向中国大学生数学建模竞赛的本地工具核心，以及由 M1a 和 M1b 组成的首个里程碑 M1。M1a 先证明可运行的功能纵向链路，M1b 再建立可信、可恢复、跨平台且可兼容演进的发布基线。本文是产品边界、架构边界、公共契约、上下文工程、验证 Harness、安全规则和验收标准的统一设计依据。

本文不包含生产实现，不创建完整项目脚手架，不安装依赖，不实现 MCP Server 或数学算法。本文通过最终审查后，才能据此编写独立的实施计划。

## 2. 仓库探索结论

### 2.1 实际发现

设计开始时的工作区是 greenfield：

- 没有根 <code>AGENTS.md</code>；
- 没有任何嵌套 <code>AGENTS.md</code>；
- 没有 <code>docs/</code> 产品、架构、契约或 ADR；
- 没有项目级 <code>.agents/skills/</code>；
- 没有 <code>pyproject.toml</code>、锁文件、源码、测试或依赖清单；
- 工作区不是有效 Git 仓库，祖先位置存在的 Git 元数据不能提供有效状态或提交历史；
- 初始可见目录只有空的工作目录；设计会话产生的 <code>.superpowers/brainstorm/</code> HTML 和状态文件仅是可视化草稿，不属于项目架构；
- 相邻目录中的旧任务不属于本项目，未作为现有架构依据。

本机已发现的开发工具包括 uv 0.11.28、Python 3.11.14、Python Launcher 3.13.6、Git 2.53 和 ripgrep 15.1。它们只证明本地环境具备后续实施条件，不构成项目依赖。

### 2.2 已确认事实

- 项目从零开始，不继承既有代码或架构；
- Codex 是 M1a 的首个宿主；
- 宿主与建模核心必须通过稳定应用契约隔离；
- 传输方式是本地 STDIO MCP；
- 使用 Python 和 uv；
- 项目状态和实验记录使用 SQLite；
- M1 只提供一个 Built-in Capability（内置能力）<code>numerical.root_finding</code>；
- M1 的 Built-in Capability 随发行物交付、由组合根显式注册并在可信进程内执行；
- 数值结果必须来自真实执行，验证器必须独立于求解器；
- Windows 是主支持平台，同时保持路径和进程逻辑可移植。

### 2.3 合理推断与已批准的设计假设

- 一个 MCP 进程绑定一个项目根；
- 每个项目在自身目录内保存自包含状态；
- M1 不进行任意 Python Entry Point、目录扫描或 External Plugin 自动发现；
- M1 不以恶意 External Plugin 为威胁模型；
- 默认复现性是相同契约和环境下的语义、分类及容差内一致，而非跨平台位级一致；
- M1a 是端到端 tracer bullet，M1b 是该 tracer bullet 的可信化加固；二者都不是竞赛全流程自动求解器。

### 2.4 仍需确认的问题

Phase 0 没有阻塞 M1 设计的问题。M1a 采用最多 12 个可独立验收实施任务的推荐预算；未来需求通过 M1b、后续里程碑和 ADR 引入，不提前扩张 M1a。

### 2.5 是否拆成多个子项目

不拆成多个仓库、发行物或独立产品。M1a 和 M1b 是同一模块化单体的两个验收检查点，采用一个仓库、一个 <code>pyproject.toml</code>、一个锁文件和一个 Python 发行物；M1 仍只有一个服务器进程。边界通过包结构、必要端口、组合根、契约测试和导入图强制，而不是通过多仓库、多 wheel 或进程网络强制。受控计算子进程在 M2.5 引入，不反向增加 M1a 的框架预算。

## 3. 术语

| 术语 | 规范含义 |
|---|---|
| Host | 调用本地工具的宿主。M1 首个宿主是 Codex，未来可以是 Claude Code、TRAE 或其他客户端 |
| Host Adapter | 把宿主协议映射为应用用例的薄层，例如 MCP 或 CLI |
| Stable Core | 不依赖宿主、SQLite、具体能力实现、External Plugin 或 UI 的建模核心 |
| Capability | 通过 Capability Contract 暴露的一种数学或数据行为，不等同于安装包或发现机制 |
| Capability Contract | Stable Core 与能力实现之间的版本化编程、Schema 和行为契约 |
| Built-in Capability | 随本发行物交付、受信任并由组合根显式注册的能力模块；M1 只支持这一类 |
| External Plugin | 未来可由第三方独立安装、发现和治理，且可贡献一个或多个 Capability 的分发单元；不属于 M1 |
| Validator | 独立注册且独立于求解器，对既有结果快照执行数值检查的能力组件 |
| Project | 绑定到一个规范化本地根目录的建模工作空间 |
| Experiment | 不可变的建模意图，包括能力、契约、规范化输入和执行政策 |
| Attempt | 对一个 Experiment 的一次实际执行 |
| ResultSnapshot | Attempt 产生的不可变成功结果或数值失败快照 |
| Validation | 对指定 Attempt 和结果哈希执行的一次独立验证 |
| Artifact | M1b 起使用的内容寻址、不可变、带哈希和媒体类型的输出文件 |
| InputSnapshot | 规范化输入及其引用数据的不可变快照 |
| EnvironmentSnapshot | 复现所需的运行环境版本摘要 |
| MMIR | 未来的数学建模中间表示，不属于 M1 |

### 3.1 M1 版本基线

| 版本轴 | M1a 功能预览 | M1b 可信基线 |
|---|---|---|
| Application Release | <code>0.1.0</code> | <code>0.2.0</code> |
| MCP Protocol | <code>2025-11-25</code> | <code>2025-11-25</code> |
| MCP Tool Contract | <code>modeling-tools/0.1.0</code> | <code>modeling-tools/1.0.0</code> |
| Project Format | <code>modeling-project/0.1.0</code> | <code>modeling-project/1.0.0</code> |
| SQLite Schema | <code>1</code>（预览） | <code>2</code>（首个稳定基线） |
| Capability API | <code>modeling-capability/0.1.0</code> | <code>modeling-capability/1.0.0</code> |
| Error Schema | <code>modeling-error/0.1.0</code> | <code>modeling-error/1.0.0</code> |
| Result Snapshot Schema | <code>modeling-result/0.1.0</code> | <code>modeling-result/1.0.0</code> |
| Validation Report Schema | <code>modeling-validation-report/0.1.0</code> | <code>modeling-validation-report/1.0.0</code> |
| Canonicalization | <code>canonical-json/0.1.0</code> | <code>canonical-json/1.0.0</code> |
| Root-finding Contract | <code>numerical.root_finding/0.1.0</code> | <code>numerical.root_finding/1.0.0</code> |
| Root-finding Canonical Input | <code>numerical.root_finding.canonical-input/0.1.0</code> | <code>numerical.root_finding.canonical-input/1.0.0</code> |
| Residual Policy | <code>numerical.root_finding.residual/0.1.0</code> | <code>numerical.root_finding.residual/1.0.0</code> |

M1a 的 0.x 契约是内部功能预览，不是向后兼容基线；M1a 项目状态允许在进入 M1b 时重建，不要求设计一次性迁移框架。M1b 冻结首个 1.0 公共契约、Project Format 和 Schema 兼容基线；从 M1b 起的变更必须遵守第 14.8 节。M1a 与 M1b 共享工具名、用例语义和主要请求字段，差异只允许出现在第 11.2 节明确列出的存储与追踪形态。

M1 服务器只声明支持 MCP Protocol 2025-11-25，并通过初始化协商确认。实现锁定官方 Python SDK 稳定 1.x 线，依赖范围限制为 <code>mcp&gt;=1.27,&lt;2</code>，锁文件固定精确版本。迁移到 SDK 2.x 或新的不兼容 MCP Protocol 必须先通过 ADR 和 STDIO 契约回归。

公共字段统一使用完整名称，例如 <code>validator_implementation_id</code> 和 <code>validator_implementation_version</code>，不能用斜线缩写混合 ID 与版本。所有结构化工具成功结果包含当前里程碑对应的 <code>tool_contract_version</code> 和 <code>correlation_id</code>；所有错误包含对应 Error Schema 版本。

Project、Experiment、Attempt、ResultSnapshot 和 Validation，以及 M1b 的 InputSnapshot、EnvironmentSnapshot 的服务端实体 ID，加上客户端 <code>operation_id</code>，使用规范化小写 UUID v4 字符串。M1b Artifact ID 是例外：它直接等于内容 Hash，不是 UUID。时间使用 UTC RFC 3339，精度为毫秒并以 <code>Z</code> 结尾。哈希使用第 8.5 节定义的 <code>sha256:&lt;64 位小写十六进制&gt;</code>。

## 4. 产品边界

### 4.1 产品定位

系统是本地单用户的“数学建模执行与证据核心”。宿主负责决定要做什么，核心负责：

- 验证并规范化请求；
- 选择显式注册的能力；
- 真实执行数值实验；
- 独立验证结果；
- 保存状态、版本、制品和溯源；
- 通过稳定应用用例向不同宿主暴露能力。

核心不是自主研究代理，不负责自动选择完整建模方案，也不承诺直接解决任意竞赛题。

### 4.2 M1 用户价值

M1a 必须尽快证明以下完整链路真实可运行：

~~~text
Codex
→ 本地 STDIO MCP
→ 宿主无关应用门面
→ 项目状态
→ Built-in Capability 显式注册表
→ numerical.root_finding 真实执行
→ 独立残差验证
→ SQLite 基础记录
→ 可追溯内联响应
~~~

M1b 在保持同一功能链的基础上，进一步证明可重启、可恢复、可审计、可跨平台验证和可兼容演进。

### 4.3 M1a 与 M1b 必须交付

M1a 功能垂直切片：

1. Python 3.11 本地项目、uv 锁定环境和模块化单体；
2. 宿主无关 <code>modeling_core</code> 与唯一 Application Facade；
3. 本地 STDIO <code>modeling_mcp</code> 与六个 0.x 预览工具；
4. SQLite 项目、实验、执行、结果和验证基础记录；
5. Built-in Capability 与 Validator 的显式注册；
6. <code>numerical.root_finding</code> 真实执行和独立残差验证；
7. 一条真实字节管道的 STDIO 黄金链路；
8. bootstrap、基础 doctor 和单一 verify 入口；
9. 根与关键目录的基础 AGENTS、上下文索引和 Codex 配置模板；
10. 足以证明边界和数学正确性的单元、契约、架构、数学变形及 STDIO 测试。

M1b 可信化加固：

1. 完整 RFC 8785 通用与项目向量；
2. 内容寻址、不可变制品及其原子发布和完整性检查；
3. 完整幂等重放、崩溃恢复和故障注入矩阵；
4. 六工具和能力 Schema 的首个兼容基线与固定语料；
5. Windows 与 Ubuntu 使用同一完整验证命令；
6. 完整 Context/Skill、契约、运维文档和 ADR；
7. 完整完成证据包与可信发布判定。

### 4.4 实施成本上限

M1a 的实施计划必须满足以下硬上限：

- 最多 12 个顶层实施任务、最多 4 个有顺序依赖的工作包；
- 每个任务只有一个主要架构关注点，并以可运行或可自动验证的增量结束；子任务不得隐藏新的架构工作包；
- 若第 16.2 节的 M1a 验收无法在该预算内完成，先缩减非核心可靠性并移入 M1b，不得扩大 M1a 任务数；
- M1b 使用独立实施计划，最多 12 个顶层加固任务，不得把其可靠性工作伪装成 M1a 前置条件；
- 每个新增抽象必须在设计或实施计划中列出“当前调用方”和“当前具体实现”；仅以未来可能需要为理由的抽象禁止进入；
- 不为尚不存在的第二种存储、执行后端、宿主协议或 External Plugin 实现通用框架；
- M1a 禁止引入通用 DI 容器、事件总线、Repository 基类族、任务队列、worker 池、External Plugin 管理器或预留式 External Plugin SDK；
- 新生产依赖必须直接服务某项 M1a 验收条件，并记录不能用标准库或既有依赖满足的原因。

推荐的 12 任务预算分配为：环境与 verify 入口 1；预览契约与错误 1；领域与 Application Facade 1；SQLite 与项目生命周期 1；显式注册与能力发现 1；表达式和规范输入 1；root finding 1；独立验证器 1；运行/验证记录编排 1；六工具 STDIO 适配 1；黄金链路与自动测试 1；基础上下文、诊断和证据 1。后续实施计划可以合并，但不得拆出第 13 个顶层任务。

## 5. 架构方案比较

### 5.1 方案

| 维度 | A：单发行物模块化单体 | B：多包工作区 | C：子进程能力微内核 |
|---|---|---|---|
| 实现复杂度 | 低；一个环境和组合根 | 中；多包版本和发布协调 | 高；IPC、生命周期、序列化和进程恢复 |
| 长期可维护性 | 高；边界由契约和架构测试保护 | 高，但个人维护成本更高 | 中高；隔离强但运行面显著扩大 |
| 跨宿主能力 | 高；宿主只依赖应用门面 | 高 | 高 |
| 能力扩展成本 | 低；新增 Built-in Capability、契约、测试和注册项 | 中；可能新增包和版本 | 高；还需定义进程协议和部署 |
| 数学计算可靠性 | 高；单进程调试简单，独立验证 | 高 | 潜在最高，但必须先解决 IPC 和故障语义 |
| 测试难度 | 中低 | 中 | 高 |
| 个人本地使用 | 合适 | 略重 | 明显过度设计 |

### 5.2 决策

采用方案 A。它在不牺牲宿主独立性和能力边界的前提下，最适合 M1a 的个人本地垂直切片。

不采用多包工作区，因为 M1 没有独立发布节奏。
不采用子进程能力微内核作为 M1 架构，因为 M1 只加载可信 Built-in Capability，微内核、External Plugin 沙箱和复杂跨进程生命周期明显超出当前需求。

最小计算进程隔离不是取消，而是明确安排在 M2.5：届时以每次执行一个受控 worker 的方式提供硬超时和资源限制，不引入复杂任务队列，并作为 M3 长计算能力的前置门禁。

## 6. 系统架构

~~~mermaid
flowchart LR
    H["Codex / 未来宿主"] --> A["Host Adapter"]
    A --> F["Application Facade"]
    F --> D["Domain + Contracts"]
    F --> R["Sealed Capability Registry"]
    F --> P["Core Ports"]
    R --> C["Built-in Capabilities"]
    R --> V["Independent Validators"]
    P --> S["SQLite Adapter"]
    P --> O["Artifact Store Adapter（M1b）"]
    B["Composition Root"] -. "唯一组装位置" .-> A
    B -.-> F
    B -.-> C
    B -.-> V
    B -.-> S
    B -.-> O
~~~

### 6.1 架构不变量

- 核心不得导入 Codex、MCP SDK、CLI、SQLite 或具体能力；
- MCP 和 CLI 只能调用应用门面；
- MCP 层不得实现数学算法或直接访问数据库；
- Built-in Capability 和 Validator 不得直接访问 SQLite、项目根或宿主；
- 验证器不得导入对应求解器的数值实现；
- 只有组合根可以同时认识应用门面、具体能力实现和基础设施；
- 注册表在启动阶段显式组装、校验并封存，运行期不可变；
- 所有跨边界数据使用明确、严格、可版本化的 Schema。

## 7. 模块职责

### 7.1 稳定核心

| 模块 | 职责 |
|---|---|
| <code>modeling_core.contracts</code> | 公共 DTO、版本、错误、能力与验证器协议、端口数据结构 |
| <code>modeling_core.domain</code> | Project、Experiment、Attempt、ResultSnapshot、Validation 等领域对象与状态不变量 |
| <code>modeling_core.ports</code> | M1a 仅保留 ProjectStore 及必要的 Clock、IdGenerator 边界；M1b 增加 ArtifactStore |
| <code>modeling_core.registry</code> | 描述符校验、唯一性检查、版本解析、注册表指纹和封存 |
| <code>modeling_core.application</code> | 六个宿主无关用例、事务编排、幂等、执行和验证流程 |

### 7.2 外围模块

| 模块 | 职责 |
|---|---|
| <code>modeling_capabilities.numerical.root_finding</code> | Built-in Capability 描述符、版本化 Schema、安全表达式、求解器、独立验证器和能力上下文 |
| <code>modeling_infrastructure.sqlite</code> | SQLite 仓储、项目锁、Schema 版本和恢复状态 |
| <code>modeling_infrastructure.artifacts</code> | M1b 的 staging、哈希、内容寻址发布和制品完整性 |
| <code>modeling_mcp</code> | STDIO MCP 握手、工具 Schema、调用映射、MCP 错误映射和 STDOUT 纪律 |
| <code>modeling_cli</code> | bootstrap、doctor、verify、本地诊断，以及 M1b 的能力脚手架 |
| <code>modeling_bootstrap</code> | 唯一组合根，显式注册内置能力并组装具体适配器 |

能力专属 Schema 留在能力模块内，不进入稳定核心。新增 Built-in Capability 原则上只新增能力目录、契约、测试、文档和组合根注册项。External Plugin 的发现、安装、权限和分发契约不在 M1 定义。

### 7.3 目标源码布局

以下是 M1 实施时采用的逻辑布局，不在 Phase 0 创建：

~~~text
src/
  modeling_core/
    contracts/
      schemas/0.1.0/            # M1a
      schemas/1.0.0/
    domain/
    ports/
    registry/
    application/
  modeling_capabilities/
    numerical/root_finding/
      descriptor.json
      capability.py
      validator.py
      context.md
      contracts/0.1.0/          # M1a
      contracts/1.0.0/
  modeling_infrastructure/
    sqlite/
    artifacts/                  # M1b
  modeling_mcp/
    contracts/modeling-tools/0.1.0/  # M1a
    contracts/modeling-tools/1.0.0/
  modeling_cli/
  modeling_bootstrap/
tests/
  contract/corpus/
docs/
.agents/skills/                 # M1b
~~~

### 7.4 M1a 抽象与当前使用方

| 抽象 | 当前调用方 | M1a 当前具体实现 | 引入理由 |
|---|---|---|---|
| Application Facade | MCP、CLI 诊断和直接核心测试 | 单一应用服务 | 隔离宿主协议并承载六个用例 |
| ProjectStore | Application Facade | SQLiteProjectStore | 保持 Stable Core 不依赖 SQLite |
| Capability/Validator Contract | 显式注册表与 Application Facade | root_finding 与 residual validator | 让执行与独立验证通过同一稳定边界调用 |
| Clock、IdGenerator | 状态时间、截止时间、实体创建和确定性测试 | 系统时钟、UUID v4；测试替身 | 当前状态机和可重复测试直接需要 |

M1a 不定义 ArtifactStore、ExecutionBackend、ExternalPluginManager 或通用 Repository 基类。ArtifactStore 在 M1b 有内容寻址制品这一当前使用方时引入；ExecutionWorker 边界在 M2.5 有受控子进程这一当前实现时引入。若实现计划提出表外抽象，必须先更新本表并证明其当前使用方。

## 8. 数据流与状态模型

本节同时描述 M1a 的最小可运行状态和 M1b 的可信最终状态。除非段落明确标注 M1a，Artifact、独立 InputSnapshot/EnvironmentSnapshot 表、完整幂等恢复和文件发布顺序均为 M1b 要求。M1a 不得因为本节存在 M1b 设计而提前实现其存储抽象。

### 8.1 项目生命周期

项目根有四个可观察状态：

~~~mermaid
stateDiagram-v2
    [*] --> UNINITIALIZED
    UNINITIALIZED --> STORAGE_READY: bootstrap
    UNINITIALIZED --> READY: create_project
    STORAGE_READY --> READY: create_project
    UNINITIALIZED --> DEGRADED: 初始化冲突
    STORAGE_READY --> DEGRADED: 完整性失败
    READY --> DEGRADED: 完整性失败
~~~

- <code>UNINITIALIZED</code>：没有合法 <code>.modeling/</code>；
- <code>STORAGE_READY</code>：目录、锁设施和 SQLite Schema 已建立，但没有 Project 领域记录；
- <code>READY</code>：恰有一个不可变 Project 记录，可以执行项目工具；
- <code>DEGRADED</code>：检测到版本、完整性、锁或存储冲突，只允许 health 和只读 doctor。

CLI <code>bootstrap</code> 只负责从 UNINITIALIZED 到 STORAGE_READY，不创建 Project 领域记录。MCP <code>create_project</code> 在 UNINITIALIZED 时复用同一存储初始化原语并继续创建 Project，在 STORAGE_READY 时只创建 Project，在 READY 时按幂等规则返回唯一 Project。

存储初始化在项目根内创建唯一 <code>.modeling.tmp.&lt;uuid&gt;</code>，并生成不可变的 <code>storage_instance_id</code>；完整建立后以原子目录发布竞争决定唯一赢家，失败或竞争失败的临时目录不得被引用。READY 后由 <code>.modeling/project.lock</code> 串行化写入。

<code>health_check</code> 在 UNINITIALIZED 和 STORAGE_READY 都可返回 <code>status=OK</code> 与 <code>ready_for_project_creation=true</code>；在 READY 返回 <code>status=OK</code> 与 <code>ready_for_project_creation=false</code>；完整性失败返回 DEGRADED。服务器进程可在四种状态启动。

### 8.2 不可变与可变对象

不可变：

- Project 创建身份和项目格式版本；
- Experiment；
- ResultSnapshot；
- M1b 的 InputSnapshot、Artifact 和 EnvironmentSnapshot。

有受控状态转换：

- Attempt；
- Validation 的运行状态。

重跑不会重写 Experiment 或 Attempt，而是创建新的 Attempt。重新验证不会覆盖旧报告，而是创建新的 Validation。

### 8.3 核心关系

M1a 的最小关系为：

~~~text
Project → Experiment → Attempt → ResultSnapshot → Validation
~~~

规范输入与版本字段内联于 Experiment，环境摘要内联于 Attempt，结果和验证报告的规范 JSON 内联于 SQLite。M1a 仍须保存各自哈希，但不创建 Artifact，也不要求为尚无第二存储实现的对象建立 Repository 家族。

M1b 扩展为：

~~~mermaid
erDiagram
    PROJECT ||--o{ EXPERIMENT : owns
    EXPERIMENT ||--o{ ATTEMPT : executes
    EXPERIMENT }o--|| INPUT_SNAPSHOT : uses
    ATTEMPT }o--|| ENVIRONMENT_SNAPSHOT : records
    ATTEMPT ||--o| RESULT_SNAPSHOT : produces
    RESULT_SNAPSHOT ||--o{ ARTIFACT : references
    ATTEMPT ||--o{ VALIDATION : receives
    VALIDATION ||--o| ARTIFACT : report
~~~

M1a 的 Validation 只有在运行状态 SUCCEEDED 时必须存在内联 report payload；M1b 对应为 report Artifact。其他终态不得伪造数学报告。

### 8.4 实体最低字段

M1a 的 SQLite 最低记录为：

| 实体 | M1a 最低持久字段 |
|---|---|
| Project | project_id、storage_instance_id、project_format_version、display_name、created_at |
| Experiment | project_id、capability_id、contract_version、canonical_input_schema_version、canonical_payload、canonical_payload_hash、model_snapshot_hash、空 data_snapshot_references、data_snapshot_set_hash、execution_policy、created_at |
| Attempt | experiment_id、implementation_id、implementation_version、environment_summary、randomness、seed、status、时间、warnings、system_error、numerical_failure、terminal_reason |
| ResultSnapshot | attempt_id、result_kind、result_schema_version、result_hash、result_payload_json |
| Validation | attempt_id、expected_result_hash、validator_id、validator_implementation_id、validator_implementation_version、policy_version、policy、policy_hash、status、outcome、metrics、validation_report_hash、report_payload_json、operational_error、terminal_reason |
| IdempotencyRecord | scope_id、tool_name、operation_id、canonical_request_hash、status、result_entity_references |

M1b 把规范输入、环境和制品提升为可独立引用的不可变实体，最低字段为：

| 实体 | 最低持久字段 |
|---|---|
| Project | project_id、storage_instance_id、project_format_version、display_name、created_at |
| InputSnapshot | canonical_input_schema_version、canonical_input_schema_hash、canonical_payload、canonical_payload_hash、model_snapshot_hash、data_snapshot_references、data_snapshot_set_hash |
| Experiment | project_id、capability_id、contract_version、input_snapshot_id、execution_policy、created_at |
| Attempt | experiment_id、implementation_id、implementation_version、environment_snapshot_id、randomness、seed、session_id、status、时间、warnings、system_error、numerical_failure、terminal_reason |
| ResultSnapshot | attempt_id、result_kind、result_schema_version、result_hash、result_artifact_id |
| Artifact | artifact_id、sha256、project_relative_path、media_type、size_bytes、created_at |
| Validation | attempt_id、expected_result_hash、validator_id、validator_implementation_id、validator_implementation_version、policy_version、policy、policy_hash、status、outcome、metrics、validation_report_hash、report_artifact_id、operational_error、terminal_reason |
| IdempotencyRecord | scope_id、tool_name、operation_id、canonical_request_hash、status、result_entity_references |

M1 没有外部数据时也必须记录规范化空数据引用集合及其哈希，不能省略“数据版本”。M1a 可以内联这些字段，M1b 使用独立 InputSnapshot。

字段名固定为 <code>data_snapshot_references</code> 和 <code>data_snapshot_set_hash</code>。<code>storage_instance_id</code> 是 bootstrap 时生成并写入 <code>project.json</code> 和 SQLite 元数据的小写 UUID v4；项目目录移动不改变该值。<code>scope_id</code> 对普通写工具是 project_id；对 Project 尚不存在时的 create_project 是 storage_instance_id。这样幂等作用域不依赖尚不存在的 Project，也不持久化绝对路径。

### 8.5 canonical-json 与哈希

M1a 的 <code>canonical-json/0.1.0</code> 与 M1b 的 <code>canonical-json/1.0.0</code> 使用同一规范化算法；版本差异表示 M1a 尚未建立完整符合性和兼容承诺，不表示允许两套算法。所有结构化哈希、幂等比较和 JSON payload 使用同一规范：

1. 先按对应契约校验并生成 CanonicalInput；
2. 显式填充所有契约默认值，删除不属于契约的数据；
3. 字符串预处理为 Unicode NFC；
4. math-expr-v1 表达式使用解析后 AST 的规范表达形式，而不是保留无意义空白；
5. Schema 类型为 number 的值在进入 CanonicalInput 前转换为有限 IEEE-754 binary64，<code>-0.0</code> 规范为 <code>0</code>，整数形式 <code>1</code> 与数值等价的 <code>1.0</code> 规范为相同值；Schema 类型为 integer 的字段保持 JSON 安全整数，不经有损转换；
6. 采用 RFC 8785 JSON Canonicalization Scheme 生成无空白、无 BOM 的 UTF-8 字节；
7. 对这些字节计算 SHA-256，并表示为 <code>sha256:&lt;64 位小写十六进制&gt;</code>；
8. 持久化当前里程碑对应的 <code>canonicalization_version</code>，未知版本拒绝写入。

math-expr-v1 的规范 AST 只使用以下禁止未知字段的 JSON 节点：

| kind | 字段 |
|---|---|
| number | kind、value=binary64 JSON number |
| variable | kind、name，M1 只能是 x |
| constant | kind、name=pi 或 e |
| unary | kind、op=positive 或 negative、operand |
| binary | kind、op=add、subtract、multiply、divide 或 power、left、right |
| call | kind、name 为允许函数名、argument |

解析树保留操作数顺序，不做常量折叠、交换、结合或代数化简；括号和空白不进入 AST。直接作用于数值字面量的正负号归并到 number value，因此 <code>-0.0</code> 成为 <code>0</code>。

公开 RootFindingCanonicalInput 受当前里程碑对应的 <code>numerical.root_finding.canonical-input</code> 严格 Schema 约束，根对象恰有 canonical_input_schema_version、expression_ast、lower、upper、absolute_tolerance、relative_tolerance、function_tolerance 和 max_iterations。canonical_input_schema_version 是对应版本常量；其余数值和范围与第 10.2 节一致，所有默认值均已物化。它使用 expression_ast 代替原始 expression 字符串；持久化层不保存仅有排版差异的原始传输文本。

哈希语义固定如下：

| 名称 | 覆盖字节 |
|---|---|
| canonical_payload_hash | 填充默认值后的 CanonicalInput JSON |
| canonical_request_hash | <code>{"tool_contract_version":当前里程碑版本,"request":...}</code> 的规范 JSON；request 只含写工具的语义字段，不含 operation_id、correlation_id 和传输元数据；tool_name 单独位于幂等唯一键中 |
| model_snapshot_hash | <code>{"language":"math-expr-v1","ast":...}</code> 的规范 JSON |
| data_snapshot_set_hash | 按 snapshot ID 排序的 <code>[{"snapshot_id":...,"sha256":...}]</code>；M1 无数据时是规范 JSON <code>[]</code> 的哈希 |
| result_hash | ResultSnapshot payload 的规范 JSON 字节哈希；M1a 的相同字节内联于 SQLite，M1b 的相同字节作为结果 JSON Artifact 并等于其 SHA-256 |
| validation_policy_hash | 物化默认值后的严格 ValidationPolicy JSON |
| validation_report_hash | ValidationReport payload 的规范 JSON 字节哈希；M1a 内联于 SQLite，M1b 等于报告 Artifact 的 SHA-256 |
| binary artifact SHA-256 | 原始文件字节，不经过 JSON 规范化 |

canonical_request_hash 中的 request 先物化所有工具默认值并规范化 ID；run_experiment/new 嵌入 CanonicalInput 而不是原始 payload 文本，create_project 嵌入按当前项目状态解析后的 display_name。这样语义等价请求得到同一哈希，真正不同的执行政策得到不同哈希。

<code>expected_result_hash</code> 只指 result_hash。M1a 验证前重新读取内联 payload，并核对重算哈希、ResultSnapshot.result_hash 和调用者 expected_result_hash 三者一致。M1b 再核对 Artifact ID、原始字节 SHA-256、ResultSnapshot.result_hash 和调用者 expected_result_hash 四者一致。

Result payload 的规范根对象恰有 <code>result_schema_version</code>、<code>capability_id</code>、<code>contract_version</code>、<code>result_kind</code> 和 <code>data</code>；ValidationReport payload 的规范根对象恰有 <code>report_schema_version</code>、<code>validator_id</code>、<code>validator_implementation_id</code>、<code>validator_implementation_version</code>、<code>policy_version</code>、<code>policy</code>、<code>policy_hash</code>、<code>capability_id</code>、<code>contract_version</code>、<code>canonical_payload_hash</code>、<code>model_snapshot_hash</code>、<code>data_snapshot_set_hash</code>、<code>result_hash</code>、<code>outcome</code> 和 <code>metrics</code>。两者都不包含实体 ID、制品 ID、时间戳、operation_id 或 correlation_id；这些溯源字段由 SQLite 关系保存。M1b 将相同规范字节发布为可复用内容地址。

固定项目向量至少包括：

| 输入语义 | 规范 UTF-8 文本 | SHA-256 |
|---|---|---|
| 空数据快照集合 | <code>[]</code> | <code>sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945</code> |
| M1 空 ValidationPolicy | <code>{}</code> | <code>sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a</code> |
| <code>{"b":1.0,"a":-0.0}</code> | <code>{"a":0,"b":1}</code> | <code>sha256:f4c1d8bd90d7ccd720aa5a69a67185fb9caf4f35926a4eacf53a86d0e70bdf88</code> |

M1a 只要求上表三个固定烟测向量，以及表达式空白与默认值填充各一个项目向量；不通过时阻止写入。M1b 必须增加 RFC 8785 完整通用向量，以及对象键顺序、1 与 1.0、-0.0、Unicode NFC、默认值填充和表达式空白的完整项目向量；任何向量不匹配都阻止写入与制品发布。

### 8.6 Attempt 状态

~~~mermaid
stateDiagram-v2
    [*] --> PENDING
    PENDING --> RUNNING
    RUNNING --> SUCCEEDED
    RUNNING --> NUMERICAL_FAILURE
    RUNNING --> ERRORED
    RUNNING --> TIMED_OUT
    PENDING --> ABANDONED
    RUNNING --> ABANDONED
~~~

- <code>NUMERICAL_FAILURE</code> 是预期的数学失败；
- <code>ERRORED</code> 是能力实现异常、运行期资源拒绝或基础设施故障等非数学运行失败；
- <code>TIMED_OUT</code> 是协作式截止时间到达；
- 前一服务器 Session 留下的 PENDING 或 RUNNING 在恢复时变为 <code>ABANDONED</code>；
- 宿主取消在被 Built-in Capability 协作观察后也记录为 <code>ABANDONED</code>，并保存原因。

### 8.7 Validation 状态

Validation 的运行状态与数学结论分离：

- 运行状态：PENDING、RUNNING、SUCCEEDED、ERRORED、TIMED_OUT、ABANDONED；
- 只有运行状态 SUCCEEDED 时才有 outcome；
- outcome：PASSED、FAILED、INCONCLUSIVE。

运行错误不得伪装为 FAILED，FAILED 也不得作为 MCP 系统错误。

合法转换为：

~~~mermaid
stateDiagram-v2
    [*] --> PENDING
    PENDING --> RUNNING
    RUNNING --> SUCCEEDED
    RUNNING --> ERRORED
    RUNNING --> TIMED_OUT
    PENDING --> ABANDONED
    RUNNING --> ABANDONED
~~~

<code>terminal_reason</code> 只用于 TIMED_OUT 或 ABANDONED，枚举为 deadline_exceeded、host_cancelled 或 server_recovery。ERRORED 使用稳定 system_error 或 operational_error，不同时设置 terminal_reason。PENDING 不直接进入 TIMED_OUT，因为 M1 没有队列；deadline 从 RUNNING 前一刻计算。

### 8.8 终态输出矩阵

下表是 M1b 的完整制品矩阵；M1a 把其中“JSON Artifact 必须”替换为“对应规范 payload 必须内联于 SQLite”，把“不得存在 Artifact”替换为“不得存在 payload”，其他状态语义相同。

| 实体终态 | ResultSnapshot | Report Artifact | 数学 outcome | 错误或失败字段 |
|---|---|---|---|---|
| Attempt SUCCEEDED | 必须，kind=success | 结果 JSON Artifact 必须 | 不适用 | error 与 numerical_failure 为空 |
| Attempt NUMERICAL_FAILURE | 必须，kind=numerical_failure | 失败 JSON Artifact 必须 | 不适用 | capability failure 必须，system_error 为空 |
| Attempt ERRORED | 不得存在 | 不得存在 | 不适用 | system_error 必须 |
| Attempt TIMED_OUT | 不得存在 | 不得存在 | 不适用 | terminal_reason=deadline_exceeded |
| Attempt ABANDONED | 不得存在 | 不得存在 | 不适用 | terminal_reason 必须 |
| Validation SUCCEEDED | 不适用 | ValidationReport Artifact 必须 | PASSED、FAILED 或 INCONCLUSIVE 必须 | operational_error 为空 |
| Validation ERRORED | 不适用 | 不得存在 | 为空 | operational_error 必须 |
| Validation TIMED_OUT | 不适用 | 不得存在 | 为空 | terminal_reason=deadline_exceeded |
| Validation ABANDONED | 不适用 | 不得存在 | 为空 | terminal_reason 必须 |

M1a 的成功或数值失败结果及成功运行的验证结论在最终 SQLite 事务中原子写入规范 payload、哈希和终态。M1b 才要求“文件先发布、最终事务再引用”。ERRORED、TIMED_OUT 和 ABANDONED 只保存结构化运行元数据，不生成伪报告。

### 8.9 幂等事务

幂等唯一键为 <code>(scope_id, tool_name, operation_id)</code>。

M1a 只提供健康运行路径的基础幂等：同 key 同请求且已 COMPLETED 时返回同一实体，同 key 不同请求时返回 CONFLICT，IN_PROGRESS 时返回 operation_in_progress。M1a 必须让实体终态和 COMPLETED 记录在同一 SQLite 事务提交，但不承诺崩溃后自动收敛遗留 IN_PROGRESS；基础 doctor 报告遗留状态并拒绝继续写入，预览项目可以重建。以下完整恢复语义属于 M1b。

run_experiment 和 validate_experiment 的第一个短事务必须原子完成：

- 创建 <code>IdempotencyRecord(status=IN_PROGRESS, canonical_request_hash)</code>；
- 对 run_experiment 在 new 模式创建 InputSnapshot 和 Experiment，在两种模式都创建本次 EnvironmentSnapshot 与 Attempt(PENDING)；rerun 复用既有 InputSnapshot 和 Experiment；
- 对 validate_experiment 创建 Validation(PENDING)。

它们的最终短事务必须原子提交实体终态、所有已发布制品引用、响应实体引用，并把 IdempotencyRecord 改为 COMPLETED。

create_project 没有长计算或制品发布阶段：存储初始化完成后，以一个短 SQLite 事务原子创建或解析唯一 Project、写入完整响应引用，并直接插入 <code>IdempotencyRecord(status=COMPLETED)</code>。事务提交前崩溃时二者都不存在，提交后响应丢失时重放直接返回 COMPLETED；create_project 不允许留下 IN_PROGRESS 记录。

同一 key 的并发调用：

- request hash 不同：立即 CONFLICT/idempotency_mismatch；
- request hash 相同且 IN_PROGRESS：返回可重试 CONFLICT/operation_in_progress，不等待也不创建新实体；
- request hash 相同且 COMPLETED：先重新核对响应引用及其全部制品的存在性、大小和哈希；完整才返回持久化原结果并设置 <code>replayed=true</code>，不一致则 INTEGRITY_FAILURE 且不返回陈旧成功。

服务器恢复时，把遗留实体改为 ABANDONED，并在同一事务把相应 IN_PROGRESS 幂等记录改为 COMPLETED。之后重放只能返回 ABANDONED，不能自动重新执行；需要调用 run_experiment 的 rerun 模式并使用新 operation_id。

### 8.10 持久化顺序

执行期间不保持长 SQLite 事务。M1a 成功结果的顺序固定为：

~~~text
原子创建幂等记录、Experiment 和 Attempt(PENDING)
→ 标记 RUNNING
→ 真实执行
→ 校验规范结果 payload 并计算哈希
→ 短 SQLite 事务提交 ResultSnapshot 内联 payload、终态和幂等完成状态
→ 返回工具响应
~~~

M1b 成功结果的顺序固定为：

~~~text
原子创建幂等记录，以及需要的 InputSnapshot、Experiment、EnvironmentSnapshot 和 Attempt(PENDING)
→ 标记 RUNNING
→ 真实执行
→ 写入同卷 staging
→ 关闭、刷新、计算哈希、校验 Schema
→ 原子发布内容寻址制品
→ 短 SQLite 事务提交 ResultSnapshot、引用、终态和幂等完成状态
→ 返回工具响应
~~~

M1b 先发布文件再提交引用，保证 SQLite 不会指向缺失文件。最坏情况是留下未被引用的安全孤儿。

## 9. Built-in Capability 契约

本节的 Capability Contract 服务于能力执行，不定义第三方包的发现、安装或信任。M1 中所有生产实现都是 Built-in Capability；“External Plugin”专指未来第三方分发单元，不得用来称呼本节内置模块。

### 9.1 概念接口

~~~text
normalize_and_validate(raw_payload) -> CanonicalInput
execute(CanonicalInput, ExecutionContext) -> ExecutionOutcome
validate(CanonicalInput, ResultSnapshot, ValidationPolicy, ValidationContext)
  -> ValidationReport
~~~

### 9.2 描述符

每个能力描述符至少包含：

- <code>capability_api_version</code>；
- <code>capability_id</code>；
- <code>contract_version</code>；
- <code>implementation_id</code>；
- <code>implementation_version</code>；
- 标题、摘要、分类和标签；
- 原始输入、CanonicalInput、成功、失败 Schema 的版本化引用及 SHA-256；
- 确定性和随机性声明；
- 默认与最大执行限制；
- 支持的制品角色；
- 可用验证器摘要；
- 能力文档和上下文入口。

### 9.3 三个独立版本轴

1. Capability API Version：Stable Core 与能力实现的编程契约；
2. Capability Contract Version：能力对调用者可观察的输入输出，使用 SemVer；
3. Implementation Version：算法或代码实现版本，不改变契约时仍可递增。

CanonicalInput Schema 隶属于 Capability Contract：其可观察结构变化必须按同一 SemVer 政策演进，但使用独立的完整版本标识以便 InputSnapshot 自描述。运行前必须持久化三个版本和原始输入、CanonicalInput、成功、失败及报告的所有 Schema 哈希。

### 9.4 Schema 规则

- JSON Schema 2020-12；
- 根类型必须是 object；
- 根对象和结构化子对象默认 <code>additionalProperties: false</code>；
- 字段必须明确 required、类型、范围、枚举和空值语义；
- 数值必须是有限值，不能依赖非标准 JSON 的 NaN 或 Infinity；
- Schema 文件是数据形状的权威来源；
- 人类契约文档定义 Schema 无法表达的语义和兼容规则；
- 注册表启动时加载、校验并计算 Schema 哈希。

### 9.5 ExecutionContext

Built-in Capability 只能获得：

- attempt_id；
- 已持久化的 seed 或 <code>randomness=not_used</code>；
- 单调时钟 deadline；
- 协作取消信号；
- M1b 的受限 ArtifactSink；M1a 直接返回规范 ExecutionOutcome，不提供文件写入接口。

Built-in Capability 不能获得：

- SQLite 连接；
- 项目根或任意路径；
- MCP 上下文；
- 宿主身份；
- 秘密或完整进程环境；
- 任意状态修改接口。

能力实现不得打印 STDOUT。预期数学失败必须返回版本化失败对象，不能抛出通用异常。

### 9.6 验证器独立性

- 验证器独立注册，求解器不能选择自己的验证器；
- 描述符声明支持的 capability ID 和契约版本范围；
- 验证器有独立 implementation version、版本化 policy Schema 及哈希、policy version 和 report Schema 及哈希；
- 验证器不得导入求解器的数值实现；
- 求解器与验证器的共享代码 allowlist 只包括能力 contracts、JSON Schema 资产、<code>expression.syntax</code> 的语法解析与不可变 AST 类型；
- 求解器和验证器必须使用不同 evaluator 实现，不能共享 root search、终止判定、残差判定、结果构造或数值求值函数；
- 验证器必须独立重新求值和判定；
- 验证器永远读取已提交 ResultSnapshot，不接受求解器自报“已验证”。

M1 每个 validator ID 和 policy version 只允许一个活动实现。注册表确定性解析并在 Validation 建立前持久化 <code>validator_implementation_id</code> 和 <code>validator_implementation_version</code>。

### 9.7 注册与封存

组合根显式注册所有内置能力和验证器。启动阶段执行：

1. 描述符和 Schema 校验；
2. ID 与版本唯一性检查；
3. Capability API 兼容检查；
4. 验证器支持范围检查；
5. 必需能力存在性检查；
6. 计算注册表指纹；
7. 封存注册表。

重复、歧义、不兼容或缺少 M1 必需能力时，服务器拒绝进入 ready。

### 9.8 External Plugin 的未来边界

External Plugin 是未来可安装的第三方分发单元，不是 Capability 的同义词。若未来引入，它必须通过单独 ADR 定义发现、安装、签名、权限、依赖冲突、进程隔离和卸载语义；它可以贡献 Capability 与 Validator，但不能绕过本节契约。M1 不提供 Entry Point 扫描、External Plugin 目录、远程索引、安装命令、权限清单或 External Plugin SDK。

## 10. M1 Built-in Capability：numerical.root_finding

### 10.1 身份

- capability ID：<code>numerical.root_finding</code>
- contract version：M1a 为 <code>0.1.0</code>，M1b 为 <code>1.0.0</code>
- canonical input schema version：M1a 为 <code>numerical.root_finding.canonical-input/0.1.0</code>，M1b 为 <code>numerical.root_finding.canonical-input/1.0.0</code>
- implementation ID：<code>builtin.numerical.root_finding.bisection</code>
- implementation version：M1a 为 <code>0.1.0</code>，M1b 为 <code>1.0.0</code>
- 类别：numerical
- 随机性：not_used
- 执行模型：可信进程内、同步、协作式截止时间

### 10.2 输入契约

| 字段 | 约束 |
|---|---|
| expression | <code>math-expr-v1</code> 字符串，最大 4096 UTF-8 字节 |
| lower | 有限数 |
| upper | 有限数且 upper 大于 lower |
| absolute_tolerance | 有限、0 小于值且值不大于 1；默认 1e-10 |
| relative_tolerance | 有限、0 小于值且值不大于 1；默认 1e-10 |
| function_tolerance | 有限、0 小于值且值不大于 1；默认 1e-10 |
| max_iterations | 整数 1 至 10000；默认 100 |

表达式只允许变量 x、有限数值、常量 pi 和 e、运算符 +、-、*、/、**、括号、一元正负号，以及函数 abs、sqrt、exp、log、sin、cos、tan。禁止隐式乘法和其他 Python 语法。

pi 与 e 分别固定为 binary64 <code>0x1.921fb54442d18p+1</code> 和 <code>0x1.5bf0a8b145769p+1</code>。AST 按树顺序逐节点求值，不重排或使用 fast-math；允许两个独立 evaluator 分别调用 Python 标准 <code>math</code> 原语，但不得共享项目内数值包装、缓存或求值函数。平台 libm 差异按声明容差和 EnvironmentSnapshot 管理，不宣称跨平台位级一致。

数值字面量最多 64 个字符，并在解析时立即转换为 binary64，不允许任意精度整数。指数运算的右操作数必须是 [-1024, 1024] 内的规范 number 节点，不允许变量或复合指数。一次表达式求值最多访问 256 个 AST 节点；每个节点前检查 deadline 和取消信号；一次 Attempt 的函数求值总数最多 20000。解析阶段超限在建立 Attempt 前返回 RESOURCE_LIMIT_EXCEEDED；运行中域错误、溢出或非有限中间值使用能力失败 Schema；达到 max_iterations 使用 non_convergence；若实现异常耗尽 20000 次函数求值安全预算，则 Attempt=ERRORED 并嵌入 RESOURCE_LIMIT_EXCEEDED。

### 10.3 成功结果

成功 Result payload 的 <code>result_kind=success</code>，<code>data</code> 恰有以下字段；M1a 将规范 payload 内联于 SQLite，M1b 将相同字节发布为 Result Artifact：

- root：有限 binary64；
- function_value：在返回 root 处真实求值的有限 binary64；
- iterations：0 至 max_iterations 的整数；
- evaluations：1 至 20000 的整数；
- termination_reason：endpoint_root、residual_tolerance 或 interval_tolerance。

M1 活动实现固定为确定性 binary64 二分法，契约顺序为：

1. 从原表达式真实求值 lower 和 upper；任一端点满足 <code>abs(f(x)) &lt;= function_tolerance</code> 时按 lower、upper 顺序返回 endpoint_root；
2. 两端均不满足且有限函数值没有异号时返回 no_sign_change；异号比较使用符号位，不以乘法判断，避免乘法溢出；
3. 每轮使用防溢出的 binary64 中点与半宽原语：当 lower 与 upper 坐标的数值符号不同时，用 <code>lower/2 + upper/2</code> 和 <code>upper/2 - lower/2</code>；坐标同号时用 <code>lower + (upper-lower)/2</code> 和 <code>(upper-lower)/2</code>。先检查 <code>abs(f(midpoint)) &lt;= function_tolerance</code>，满足则返回 residual_tolerance；
4. 否则按符号保持一个有效括区，再检查 <code>half_width &lt;= absolute_tolerance + relative_tolerance * abs(midpoint)</code>；满足则返回当前 midpoint 和对应真实函数值，termination_reason=interval_tolerance；
5. 达到 max_iterations，或 binary64 中点与端点相同但尚未满足任何成功条件时，返回 non_convergence。

每次表达式求值只计一次 evaluation；iterations 是完成的中点轮数。端点域错误、溢出或非有限值分别进入 domain_error 或 non_finite_evaluation，不把无效括区伪装成 no_sign_change。

### 10.4 数值失败

数值失败 Result payload 的 <code>result_kind=numerical_failure</code>，<code>data</code> 恰有 <code>failure_code</code>、<code>iterations</code> 和 <code>evaluations</code>。M1a 内联保存，M1b 发布为 Artifact。后两者是非负整数且不超过本次政策上限；failure_code 只能是：

- no_sign_change；
- non_convergence；
- domain_error；
- non_finite_evaluation。

无效表达式、非法区间和非法限制在 Attempt 建立前被拒绝，不是数值失败。

### 10.5 验证器

验证器 ID 为 <code>numerical.root_finding.residual</code>，validator implementation ID 为 <code>builtin.numerical.root_finding.residual</code>；implementation version 和 policy version 在 M1a 均为 <code>0.1.0</code>，在 M1b 均为 <code>1.0.0</code>。M1 policy 参数是严格空对象，其 policy_hash 是第 8.5 节固定空对象向量；阈值来自原实验输入。ValidationContext 提供与 ExecutionContext 相同语义的单调时钟 deadline 和协作取消信号。

验证器独立检查：

1. 结果 Schema 与预期哈希；
2. root 和 function_value 有限；
3. root 位于原区间；
4. 原表达式在 root 处可定义且重新求值有限；
5. <code>abs(recomputed_f - function_value) &lt;= function_tolerance</code>；
6. <code>abs(recomputed_f) &lt;= function_tolerance</code>。

M1 residual policy 只返回 PASSED 或 FAILED，不使用 INCONCLUSIVE。报告 metrics 恰有 <code>root_within_interval</code>、<code>reported_function_value</code>、<code>recomputed_function_value</code>、<code>absolute_reported_delta</code>、<code>absolute_residual</code>、<code>function_tolerance</code> 和 <code>failed_checks</code>。重新求值无法得到有限数时，三个 recomputed 派生数值为 null；failed_checks 是按上述检查顺序排列的枚举数组，只允许 root_out_of_interval、expression_undefined、non_finite_recomputed_value、reported_value_mismatch、residual_exceeds_tolerance。数组为空才是 PASSED，否则是 FAILED。

PASSED 只证明上述数值策略成立，不证明根唯一、模型正确或存在形式化证明。

求解器以 interval_tolerance 合法终止但残差验证 FAILED 是允许且必须测试的组合：SUCCEEDED 表示求解器满足其终止契约，Validation outcome 表示独立残差政策的结论，两者不能合并。

## 11. MCP 工具边界

### 11.1 通用规则

- M1 只暴露六个工具；
- 不提供 MCP Prompt、Resource、Sampling、Elicitation 或异步 Job API；
- 工具契约在 M1a 为 <code>modeling-tools/0.1.0</code>，在 M1b 冻结为 <code>modeling-tools/1.0.0</code>，与 MCP Protocol 2025-11-25 和能力契约分开管理；
- 所有输入输出使用严格 JSON Schema 2020-12；
- JSON 解析拒绝重复对象键、无效 UTF-8、未配对 surrogate、NaN 和 Infinity；
- MCP 只验证通用外壳，Built-in Capability 验证 capability payload；
- 进程启动时绑定一个项目根，工具不接受任意数据库或输出路径；
- M1a 对超过内联上限的结果失败关闭；M1b 的大结果返回制品清单；
- STDOUT 仅用于 MCP 协议帧，日志写 STDERR。

### 11.2 公共类型与响应

本节其余字段定义是 M1b <code>modeling-tools/1.0.0</code> 的规范性基线。M1a <code>modeling-tools/0.1.0</code> 使用同一六工具名和通用 Error 结构，但采用以下严格、有限的预览差异：

| M1a 范围 | 0.1.0 预览规则 |
|---|---|
| 通用成功根 | tool_contract_version=<code>modeling-tools/0.1.0</code>、correlation_id、server_time 和工具专属字段；写工具另含 operation_id、replayed |
| health_check | versions 使用第 3.1 节 M1a 列；checks 只要求 MCP、SQLite、注册表和项目状态 |
| get_project_status | 只支持 summary 与单个 experiment 查询；summary 最多返回最近 20 个 Experiment，experiment 一次返回完整 M1a 内联 trace；不提供 cursor，超出 256 KiB 时明确失败 |
| list_capabilities | 支持 summary 和精确 contract；字段使用 capability_api_version；artifact_roles 固定为空数组 |
| run_experiment | 只支持 new 模式；成功或数值失败返回 result_hash 与严格 result_summary，不返回 ArtifactManifest、input_snapshot_id 或 environment_snapshot_id |
| validate_experiment | 成功返回 outcome、metrics 和 validation_report_hash，不返回 report_artifact |
| trace | Experiment 内联 canonical payload 和哈希，Attempt 内联 environment_summary，Result 与 Validation 内联规范 payload；无 Artifact 字段 |
| 兼容承诺 | 必须有六工具严格 JSON Schema 和合法/非法烟测语料，但它们不是发布兼容基线 |

M1a 对 M1b 字段定义采用以下精确覆盖；未列出的业务规则沿用对应工具章节：

- <code>health_check</code> 请求仍是严格空对象；响应字段仍为 status、project_state、ready_for_project_creation、versions、registry、checks、warnings，其中 versions 包含 <code>capability_api_version</code> 并使用第 3.1 节 M1a 列。
- <code>create_project</code> 的请求和响应字段与第 11.4 节相同，只使用 M1a Project Format、Error 和 tool contract 版本。
- <code>get_project_status</code> 请求恰有 project_id、可选 view，省略 view 时默认为 summary；view=experiment 时还必须有 experiment_id，view=summary 时禁止 experiment_id；0.1.0 不接受 cursor 或 limit。
- M1a summary 响应的工具专属字段恰有 <code>view=summary</code>、project、attempt_status_counts、validation_status_counts、registry_fingerprint、last_activity_at 和 <code>experiments={items,truncated}</code>；items 按 <code>(created_at,experiment_id)</code> 降序并最多 20 项，truncated 表示是否仍有未返回项。
- M1a experiment 响应的工具专属字段恰有 <code>view=experiment</code>、project、experiment 和 trace。trace 是按 <code>(created_at,record_type,entity_id)</code> 升序的完整数组；若整个合法响应超过内联上限则失败，不截断。
- M1a ExperimentSummary 恰有 experiment_id、capability_id、contract_version、created_at、attempt_count、latest_attempt_id、latest_attempt_status、latest_attempt_at 和 validation_count。
- M1a ExperimentRecord 恰有 experiment_id、project_id、capability_id、contract_version、canonical_input_schema_version、canonical_payload、canonical_payload_hash、canonicalization_version、model_snapshot_hash、data_snapshot_references、data_snapshot_set_hash、execution_policy 和 created_at。
- M1a ResultTrace 恰有 result_snapshot_id、result_kind、result_schema_version、result_hash 和 result_payload；result_payload 是第 8.5、10 节的完整规范 Result payload。
- M1a AttemptTrace 恰有 record_type=attempt、attempt_id、experiment_id、implementation_id、implementation_version、environment_summary、randomness、seed、session_id、status、created_at、started_at、finished_at、warnings、result、system_error、numerical_failure 和 terminal_reason；warnings 是必填数组，started_at、finished_at、result、system_error、numerical_failure、terminal_reason 是按第 8.8 节组合的必填 nullable 字段。
- M1a ValidationTrace 恰有 record_type=validation、validation_id、attempt_id、expected_result_hash、result_hash、validator_id、validator_implementation_id、validator_implementation_version、policy_version、policy、policy_hash、status、created_at、started_at、finished_at、outcome、metrics、validation_report_hash、report_payload、operational_error 和 terminal_reason；从 started_at 到 terminal_reason 的状态相关字段是第 8.8 节定义的必填 nullable 组合。
- <code>list_capabilities</code> 请求和 summary/contract 响应结构沿用第 11.6 节，但 contract 中字段名是 capability_api_version，artifact_roles 必须为空。
- M1a <code>run_experiment</code> 请求必须带 <code>mode=new</code>，并带 operation_id、project_id、capability、payload，可选 execution；禁止 experiment_id。响应的共同工具专属字段恰有 experiment_id、attempt_id、attempt_status、capability_id、contract_version、implementation_id、implementation_version、randomness、seed、warnings，再按终态增加 result_kind/result_hash/result_summary、system_error 或 terminal_reason；不出现 input_snapshot_id、environment_snapshot_id 或 artifacts。
- M1a <code>validate_experiment</code> 请求字段沿用第 11.8 节并使用 0.1.0 policy_version。响应共同工具专属字段恰有 validation_id、attempt_id、result_hash、validator_id、validator_implementation_id、validator_implementation_version、policy_version、policy_hash、validation_status；SUCCEEDED 增加 outcome、metrics、validation_report_hash，其他终态增加对应 operational_error 或 terminal_reason；不出现 report_artifact。

M1a 预览 Schema 是实现时的权威资产，不得通过“任意 object”规避严格字段。第 11.3 至 11.12 节的业务语义同时适用；其中 rerun、cursor、InputSnapshotTrace、EnvironmentSnapshotTrace、ArtifactManifest、报告制品和四重 Artifact 哈希只在 M1b 启用。M1b 字段如下：

| 类型 | 规范 |
|---|---|
| EntityId / operation_id / correlation_id | 小写 UUID v4 字符串；EntityId 不包含 ArtifactId |
| ArtifactId | 与制品内容 Hash 完全相同，不是 UUID |
| Hash | <code>sha256:&lt;64 位小写十六进制&gt;</code> |
| Version | 本文固定值或 SemVer 字符串 |
| Timestamp | UTC RFC 3339，毫秒精度，以 Z 结尾 |
| ArtifactManifest | artifact_id、role、sha256、media_type、size_bytes、project_relative_path |
| Warning | code、message；message 为 NFC、禁止控制字符、最多 1024 UTF-8 字节，不得包含秘密或绝对路径 |

每个成功响应的根对象都要求：

- <code>tool_contract_version</code>，常量 <code>modeling-tools/1.0.0</code>；
- <code>correlation_id</code>；
- <code>server_time</code>；
- 工具专属字段；
- 根对象禁止未知字段。

写工具响应还要求 <code>operation_id</code> 和 <code>replayed</code>。ArtifactManifest 的相对路径由核心生成，调用方不能在请求中指定。

ArtifactManifest 中 <code>artifact_id == sha256</code>，M1b role 只能是 result 或 validation_report，media_type 为 <code>application/json</code>，size_bytes 是非负整数。若 Hash 的十六进制部分为 h，project_relative_path 恰为 <code>.modeling/artifacts/sha256/h[0:2]/h.json</code>，使用正斜杠。system_error 与 operational_error 使用第 15.2 至 15.3 节的稳定 Error 对象；terminal_reason 使用第 8.7 节枚举。

内联响应上限是 structuredContent 按当前 canonical-json 版本编码后的 262144 个 UTF-8 字节。非分页工具若合法单个响应仍超过上限，返回 RESOURCE_LIMIT_EXCEEDED/inline_response_bytes；不得截断字段。M1a 不接受超过上限的结果；M1b 的大能力结果必须把主体写入 Artifact，只内联严格 result_summary。

所有包含 project_id 的工具都要求它等于当前绑定项目；不匹配统一返回 NOT_FOUND/project，且不泄露其他项目是否存在。

项目状态门禁是规范性的：

| 工具 | UNINITIALIZED | STORAGE_READY | READY | DEGRADED |
|---|---|---|---|---|
| health_check | 允许 | 允许 | 允许 | 允许，只读退化报告 |
| create_project | 允许并初始化存储 | 允许 | 允许幂等读取或元数据冲突 | 拒绝 PRECONDITION_FAILED/project_degraded |
| get_project_status | 拒绝 PRECONDITION_FAILED/project_not_ready | 拒绝同左 | 允许 | 拒绝 PRECONDITION_FAILED/project_degraded |
| list_capabilities | 允许 | 允许 | 允许 | 拒绝 PRECONDITION_FAILED/project_degraded |
| run_experiment | 拒绝 PRECONDITION_FAILED/project_not_ready | 拒绝同左 | 允许 | 拒绝 PRECONDITION_FAILED/project_degraded |
| validate_experiment | 拒绝 PRECONDITION_FAILED/project_not_ready | 拒绝同左 | 允许 | 拒绝 PRECONDITION_FAILED/project_degraded |

只读 CLI doctor 可在四种状态运行。list_capabilities 在非退化的建项前状态可用，因为它只读取已封存注册表。

以下嵌套类型同样禁止未知字段；表中标为 nullable 的字段仍是必填键，其值可以是 null：

| 类型 | 必填字段与约束 |
|---|---|
| RegistrySummary | sealed:boolean、fingerprint:Hash、capability_count:非负整数 |
| ProjectSummary | project_id、display_name、project_format_version、project_state=READY、created_at |
| AttemptStatusCounts | pending、running、succeeded、numerical_failure、errored、timed_out、abandoned，均为非负整数 |
| ValidationStatusCounts | pending、running、succeeded、errored、timed_out、abandoned，均为非负整数 |
| ExperimentSummary | experiment_id、capability_id、contract_version、input_snapshot_id、created_at、attempt_count、latest_attempt_id、latest_attempt_status、latest_attempt_at、validation_count |
| ExperimentRecord | experiment_id、project_id、capability_id、contract_version、input_snapshot_id、execution_policy={timeout_ms,seed}、created_at |
| InputSnapshotTrace | input_snapshot_id、canonical_input_schema_version、canonical_input_schema_hash、canonical_payload、canonical_payload_hash、canonicalization_version、model_snapshot_hash、data_snapshot_references、data_snapshot_set_hash |
| DataSnapshotReference | snapshot_id:EntityId、sha256:Hash；数组按 snapshot_id 升序，M1 固定为空数组 |
| EnvironmentSnapshotTrace | environment_snapshot_id、python_version、uv_version、os_name、os_version、architecture、application_version、lock_hash、numerical_libraries、locale；numerical_libraries 是按 name 升序的严格 {name,version} 数组 |
| ResultTrace | result_snapshot_id、result_kind、result_schema_version、result_hash、result_summary、artifacts；artifacts 是非空 ArtifactManifest 数组，M1b 恰有 role=result 的 JSON Artifact |
| AttemptTrace | record_type=attempt、attempt_id、experiment_id、implementation_id、implementation_version、environment_snapshot、randomness、seed、session_id、status、created_at、started_at:nullable、finished_at:nullable、warnings、result:nullable、system_error:nullable、numerical_failure:nullable、terminal_reason:nullable |
| ValidationTrace | record_type=validation、validation_id、attempt_id、expected_result_hash、result_hash、validator_id、validator_implementation_id、validator_implementation_version、policy_version、policy、policy_hash、status、created_at、started_at:nullable、finished_at:nullable、outcome:nullable、metrics:nullable、validation_report_hash:nullable、report_artifact:nullable、operational_error:nullable、terminal_reason:nullable |

AttemptTrace 与 ValidationTrace 的 nullable 组合必须逐行符合第 8.8 节；numerical_failure 在对应终态恰等于失败 ResultTrace.result_summary。<code>canonical_payload</code> 和 <code>result_summary</code> 分别受选定能力的版本化 CanonicalInput 与结果 Schema 约束，不是任意未校验 JSON；M1 canonical_payload 的具体类型就是第 8.5 节 RootFindingCanonicalInput。

### 11.3 health_check

请求是严格空对象。

响应必填：

| 字段 | 类型与语义 |
|---|---|
| status | OK 或 DEGRADED |
| project_state | UNINITIALIZED、STORAGE_READY、READY 或 DEGRADED |
| ready_for_project_creation | boolean；只在 UNINITIALIZED 或 STORAGE_READY 为 true |
| versions | 严格对象：application_version、mcp_protocol_version、tool_contract_version、project_format_version、database_schema_version、capability_api_version、error_schema_version、result_schema_version、validation_report_schema_version、canonicalization_version、root_finding_contract_version、root_finding_canonical_input_version、residual_policy_version；值来自第 3.1 节对应里程碑列 |
| registry | RegistrySummary |
| checks | 严格 {name,status,code} 数组；status=OK/WARN/FAIL，code 是稳定诊断码 |
| warnings | Warning 数组 |

UNINITIALIZED 不是故障，health 返回 OK。现有项目的版本、锁或完整性检查失败时返回 DEGRADED，仍以正常工具结果返回而不是 <code>isError=true</code>。health 不创建文件、不打开长事务、不执行数学能力。

### 11.4 create_project

请求：

| 字段 | 必填 | 约束与默认 |
|---|---|---|
| operation_id | 是 | UUID v4 |
| display_name | 否 | Unicode NFC，1 至 128 字符；首次创建默认项目根最后一个目录名，READY 时省略则解析为既有 display_name |

除通用写响应字段外，响应恰有 project_id、display_name、project_format_version、project_state=READY、created:boolean 和 created_at。首次创建时 created=true；合法读取既有同一 Project 时为 false。

一个绑定根只能有一个 Project。READY 状态下 display_name 与既有值相同则返回既有 Project；不同则 CONFLICT/project_metadata_mismatch。UNINITIALIZED 时先执行第 8.1 节存储初始化，再用唯一数据库事务原子创建或解析 Project、完成幂等记录并保存响应引用。调用开始时已是 DEGRADED 则按状态矩阵返回 PRECONDITION_FAILED/project_degraded；若本次初始化才发现完整性冲突，则返回 INTEGRITY_FAILURE 并进入 DEGRADED。请求不包含任何路径。

处理顺序固定为：校验请求外壳与项目状态；必要时原子初始化存储；取得项目写锁；按当前状态物化 display_name 并计算 canonical_request_hash；在唯一事务中先执行幂等键判断，再创建或解析 Project，最后直接保存 COMPLETED 记录与响应引用。事务回滚不留下 Project 或幂等记录。

### 11.5 get_project_status

请求使用以下二选一 view：

| 字段 | summary view | experiment view |
|---|---|---|
| project_id | 必填 | 必填 |
| view | 省略或 summary | experiment |
| cursor | 可选 | 可选 |
| limit | 可选，默认 20，1 至 100；是项目数上限 | 可选，默认 20，1 至 100；是 trace 记录数上限 |
| experiment_id | 禁止 | 必填 |

project_id 与绑定项目不一致返回 NOT_FOUND/project。

summary 响应的工具专属根字段恰有：

- <code>view=summary</code>；
- <code>project:ProjectSummary</code>；
- <code>attempt_status_counts:AttemptStatusCounts</code>；
- <code>validation_status_counts:ValidationStatusCounts</code>；
- <code>registry_fingerprint:Hash</code>；
- <code>last_activity_at:Timestamp</code>，为 Project.created_at 与所有实体 created_at/finished_at 的最大值；
- <code>experiments={items:ExperimentSummary[],next_cursor:string|null}</code>。

ExperimentSummary 按 <code>(created_at, experiment_id)</code> 降序。Experiment 总在首事务与首个 Attempt 同建，因此 latest_attempt_id、latest_attempt_status 和 latest_attempt_at 不可为 null。

experiment 响应的工具专属根字段恰有：

- <code>view=experiment</code>；
- <code>project:ProjectSummary</code>；
- <code>experiment:ExperimentRecord</code>；
- <code>input_snapshot:InputSnapshotTrace</code>；
- <code>trace={items:(AttemptTrace|ValidationTrace)[],next_cursor:string|null}</code>。

trace 把 Attempt 与 Validation 作为带 record_type 判别字段的联合记录，按 <code>(created_at, record_type, entity_id)</code> 升序分页；ValidationTrace.attempt_id 保留关系。遍历全部页面可取得每个 Attempt 的 EnvironmentSnapshot、ResultSnapshot、warnings、ArtifactManifest，以及全部 Validation、metrics 和报告 ArtifactManifest。

summary cursor 是最后一项 <code>{"view":"summary","created_at":...,"experiment_id":...}</code> 的 canonical JSON 无填充 base64url；experiment cursor 是 <code>{"view":"experiment","experiment_id":...,"created_at":...,"record_type":...,"entity_id":...}</code> 的 canonical JSON 无填充 base64url。调用方把 cursor 视为不透明。两者使用 keyset pagination；M1 不删除实体，因此边界 ID 稳定，但跨页读取是当前投影而非数据库快照。格式错误、view 或 project 不匹配、或边界不存在时返回 INVALID_REQUEST，details.reason=invalid_cursor。

分页合成规则固定为：limit 只是条目数上限；服务端依排序逐条加入，并在下一条会使完整 structuredContent 超过 262144 字节前停止，把最后已加入条目编码为 next_cursor。不得拆分单条记录。若静态响应加当前第一条记录就超限，返回 RESOURCE_LIMIT_EXCEEDED，details.resource=inline_response_bytes、limit=262144、observed 为该候选响应字节数；不得返回空页形成死循环。数据耗尽时 next_cursor=null。

### 11.6 list_capabilities

请求字段：

| 字段 | 必填 | 规则 |
|---|---|---|
| detail | 否 | summary 或 contract，默认 summary |
| category | 否 | 只允许 summary |
| capability_id | 否 | summary 可作精确筛选；contract 时必填 |
| contract_version | 否 | contract 时必填，summary 时禁止 |

CapabilitySummary 是严格对象，恰有 capability_id、contract_version、title、summary、category、tags、determinism、randomness、input_schema_hash、canonical_input_schema_version、canonical_input_schema_hash、success_schema_hash 和 failure_schema_hash；tags 按字典序且无重复。PolicyContract 恰有 policy_version、policy_schema 和 policy_schema_hash。ValidatorSummary 恰有 validator_id、policies:PolicyContract[]、report_schema_version、report_schema、report_schema_hash 和 summary；两个 schema 对象均为已校验 JSON Schema 2020-12，policies 按版本升序。

summary 响应的工具专属根字段恰有 <code>detail=summary</code>、<code>registry:RegistrySummary</code> 和 <code>capabilities:CapabilitySummary[]</code>；数组按 <code>(capability_id, contract_version)</code> 升序。

contract 响应的工具专属根字段恰有 <code>detail=contract</code>、<code>registry:RegistrySummary</code> 和 <code>capability</code>。capability 是严格对象，恰有 CapabilitySummary 的全部字段，加上 capability_api_version、implementation_id、implementation_version、input_schema、canonical_input_schema、success_schema、failure_schema、default_limits、maximum_limits、artifact_roles、validators:ValidatorSummary[] 和 context_ref。四个 schema 字段是已校验的 JSON Schema 2020-12 对象；limits 是字段固定为 timeout_ms、max_iterations、max_evaluations 的非负整数对象；artifact_roles 是无重复字符串数组；context_ref 是项目内文档逻辑引用，不是调用方可访问的任意文件路径。M1a 的 artifact_roles 是空数组；M1b 可声明 result 和 validation_report。

不存在的 ID 返回 NOT_FOUND；存在 ID 但版本不支持返回 UNSUPPORTED_VERSION。M1 不允许 contract 模式隐式选择最新版本。

### 11.7 run_experiment

请求根字段 <code>operation_id</code>、<code>project_id</code> 和 <code>mode</code> 必填，并使用以下二选一：

| 字段 | new 模式 | rerun 模式 |
|---|---|---|
| capability | 必填对象：capability_id、contract_version | 禁止 |
| payload | 必填对象，由能力 Schema 校验 | 禁止 |
| execution | 可选 | 禁止 |
| experiment_id | 禁止 | 必填 |

execution 对象字段：

| 字段 | 约束 |
|---|---|
| timeout_ms | 整数 1 至 60000；默认 10000 |
| seed | null 或 JSON 安全整数 [-9007199254740991, 9007199254740991]；确定性能力只允许省略或 null |

有效 deadline 为 <code>monotonic_now + min(requested_or_default_timeout_ms, capability_max_timeout_ms, 60000) / 1000</code>，在 Attempt 进入 RUNNING 前一刻计算。到达边界的判断是 <code>monotonic_now &gt;= deadline</code>。

new 模式总是创建新的不可变 Experiment 和第一个 Attempt；只有同 operation_id 重放才复用。
rerun 模式读取既有 Experiment 的完整意图和执行政策，只创建新 Attempt；记录的 capability contract 和 implementation 必须仍可用，否则返回 UNSUPPORTED_VERSION。rerun 必须使用新的 operation_id。

处理顺序固定为：校验工具外壳；校验项目状态与 project_id；校验能力 payload、物化默认值并计算 canonical_request_hash；查找幂等记录并按第 8.9 节复核重放完整性；校验资源上限；确定性解析并捕获实现与环境；执行第 8.9 节首事务；进入 RUNNING 并计算 deadline；真实执行；按第 8.8 至 8.10 节完成最终持久化。M1a 内联 payload，M1b 发布制品。首事务之前的任何失败都不创建 Experiment 或 Attempt。

M1b 除通用写响应字段外，响应始终恰有 experiment_id、attempt_id、attempt_status、capability_id、contract_version、implementation_id、implementation_version、input_snapshot_id、environment_snapshot_id、randomness、seed 和 warnings，再加下述终态互斥字段；M1a 使用第 11.2 节覆盖字段。同步正常响应的 attempt_status 只能是 SUCCEEDED、NUMERICAL_FAILURE、ERRORED、TIMED_OUT 或 ABANDONED，不返回 PENDING/RUNNING。

响应按终态条件包含：

- SUCCEEDED 或 NUMERICAL_FAILURE：M1a 返回 result_kind、result_hash 和严格 result_summary；M1b 另返回 <code>artifacts:ArtifactManifest[]</code>，数组恰有一个 role=result 的 JSON Artifact；result_summary 恰为第 10.3 或 10.4 节的 data 对象；
- ERRORED：system_error；
- TIMED_OUT 或 ABANDONED：terminal_reason；
- 其他字段按第 8.8 节必须为空且不得出现。

### 11.8 validate_experiment

请求：

| 字段 | 必填 | 约束 |
|---|---|---|
| operation_id | 是 | UUID v4 |
| project_id | 是 | 必须等于 Attempt 所属 Project |
| attempt_id | 是 | 必须存在且状态为 SUCCEEDED |
| expected_result_hash | 是 | 第 8.5 节 result_hash |
| validator_id | 是 | M1 为 numerical.root_finding.residual |
| policy_version | 是 | M1a 为 0.1.0，M1b 为 1.0.0 |
| policy | 是 | M1 是严格空对象 |
| timeout_ms | 否 | 整数 1 至 60000；默认 10000 |

Validation 的 effective deadline 使用与 run_experiment 相同的公式和边界比较，并受验证器描述符与全局 60000 ms 上限共同约束。

处理顺序是：

1. 校验请求 Schema 并计算 canonical_request_hash；
2. 校验项目状态和 project_id；
3. 查找幂等记录；已完成时按第 8.9 节核对 Result 与报告 payload 后重放，M1b 另核对制品；
4. 校验 Attempt=SUCCEEDED、success ResultSnapshot 存在；
5. 重新读取规范输入，复核 CanonicalInput Schema、canonical payload、model snapshot 和 data snapshot set 哈希；M1a 读取内联结果并核对三重哈希，M1b 读取结果 Artifact 并核对四重哈希；
6. 校验 validator 支持 capability contract 和 policy version；
7. 原子创建 IdempotencyRecord(IN_PROGRESS) 与 Validation(PENDING)；
8. 进入 RUNNING，计算 deadline，独立验证；
9. 按第 8.8、8.9 节提交报告、终态和幂等完成；M1a 内联报告，M1b 先发布报告制品。

第 2、4、5、6 步失败发生在 Validation 建立前，返回 <code>isError=true</code>；错误 expected_result_hash 返回 INTEGRITY_FAILURE，不创建 Validation。第 3 步的幂等冲突同样不创建新 Validation。

除通用写响应字段外，响应始终恰有 validation_id、attempt_id、result_hash、validator_id、validator_implementation_id、validator_implementation_version、policy_version、policy_hash 和 validation_status，再加下述终态互斥字段。同步正常响应的 validation_status 只能是 SUCCEEDED、ERRORED、TIMED_OUT 或 ABANDONED。SUCCEEDED 在 M1a 增加 outcome、metrics 和 validation_report_hash，M1b 再增加 <code>report_artifact:ArtifactManifest</code>，其 role=validation_report；ERRORED 只增加 operational_error；TIMED_OUT 或 ABANDONED 只增加 terminal_reason。互斥字段按第 8.8 节不得出现。

### 11.9 工具错误集合

| 工具 | 允许的业务错误码 |
|---|---|
| health_check | INVALID_REQUEST、RESOURCE_LIMIT_EXCEEDED、INTERNAL_ERROR；组件故障进入 DEGRADED 正常结果 |
| create_project | INVALID_REQUEST、UNSUPPORTED_VERSION、CONFLICT、PRECONDITION_FAILED、SECURITY_VIOLATION、RESOURCE_LIMIT_EXCEEDED、INTEGRITY_FAILURE、INTERNAL_ERROR |
| get_project_status | INVALID_REQUEST、NOT_FOUND、UNSUPPORTED_VERSION、PRECONDITION_FAILED、RESOURCE_LIMIT_EXCEEDED、INTEGRITY_FAILURE、INTERNAL_ERROR |
| list_capabilities | INVALID_REQUEST、NOT_FOUND、UNSUPPORTED_VERSION、PRECONDITION_FAILED、RESOURCE_LIMIT_EXCEEDED、INTERNAL_ERROR |
| run_experiment | 九个稳定错误码全部允许，阶段映射见第 15.4 节 |
| validate_experiment | 九个稳定错误码全部允许，阶段映射见第 15.4 节 |

### 11.10 同步语义

<code>run_experiment</code> 和 <code>validate_experiment</code> 在 M1 中同步、有协作式截止时间，只接受可信短任务。M1 不以轮询式假异步接口掩盖未来需求。M2.5 先引入受控计算 worker 和硬超时；只有真实长任务需要排队时，才另行通过契约和 ADR 引入 Job 模型。

### 11.11 实现解析

调用方指定 capability ID 和 contract version。M1 每个契约只允许一个活动实现，注册表确定性解析并在执行前持久化精确 implementation ID/version。未来存在多实现时，必须先设计显式选择政策，不能隐式选择“最新”。

### 11.12 MCP 错误与记录

- 记录建立前的请求、版本、安全和前置条件问题使用 MCP <code>isError=true</code>；
- Attempt 或 Validation 建立后，终态作为正常结构化结果返回；
- 数值失败和验证 FAILED 不是 MCP 错误；
- JSON-RPC 解析和传输错误使用 MCP 标准错误，业务错误使用本文稳定错误对象。

业务错误的 MCP ToolResult 设置 <code>isError=true</code>，其 structuredContent 恰为第 15.2 至 15.3 节 Error 对象，不混入成功响应字段；可选人类文本不得成为机器判定依据。正常结果设置 <code>isError=false</code>。

### 11.13 M1b 首发 Schema 基线

M1a 必须生成并自洽验证六组 0.x request/result/error JSON Schema 和基本语料，但不保存为兼容基线。本文第 11 节的 1.0 形态是 M1b 工具契约设计基线；M1b 实施必须提交与其逐字段一致的六组 request/result/error JSON Schema，以及每个工具固定的合法、非法、边界和错误请求语料。

Greenfield 首次可信发布的 B-01 定义为：

1. 生成 Schema 与本文设计基线一致；
2. 所有固定语料得到本文规定结果；
3. 把这些 Schema 和语料标记为首个发布基线。

只有 M1b 基线之后的发布才执行“新版本相对最近发布基线向后兼容”的集合比较。M1a 到 M1b 是明确的 0.x 到 1.0 升级，不承担向后兼容义务；这样首发不依赖不存在的历史基线，也不把兼容框架塞入 M1a。

## 12. 项目状态、SQLite 与制品

### 12.1 项目内部目录

M1a 在绑定项目根内保留最小状态目录：

~~~text
.modeling/
  project.json
  state.sqlite3
  project.lock
~~~

M1b 增加：

~~~text
.modeling/
  staging/
  artifacts/sha256/
~~~

原始附件不移动、不覆盖。M1 的根求解 payload 不引用附件。

<code>project.json</code> 在 STORAGE_READY 保存 Project Format、canonicalization version 和 storage_instance_id，不包含绝对项目路径，也不代表 Project 领域记录已经存在；唯一 Project 领域记录由 create_project 写入 SQLite。

### 12.2 SQLite 规则

- 一个项目同一时间只有一个写入服务器；
- 使用操作系统级项目锁，Session UUID 用于诊断，PID 不是权威锁；
- 单个服务器内也只有一个活动写工作流；create_project、run_experiment 和 validate_experiment 通过应用层 admission gate 串行化，不排队；同 operation_id 按幂等规则响应，其他并发写请求返回可重试 CONFLICT/project_busy 且不创建实体；
- health_check、list_capabilities 和 get_project_status 只读取已提交状态，可以与活动写工作流并发；
- SQLite 启用 foreign keys、WAL、完整同步和 <code>busy_timeout=250 ms</code>；
- M1a 设置并校验 <code>PRAGMA user_version=1</code>；M1b 首个稳定 Schema 使用 <code>user_version=2</code>，二者就是各自 database_schema_version；
- 数值计算不在数据库事务中执行；
- 新版本程序遇到更高项目 Schema 版本时拒绝写入；
- 普通工具调用不隐式迁移；
- M1a 和 M1b 都必须测试未知版本拒绝；M1a 状态可重建，不要求实现 1 到 2 的通用迁移器；
- 数据库损坏或引用不一致时失败关闭，不自动删除或重建。

### 12.3 M1b 内容寻址

M1a 不创建 Artifact 或 staging，结果和验证报告的规范 payload 连同哈希原子内联到 SQLite。M1b 才引入以下内容寻址规则。

Artifact ID 由内容哈希确定。发布过程使用同卷 staging、关闭句柄、持久化刷新、SHA-256、Schema 或媒体校验、no-clobber 原子发布和短数据库事务。

发布遵循 no-clobber：

- 在独占项目写锁下，目标不存在时才把 staging 原子移动到最终地址；
- 目标已存在时重新读取并核对大小和 SHA-256，完全一致才复用；
- 目标已存在但内容、大小或哈希不一致时返回 INTEGRITY_FAILURE，绝不替换、修复或覆盖既有文件；
- 任何数据库引用都晚于上述检查和发布。

项目写锁排除正常进程竞争；同账户恶意进程不在 M1b 威胁模型内，但也不能通过正常代码路径覆盖内容寻址证据。

### 12.4 环境快照

M1a 把以下允许列表作为 <code>environment_summary</code> 内联于 Attempt；M1b 将其提升为独立不可变 EnvironmentSnapshot：

只记录复现需要的：

- Python 版本；
- uv 与锁文件摘要；
- 操作系统和架构；
- 本项目包、能力和验证器版本；
- 直接影响数值行为的库版本；
- locale 等明确影响解析的设置。

不记录用户名、主机名、绝对路径、秘密或整个进程环境。

## 13. Context Engineering

### 13.1 总体模型

采用“薄入口、目录护栏、任务路由、按需 Skill、能力上下文包”：

~~~text
根 AGENTS.md
→ 最近的嵌套 AGENTS.md
→ docs/context/index.md 的任务行
→ 相关权威文档与契约
→ 仅在需要时加载 Skill 和能力数学上下文
~~~

未来 <code>CLAUDE.md</code> 和 TRAE 规则只作为薄入口，链接同一套权威文档，不复制规则。

### 13.2 根 AGENTS.md

根文件保持约 100 至 150 行，只放跨里程碑稳定规则：

- 项目使命和宿主无关原则；
- 上下文读取顺序；
- 模块依赖方向；
- MCP 不包含数学算法；
- Schema、版本和 ADR 纪律；
- 真实执行、独立验证、数据只读和溯源要求；
- STDOUT、路径、文件写入和秘密安全；
- 单一验证命令和完成证据；
- 当前里程碑文档链接。

详细数学知识、易变化目录清单、故障排查长流程和当前任务日志不得常驻根文件。

### 13.3 嵌套 AGENTS.md

M1a 只交付根 <code>AGENTS.md</code> 以及 <code>src/modeling_core</code>、<code>src/modeling_capabilities</code>、<code>src/modeling_mcp</code> 和 <code>tests</code> 四个关键嵌套文件。M1b 补齐下表其余目录规则。没有独立规则的目录继承最近父级文件，不为凑齐目录而创建空 AGENTS。

| 目录 | 目录级规则 |
|---|---|
| src/modeling_core | 稳定核心依赖禁令、领域和端口约束 |
| src/modeling_capabilities | Built-in Capability 契约、版本、验证独立和封存规则 |
| src/modeling_mcp | 协议适配、STDOUT 纪律和兼容要求 |
| src/modeling_infrastructure | 迁移、原子写入和路径边界 |
| src/modeling_bootstrap | 唯一组合位置，不承载业务逻辑 |
| tests | 测试分层、证据、快照和真实执行规则 |
| docs | 文档分类、ADR 生命周期和权威来源 |
| .agents/skills | Skill 触发、渐进披露和禁止复制契约正文 |

默认不为每个能力创建 AGENTS.md。能力特有内容放在本地 <code>context.md</code> 和按需 Skill 引用。

### 13.4 Skills

M1a 不要求创建项目级 Skill；其唯一能力和黄金链路由基础 AGENTS、上下文索引、契约和 verify 覆盖，避免为尚无第二能力的流程建立额外入口。M1b 必需的项目级 Skills 保存已经反复使用的程序性工作方法：

- add-capability；
- numerical-validation；
- stdio-diagnostics；
- reproducibility-audit；
- release-verification。

<code>evolve-schema</code> 的职责已经在本设计中定义，但等到 M1b 首个已发布契约确实需要演进时再增加；M1b 只需提供 schema-evolution 运维文档和兼容测试，避免为尚不存在的第二个稳定版本增加额外入口。

产品边界、架构、公共契约、状态模型、JSON Schema 和 ADR 不能只存在于 Skill。Skill 必须链接权威来源，不复制其正文。

### 13.5 docs/context/index.md

索引只做路由，包含：

1. 当前里程碑和有效规格；
2. 产品、架构、契约、ADR、运维和能力目录入口；
3. 任务类型到必读和按需上下文的矩阵；
4. 能力发现入口；
5. 冲突处理和变更触发规则；
6. 已废弃文档及替代位置。

链接和重复权威来源由 verify 检查。

### 13.6 文档边界

| 文档 | 权威范围 |
|---|---|
| 产品文档 | 用户、问题、结果、范围、非目标和里程碑 |
| 架构文档 | 当前模块、依赖、数据流、状态和安全结构 |
| 契约文档 | 可观察行为、字段语义、错误、版本和兼容性 |
| JSON Schema | 数据形状 |
| ADR | 重要决策的背景、备选、决定、后果和取代关系 |
| 运维手册 | bootstrap、doctor、恢复、迁移、发布和诊断 |

架构文档表达当前状态；ADR 保留为什么这样决定。

### 13.7 渐进式能力发现

1. 先读取能力 ID、摘要、版本和标签；
2. 选定能力后读取描述符和 Schema；
3. 开发或审查时读取能力 <code>context.md</code>、验证政策和测试说明；
4. 遇到具体数学问题时才读取 Skill 的推导、参考和诊断材料。

ODE、PDE、优化、统计等知识不进入全局上下文。

### 13.8 冲突处理

| 问题 | 权威来源 |
|---|---|
| 产品意图 | 已批准产品规格 |
| 架构决策 | 有效 ADR 和当前架构文档 |
| 数据形状 | 版本化 JSON Schema |
| 字段语义和兼容 | 契约文档 |
| 数据库存储结构 | 迁移文件 |
| 实际运行行为 | 代码 |
| 符合性证据 | 测试 |

冲突本身是验证失败，不用“代码永远正确”掩盖：

- 有意改变行为时，先更新规范或 ADR 和版本，再在同一变更同步 Schema、代码、测试和文档；
- 非预期偏差时，修复代码或测试以恢复契约；
- 不允许只重生成快照；
- 无法判断意图时停止完成声明并请求产品决策。

### 13.9 最小上下文矩阵

| 任务 | 最小读取集合 |
|---|---|
| 稳定核心变更 | 根与核心规则、上下文索引、架构边界、相关领域或端口契约 |
| 新 Built-in Capability（M1b 起） | 根与能力规则、Capability API、add-capability Skill、选定数学上下文和验收清单 |
| MCP 工具 | MCP 规则、应用门面、工具 Schema 和兼容政策 |
| 验证器 | 能力规则、Capability Contract、验证政策和数学变形说明 |
| SQLite 或制品 | 基础设施规则、状态模型、迁移和原子写入文档 |
| 缺陷修复 | 最近源代码规则、测试规则、相关契约和失败证据 |
| 文档或 ADR | 文档规则、受影响权威来源和契约 |
| 宿主适配器 | 系统架构、应用门面和适配器契约 |
| 发布 | 里程碑验收、release-verification Skill 和验证报告 |

## 14. Harness Engineering

### 14.1 单一验证命令

环境准备：

~~~text
uv sync --locked --group dev
~~~

验证只有一个 CLI 入口；完成证据必须显式指定里程碑：

~~~text
uv run --locked --no-sync modeling verify --milestone m1a
uv run --locked --no-sync modeling verify --milestone m1b
~~~

这不是两套 Harness：<code>modeling verify</code> 是唯一编排入口，M1b profile 是 M1a profile 的严格超集。省略 <code>--milestone</code> 时运行仓库声明的最高已实现里程碑并在首行打印目标，但完成证据不得省略该参数。verify 由跨平台 Python 编排，不依赖 Make、Bash 或 PowerShell；不访问网络，不修改权威项目状态。快速或单能力模式只用于开发反馈，不能作为完成证据。

### 14.2 Bootstrap

~~~text
uv run --locked --no-sync modeling bootstrap --project-root <path>
~~~

- 只初始化保留状态目录；
- 不移动、改名或修改原始附件；
- 在同卷临时目录完整创建后原子发布；
- 只创建 STORAGE_READY，不创建 Project 领域记录；
- 对 STORAGE_READY 或 READY 的合法同版本项目幂等；
- 遇到未知版本、冲突或部分初始化时拒绝覆盖。

### 14.3 Doctor

~~~text
uv run --locked --no-sync modeling doctor --project-root <path> [--deep] [--json]
~~~

- 默认只读；
- M1a 检查项目版本、SQLite 完整性、注册表、Schema 哈希、遗留 IN_PROGRESS/RUNNING 和配置；发现遗留状态时报告 DEGRADED，不自动恢复；
- M1b 增加制品引用、输入漂移、幂等恢复结果和孤儿报告；
- deep 模式在一次性诊断目录检查锁和真实根求解烟测；M1b 另检查 no-clobber 原子发布与恢复；
- M1 不提供自动修复开关；
- 退出码 0 表示就绪，1 表示警告，2 表示不可安全运行。

### 14.4 测试层

| 层 | M1a 必需 | M1b 增量 |
|---|---|---|
| 单元 | 领域不变量、基础状态/幂等、注册表、规范化烟测、求解器和验证器 | 完整恢复状态、RFC 8785 向量、制品边界 |
| 契约 | Capability、Validator、ProjectStore、六工具 0.x Schema | ArtifactStore、六工具 1.0 基线、兼容语料 |
| 数学变形 | 平移、缩放、符号翻转、括区缩窄和伪造结果 | 完整仿射生成集和固定种子重放 |
| 架构 | 导入图、组合根唯一性、求解/验证独立、能力模块无数据库或 MCP | test.echo 扩展证明与完整上下文边界 |
| STDIO 集成 | 真实子进程、握手、六工具、错误、关闭和 STDOUT 纯净 | 重启、幂等重放、哈希篡改和跨平台 |
| 复现与恢复 | 同进程确定性重复实验的分类和容差 | rerun、重启、完整幂等、遗留状态和故障注入 |
| 安全 | 表达式、请求大小、协作超时、STDOUT、项目锁和基本路径边界 | 制品路径、原子发布、崩溃窗口和完整安全矩阵 |

### 14.5 STDIO 黄金链路

M1a 测试必须使用真实字节管道完成：

~~~text
initialize
→ tools/list
→ health_check（UNINITIALIZED 或 STORAGE_READY，ready_for_project_creation=true）
→ create_project
→ health_check（READY）
→ get_project_status
→ list_capabilities
→ run_experiment
→ validate_experiment
→ 查询并核对溯源
~~~

M1a 同时覆盖无符号变化、非法输入、一次 COMPLETED 幂等重放和幂等冲突，并检查 STDOUT 无 BOM、日志或提示文字，Windows 句柄和 MCP 子进程全部关闭。M1b 在同一链路增加服务器重启、遗留状态恢复、结果/报告制品哈希篡改和完整幂等重放。

### 14.6 数学变形

- c 乘 f(x)，c 不等于 0，保持同根；
- 变量平移后根按同样位移变化；
- 非零仿射变换后根按反变换映射；
- 缩窄但仍含唯一根的区间保持一致；
- 越界、非有限、残差超限和伪造结果必须被验证器拒绝。

断言使用契约容差，不比较固定迭代次数或默认要求跨平台浮点位级相等。生成案例的种子必须固定并可重放。

### 14.7 依赖边界

自动导入图证明：

- core 不导入 MCP、CLI、SQLite 或具体能力实现；
- capability module 只依赖稳定核心契约；
- MCP 只依赖应用门面和公共契约；
- infrastructure 通过端口接入；
- bootstrap 是唯一组装具体实现的位置；
- validator 不导入 solver 数值实现。

### 14.8 M1b Schema 兼容

M1a 只验证 0.x Schema 自洽和固定烟测语料，不创建兼容基线。M1b 首次发布按第 11.13 节验证实现符合设计基线并产出首个发布基线；后续发布把当前 MCP Schema 与最近发布的规范化基线和旧请求语料比较：

- 工具不得删除或重命名；
- 新服务器必须接受所有旧合法输入；
- 不得新增必填字段或收窄类型、范围、枚举；
- 新输出必须仍符合旧输出契约；
- 严格根对象新增字段是破坏性变化；
- 错误码和既有字段语义不得静默改变；
- 破坏性变化必须升级主版本并有 ADR；
- verify 不自动更新基线。

能力 Schema 同时执行 SemVer 检查。

### 14.9 复现性

M1a 在同一健康 Session 对相同规范输入执行两次新实验，比较分类、版本、输入哈希和声明容差；它不要求 rerun 或重启恢复。M1b 对同一 Experiment 使用 run_experiment/rerun 模式在干净项目、重复调用和服务器重启后比较：

- 输入、模型、数据和 Schema 哈希；
- 能力、实现、验证器和 policy 版本；
- Python、平台和锁摘要；
- 随机性声明和 seed；
- 终止分类、验证结论和数值容差；
- 制品和溯源关系。

只有能力显式声明 bitwise reproducible 时才比较字节完全一致。

### 14.10 M1b 故障注入

M1a 不建立故障注入框架。M1b 在 Attempt 创建后、RUNNING 后、staging 写入中、文件发布后数据库提交前、数据库提交后响应前注入故障。必须证明：

- SQLite 不引用缺失文件；
- 孤儿文件安全且可报告；
- 遗留运行变为 ABANDONED；
- 幂等重放不产生第二个实体；
- 成功响应晚于数据库提交。

### 14.11 CI 与本地等价

M1a 只要求 Windows 主平台通过 <code>verify --milestone m1a</code>，但 Harness 和路径逻辑必须使用跨平台 Python，不得写死 PowerShell 或盘符。M1b 要求 Windows 和 Ubuntu 执行完全相同的 <code>verify --milestone m1b</code>。M1 固定一个 Python 3.11 支持基线，不扩大 Python 小版本矩阵。

### 14.12 验证报告

每次验证生成版本化 JSON 和人类可读摘要。M1a 最低包含当前源文件指纹、Python/uv/Windows/锁摘要、各检查状态、测试数、架构报告、黄金 Experiment/Attempt/Validation ID 和脱敏 STDIO 记录。M1b 完整报告另包含：

- 每项检查状态、耗时、测试数和跳过数；
- Schema 兼容报告；
- 复现、恢复和安全报告；
- 制品哈希复核；
- 脱敏失败信息。

### 14.13 能力脚手架

能力脚手架和第二实现扩展证明属于 M1b；M1a 只有一个生产 Built-in Capability，不为未来可能存在的第二能力建立生成框架。

~~~text
uv run --locked --no-sync modeling capability scaffold <capability-id>
~~~

它只生成描述符、版本化 Schema、executor、独立 validator、context.md、测试骨架和组合根显式注册项。它不安装依赖、不扫描目录、不修改稳定核心，遇到冲突时拒绝覆盖。

单能力验证可用于反馈：

~~~text
uv run --locked --no-sync modeling verify --capability <capability-id>
~~~

Built-in Capability 最终验收仍要求当前目标里程碑的完整 verify。

M1b 架构扩展验收使用只存在于 tests fixture 的 <code>test.echo/1.0.0</code>：输入严格 Schema 为 <code>{"value": number}</code>，成功输出同一 value，randomness=not_used。测试组合根显式注册该 Built-in Capability fixture，以 value=2.0 调用并得到 2.0。它不得进入生产注册表，也不得要求修改 modeling_core。

## 15. 错误处理和安全

### 15.1 信任边界

信任本地用户、随发行版交付的 Built-in Capability、锁定依赖和已授权本地宿主。MCP 参数、数学表达式、文件名、附件、手工修改或中断留下的状态都视为不可信。

M1 不加载 External Plugin，也不防御被植入依赖、同账户恶意进程或失陷操作系统。未来 External Plugin 必须建立独立信任和进程隔离设计。

### 15.2 稳定错误码

| 错误码 | 语义 |
|---|---|
| INVALID_REQUEST | 工具外壳、payload 或字段组合无效 |
| NOT_FOUND | 项目、能力或实体不存在 |
| UNSUPPORTED_VERSION | 工具、Capability API、能力契约、项目或 Schema 版本不支持 |
| CONFLICT | 幂等冲突、重复注册或项目被占用 |
| PRECONDITION_FAILED | 当前状态不允许操作 |
| SECURITY_VIOLATION | 路径、表达式或执行边界违规 |
| RESOURCE_LIMIT_EXCEEDED | 请求大小、解析预算、运行安全预算或输出上限超限 |
| INTEGRITY_FAILURE | 哈希、数据库关系、输入或制品不一致 |
| INTERNAL_ERROR | 未预期软件或基础设施故障 |

错误对象字段为 error_schema_version、code、message、retryable、correlation_id 和按错误码严格定义的 details。公共错误不含栈、SQL、绝对路径、完整 payload、环境变量或秘密。

### 15.3 错误 details Schema

每种 details 都是禁止未知字段的对象：

| code | details 字段 |
|---|---|
| INVALID_REQUEST | field_path、reason |
| NOT_FOUND | resource_type、resource_id |
| UNSUPPORTED_VERSION | subject、requested_version、supported_versions |
| CONFLICT | conflict_type、可选 existing_resource_id、可选 retry_after_ms |
| PRECONDITION_FAILED | condition、current_state |
| SECURITY_VIOLATION | rule |
| RESOURCE_LIMIT_EXCEEDED | resource、limit、可选 observed |
| INTEGRITY_FAILURE | subject、可选 expected_hash、可选 observed_hash |
| INTERNAL_ERROR | event_id |

field_path 使用 JSON Pointer。M1 固定子码如下：

- INVALID_REQUEST.reason：missing_required、unknown_field、invalid_type、invalid_format、out_of_range、invalid_combination、expression_parse_error、capability_payload_violation、invalid_cursor；
- CONFLICT.conflict_type：idempotency_mismatch、operation_in_progress、project_busy、project_metadata_mismatch、duplicate_registration；
- PRECONDITION_FAILED.condition：project_not_ready、project_degraded、attempt_not_succeeded、missing_success_result、validator_incompatible；
- SECURITY_VIOLATION.rule：math_expr_forbidden_syntax、path_outside_project、unsafe_reparse_point、stdout_protocol_violation；
- RESOURCE_LIMIT_EXCEEDED.resource：M1a 为 mcp_request_bytes、inline_response_bytes、expression_bytes、ast_nodes、ast_depth、numeric_literal_chars、function_evaluations、warnings；M1b 增加 artifact_bytes、artifact_count；
- INTEGRITY_FAILURE.subject：M1a 为 project_metadata、database_relation、result_hash、validation_report_hash、input_snapshot；M1b 增加 artifact_content。

只有 CONFLICT/operation_in_progress、CONFLICT/project_busy 等明确瞬时冲突可设置 <code>retryable=true</code> 并提供 <code>retry_after_ms</code>；其他错误默认 false。message 用于人类诊断，不作为程序分支依据。

预执行条件到唯一错误的映射为：

| 条件 | code 与 details |
|---|---|
| 缺字段、未知字段、类型或 UUID/Hash 格式错误 | INVALID_REQUEST；对应 field_path，reason=missing_required、unknown_field、invalid_type 或 invalid_format |
| 参数对象含重复键或未配对 surrogate | INVALID_REQUEST；对应 field_path，reason=invalid_format |
| mode/view 字段组合非法 | INVALID_REQUEST；reason=invalid_combination |
| timeout_ms 超出 1..60000、seed 超出安全整数域、容差/区间/max_iterations 或指数数值超出声明范围 | INVALID_REQUEST；reason=out_of_range |
| capability payload 违反其普通数据 Schema | INVALID_REQUEST；reason=capability_payload_violation |
| 表达式词法或括号无法解析 | INVALID_REQUEST；field_path=/payload/expression，reason=expression_parse_error |
| 属性、下标、导入、Lambda、未知变量、未知函数、未知运算符、变量或复合指数、或其他禁止语法 | SECURITY_VIOLATION；rule=math_expr_forbidden_syntax |
| MCP 请求超过 1 MiB | RESOURCE_LIMIT_EXCEEDED；resource=mcp_request_bytes |
| expression 超过 4096 字节、字面量超过 64 字符、AST 超过 256 节点或深度 32 | RESOURCE_LIMIT_EXCEEDED；resource 分别为 expression_bytes、numeric_literal_chars、ast_nodes、ast_depth |
| capability_id、validator_id 或实体不存在 | NOT_FOUND；resource_type 和 resource_id 指向请求值 |
| 已知 ID 的 contract、policy、capability_api、project 或 Schema 版本不支持 | UNSUPPORTED_VERSION；填充 subject、requested_version、supported_versions |
| 项目状态或 Attempt/Result 前置条件不满足 | PRECONDITION_FAILED；condition 使用上述固定子码 |
| project_id 与绑定项目不一致 | NOT_FOUND；resource_type=project，resource_id 为请求值 |
| expected_result_hash 格式错误 | INVALID_REQUEST；field_path=/expected_result_hash，reason=invalid_format |
| 格式合法但四重哈希不一致 | INTEGRITY_FAILURE；subject=result_hash，填充 expected_hash 与 observed_hash |

### 15.4 发生阶段到结果的映射

| 发生条件 | MCP isError | 实体结果 |
|---|---|---|
| JSON-RPC 或 MCP 帧无效 | MCP 标准协议错误 | 无领域实体 |
| 请求 Schema、未知字段、版本、项目归属、前置条件或预执行资源上限失败 | true | 不创建 Attempt 或 Validation |
| create_project 存储或首事务失败 | true | 不存在 Project；临时目录不被引用 |
| 同 operation_id 正在执行 | true，CONFLICT/operation_in_progress | 返回既有实体 ID，不新建 |
| 求解器返回契约内数学失败 | false | Attempt=NUMERICAL_FAILURE，失败 ResultSnapshot 必须存在 |
| 运行达到 effective deadline | false | Attempt 或 Validation=TIMED_OUT |
| 宿主取消被协作观察 | false | Attempt 或 Validation=ABANDONED/host_cancelled |
| Built-in Capability 抛出未预期异常 | false | 实体=ERRORED，嵌入 INTERNAL_ERROR |
| 运行期运算预算超限，或 M1b 制品数量/大小超限 | false | 实体=ERRORED，嵌入 RESOURCE_LIMIT_EXCEEDED |
| 运行期内容哈希或既有内容地址不一致 | false | 实体=ERRORED，嵌入 INTEGRITY_FAILURE；提交该终态后项目进入 DEGRADED |
| M1b 运行期 ArtifactStore 或任一阶段可提交的 SQLite 故障 | false | 能持久化终态时实体=ERRORED/infrastructure_failure |
| SQLite 故障导致终态本身无法提交 | true，INTERNAL_ERROR | 实体保留 PENDING/RUNNING，重启恢复为 ABANDONED |
| M1a expected_result_hash、ResultSnapshot 或内联 payload 三重哈希不一致；M1b Artifact 四重哈希不一致 | true，INTEGRITY_FAILURE | 不创建 Validation |
| 验证器正常判定 | false | Validation=SUCCEEDED，outcome=PASSED/FAILED/INCONCLUSIVE |
| 验证器异常、运行期资源或基础设施故障 | false | Validation=ERRORED，outcome 为空 |

调用方根据 MCP isError、实体运行状态和数学 outcome 三个正交层次判断结果。

### 15.5 幂等和重试

M1a 只对已提交 COMPLETED 记录提供同 ID 重放，对遗留 IN_PROGRESS 失败关闭；M1b 才承诺崩溃窗口内的完整恢复和响应丢失重放。共同规则为：

- 写操作持久化 operation_id、工具名和规范化请求哈希；
- 同 ID 同请求返回原结果；
- 同 ID 不同请求返回 CONFLICT；
- 核心不自动重试数学求解、验证或未知内部错误；
- SQLite 每次事务只使用一次 250 ms busy_timeout；首事务仍忙则返回可重试 CONFLICT/project_busy，最终事务仍忙按第 15.4、15.6 节处理；
- M1b 的 Windows 文件共享冲突只允许 25、50、100 ms 三次退避重试，每次重试前都检查已建立的 execution deadline；
- M1a 的响应丢失仅在最终事务已提交时可用原 operation_id 重放；M1b 覆盖全部声明的崩溃窗口。

### 15.6 崩溃恢复

M1a 启动时检测遗留 PENDING、RUNNING 或 IN_PROGRESS；一旦存在就进入 DEGRADED，基础 doctor 报告实体 ID，且不自动改写或继续执行。M1a 预览状态可以由用户删除后重新 bootstrap，不为它实现恢复框架。

M1b 服务器获得项目锁后生成 Session UUID，并把前一 Session 遗留 PENDING/RUNNING 标记 ABANDONED。未提交事务由 SQLite 回滚；未完成 staging 被隔离；已发布未引用文件保留；缺失被引用文件时停止写入。

若当前 Session 连实体终态事务都无法提交，服务器立即进入内存只读 DEGRADED、拒绝后续写工具并尝试有序退出；不得继续执行新实验。下一 Session 在获得锁后按上述规则把遗留运行与 IN_PROGRESS 幂等记录一并收敛为 ABANDONED/COMPLETED。

M1b 也不自动删除记录、重建数据库、重新执行实验或修复损坏。

### 15.7 路径规则

- MCP 不接受数据库、制品根或任意输出路径；
- 项目根在启动时规范化；
- 内部路径只使用系统 ID 和十六进制哈希；
- 原文件名仅作元数据；
- .modeling 不得是符号链接、目录联接或重解析点；
- 拒绝父目录、绝对路径、跨盘符、UNC、NUL、ADS、Windows 保留名、尾随点和尾随空格；
- 所有访问在解析后必须仍位于项目根；
- 核心不写原始附件。

### 15.8 math-expr-v1 安全

使用专用解析器和受限 AST，最大 4096 字节、256 个节点、深度 32。所有字面量和中间值使用有限 binary64；指数范围、节点预算和函数求值预算按第 10.2 节执行。不得使用 eval、exec、compile，也不允许属性、下标、导入、Lambda、推导、赋值、任意函数、多变量或非有限字面量。

域错误、溢出和非有限求值映射为版本化数值失败，不传播原始异常。

### 15.9 资源上限

| 资源 | M1a 上限 | M1b 上限 |
|---|---:|---:|
| MCP 请求 | 1 MiB | 1 MiB |
| 内联 structuredContent | 256 KiB（262144 UTF-8 字节） | 256 KiB（262144 UTF-8 字节） |
| 默认根求解迭代 | 100 | 100 |
| 最大根求解迭代 | 10000 | 10000 |
| 默认执行截止时间 | 10 秒 | 10 秒 |
| 最大执行截止时间 | 60 秒 | 60 秒 |
| 单 Attempt 制品 | 不支持；结果必须适合内联上限 | 64 MiB，最多 16 个 |
| 警告 | 最多 50 条，每条 1024 UTF-8 字节 | 同 M1a |

能力可以声明更低限制，不能突破全局限制。

### 15.10 超时边界

Built-in Capability 在服务器进程内执行，因此 M1 的 timeout 是协作式：求解器、验证器在每轮迭代、每次函数求值和每个 AST 节点前检查单调时钟与取消信号。<code>monotonic_now &gt;= deadline</code> 即超时；边界到达后产生的结果不得接受。能力返回后和最终事务开始前都再次检查；M1b 在制品发布后也检查。任一检查超时则不引用结果或报告，M1b 已发布文件只成为安全孤儿。最终事务开始前的检查通过后，不以 timeout 中断原子提交。忽略 deadline 的错误内置能力可能阻塞服务器。测试 Harness 的外部看门狗可终止整个 MCP 测试进程，但 M1 不宣称通用硬超时；M2.5 必须以受控计算子进程补上该边界。

### 15.11 日志与隐私

- STDOUT 仅有 MCP 帧；
- 结构化日志写 STDERR；
- 日志包含关联 ID 和必要实体 ID；
- 默认不记录完整 payload、附件、结果、绝对路径和环境变量；
- 环境快照使用允许列表；
- 核心无遥测、网络上传或后台同步。

### 15.12 失败关闭

遇到未知版本、注册表不一致、哈希不匹配、数据库损坏、锁异常或无法证明路径边界时停止写入并保留现场。doctor 只报告，不在 M1 自动修复；M1a 对遗留运行同样失败关闭，M1b 按已定义规则收敛后再决定是否可写。

## 16. 测试与验收标准

### 16.1 黄金实验

M1a 和 M1b 都必须通过真实 STDIO MCP 执行：

~~~json
{
  "expression": "x*x - 2",
  "lower": 0.0,
  "upper": 2.0,
  "absolute_tolerance": 1e-10,
  "relative_tolerance": 1e-10,
  "function_tolerance": 1e-10,
  "max_iterations": 100
}
~~~

必须满足：

- Attempt 为 SUCCEEDED；
- root 有限且在区间内；
- <code>abs(root * root - 2) &lt;= 1e-10</code>；
- <code>abs(root - sqrt(2)) &lt;= 1e-8</code>；
- iterations 不超过 100；
- 独立验证器返回 PASSED；
- M1a 的 ResultSnapshot 和 ValidationReport 规范 payload、哈希均内联持久化到 SQLite；
- M1b 的相同规范 payload 另持久化为内容寻址 JSON 制品并通过完整性复核。

### 16.2 验收矩阵

M1a 完成条件：

| ID | 验收条件 |
|---|---|
| A-01 | Windows 上锁定环境可建立；bootstrap 首次成功且重复幂等；基础 doctor 就绪 |
| A-02 | 真实 STDIO 字节管道完成初始化、六工具调用和干净关闭；STDOUT 只有协议帧 |
| A-03 | Application Facade 可被 MCP、CLI 诊断和直接核心测试调用；核心不导入 MCP、SQLite 或具体能力实现 |
| A-04 | 显式注册表可列出并精确取得 <code>numerical.root_finding/0.1.0</code> 及独立 validator 契约 |
| A-05 | 黄金实验真实执行并满足精度，独立验证返回 PASSED |
| A-06 | <code>x*x + 1</code> 在 [-1,1] 返回 NUMERICAL_FAILURE/no_sign_change；非法表达式在 Attempt 建立前拒绝 |
| A-07 | validator 不导入求解器 evaluator 或搜索实现，并能拒绝哈希自洽但 root 或 function_value 伪造的 fixture |
| A-08 | SQLite 可追踪项目、规范输入、能力/实现版本、参数、随机性/seed、Attempt、结果、警告、Validation、报告和全部哈希 |
| A-09 | 已完成 operation_id 同请求返回同一实体，不同请求产生 CONFLICT；表达式、请求大小、协作超时、项目锁和基本路径测试通过 |
| A-10 | <code>verify --milestone m1a</code> 零退出且无必需跳过；基础 AGENTS、上下文索引、Codex 配置和 M1a 证据存在；实施计划不超过第 4.4 节预算 |

M1b 必须继续通过全部 A 条目，并增加：

| ID | 验收条件 |
|---|---|
| B-01 | 工具、Project Format、Capability API 和能力契约晋升到第 3.1 节 1.0 基线；六工具 Schema、错误和固定语料形成首个兼容基线 |
| B-02 | RFC 8785 完整通用向量和全部项目规范化向量通过 |
| B-03 | ResultSnapshot 和 ValidationReport 以内容寻址 Artifact 原子发布；SQLite、路径、大小和四重哈希一致 |
| B-04 | 完整幂等重放、服务器重启、遗留状态收敛和响应丢失恢复不产生第二实体 |
| B-05 | 全部声明故障点注入后无悬空引用，孤儿安全可报告，成功响应晚于提交 |
| B-06 | rerun 保留同一 Experiment、创建新 Attempt，并在声明容差内复现分类与结果 |
| B-07 | no-clobber、路径、制品篡改、资源、日志、锁、协作超时和失败关闭安全矩阵通过 |
| B-08 | test.echo fixture 可经 Capability Contract 显式注册和执行而不修改 Stable Core；能力脚手架不扫描或覆盖 |
| B-09 | Windows 与 Ubuntu 运行同一 <code>verify --milestone m1b</code> 通过 |
| B-10 | 第 17 节完整 AGENTS、Skills、契约、8 个 ADR、维护手册和完成证据包存在、链接有效且与当前源指纹一致 |

### 16.3 根求解最低案例

M1a 最低案例：区间内部单根、左右端点根、无符号变化、不收敛、域错误、非法区间/容差、最大迭代/截止时间、平移、缩放、符号翻转、括区缩窄和伪造结果。M1b 增加完整非有限求值、仿射生成集、固定种子重放和跨平台容差案例。

不要求固定迭代次数。

### 16.4 溯源链

M1a 任一 attempt_id 必须返回以下内联主干：

~~~text
Project
→ Experiment + canonical input/model/data hashes
→ Capability contract + implementation/environment summary
→ Attempt
→ optional ResultSnapshot inline payload
→ zero or more Validation inline reports
~~~

M1b 对所有 Attempt 的主干为：

~~~text
Project
→ Experiment
→ InputSnapshot
→ model snapshot hash
→ data snapshot set hash
→ Capability contract
→ implementation version
→ EnvironmentSnapshot
→ Attempt
~~~

M1a 的 SUCCEEDED 或 NUMERICAL_FAILURE Attempt 必须取得 ResultSnapshot 内联 payload；M1b 还必须取得 Result Artifact。ERRORED、TIMED_OUT、ABANDONED 不得伪造该分支。每个已创建 Validation 都必须可取得；M1a 只有 Validation=SUCCEEDED 时存在内联报告，M1b 再继续取得 ValidationReport Artifact。黄金实验必须具有从 Project 到验证报告的完整链。

确定性根求解记录 <code>randomness=not_used</code> 和 <code>seed=null</code>。

### 16.5 宿主无关验收

- core 可在不导入 MCP SDK 的进程直接调用；
- CLI 和 MCP 使用同一应用门面；
- 核心类型不包含 Codex、Claude Code 或 TRAE 概念；
- 自动集成使用通用 MCP 客户端；
- Codex 真实烟测只验证首宿主接入，不成为核心测试依赖。

### 16.6 测试质量

- 必需测试不得跳过；
- 禁止自动重试掩盖不稳定；
- 时间测试使用可控时钟，不依赖长 sleep；
- SQLite 和恢复测试使用真实磁盘；
- STDIO 测试拉起真实进程；
- 数值断言使用契约容差；
- Snapshot 不自动更新；
- 预期数值失败和验证 FAILED 不算 Harness 失败。

不以单一覆盖率百分比替代验收。M1a 必须把其状态转换、六工具成功路径、稳定错误、Capability Contract 分支和 A-01 至 A-10 映射到测试；M1b 追加 B-01 至 B-10 的证据映射。

### 16.7 完成证据包

M1a 基础证据：

- 当前源指纹对应的 verification-report.json 与人类摘要；
- Windows 锁定环境和基础 doctor 结果；
- 架构依赖报告；
- 脱敏真实 STDIO 黄金链路记录；
- 黄金 Experiment、Attempt、Validation ID 与 SQLite 溯源导出；
- A-01 至 A-10 的测试映射。

M1b 完整证据在上述基础上增加：

- verification-report.json；
- Schema 兼容报告；
- 数学变形与复现报告；
- 故障恢复与安全报告；
- 溯源与制品哈希清单；
- Windows、Ubuntu 结果；
- Codex 黄金链路烟测记录；
- B-01 至 B-10 的证据映射。

只有当前源指纹对应的 <code>verify --milestone m1a</code> 退出码为零、必需跳过数为零且 A-01 至 A-10 全有证据时，才可声明 M1a 可运行。只有 <code>verify --milestone m1b</code> 退出码为零、doctor deep 就绪、A 与 B 条目全有证据时，才可声明 M1 完成或形成可信发布基线。M1a 不得使用“生产就绪”“兼容基线”或“M1 完成”的措辞。

## 17. Context 与文档交付清单

M1a 只建立能够安全实施和验证纵向链路的最小集合：

- 根 AGENTS.md，以及 <code>src/modeling_core</code>、<code>src/modeling_capabilities</code>、<code>src/modeling_mcp</code>、<code>tests</code> 的嵌套 AGENTS.md；
- docs/context/index.md；
- docs/product/m1-scope.md，明确 M1a/M1b 门禁；
- docs/architecture/overview.md；
- docs/contracts/mcp-tools-v0.md、docs/contracts/capability-api-v0.md 和 docs/contracts/root-finding-v0.md；
- 0.x 工具、Error、Capability、Validator、CanonicalInput、成功和失败 JSON Schema；
- docs/operations/bootstrap-and-doctor.md；
- docs/templates/codex/config.toml；
- root_finding context.md；
- M1a verify 和证据说明。

M1b 补齐可信发布集合：

- docs/product/vision.md；
- docs/architecture/state-model.md；
- docs/architecture/security.md；
- docs/contracts/mcp-tools-v1.md；
- docs/contracts/capability-api-v1.md；
- docs/contracts/root-finding-v1.md；
- 随 wheel 交付的 1.0 工具、Error、Result、ValidationReport、Capability API、原始输入、CanonicalInput、成功和失败 JSON Schema，以及 tests/contract/corpus 固定语料；docs/contracts 只链接这些权威资产，不维护第二份副本；
- docs/operations/recovery.md；
- docs/operations/schema-evolution.md；
- docs/operations/release-verification.md；
- 第 13.3 节其余嵌套 AGENTS；
- 能力目录和第 13.4 节所列五个项目级 Skills。

以下 8 个初始 ADR 是 M1b 必交付项；M1a 直接引用本文决策，不为达到可运行检查点复制一套不完整 ADR：

1. 模块化单体；
2. 端口、适配器和唯一组合根；
3. SQLite 与内容寻址制品；
4. 显式可信 Built-in Capability；
5. 本地 STDIO MCP；
6. Schema 和 SemVer 政策；
7. 求解与验证独立；
8. 单写入项目锁和崩溃恢复。

## 18. M1a 延后项与 M1 明确不做

以下内容是 M1b 的明确范围，因此缺少它们不构成 M1a 未完成：完整 RFC 8785 向量、内容寻址制品、完整幂等与崩溃恢复、故障注入、1.0 Schema 兼容基线、rerun 复现、Windows/Ubuntu 双平台、能力脚手架、完整嵌套 AGENTS/Skills、8 个 ADR 和完整完成证据包。它们不得以“将来很难补”为理由进入 M1a。

以下内容不属于 M1，缺少它们不构成 M1 未完成：

- PDF OCR、复杂版面恢复或完整赛题附件解析；
- MMIR 定义或转换；
- 自动理解整道赛题、自动选择模型或完整历年题求解；
- 动态工作流编排、任务图或自主规划；
- 除 root_finding 外的生产数学能力；
- ODE、PDE、优化、统计、几何、空间、信号、机器学习和不确定性量化；
- 符号代数系统；
- Excel、图表、论文素材或自动论文写作；
- 向量数据库、知识库或检索增强；
- Web UI、桌面 UI 或交互式 Notebook 前端；
- 多用户、远程服务、认证、授权或项目共享；
- 完整 Claude Code 和 TRAE 适配；
- 自主多智能体讨论；
- 本地大模型部署；
- External Plugin 自动发现、下载安装、签名或权限系统；
- 子进程 worker、External Plugin 沙箱、进程级硬超时或内存隔离；这些属于 M2.5 或更后阶段；
- 异步 Job、队列、调度器和分布式执行；
- 网络文件系统和 UNC 项目根；
- 自动数据库修复、自动删除孤儿或隐式迁移；
- 跨平台浮点位级复现保证；
- 遥测、云同步或后台网络服务。

任何上述 M1 非目标都必须进入 M2 或更后里程碑，明确契约、安全边界和验收标准，不能以“预留框架”为理由进入 M1。M1a 延后项只能进入已定义的 M1b，不得无限延后后仍宣称 M1 完成。

## 19. 后续演进路线

### M1a：可信同步短任务的功能垂直切片

- 模块化单体、Application Facade 和宿主无关核心；
- 六个 0.x STDIO MCP 工具与 Codex 接入；
- 显式 Built-in Capability 注册；
- root finding、独立验证和 SQLite 内联溯源；
- Windows 主平台的基础 AGENTS、doctor、verify 和真实黄金链路；
- 最多 12 个顶层实施任务，不承担 M1b 可靠性预算。

### M1b：可信化加固

- 完整 RFC 8785 向量与 1.0 Schema 兼容基线；
- 内容寻址制品、完整幂等恢复、故障注入和复现；
- Windows/Ubuntu 同一完整门禁；
- 完整 Context/Skills、契约、ADR、运维手册和完成证据包。

### M2：赛题与数据基础

- 只读附件登记和内容哈希；
- CSV、Excel 与常见文本数据快照；
- 基础 PDF 文本提取，不承诺完整 OCR；
- InputSnapshot 和 DataSnapshot 扩展；
- MMIR 最小问题、变量、约束和数据引用模型；
- Claude Code 与 TRAE 的薄配置或适配器验证，不修改核心。

### M2.5：受控计算 worker

M2.5 必须在 M3 新增长计算能力前完成最小进程隔离：

- 每次 run 或 validate 启动一个短生命周期受控 worker，不建立常驻池、队列、调度器或分布式协议；
- Application Facade 的父进程仍独占 ProjectStore、SQLite、项目锁、幂等、状态转换和 ArtifactStore；
- 父进程通过私有、本地、版本化执行信封传入 capability/validator ID 与版本、CanonicalInput、seed、deadline 和资源上限；
- worker 不获得 MCP 上下文、SQLite、项目根、任意输出路径或状态修改接口，只把版本化结果或错误返回父进程；
- 父进程复核响应 Schema 和哈希后才持久化，worker 退出、崩溃、协议违规分别映射为明确终态；
- 硬超时必须终止整个子进程树；Windows 使用 Job Object 等 OS 边界，Ubuntu 使用进程组与可用的 rlimit/cgroup 等边界，并以契约测试统一可观察语义；
- CPU、内存、输出字节和进程数至少有硬上限；平台无法完全等价的限制必须在能力描述符和验证报告中明确；
- 不自动重试数学执行，避免同一 Attempt 被静默执行两次；
- 只有 M2.5 出现真实父进程与 worker 具体实现时才引入 ExecutionWorker 边界和内部协议，M1 不预建。

### M3：建模工作流与首批能力

- 版本化 MMIR；
- 显式工作流图和步骤状态；
- 优化、统计和 ODE 的少量代表能力；
- 每个能力独立验证和数学变形测试；
- 所有数学执行必须经过 M2.5 worker；
- 能力组合仍经应用门面，不允许能力实现相互任意调用。

### M4：输出与实验管理

- Excel、图表和论文素材制品；
- 实验分支、比较和可复现实验包；
- 数据、模型和结果版本浏览；
- 统计与不确定性报告。

### M5：高级能力与可选 External Plugin

- PDE、几何、空间分析、信号、机器学习和 UQ；
- 只有真实排队需求成立时才设计长任务 Job 契约、队列或 worker 池；
- 只有第三方分发需求成立时才设计 External Plugin 发现、签名、权限和卸载。

### M6：可选宿主和产品形态

- 完整 Claude Code、TRAE 和其他宿主体验；
- 只有真实需求证明后才考虑 Web、桌面、多用户或远程服务；
- 远程形态作为独立安全和部署架构，不扭曲本地核心。

### 19.1 演进触发条件

- 只有出现独立发布节奏时才拆 wheel；
- M2.5 worker 是 M3 的固定进入条件，不再等待 ODE、优化或统计上线后才补隔离；
- 只有排队、后台执行或并发吞吐需求出现时才设计 Job、队列或进程池；
- 只有第三方分发需求出现时才设计 External Plugin 动态发现和权限；
- 只有多用户协作需求出现时才设计远程服务；
- 新宿主必须通过薄适配层接应用门面，禁止在核心加入宿主分支；
- 新 Built-in Capability 必须通过描述符、Schema、验证器、测试、上下文包和显式注册进入；External Plugin 另受未来分发契约约束。

## 20. 风险与缓解

| 风险 | 缓解 |
|---|---|
| MCP SDK 或协议演进 | 锁定依赖；自有工具契约版本独立；STDIO 契约和旧语料测试 |
| Built-in Capability 越过稳定边界 | 导入图、必要端口、唯一组合根和架构测试 |
| 验证器与求解器共同错误 | 禁止数值实现互引；独立重算；解析器共享范围显式受限；数学变形 |
| Windows 句柄或路径差异 | M1a Windows 主验证；M1b Windows/Ubuntu 同门禁；真实磁盘、进程和严格逻辑路径 |
| SQLite 与文件提交不一致 | M1a 无文件制品；M1b 文件先发布、数据库后引用、故障注入、内容寻址和 doctor |
| 进程内能力忽略 timeout | M1 仅可信有界短任务、协作检查和测试外部看门狗；M2.5 在 M3 前提供硬隔离 |
| 文档和契约漂移 | 权威矩阵、Schema 基线、链接和上下文检查、同一变更同步 |
| 数学知识淹没上下文 | 摘要目录、能力上下文包和按需 Skill |
| Built-in Capability 与 External Plugin 混淆 | 第 3、9 节使用不同名称；M1 禁止动态发现、安装和 External Plugin SDK |
| 长时间看不到可运行成果 | M1a 最多 12 个任务、4 个工作包；M1b 独立加固计划；两套完成声明严格分离 |
| M1 范围失控 | 第 4.4、18 节和 A/B 验收矩阵共同作为完成边界 |

## 21. 设计一致性与实施边界

### 21.1 与原则一致

- 稳定内核和能力实现分离由模块与导入图保证；
- 核心没有宿主依赖；
- MCP 只做协议适配；
- 能力经统一版本化契约注册；
- 所有 I/O 有严格 Schema；
- 数值由真实执行产生；
- 验证器独立运行；
- 原始附件只读；M1a 生成 payload 有版本和哈希，M1b 制品不可变且内容寻址；
- 实验记录完整版本、seed、输出引用、警告和验证；M1b 的输出引用指向内容寻址制品；
- 新能力不改稳定核心；
- Windows 是 M1a 主平台，M1b 在 Ubuntu 验证同一编排；
- 未确认的复杂框架被明确排除。

### 21.2 M1a 是可运行切片，M1b 是可信门

M1a 从宿主调用一直到 SQLite 结果和独立验证，没有只搭框架而缺少真实计算的横向层。其唯一生产 Built-in Capability 足以验证：

- Host Adapter 可替换；
- Application Facade 稳定；
- Registry 可显式注册；
- SQLite 可保存基础溯源；
- Capability 和 Validator 契约可执行；
- 基础 Context 与 Harness 能支撑一次真实宿主调用。

M1b 不增加新的用户功能主链，只把同一链路加固为内容寻址、可恢复、可兼容、跨平台并有完整证据的可信基线。任何不能直接服务 A 条目的工作都不得阻塞 M1a；任何 B 条目缺失都不得宣称 M1 完成。

### 21.3 两个有界实施计划

M1 仍是一个仓库、一个发行物和一个服务器进程，但实施必须拆成两个连续、各自可验收的计划，而不是一份近乎无界的大计划：

- M1a 最多 12 个顶层任务和 4 个工作包：入口/预览契约；核心/SQLite/能力；MCP/黄金链路；基础上下文/证据；
- M1b 在 M1a 通过后另写计划，最多 12 个顶层加固任务：1.0 契约/规范化；ArtifactStore/恢复；兼容/跨平台 Harness；完整文档/证据；
- M1b 可以修改 0.x 预览 Schema 和可重建状态，不要求先在 M1a 设计迁移框架；
- 若任一计划超过预算，先合并同一关注点或把非必要工作移到后续里程碑，不得用深层子任务隐藏预算超支；
- 计划中的每个抽象都必须引用第 7.4 节或补充当前调用方与具体实现。

这两个计划是同一产品里程碑的阶段门，不是独立子项目、仓库或发布体系。

### 21.4 Phase 0 停止点

本文提交后停止。下一步是用户审查本文；在用户另行要求前，不编写实施计划，不创建生产脚手架，不安装依赖，不实现服务器或算法。

## 22. 需求覆盖索引

| 设计要求 | 本文位置 |
|---|---|
| 产品边界 | 第 4 节 |
| 架构方案比较与推荐 | 第 5 节 |
| 系统架构 | 第 6 节 |
| 模块职责 | 第 7 节 |
| 数据流和状态模型 | 第 8、12 节 |
| Built-in Capability 契约与 External Plugin 边界 | 第 3、9、10 节 |
| MCP 工具边界 | 第 11 节 |
| Context Engineering | 第 13、17 节 |
| Harness Engineering | 第 14 节 |
| 错误处理和安全 | 第 15 节 |
| 测试与验收 | 第 16 节 |
| M1a 延后项与 M1 非目标 | 第 18 节 |
| 实施成本上限 | 第 4.4、7.4、21.3 节 |
| M2.5 进程隔离 | 第 5.2、15.10、19 节 |
| 演进路线 | 第 19 节 |
| 架构与需求一致性 | 第 21 节 |
| 版本与规范基线 | 第 3.1、8.5、23 节 |

## 23. 规范性外部基线

以下外部规范固定本文使用的协议、序列化和标识语义；若链接内容出现不兼容更新，M1 仍以表中固定版本为准，变更必须经过 ADR。M1a 只执行第 8.5 节烟测子集，M1b 才以完整 RFC 8785 向量建立发布基线：

- [MCP Protocol 版本说明](https://modelcontextprotocol.io/docs/learn/versioning)与 [2025-11-25 STDIO Transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)；
- [官方 MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)，M1 使用稳定 1.x 线；
- [RFC 8785：JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785)；
- [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12)；
- [RFC 3339：Internet 时间戳](https://www.rfc-editor.org/rfc/rfc3339)；
- [RFC 9562：UUID，含 UUID v4](https://www.rfc-editor.org/rfc/rfc9562)。
