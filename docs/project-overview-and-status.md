# Math Modeling MCP：设计、计划与实施状态总览

> 更新日期：2026-07-31
> 当前分支：`codex/m1a`
> 状态基准：A9a 提交 `665a53f69b092a408d1fff4ec95ae8ebca5aad78`
> 最新实现提交：`665a53f69b092a408d1fff4ec95ae8ebca5aad78`

状态口径：只有已经提交、通过规定测试并完成独立审查的任务才标记为“完成”。

权威来源：

- [Phase 0 设计规格](superpowers/specs/2026-07-16-math-modeling-mcp-design.md)
- [M1 实施计划](superpowers/plans/2026-07-17-math-modeling-mcp-m1.md)
- [C1 设计规格](superpowers/specs/2026-07-23-cumcm-2022-a-q1-contest-vertical-slice-design.md)
- [C1 实施计划](superpowers/plans/2026-07-23-cumcm-2022-a-q1-contest-vertical-slice.md)

## 1. Phase 0 设计

### 1.1 产品定位

本项目不是依赖长提示词直接生成国赛论文的聊天机器人，而是：

> 一个本地运行、宿主无关、可扩展、可验证、可追溯的数学建模计算核心。

Codex 是第一个宿主。后续 Claude Code、TRAE 等宿主通过薄适配层连接同一核心，
不重复实现数学求解、项目状态、实验记录和验证逻辑。

```text
Codex / Claude Code / TRAE
             ↓
        宿主薄适配层
             ↓
      本地 STDIO MCP
             ↓
     Application Facade
             ↓
稳定核心 + 能力注册表 + 验证器
             ↓
 SQLite / 制品 / 数值执行环境
```

### 1.2 核心架构决策

- 采用单仓库、单 Python 发行物的模块化单体，不在 M1 提前引入微服务。
- `modeling_core` 不依赖 MCP、SQLite、Codex 或任何具体数学能力。
- MCP 层只完成协议转换，不实现数学算法或直接访问 SQLite。
- 数学能力以显式注册的 **Built-in Capability** 提供；未来可安装的第三方单元才称为
  **External Plugin**。
- 所有数值结论必须来自真实程序执行，不能由大模型在文字中虚构。
- 求解器与验证器相互独立；验证器不能复用求解器的搜索或数值判定实现。
- Project、Experiment、Attempt、ResultSnapshot、Validation 和报告形成可查询的
  溯源链。
- 写操作使用 `operation_id + canonical_request_hash` 实现幂等；数学执行期间不保持
  长 SQLite 事务。
- 原始赛题附件只读；生成数据、结果和报告必须版本化并可追溯。
- 在 ODE、优化等重计算能力前引入短生命周期 worker、硬超时和资源限制。

### 1.3 M1 公共工具

M1 对宿主只暴露六个工具：

```text
health_check
create_project
get_project_status
list_capabilities
run_experiment
validate_experiment
```

内部求解器、SQLite 表、表达式解析器和验证器不是公共 MCP 工具。

### 1.4 状态与可信性模型

- Project：`UNINITIALIZED → STORAGE_READY → READY`，完整性异常进入
  `DEGRADED`。
- Attempt：
  `PENDING → RUNNING → SUCCEEDED | NUMERICAL_FAILURE | ERRORED | TIMED_OUT | ABANDONED`。
- Validation：
  `PENDING → RUNNING → SUCCEEDED | ERRORED | TIMED_OUT | ABANDONED`。
- Validation 的运行状态与数学结论分离；只有运行成功后才有
  `PASSED | FAILED | INCONCLUSIVE`。
- `NUMERICAL_FAILURE` 是正常数学结果，例如区间内没有符号变化；它不是系统错误。
- 输入、模型、数据、结果和验证报告均通过规范 JSON 与 SHA-256 建立证据链。

### 1.5 Context Engineering

上下文采用渐进式加载：

```text
根 AGENTS.md
→ 最近目录的嵌套 AGENTS.md
→ docs/context/index.md
→ 与当前任务有关的架构、契约和 ADR
→ 仅在需要时加载对应 Skill 和数学知识
```

长期规则进入 `AGENTS.md`，权威产品和架构知识进入 `docs/`，程序性工作流进入
Skills，当前增量目标进入任务 Prompt。ODE、PDE、统计和优化知识不会常驻每次开发
上下文。

### 1.6 Harness Engineering

- 单一验证入口：`modeling verify --milestone <milestone>`。
- 测试分为单元、契约、架构、数学、集成、复现、安全、验收和真实 STDIO 黄金链路。
- 架构测试阻止核心反向依赖适配器、数据库或具体能力。
- 数学变形测试验证平移、缩放、符号翻转和单位变换等不变量。
- 完成声明必须包含真实命令、测试统计、Git diff、完整 commit hash 和已知偏差。
- M1b 增加故障注入、内容寻址制品、跨平台验证和崩溃恢复证据。

### 1.7 Phase 0 明确不做

M1 不包含完整赛题自动理解、全题自主模型选择、论文自动生成、Web UI、多用户服务、
External Plugin 市场、任务队列、worker 池或所有历年题求解。它首先建立可信、
可扩展的计算与验证纵向切片。

## 2. M1 实施计划

当前批准路线为：

```text
M1a-0R 宿主证据修复门
→ M1a A1–A12 功能纵向切片
→ C1 真实国赛小问产品验证
→ M1b B1–B12 可信化加固
```

C1 放在完整 M1b 之前，用真实国赛小问检验平台是否具有产品价值；C1 仍必须等待
M1a Hard Gate 通过。

### 2.1 M1a-0R

目标是证明正式 Codex 宿主能够通过真实 STDIO MCP 调用一次 `root_finding`，而不是
依靠 shell、手写 JSON、截图或模型自述。该门已经完成。

### 2.2 M1a：功能纵向切片

| 任务 | 交付内容 | 状态 |
|---|---|---|
| A1 | 锁定 Python/uv 项目与验证入口 | 完成 |
| A2 | 严格 0.1 工具、错误和稳定哈希契约 | 完成 |
| A3 | 领域不变量、端口和 Application Facade | 完成 |
| A4 | 原子存储 bootstrap 与 SQLite schema 1 | 完成 |
| A5 | 封存的 Built-in Capability 注册表 | 完成 |
| A6 | 安全 math-expr-v1 与规范求根输入 | 完成 |
| A7 | 确定性二分法求根能力 | 完成 |
| A8 | 独立残差验证器 | 完成 |
| A9a | A9 所需的最小存储/异常契约修复 | 完成 |
| A9b | Facade、SQLite、幂等和实验/验证编排 | 已授权，待实施 |
| A10 | 严格低层 STDIO MCP 六工具适配 | 未开始 |
| A11 | 真实 STDIO 黄金链路与 M1a Harness | 未开始 |
| A12 | doctor、基础上下文、Codex 模板与验收门 | 未开始 |

A9a 是 A9 内部的 enabling slice，不增加第 13 个顶层任务。

### 2.3 M1a Hard Gate

```powershell
uv run --locked --no-sync modeling verify --milestone m1a
```

只有退出码 0、必需跳过为 0，并证明真实 STDIO 六工具链路、黄金求根实验、独立验证、
SQLite 溯源、幂等、超时、安全边界、Context 文档和验证证据都存在，M1a 才完成。

### 2.4 M1b：可信化加固

M1b 按批准路线在 C1 之后继续：

| 任务 | 计划内容 |
|---|---|
| B1 | 将已证明的 0.x 切片晋升为稳定 1.0 契约 |
| B2 | 完整 RFC 8785 向量与 Schema 兼容基线 |
| B3 | 带护栏的 Built-in Capability 脚手架 |
| B4 | SQLite schema 2 与内容寻址 ArtifactStore |
| B5 | 输入/环境快照和结果/报告制品发布 |
| B6 | 完整幂等恢复、重启收敛和 rerun |
| B7 | 五个崩溃窗口故障注入与文件系统安全 |
| B8 | 深化 doctor 与数学/重启复现 |
| B9 | 渐进式上下文路由和能力 Skills |
| B10 | 稳定架构、契约、运维和 ADR 文档 |
| B11 | Windows/Ubuntu 一致的 M1b 验证超集 |
| B12 | 完成证据包与 Codex 宿主黄金链路 |

## 3. C1 计划

### 3.1 目标

C1 选用 2022 年全国大学生数学建模竞赛 A 题问题一，建立第一个真实闭环：

```text
官方题面和附件
→ 只读内容寻址资产
→ Codex 生成 MMIR
→ 用户确认具体 revision
→ 两个阻尼情形分别执行
→ 两套独立数值验证
→ Excel、图、结果卡和 provenance
→ 真实 Codex MCP 端到端证据
```

C1 是 `0.x product-validation preview`，不宣称通用赛题工作流、完整 M1b 或跨平台
稳定发布已经完成。

### 3.2 数学能力

能力 ID：

```text
dynamics.coupled_heave/0.1.0
```

两种阻尼情形：

```text
linear:    D(q) = 10000 q
power_law: D(q) = 10000 |q|^0.5 q
```

生产求解使用 DOP853，`rtol=1e-9`、`atol=1e-11`。输出固定为
`t_i=0.2i, i=0…897`，共 898 行，终点 179.4 秒。

线性情形由增广状态矩阵指数解独立验证；非线性情形由步长 0.01 秒和 0.005 秒的
固定步长 RK4 独立验证。生产解与参考解要求 `rtol=2e-4`、`atol=2e-6`，归一化
能量闭合误差不超过 `1e-3`。

### 3.3 八个实施任务

| 任务 | 交付内容 | 状态 |
|---|---|---|
| C1.1 | 四个预览工具契约和稳定错误 | 未开始 |
| C1.2 | 只读、内容寻址的官方资产快照 | 未开始 |
| C1.3 | 带 revision 和人工确认的最小 MMIR | 未开始 |
| C1.4 | 60 秒硬超时、16 MiB 上限的短生命周期 worker | 未开始 |
| C1.5 | `dynamics.coupled_heave` DOP853 生产求解 | 未开始 |
| C1.6 | 矩阵指数、RK4 和能量闭合独立验证 | 未开始 |
| C1.7 | 两份 Excel、时序图、结果卡和 provenance | 未开始 |
| C1.8 | `verify --milestone c1` 与真实 Codex 宿主门 | 未开始 |

### 3.4 预期输出

- `result1-1.xlsx`
- `result1-2.xlsx`
- 两种阻尼情形时序图
- 10、20、40、60、100 秒结果卡
- 参数、单位、来源、假设、代码版本、运行和验证 provenance

只有两个 Attempt 都具有 `PASSED` Validation 时，`export_subproblem` 才能发布最终
制品。

### 3.5 C1 Hard Gate

```powershell
uv run --locked --no-sync modeling verify --milestone c1
```

要求退出码 0、必需跳过 0、两个 Validation 均为 `PASSED`，且真实 Codex 宿主只经
MCP 完成建项、资产登记、MMIR 草拟/确认、两次运行、两次验证和一次导出。

## 4. 已完成任务和提交记录

以下记录来自当前 Git 历史和 SDD progress ledger。

| 阶段/任务 | 提交 | 说明 | 审查状态 |
|---|---|---|---|
| M1a-0R | `d3fb4c126e8b81b2f74bab31d80e7b4a7313cdae` | `spike: prove Codex-hosted MCP root-finding round trip` | 后续修复 |
| M1a-0R 修复 | `610c23869452cbd9e5801e7ff44cdd58cb5d3c22` | `fix: close M1a-0R evidence gate gaps` | 独立审查通过 |
| A1 | `fe0018314c98dcb523df6369344d0cf5946a42b4` | `build: establish locked Python project` | 独立审查通过 |
| A2 | `2c5c37f76a331211dd53dcc7075369f43432be14` | `feat: define strict M1a public contracts` | 后续修复 |
| A2 修复 1 | `26f33ae606677166f7f30a9a75c2b263e850f82f` | `fix: enforce strict M1a contract invariants` | 后续修复 |
| A2 修复 2 | `456551a27adde5cbab38b4b8a08ccf6fa08b2d47` | `fix: constrain M1a validation trace policy` | 独立审查通过 |
| A3 | `9f30b904ddfae89caed9c2b3a8c5dbbc5c4f1ff7` | `feat: define host-independent core boundaries` | 后续修复 |
| A3 修复 | `14c0a45353885ea36c59a01e885d393b4fc8d421` | `fix: enforce validated A3 domain contracts` | 独立审查通过 |
| A4 计划修正 | `fcb7358c73ee39ccbf8ed73534c61198b8e47dfc` | `docs: correct A4 package ownership` | 独立审查通过 |
| A4 | `878acf1058bea4e46e4168c000a5ac97a904d55a` | `feat: add atomic SQLite project storage` | 后续修复 |
| A4 修复 | `670e8e00232b9d34edace9270f96b597ce5e386a` | `fix: reject reparse ancestors in project paths` | 独立审查通过 |
| A5 | `0b5ca4c6d9801a9f5f459c2a4403fabc662fb265` | `feat: add sealed built-in capability registry` | 后续修复 |
| A5 修复 1 | `4f04cd126368f39d7c3ebad4d828897c85e750a3` | `fix: seal registry descriptor snapshots` | 后续修复 |
| A5 修复 2 | `604482e323e1479348844dbd2dd46ed7c9ac9c13` | `fix: resolve sealed registry adapters` | 独立审查通过 |
| A6 | `ffa1a05b9e65bd9cbcd0ebb8281797dab5e819ae` | `feat: add safe canonical math expression input` | 后续修复 |
| A6 修复 | `084c15a17684e32a03b898d0ff875faa8cb98c6d` | `fix: seal canonical expression snapshots` | 独立审查通过 |
| A7 | `e70fc0432730f48e9c1ecfcd2d3fd8820c44b247` | `feat: execute bisection root finding` | 后续修复 |
| A7 修复 | `d44e8023b8b10f7077559994d1d5c39c4e71340e` | `fix: preserve bisection termination order` | 独立审查通过 |
| A8 | `7719f2937d640ec90bc8b96cf8b1a6d007b3e459` | `feat: add independent residual validation` | 独立审查通过 |
| A9a | `665a53f69b092a408d1fff4ec95ae8ebca5aad78` | `refactor: repair A9 persistence contracts` | 独立审查通过 |

当前已具备：

- 锁定的 Python/uv 环境；
- 严格工具和错误 Schema；
- 宿主无关核心边界；
- SQLite schema 1 与安全项目路径；
- 封存的能力注册表；
- 安全表达式解析和规范输入；
- 确定性二分法求根；
- 与求解器独立的残差验证器；
- A9 所需的宿主中立错误和存储端口契约。

A9a 的最终独立证据：

- 聚焦测试：326 passed；
- 全量测试：538 passed；
- MyPy：42 个源文件无问题；
- Ruff：通过；
- diff check：通过；
- 事后审查：`TASK REVIEW PASS — A9b AUTHORIZED`。

## 5. 当前未完成事项

### 5.1 正在进行：A9b

A9b 已获得授权，下一步实现：

- `ModelingApplication` 六个用例；
- schema-1 `SQLiteProjectStore` 的真实读写；
- create/run/validate 的规范幂等哈希和短事务；
- Experiment、Attempt、ResultSnapshot、Validation 与报告的内联溯源；
- 预执行错误、数值失败、超时、取消、系统错误和 Validation FAILED 的正交映射；
- 直接 Facade 黄金链路和复现测试。

### 5.2 M1a 剩余

1. 完成 A9b 并通过独立审查。
2. 完成 A10：严格 STDIO MCP 六工具适配和唯一组合根。
3. 完成 A11：真实 MCP 子进程黄金链路、安全测试和 M1a evidence。
4. 完成 A12：doctor、AGENTS、上下文索引、Codex 配置、维护文档和验收映射。
5. 通过 `modeling verify --milestone m1a`。

### 5.3 C1 剩余

C1.1–C1.8 尚未进入生产实现。M1a Hard Gate 通过前不得编写 C1 生产代码。后续需要
完成资产、MMIR、worker、耦合垂荡能力、独立验证、Excel/图表导出和真实宿主证据。

### 5.4 M1b 剩余

B1–B12 尚未开始。按当前批准路线，只有 C1 Hard Gate 通过后才恢复完整 M1b，包括
稳定 1.0 Schema、RFC 8785 完整符合性、内容寻址制品、恢复/重放、故障注入、
Windows/Ubuntu 双平台验证和正式发布证据。

### 5.5 后续里程碑

- M2：赛题、附件和数据基础；
- M2.5：受控 worker、硬超时和资源限制；
- M3：MMIR、动态建模工作流和首批 ODE/优化/统计能力；
- M4：Excel、图表、实验比较和论文素材；
- M5：高级能力和可选 External Plugin；
- M6：Claude Code、TRAE 和其他产品形态。

C1 会提前以有界预览方式验证其中部分能力，但不会替代这些正式里程碑。

## 6. 维护说明

本文件是项目导航和状态摘要，不替代权威规格。发生冲突时：

1. 已批准设计规格和实施计划决定目标与边界；
2. 版本化 Schema 与契约决定公开数据形状；
3. Git 提交、测试输出和 verifier 证据决定实际完成状态；
4. 本文件在每个任务完成并通过独立审查后更新。
