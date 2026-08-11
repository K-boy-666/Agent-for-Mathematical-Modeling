# Math Modeling MCP M1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 先用 48 小时 M1a-0 可行性 Spike 证明 Codex 能经本地 STDIO MCP 调用一次真实求根并收到结果，再以 M1a、M1b 两个正式阶段门交付宿主无关、能力可显式扩展的数学建模模块化单体及其可信基线。

**Architecture:** 正式产品仍是单一 Python 发行物中的模块化单体。M1a-0 只在 `spikes/m1a_0/` 放一个不进 wheel、不被正式代码导入的风险探针；宿主只依赖 `ApplicationFacade`，`modeling_mcp` 只做协议适配，数学与状态仍由稳定核心和显式 Built-in Capability 承担。M1 不实现 External Plugin、worker、队列、通用 DI 或第二存储后端。

**Tech Stack:** Python 3.11；uv 与锁文件；官方 MCP Python SDK 稳定 1.x（`mcp>=1.27,<2`）；Pydantic 2；JSON Schema Draft 2020-12；标准库 `sqlite3`；`rfc8785==0.1.4`；pytest、Ruff、mypy；Windows 为 M1a 主平台，Windows 与 Ubuntu 为 M1b 门禁。

## Global Constraints

- 本文只规划实施，不授权本次会话创建生产脚手架、安装依赖、实现服务器或算法。
- 规范性来源是 `docs/superpowers/specs/2026-07-16-math-modeling-mcp-design.md`；2026-07-18 用户批准的三项计划修订只增加前置风险探针、收紧 RFC 验证分期和任务交接证据，同日另批准将 uv 固定版本从 0.11.16 更新为 0.11.28；这些修订均不改变正式系统架构。其他冲突仍必须停止实施并修正规划。
- 执行顺序固定为 M1a-0 → A1–A12 → B1–B12。M1a-0 未过门时不得开始 A1；M1a 未过门时不得开始 B1。
- 2026-07-23 批准的 `M1a-0R` 是 Attempt 1/2 之后唯一且最终的宿主证据补救；它只取代原 M1a-0 宿主证据门，并保留通用真实 STDIO 子进程测试为独立硬门。现行路线为 `M1a-0R → A1–A12/M1a Hard Gate → C1 → deferred M1b`，C1 以 2026-07-23 的 contest-vertical-slice 设计附录及实施计划为准。
- M1a-0 恰有 1 个非生产 Feasibility Spike 任务，不计入设计规定的正式 M1a 预算；M1a 恰有 12 个顶层任务、4 个有序工作包；M1b 恰有 12 个顶层任务、4 个有序工作包。
- 每个任务都遵循：先写失败测试，运行并观察指定失败，写满足该测试的最小实现，运行目标测试，运行相关回归，提交一次可独立审查的变更。
- 每次执行命令前都位于仓库根。M1a-0 建立根锁文件后统一使用 `uv run --locked --no-sync`；只有依赖声明变化时才运行 `uv lock` 和 `uv sync --locked --group dev`。当拥有任务在现有单一发行物下创建新的顶层包时，该任务必须更新 Hatchling 的显式 package 列表，并且可在目录存在后恰好运行一次 `uv sync --locked --group dev`；这只是 editable-install 刷新，不是依赖声明或 `uv lock` 变更。
- 完成声明只接受新鲜命令输出。M1a 只能称为“可运行纵向切片”；A、B 两组证据全部成立后才能称为“M1 完成”或“可信发布基线”。
- M1a 只承诺三个固定 hash 烟测向量、表达式空白/默认值的稳定 hash 和同环境重复执行一致；完整 RFC 8785 通用与项目符合性向量只由 B2/M1b 声明和验收。
- 生产代码不得把 Built-in Capability 称为插件；`External Plugin` 只表示未来第三方安装单元。
- 所有测试项目根使用 pytest 的 `tmp_path` 或 Harness 创建的临时目录；不得在仓库根创建权威 `.modeling/` 状态。
- `build/verification/` 是可删除的验证输出，不是权威项目状态；它必须被 `.gitignore` 排除。
- 实现中的公共模型使用 `ConfigDict(strict=True, extra="forbid")`；JSON Schema 是数据形状权威，契约文档是字段语义与兼容规则权威。
- 每个新增抽象必须使用下文“抽象预算”中已列出的当前调用方和当前具体实现；不得为未出现的第二实现扩展通用框架。

## Agent Execution Discipline

本节按引用并入 M1a-0、A1–A12 和 B1–B12 的每一个 Commit 步骤与 Acceptance。任务只有在测试、diff 和提交三类证据同时齐全时才能标记完成。

1. **Test result:** 报告本任务 focused test 与 related regression 的原样命令、退出码、passed/failed/skipped 数；任何失败、required skip 或只引用旧输出都令任务保持未完成。
2. **Git diff summary:** 在任务专属 `git add` 之后、`git commit` 之前运行并保存以下完整输出；`git diff --cached --check` 必须退出 0，stat 中的路径必须是该任务 Files 清单的子集。

   ```powershell
   git status --short
   git diff --cached --stat
   git diff --cached --check
   ```

3. **Commit hash:** 执行任务给定的 commit 命令后立即运行以下命令；报告仓库对象格式对应的完整 40 位或 64 位小写 hash 和 `git show` 摘要，不接受分支名、短 hash 或工作树描述代替。

   ```powershell
   $taskCommit = (git rev-parse HEAD).Trim()
   if ($taskCommit -notmatch '^(?:[0-9a-f]{40}|[0-9a-f]{64})$') { throw 'task commit hash is not a full lowercase object ID' }
   git show --stat --oneline --no-renames $taskCommit
   ```

每个任务的交接消息必须恰有 `Task`、`Test result`、`Git diff summary`、`Commit hash` 四个字段。提交后发现证据缺失、diff 越界或测试未过时，不得补写“通过”说明，必须保持任务开放并修正后重新执行该任务的完成门。

## Repository Baseline

实施计划编写时的实际仓库状态：

- 唯一项目文件是已批准规格 `docs/superpowers/specs/2026-07-16-math-modeling-mcp-design.md`。
- 根 `AGENTS.md`、嵌套 `AGENTS.md`、`docs/context/index.md`、产品/架构/契约/ADR、源码、Schema、测试、`pyproject.toml`、`uv.lock` 和 CI 均不存在。
- `.agents/` 与 `.codex/` 为空。
- Git 元数据无效，`git status` 返回“not a git repository”；M1a-0 必须先执行 `git init`，之后才能满足逐任务提交要求。
- 因此所有下列项目文件相对编写时基线均为新文件；文件表明确标出 M1a-0 → A1 和 M1a → M1b 的后续修改责任。

## Normative References

- 已批准设计：`docs/superpowers/specs/2026-07-16-math-modeling-mcp-design.md`
- 官方 MCP Python SDK 稳定分支：<https://github.com/modelcontextprotocol/python-sdk/tree/v1.x>
- uv 锁定与 `--no-sync`：<https://docs.astral.sh/uv/concepts/projects/sync/>
- RFC 8785：<https://www.rfc-editor.org/rfc/rfc8785>
- Python RFC 8785 包 0.1.4：<https://pypi.org/project/rfc8785/>
- Codex 项目级配置：<https://developers.openai.com/codex/config-reference>
- Codex STDIO MCP 配置：<https://developers.openai.com/codex/mcp>
- Codex 非交互烟测：<https://learn.chatgpt.com/docs/non-interactive-mode>
- GitHub checkout Action：<https://github.com/actions/checkout>
- GitHub artifact Action：<https://github.com/actions/upload-artifact>
- Astral setup-uv Action：<https://github.com/astral-sh/setup-uv>

## Dependency Budget

| 依赖 | 范围 | 当前使用方与不可替代原因 |
|---|---|---|
| `mcp` | `>=1.27,<2` | M1a-0 风险探针、正式 `modeling_mcp` 和真实 STDIO 客户端测试；复用官方协议、会话与类型实现，避免自写 MCP |
| `pydantic` | `>=2.13,<3` | 严格公共 DTO 与能力契约模型；MCP SDK 也以类型模型表达结构化内容 |
| `jsonschema` | `>=4.26,<5` | 启动时和契约测试中校验随 wheel 交付的 Draft 2020-12 权威 Schema；Pydantic 不能替代独立 Schema 符合性检查 |
| `rfc8785` | `==0.1.4` | M1a 用锁定实现生成稳定 hash，但不声明完整符合性；B2 才用完整 RFC 8785 通用/项目向量建立符合性证据 |
| `hatchling` | `>=1.27,<2` | PEP 517 构建单个多包发行物并携带 JSON Schema 与 SQL 资产 |
| `pytest` | `>=8.4,<10` | 所有自动测试与临时目录夹具 |
| `ruff` | `>=0.12,<1` | 单一跨平台 lint/format 门禁 |
| `mypy` | `>=1.17,<2` | `src/` 严格静态类型门禁和 Facade/端口一致性 |
| `editables` | `~=0.3` | 仅限 dev：Hatchling `dev-mode-exact` 生成的 editable loader 在 Python 3.11/Windows 非 ASCII checkout 下需要该运行时；它不进入 `[project].dependencies` 或生产 wheel |

除上表外，M1 不增加生产或开发依赖。SQLite、CLI、哈希、UUID、时间、路径、进程、锁、原子替换、表达式 tokenizer/Pratt parser 和 Harness 编排均使用 Python 标准库。

External executables are not package dependencies: Git is required from M1a-0; uv is fixed to 0.11.28; an authenticated Codex CLI is required for the M1a-0 feasibility gate and again for B12's production-host smoke; the authenticated GitHub CLI is required only to retrieve the exact B12 CI artifacts. The formal core and normal verification never install, vendor or invoke Codex/GitHub; host CLI evidence is isolated to the two explicit gates and is not part of mathematical reproducibility.

## Abstraction Budget

| 抽象 | 首次任务 | 当前调用方 | 当前具体实现 |
|---|---|---|---|
| `ApplicationFacade` | A3 | MCP 适配器、CLI doctor、直接核心测试 | `ModelingApplication` |
| `ProjectStore` | A3/A4 | `ModelingApplication`、恢复服务 | `SQLiteProjectStore`；M1 不建 Repository 基类族 |
| `Clock` | A3 | 执行截止时间、验证截止时间、时间戳 | `SystemClock`；测试用 `FakeClock` |
| `IdGenerator` | A3 | 实体、Session、correlation ID | `Uuid4Generator`；测试用 `FixedIdGenerator` |
| `BuiltInCapability` | A5 | `CapabilityRegistry`、`ModelingApplication` | `BisectionRootFindingCapability` |
| `CapabilityValidator` | A5 | `CapabilityRegistry`、`ModelingApplication` | `ResidualRootFindingValidator` |
| `ArtifactStore` | B4 | M1b 结果/报告发布、doctor 完整性检查 | `ContentAddressedArtifactStore` |
| `ArtifactSink` | B5 | M1b `ExecutionContext` 和 `ModelingApplication` 的当前 Attempt 结果发布 | `AttemptArtifactSink`，只写且受 16 个/64 MiB 预算约束 |
| `FaultInjector` | B7 | M1b 执行与发布编排的五个命名检查点 | 生产 `NoFaults`；测试 `ScriptedProcessExitFaults` |

不得增加 `ExecutionBackend`、通用事件发布器、动态插件发现器、服务定位器、任务队列、worker 池或第二种数据库端口。M2.5 出现真实父进程与 worker 后才设计执行边界。

---

## Complete File Map

### Repository, package and entry-point files

| 文件 | 阶段 | 单一职责 |
|---|---|---|
| `docs/superpowers/plans/2026-07-17-math-modeling-mcp-m1.md` | 计划/M1a-0 基线提交 | 本文；唯一 M1a-0/M1a/M1b 任务、命令和验收映射 |
| `docs/superpowers/specs/2026-07-16-math-modeling-mcp-design.md` | 已批准/M1a-0 基线提交 | 不修改的规范性设计来源；M1a-0 初始化 Git 时与本计划一并纳入首个提交 |
| `.gitignore` | M1a-0/A1 修改 | 从 Spike 起排除 `.venv/`、`.codex/`、Python 缓存、`build/`、测试缓存和本地 `.modeling/` |
| `.gitattributes` | M1a-0 | 将文本工作树固定为 LF，保证后续 Windows/Ubuntu 源指纹按同一字节计算 |
| `.python-version` | M1a-0 | 固定 Python 3.11 基线 |
| `pyproject.toml` | M1a-0/A1 修改 | Spike 先建立唯一根项目和 MCP/pytest 锁；A1 扩为正式单发行物配置 |
| `uv.lock` | M1a-0/A1 修改 | 从 Spike 起解析并固定所有直接与传递依赖的精确版本 |
| `README.md` | A1/A12/B10 修改 | 入口命令、里程碑状态和权威文档导航 |
| `spikes/m1a_0/README.md` | M1a-0 | 48 小时时限、非生产边界、运行步骤和退出条件 |
| `spikes/m1a_0/server.py` | M1a-0 | 只证明 STDIO MCP 与固定 `x*x-2` 二分求根往返的隔离探针 |
| `spikes/m1a_0/test_spike.py` | M1a-0 | 直接数值测试和真实通用 MCP STDIO 子进程测试 |
| `spikes/m1a_0/codex-config.toml` | M1a-0 | 仅供临时可信 checkout 复制的单工具 Codex 项目配置 |
| `spikes/m1a_0/verify_codex_transcript.py` | M1a-0 | 验证 Codex transcript 含启动、连接、唯一求根调用和真实结果 |
| `.github/workflows/verify.yml` | B11 | Windows/Ubuntu 运行相同 M1b 验证命令并上传各自证据 |
| `src/modeling_core/__init__.py` | A1 | 核心包身份，不重导出外围实现 |
| `src/modeling_core/version.py` | A1/B1/B6 修改 | M1a/M1b Release 常量与 B6 的一次性当前版本切换 |
| `src/modeling_cli/__init__.py` | A1 | CLI 包身份 |
| `src/modeling_cli/__main__.py` | A1 | `python -m modeling_cli` 入口 |
| `src/modeling_cli/main.py` | A1/A4/A12/B3/B12 修改 | `modeling` 子命令解析与退出码路由，不含领域逻辑 |
| `src/modeling_cli/doctor.py` | A12/B8 修改 | doctor 检查编排和文本/JSON 呈现 |
| `src/modeling_harness/__init__.py` | A1 | Harness 包身份 |
| `src/modeling_harness/verify.py` | A1/A11/A12/B2/B3/B11/B12 修改 | 唯一 `verify` 入口、里程碑/单能力 profile 和检查调度 |
| `src/modeling_harness/evidence.py` | A11/B11/B12 修改 | 原子生成版本化验证报告、证据清单和最终 bundle |
| `src/modeling_harness/schema_compat.py` | B2 | 1.0 基线与候选 Schema 的兼容集合比较 |
| `src/modeling_harness/capability_scaffold.py` | B3 | 用标准库模板生成 Built-in Capability 文件并拒绝覆盖 |
| `src/modeling_harness/reproducibility.py` | B8 | rerun、重启、版本和容差复现审计 |

### Stable core files

| 文件 | 阶段 | 单一职责 |
|---|---|---|
| `src/modeling_core/AGENTS.md` | A12 | 核心目录依赖、领域与端口护栏 |
| `src/modeling_core/contracts/__init__.py` | A2 | 公共契约包边界 |
| `src/modeling_core/contracts/versions.py` | A2/B1 修改 | M1a/M1b 全部版本轴的不可混用值对象 |
| `src/modeling_core/contracts/common.py` | A2 | JSON 值、UUID、Hash、Timestamp、Warning、严格基类 |
| `src/modeling_core/contracts/errors.py` | A2 | 九个错误码、严格 details 联合和 `ModelingError` |
| `src/modeling_core/contracts/tools.py` | A2/B1 修改 | 六工具请求/成功结果 DTO 和状态判别联合 |
| `src/modeling_core/contracts/capability.py` | A5/B3/B5 修改 | Built-in Capability、Validator、描述符与上下文契约 |
| `src/modeling_core/contracts/canonical_json.py` | A2/B2 修改 | A2 提供锁定算法的稳定 bytes/hash；B2 才以完整 RFC 8785 向量证明符合性 |
| `src/modeling_core/contracts/schema_catalog.py` | A2/B1 修改 | 从包资产加载、校验、哈希和按 `$id` 解析 Schema |
| `src/modeling_core/domain/__init__.py` | A3 | 领域包边界 |
| `src/modeling_core/domain/models.py` | A3/B5 修改 | Project、Experiment、Attempt、ResultSnapshot、Validation 及 M1b 快照实体 |
| `src/modeling_core/domain/states.py` | A3 | Project/Attempt/Validation 状态和终态枚举 |
| `src/modeling_core/domain/transitions.py` | A3 | 唯一合法状态转换与终态输出矩阵校验 |
| `src/modeling_core/ports/__init__.py` | A3 | 端口包边界 |
| `src/modeling_core/ports/project_store.py` | A3/B4/B6 修改 | 具体用例所需的显式持久化操作；不提供通用 CRUD |
| `src/modeling_core/ports/clock.py` | A3 | UTC 与单调时钟接口 |
| `src/modeling_core/ports/ids.py` | A3 | 小写 UUID v4 生成接口 |
| `src/modeling_core/ports/artifact_store.py` | B4/B5 | 内容寻址 JSON 发布、验证读取与受限 Attempt ArtifactSink 接口 |
| `src/modeling_core/ports/faults.py` | B7 | 五个故障注入检查点接口 |
| `src/modeling_core/registry.py` | A5/B3 修改 | 显式注册、唯一性校验、确定性解析、指纹和封存 |
| `src/modeling_core/application/__init__.py` | A3 | 应用层包边界 |
| `src/modeling_core/application/facade.py` | A3 | 六个宿主无关用例的唯一公共 Protocol |
| `src/modeling_core/application/idempotency.py` | A9/B6 修改 | canonical request hash 与 M1a/M1b 幂等决策 |
| `src/modeling_core/application/service.py` | A9/B1/B5/B6/B7 修改 | `ModelingApplication` 六用例编排、写 admission gate 和终态提交 |
| `src/modeling_core/application/recovery.py` | B6 | Session 启动时遗留实体与幂等记录收敛 |

### Versioned common and tool Schema assets

下列 JSON 文件全部使用 Draft 2020-12、固定 `$id`、根对象 `additionalProperties:false`；每个文件只定义文件名所示的一种形状。

| 文件 | 阶段 | 单一职责 |
|---|---|---|
| `src/modeling_core/contracts/schemas/common/0.1.0/modeling-error.schema.json` | A2 | Error 0.1.0 九码判别联合 |
| `src/modeling_core/contracts/schemas/common/0.1.0/modeling-project.schema.json` | A4 | `project.json` 0.1.0 形状 |
| `src/modeling_core/contracts/schemas/common/0.1.0/modeling-capability.schema.json` | A5 | CapabilityDescriptor 0.1.0 形状 |
| `src/modeling_core/contracts/schemas/common/0.1.0/modeling-validator.schema.json` | A5 | ValidatorDescriptor 0.1.0 形状 |
| `src/modeling_core/contracts/schemas/common/0.1.0/modeling-result.schema.json` | A7 | Result payload 0.1.0 外壳 |
| `src/modeling_core/contracts/schemas/common/0.1.0/modeling-validation-report.schema.json` | A8 | ValidationReport 0.1.0 外壳 |
| `src/modeling_core/contracts/schemas/common/1.0.0/modeling-error.schema.json` | B1 | Error 1.0.0 首发基线 |
| `src/modeling_core/contracts/schemas/common/1.0.0/modeling-project.schema.json` | B1 | `project.json` 1.0.0 首发基线 |
| `src/modeling_core/contracts/schemas/common/1.0.0/modeling-capability.schema.json` | B1 | CapabilityDescriptor 1.0.0 首发基线 |
| `src/modeling_core/contracts/schemas/common/1.0.0/modeling-validator.schema.json` | B1 | ValidatorDescriptor 1.0.0 首发基线 |
| `src/modeling_core/contracts/schemas/common/1.0.0/modeling-result.schema.json` | B1 | Result payload 1.0.0 首发基线 |
| `src/modeling_core/contracts/schemas/common/1.0.0/modeling-validation-report.schema.json` | B1 | ValidationReport 1.0.0 首发基线 |
| `src/modeling_core/contracts/schemas/tools/0.1.0/health_check.request.schema.json` | A2 | health_check 空请求 |
| `src/modeling_core/contracts/schemas/tools/0.1.0/health_check.result.schema.json` | A2 | health_check 预览成功结果 |
| `src/modeling_core/contracts/schemas/tools/0.1.0/health_check.error.schema.json` | A2 | health_check 允许错误子集 |
| `src/modeling_core/contracts/schemas/tools/0.1.0/create_project.request.schema.json` | A2 | create_project 预览请求 |
| `src/modeling_core/contracts/schemas/tools/0.1.0/create_project.result.schema.json` | A2 | create_project 预览成功结果 |
| `src/modeling_core/contracts/schemas/tools/0.1.0/create_project.error.schema.json` | A2 | create_project 允许错误子集 |
| `src/modeling_core/contracts/schemas/tools/0.1.0/get_project_status.request.schema.json` | A2 | 两种 M1a status view 请求 |
| `src/modeling_core/contracts/schemas/tools/0.1.0/get_project_status.result.schema.json` | A2 | M1a summary/experiment 结果联合 |
| `src/modeling_core/contracts/schemas/tools/0.1.0/get_project_status.error.schema.json` | A2 | status 允许错误子集 |
| `src/modeling_core/contracts/schemas/tools/0.1.0/list_capabilities.request.schema.json` | A2 | summary/contract 能力请求 |
| `src/modeling_core/contracts/schemas/tools/0.1.0/list_capabilities.result.schema.json` | A2 | 能力摘要/契约预览结果联合 |
| `src/modeling_core/contracts/schemas/tools/0.1.0/list_capabilities.error.schema.json` | A2 | list 允许错误子集 |
| `src/modeling_core/contracts/schemas/tools/0.1.0/run_experiment.request.schema.json` | A2 | M1a `mode=new` 请求 |
| `src/modeling_core/contracts/schemas/tools/0.1.0/run_experiment.result.schema.json` | A2 | 五种 Attempt 终态结果联合 |
| `src/modeling_core/contracts/schemas/tools/0.1.0/run_experiment.error.schema.json` | A2 | run 九码错误联合 |
| `src/modeling_core/contracts/schemas/tools/0.1.0/validate_experiment.request.schema.json` | A2 | M1a residual 验证请求 |
| `src/modeling_core/contracts/schemas/tools/0.1.0/validate_experiment.result.schema.json` | A2 | 四种 Validation 终态结果联合 |
| `src/modeling_core/contracts/schemas/tools/0.1.0/validate_experiment.error.schema.json` | A2 | validate 九码错误联合 |
| `src/modeling_core/contracts/schemas/tools/1.0.0/health_check.request.schema.json` | B1 | health_check 1.0 请求基线 |
| `src/modeling_core/contracts/schemas/tools/1.0.0/health_check.result.schema.json` | B1 | health_check 1.0 结果基线 |
| `src/modeling_core/contracts/schemas/tools/1.0.0/health_check.error.schema.json` | B1 | health_check 1.0 错误基线 |
| `src/modeling_core/contracts/schemas/tools/1.0.0/create_project.request.schema.json` | B1 | create_project 1.0 请求基线 |
| `src/modeling_core/contracts/schemas/tools/1.0.0/create_project.result.schema.json` | B1 | create_project 1.0 结果基线 |
| `src/modeling_core/contracts/schemas/tools/1.0.0/create_project.error.schema.json` | B1 | create_project 1.0 错误基线 |
| `src/modeling_core/contracts/schemas/tools/1.0.0/get_project_status.request.schema.json` | B1 | 分页 status 1.0 请求基线 |
| `src/modeling_core/contracts/schemas/tools/1.0.0/get_project_status.result.schema.json` | B1 | 分页 status 1.0 结果基线 |
| `src/modeling_core/contracts/schemas/tools/1.0.0/get_project_status.error.schema.json` | B1 | status 1.0 错误基线 |
| `src/modeling_core/contracts/schemas/tools/1.0.0/list_capabilities.request.schema.json` | B1 | list 1.0 请求基线 |
| `src/modeling_core/contracts/schemas/tools/1.0.0/list_capabilities.result.schema.json` | B1 | list 1.0 结果基线 |
| `src/modeling_core/contracts/schemas/tools/1.0.0/list_capabilities.error.schema.json` | B1 | list 1.0 错误基线 |
| `src/modeling_core/contracts/schemas/tools/1.0.0/run_experiment.request.schema.json` | B1 | new/rerun 1.0 请求基线 |
| `src/modeling_core/contracts/schemas/tools/1.0.0/run_experiment.result.schema.json` | B1 | ArtifactManifest run 结果基线 |
| `src/modeling_core/contracts/schemas/tools/1.0.0/run_experiment.error.schema.json` | B1 | run 1.0 错误基线 |
| `src/modeling_core/contracts/schemas/tools/1.0.0/validate_experiment.request.schema.json` | B1 | validate 1.0 请求基线 |
| `src/modeling_core/contracts/schemas/tools/1.0.0/validate_experiment.result.schema.json` | B1 | 报告制品 validate 结果基线 |
| `src/modeling_core/contracts/schemas/tools/1.0.0/validate_experiment.error.schema.json` | B1 | validate 1.0 错误基线 |

### Built-in Capability files and Schema assets

| 文件 | 阶段 | 单一职责 |
|---|---|---|
| `src/modeling_capabilities/__init__.py` | A5 | Built-in Capability 包身份；不执行目录扫描 |
| `src/modeling_capabilities/AGENTS.md` | A12 | 内置能力契约、版本、显式注册和验证独立护栏 |
| `src/modeling_capabilities/root_finding/__init__.py` | A6 | root finding 能力包边界 |
| `src/modeling_capabilities/root_finding/context.md` | A6/B10 修改 | 仅该能力需要的数学语义、限制与测试入口 |
| `src/modeling_capabilities/root_finding/contracts.py` | A6/B1 修改 | 原始输入、CanonicalInput、成功、失败、policy、report 类型 |
| `src/modeling_capabilities/root_finding/descriptor.py` | A7/A8/B1 修改 | 求根能力和 residual validator 的版本化描述符 |
| `src/modeling_capabilities/root_finding/expression/__init__.py` | A6 | expression 子包边界 |
| `src/modeling_capabilities/root_finding/expression/syntax.py` | A6 | tokenizer、Pratt parser、不可变 AST、规范 AST JSON |
| `src/modeling_capabilities/root_finding/expression/solver_evaluator.py` | A6 | 求解器专用 AST 数值求值与预算检查 |
| `src/modeling_capabilities/root_finding/expression/validator_evaluator.py` | A6 | 验证器独立 AST 数值求值与预算检查 |
| `src/modeling_capabilities/root_finding/solver.py` | A7/B1 修改 | 确定性 binary64 二分法 Built-in Capability |
| `src/modeling_capabilities/root_finding/validator.py` | A8/B1 修改 | 独立 residual validator 与报告构造 |
| `src/modeling_capabilities/root_finding/schemas/0.1.0/input.schema.json` | A6 | 原始求根 payload 0.1.0 |
| `src/modeling_capabilities/root_finding/schemas/0.1.0/canonical-input.schema.json` | A6 | 物化默认值和 AST 的 CanonicalInput 0.1.0 |
| `src/modeling_capabilities/root_finding/schemas/0.1.0/success-data.schema.json` | A7 | 成功 `data` 0.1.0 |
| `src/modeling_capabilities/root_finding/schemas/0.1.0/failure-data.schema.json` | A7 | 数值失败 `data` 0.1.0 |
| `src/modeling_capabilities/root_finding/schemas/0.1.0/policy.schema.json` | A8 | residual 严格空 policy 0.1.0 |
| `src/modeling_capabilities/root_finding/schemas/0.1.0/report.schema.json` | A8 | residual ValidationReport 0.1.0 |
| `src/modeling_capabilities/root_finding/schemas/1.0.0/input.schema.json` | B1 | 原始求根 payload 1.0 基线 |
| `src/modeling_capabilities/root_finding/schemas/1.0.0/canonical-input.schema.json` | B1 | CanonicalInput 1.0 基线 |
| `src/modeling_capabilities/root_finding/schemas/1.0.0/success-data.schema.json` | B1 | 成功 `data` 1.0 基线 |
| `src/modeling_capabilities/root_finding/schemas/1.0.0/failure-data.schema.json` | B1 | 数值失败 `data` 1.0 基线 |
| `src/modeling_capabilities/root_finding/schemas/1.0.0/policy.schema.json` | B1 | residual policy 1.0 基线 |
| `src/modeling_capabilities/root_finding/schemas/1.0.0/report.schema.json` | B1 | residual report 1.0 基线 |

### Infrastructure, composition, MCP and CLI files

| 文件 | 阶段 | 单一职责 |
|---|---|---|
| `src/modeling_infrastructure/__init__.py` | A4 | 基础设施包身份 |
| `src/modeling_infrastructure/AGENTS.md` | B9 | SQLite、路径、原子发布和恢复护栏 |
| `src/modeling_infrastructure/environment.py` | A9/B5 修改 | 脱敏环境摘要与 M1b EnvironmentSnapshot 构造 |
| `src/modeling_infrastructure/project_paths.py` | A4/B4 修改 | 绑定根规范化、重解析点拒绝和内部路径生成 |
| `src/modeling_infrastructure/project_lock.py` | A4/B6 修改 | Windows `msvcrt`/POSIX `fcntl` 单写入项目锁与 Session 诊断 |
| `src/modeling_infrastructure/storage.py` | A4/B4 修改 | `.modeling.tmp.{uuid4}` 初始化、`project.json` 和原子目录发布；花括号是运行时 UUID v4 值 |
| `src/modeling_infrastructure/sqlite/__init__.py` | A4 | SQLite 适配器包边界 |
| `src/modeling_infrastructure/sqlite/schema_v1.sql` | A4 | M1a 预览表、索引、约束与 `user_version=1` |
| `src/modeling_infrastructure/sqlite/schema_v2.sql` | B4 | M1b 首个稳定表、快照、Artifact 与 `user_version=2` |
| `src/modeling_infrastructure/sqlite/store.py` | A4/A9/B4/B5/B6 修改 | `ProjectStore` 的唯一 SQLite 实现和短事务 |
| `src/modeling_infrastructure/artifacts/__init__.py` | B4 | Artifact 适配器包边界 |
| `src/modeling_infrastructure/artifacts/store.py` | B4/B7 修改 | staging、flush、hash、Schema 校验、no-clobber 原子发布 |
| `src/modeling_bootstrap/__init__.py` | A10 | 组合根包身份 |
| `src/modeling_bootstrap/AGENTS.md` | B9 | 唯一组装位置和禁止业务逻辑规则 |
| `src/modeling_bootstrap/composition.py` | A10/B4/B5/B6/B7 修改 | 显式创建 store、registry、能力、validator、Facade 和 MCP |
| `src/modeling_mcp/__init__.py` | A10 | MCP 适配器包身份 |
| `src/modeling_mcp/AGENTS.md` | A12 | 协议适配、STDOUT 和 Schema 兼容护栏 |
| `src/modeling_mcp/strict_stdio.py` | A10 | 1 MiB 前置限制、重复键/UTF-8/surrogate/非有限数拒绝和纯净字节管道 |
| `src/modeling_mcp/adapter.py` | A10/B1 修改 | 六工具名到 Facade 方法、Schema 验证和 `CallToolResult` 映射 |
| `src/modeling_mcp/server.py` | A10 | MCP Protocol 2025-11-25 初始化与低层 Server 运行 |
| `src/modeling_mcp/__main__.py` | A10 | `modeling-mcp --project-root .` 进程入口 |

### Product, architecture, contract, operations and context documents

| 文件 | 阶段 | 单一职责 |
|---|---|---|
| `AGENTS.md` | A12/B10 修改 | 全仓稳定使命、依赖、安全、验证与当前里程碑规则 |
| `docs/context/index.md` | A12/B9/B10 修改 | 任务类型到最小必读上下文的路由索引 |
| `docs/product/m1-scope.md` | A12 | M1a/M1b 用户价值、门禁和非目标 |
| `docs/product/vision.md` | B10 | M1 之后的长期产品愿景与用户边界 |
| `docs/architecture/overview.md` | A12/B10 修改 | 当前模块、依赖方向、数据流和组合根 |
| `docs/architecture/state-model.md` | B10 | Project、Attempt、Validation、幂等和制品状态模型 |
| `docs/architecture/security.md` | B10 | 信任边界、路径、进程、STDOUT、资源和失败关闭 |
| `docs/contracts/mcp-tools-v0.md` | A12 | 六工具 0.1 字段语义、错误和无兼容承诺说明 |
| `docs/contracts/capability-api-v0.md` | A12 | Built-in Capability API 0.1 语义 |
| `docs/contracts/root-finding-v0.md` | A12 | 求根与 residual 0.1 数学契约 |
| `docs/contracts/mcp-tools-v1.md` | B10 | 六工具 1.0 字段语义和兼容政策 |
| `docs/contracts/capability-api-v1.md` | B10 | Built-in Capability API 1.0 语义 |
| `docs/contracts/root-finding-v1.md` | B10 | 求根与 residual 1.0 数学契约 |
| `docs/operations/bootstrap-and-doctor.md` | A12/B8 修改 | bootstrap、doctor、退出码、只读检查和诊断流程 |
| `docs/operations/recovery.md` | B10 | Session 恢复、孤儿、失败窗口和人工处置 |
| `docs/operations/schema-evolution.md` | B10 | 1.0 之后的兼容比较、版本升级和基线纪律 |
| `docs/operations/release-verification.md` | B10/B12 修改 | 双平台验证、Codex 烟测、证据包和完成声明 |
| `docs/templates/codex/config.toml` | A12 | 可复制的项目级本地 STDIO MCP 配置 |
| `docs/capabilities/index.md` | B9 | 渐进披露的能力摘要目录 |
| `docs/AGENTS.md` | B9 | 文档权威边界、链接、ADR 生命周期和同步规则 |
| `.agents/skills/AGENTS.md` | B9 | Skill 触发、渐进披露和禁止复制契约正文 |
| `.agents/skills/add-capability/SKILL.md` | B9 | 新 Built-in Capability 的显式注册与验收流程 |
| `.agents/skills/numerical-validation/SKILL.md` | B9 | 独立数值验证器设计和数学变形审计流程 |
| `.agents/skills/stdio-diagnostics/SKILL.md` | B9 | STDIO 帧、句柄、STDOUT 和错误诊断流程 |
| `.agents/skills/reproducibility-audit/SKILL.md` | B9 | 输入、版本、环境、seed、结果和制品复现审计 |
| `.agents/skills/release-verification/SKILL.md` | B9 | M1b 双平台门禁和证据检查流程 |
| `docs/adr/0001-modular-monolith.md` | B10 | 选择模块化单体的决策记录 |
| `docs/adr/0002-ports-adapters-composition-root.md` | B10 | 端口/适配器和唯一组合根决策记录 |
| `docs/adr/0003-sqlite-content-addressed-artifacts.md` | B10 | SQLite 与内容寻址制品决策记录 |
| `docs/adr/0004-explicit-built-in-capabilities.md` | B10 | 显式可信内置能力和 External Plugin 边界决策 |
| `docs/adr/0005-local-stdio-mcp.md` | B10 | 本地 STDIO MCP 决策记录 |
| `docs/adr/0006-schema-semver-policy.md` | B10 | Schema、版本轴与 SemVer 决策记录 |
| `docs/adr/0007-independent-solver-validator.md` | B10 | 求解与验证独立决策记录 |
| `docs/adr/0008-single-writer-lock-recovery.md` | B10 | 单写入锁、Session 和崩溃恢复决策记录 |

### M1a test and corpus files

| 文件 | 单一职责 |
|---|---|
| `tests/AGENTS.md` | 测试分层、真实执行、无重试、时间与证据规则 |
| `tests/conftest.py` | 仓库根、临时项目和稳定 UUID/时钟公共夹具 |
| `tests/fixtures/fakes.py` | `FakeClock`、`FixedIdGenerator` 和取消信号测试实现 |
| `tests/fixtures/forged_results.py` | 哈希自洽但数学内容伪造的独立验证 fixture |
| `tests/smoke/test_cli_entrypoints.py` | 安装后 `modeling` 与 `modeling-mcp` 入口烟测 |
| `tests/unit/contracts/test_common_types.py` | UUID、Hash、Timestamp、Error 和 canonical JSON 单元测试 |
| `tests/unit/domain/test_state_models.py` | 领域不变量、合法转换和终态输出矩阵 |
| `tests/unit/test_registry.py` | 注册、重复拒绝、版本解析、指纹和封存 |
| `tests/unit/expression/test_syntax.py` | math-expr-v1 语法、AST 和安全预算 |
| `tests/unit/expression/test_canonicalization.py` | M1a 表达式空白、默认值与重复执行稳定 hash 烟测，不承担完整 RFC 符合性 |
| `tests/unit/root_finding/test_solver.py` | 二分法成功、失败、边界和截止时间 |
| `tests/unit/root_finding/test_validator.py` | 独立 residual 检查、metrics 和伪造结果拒绝 |
| `tests/unit/test_doctor.py` | 四项目状态、遗留运行和 doctor 退出码 |
| `tests/contract/test_tool_schemas_v0.py` | 六组 0.1 request/result/error Schema 与语料 |
| `tests/contract/test_capability_schemas_v0.py` | Capability、Validator、CanonicalInput、结果和报告 0.1 Schema |
| `tests/contract/test_project_store.py` | `ProjectStore` 显式方法对 SQLite 实现的契约 |
| `tests/contract/test_mcp_adapter.py` | `tools/list` 六工具 Schema 和 ToolResult 映射 |
| `tests/integration/test_bootstrap_sqlite.py` | 原子 bootstrap、幂等、Pragma、版本拒绝和项目锁 |
| `tests/integration/test_application_workflow.py` | 直接 Facade 创建、运行、验证、追踪与基础幂等 |
| `tests/integration/test_stdio_golden_m1a.py` | 真实子进程和字节管道的 M1a 黄金链路 |
| `tests/architecture/test_dependency_boundaries.py` | core/MCP/infrastructure/capability 导入方向 |
| `tests/architecture/test_composition_root.py` | 具体实现只在唯一组合根组装 |
| `tests/architecture/test_solver_validator_independence.py` | validator 不导入 solver evaluator/search/终止逻辑 |
| `tests/math/test_root_finding_metamorphic.py` | 平移、缩放、符号翻转、括区缩窄 |
| `tests/reproducibility/test_m1a_repeatability.py` | 同 Session 两次 new 实验分类、版本、哈希与容差 |
| `tests/security/test_m1a_boundaries.py` | 请求、表达式、路径、锁、超时、警告和 STDOUT 边界 |
| `tests/acceptance/test_m1a_acceptance_map.py` | A-01 至 A-10 到测试和证据的完备映射 |
| `tests/contract/corpus/tools/0.1.0/health_check.json` | health_check 合法/非法/边界/错误固定语料 |
| `tests/contract/corpus/tools/0.1.0/create_project.json` | create_project 固定语料 |
| `tests/contract/corpus/tools/0.1.0/get_project_status.json` | status 两视图固定语料 |
| `tests/contract/corpus/tools/0.1.0/list_capabilities.json` | list 两 detail 固定语料 |
| `tests/contract/corpus/tools/0.1.0/run_experiment.json` | run 五终态与九错误固定语料 |
| `tests/contract/corpus/tools/0.1.0/validate_experiment.json` | validate 四终态与九错误固定语料 |
| `tests/contract/corpus/root-finding/0.1.0.json` | 求根输入、成功、失败、policy、report 固定语料 |

### M1b test, baseline and corpus files

| 文件 | 单一职责 |
|---|---|
| `tests/fixtures/test_echo_capability.py` | 仅测试的 `test.echo/1.0.0` 能力与 validator |
| `tests/fixtures/fault_server.py` | 以命名检查点退出进程的测试专用组合根 |
| `tests/contract/test_tool_schemas_v1.py` | 六组 1.0 request/result/error Schema 与固定语料 |
| `tests/contract/test_schema_compatibility.py` | 兼容变更接受与破坏变更拒绝的 mutation 测试 |
| `tests/contract/test_rfc8785_vectors.py` | RFC Appendix B、参考 corpus 和项目向量 |
| `tests/contract/test_artifact_store.py` | `ArtifactStore` 发布、复用、篡改、no-clobber 契约 |
| `tests/contract/test_sqlite_schema_v2.py` | 新建 v2 项目结构、关系和未知版本拒绝 |
| `tests/integration/test_artifact_workflow.py` | Input/Environment 快照、结果/报告制品、全部命名哈希和四向结果完整性 |
| `tests/integration/test_recovery_and_rerun.py` | Session 恢复、完整幂等、响应丢失和 rerun |
| `tests/integration/test_fault_recovery.py` | 五个进程故障窗口和重启收敛 |
| `tests/integration/test_stdio_restart_m1b.py` | STDIO 重启、制品篡改和幂等重放 |
| `tests/architecture/test_echo_extension.py` | test.echo 显式加入且不修改 Stable Core |
| `tests/math/test_root_finding_affine_v1.py` | 固定种子的完整仿射生成集和非有限案例 |
| `tests/reproducibility/test_m1b_rerun.py` | rerun、重启、环境和制品关系复现 |
| `tests/security/test_m1b_artifact_boundaries.py` | 制品路径、大小/数量、篡改、孤儿和失败关闭 |
| `tests/acceptance/test_m1b_acceptance_map.py` | A-01 至 A-10 与 B-01 至 B-10 完备映射 |
| `tests/architecture/test_context_boundaries.py` | 根/嵌套规则、任务路由、Skills 和能力渐进披露边界 |
| `tests/acceptance/test_documentation_consistency.py` | 稳定文档、版本、链接、术语、路线和八个 ADR 一致性 |
| `tests/acceptance/test_release_evidence.py` | 双平台、Codex、指纹、脱敏和防篡改证据 bundle 契约 |
| `tests/contract/baselines/modeling-tools-1.0.0.json` | 六工具 1.0 Schema/语料路径与固定 SHA-256 清单 |
| `tests/contract/baselines/modeling-capability-1.0.0.json` | Capability、Validator 和 root contract 1.0 固定哈希清单 |
| `tests/contract/corpus/tools/1.0.0/health_check.json` | health_check 1.0 固定语料 |
| `tests/contract/corpus/tools/1.0.0/create_project.json` | create_project 1.0 固定语料 |
| `tests/contract/corpus/tools/1.0.0/get_project_status.json` | 分页 status 1.0 固定语料 |
| `tests/contract/corpus/tools/1.0.0/list_capabilities.json` | list 1.0 固定语料 |
| `tests/contract/corpus/tools/1.0.0/run_experiment.json` | new/rerun、制品和错误 1.0 固定语料 |
| `tests/contract/corpus/tools/1.0.0/validate_experiment.json` | 报告制品和错误 1.0 固定语料 |
| `tests/contract/corpus/root-finding/1.0.0.json` | root contract 1.0 固定语料 |
| `tests/contract/corpus/rfc8785/PROVENANCE.md` | RFC 与参考 corpus 来源、许可证、检索日期和内容哈希 |
| `tests/contract/corpus/rfc8785/appendix-b.json` | RFC 8785 Appendix B 全部 IEEE-754 行与预期文本 |
| `tests/contract/corpus/rfc8785/arrays.input.json` | 参考 arrays 非规范输入 |
| `tests/contract/corpus/rfc8785/arrays.output.json` | arrays 规范 UTF-8 输出 |
| `tests/contract/corpus/rfc8785/french.input.json` | 参考 french 非规范输入 |
| `tests/contract/corpus/rfc8785/french.output.json` | french 规范 UTF-8 输出 |
| `tests/contract/corpus/rfc8785/structures.input.json` | 参考 structures 非规范输入 |
| `tests/contract/corpus/rfc8785/structures.output.json` | structures 规范 UTF-8 输出 |
| `tests/contract/corpus/rfc8785/unicode.input.json` | 参考 unicode 非规范输入 |
| `tests/contract/corpus/rfc8785/unicode.output.json` | unicode 规范 UTF-8 输出 |
| `tests/contract/corpus/rfc8785/values.input.json` | 参考 values 非规范输入 |
| `tests/contract/corpus/rfc8785/values.output.json` | values 规范 UTF-8 输出 |
| `tests/contract/corpus/rfc8785/weird.input.json` | 参考 weird 非规范输入 |
| `tests/contract/corpus/rfc8785/weird.output.json` | weird 规范 UTF-8 输出 |
| `tests/contract/corpus/rfc8785/project-vectors.json` | 键序、1/1.0、-0、NFC、默认值和表达式空白项目向量 |

`build/verification/{milestone}/{source_fingerprint_hex}/` 是运行时路径模板；花括号分别由显式里程碑值和 Harness 计算的 64 位 lowercase SHA-256 十六进制后缀替换。报告内的 `source_fingerprint` 使用 `sha256:{source_fingerprint_hex}`。其报告、摘要、架构图、STDIO transcript、trace、兼容/复现/故障/安全报告和哈希清单是命令生成物，不进入版本控制，因此不列作源文件。

---

## Exact Public Interfaces

### Application Facade

```text
ApplicationFacade.health_check(request: HealthCheckRequest) -> HealthCheckResult
ApplicationFacade.create_project(request: CreateProjectRequest) -> CreateProjectResult
ApplicationFacade.get_project_status(request: GetProjectStatusRequest) -> GetProjectStatusResult
ApplicationFacade.list_capabilities(request: ListCapabilitiesRequest) -> ListCapabilitiesResult
ApplicationFacade.run_experiment(request: RunExperimentRequest) -> RunExperimentResult
ApplicationFacade.validate_experiment(request: ValidateExperimentRequest) -> ValidateExperimentResult
```

请求在记录创建前失败时抛出只携带严格 `ErrorResponse` 的 `ModelingError`；Attempt 或 Validation 建立后的 ERRORED、TIMED_OUT、ABANDONED、NUMERICAL_FAILURE 和验证 FAILED 都作为正常结果返回。

### Core ports

```text
Clock.utc_now() -> datetime
Clock.monotonic() -> float
IdGenerator.new_uuid4() -> str

ProjectStore.inspect_project_state() -> ProjectStateInspection
ProjectStore.create_or_replay_project(command: CreateProjectCommand) -> ProjectWriteResult
ProjectStore.get_project_summary(project_id: str) -> ProjectSummary
ProjectStore.get_experiment_trace(query: ExperimentTraceQuery) -> ExperimentTrace
ProjectStore.begin_run(command: BeginRunCommand) -> BeginRunResult
ProjectStore.mark_attempt_running(attempt_id: str, started_at: datetime, session_id: str) -> None
ProjectStore.complete_attempt(command: CompleteAttemptCommand) -> StoredRunResult
ProjectStore.begin_validation(command: BeginValidationCommand) -> BeginValidationResult
ProjectStore.mark_validation_running(validation_id: str, started_at: datetime) -> None
ProjectStore.complete_validation(command: CompleteValidationCommand) -> StoredValidationResult
ProjectStore.inspect_integrity(deep: bool) -> StoreIntegrityReport
```

M1a 的 `ProjectStore` 只有上列操作；`inspect_integrity` 报告遗留项并令项目 DEGRADED，不做恢复。B6 才增加以下方法，当前调用方只有启动期 `RecoveryService`：

```text
ProjectStore.recover_previous_session(current_session_id: str, recovered_at: datetime) -> RecoveryReport
RecoveryService.recover_previous_session(current_session_id: str, recovered_at: datetime) -> RecoveryReport
```

### Built-in Capability and Validator

```text
BuiltInCapability.descriptor -> CapabilityDescriptor
BuiltInCapability.normalize_and_validate(raw_payload: JsonObject) -> CanonicalInputRecord
BuiltInCapability.execute(canonical_input: CanonicalInputRecord, context: ExecutionContext) -> ExecutionOutcome

CapabilityValidator.descriptor -> ValidatorDescriptor
CapabilityValidator.validate(
    canonical_input: CanonicalInputRecord,
    result_snapshot: ResultSnapshotView,
    policy: JsonObject,
    context: ValidationContext,
) -> ValidationReport
```

`ExecutionContext` 恰有 `attempt_id`、`randomness`、`seed`、`deadline`、`clock`、`cancellation`；M1a 无文件写入口。B5 增加受限 `artifact_sink`，类型为 `ArtifactStore` 的只写 JSON 角色视图。能力永远拿不到 SQLite、项目根、MCP context、宿主身份、秘密或完整环境。

### Registry

```text
CapabilityRegistry.register_capability(capability: BuiltInCapability) -> None
CapabilityRegistry.register_validator(validator: CapabilityValidator) -> None
CapabilityRegistry.seal(required_capabilities: frozenset[CapabilityKey]) -> RegistrySummary
CapabilityRegistry.list_summaries(category: str | None, capability_id: str | None) -> list[CapabilitySummary]
CapabilityRegistry.resolve(capability_id: str, contract_version: str) -> BuiltInCapability
CapabilityRegistry.resolve_validator(validator_id: str, capability_id: str, contract_version: str, policy_version: str) -> CapabilityValidator
```

注册只发生在 `modeling_bootstrap/composition.py`；生产代码没有 entry-point 扫描、目录扫描或“最新版本”隐式选择。

### Artifact store, restricted sink and fault seam introduced in M1b

```text
ArtifactStore.publish_json(role: Literal["result", "validation_report"], payload: bytes, schema_id: str) -> ArtifactManifest
ArtifactStore.read_verified(artifact_id: str, expected_size: int, expected_sha256: str) -> bytes
ArtifactStore.inspect(referenced_artifact_ids: frozenset[str]) -> ArtifactInspectionReport
ArtifactSink.publish_json(role: Literal["result", "validation_report"], payload: bytes, schema_id: str) -> ArtifactManifest
FaultInjector.check(point: FaultPoint, context: FaultContext) -> None
```

### M1a-0 disposable feasibility interface

The M1a-0 interface below is deliberately outside every formal package and contract. It is never imported from `src/`, never packaged, and is superseded rather than generalized after the gate:

```text
solve_fixed_root(
    equation: Literal["x*x-2"],
    lower: float,
    upper: float,
    tolerance: float,
    max_iterations: int,
) -> SpikeRootResult

SpikeRootResult(root: float, residual: float, iterations: int, equation: Literal["x*x-2"])
MCP tool root_finding(equation: Literal["x*x-2"], lower: float, upper: float, tolerance: float) -> SpikeRootResult
verify_codex_transcript(path: Path) -> SpikeTranscriptReport
```

No formal DTO, registry descriptor, SQLite row, Application Facade method or future External Plugin contract may depend on these Spike-only names.

### CLI and process interfaces

```text
uv run --locked --no-sync modeling bootstrap --project-root tests/.tmp/manual-project
uv run --locked --no-sync modeling doctor --project-root tests/.tmp/manual-project --deep --json
uv run --locked --no-sync modeling verify --milestone m1a
uv run --locked --no-sync modeling verify --milestone m1b
uv run --locked --no-sync modeling verify --milestone m1b --only schema-compatibility
uv run --locked --no-sync modeling verify --capability numerical.root_finding
uv run --locked --no-sync modeling capability scaffold numerical.secant --destination src/modeling_capabilities --tests-destination tests/capabilities
uv run --locked --no-sync modeling evidence assemble --windows-report tests/.tmp/evidence/windows/verification-report.json --ubuntu-report tests/.tmp/evidence/ubuntu/verification-report.json --codex-transcript tests/.tmp/evidence/codex-transcript.jsonl --destination tests/.tmp/evidence/bundle
uv run --locked --no-sync modeling evidence validate --bundle tests/.tmp/evidence/bundle --source-fingerprint sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
uv run --locked --no-sync modeling-mcp --project-root tests/.tmp/manual-project
```

`modeling-mcp` 的 STDOUT 只写 MCP JSON-RPC 帧；结构化日志只写 STDERR。

---

## M1a-0 Plan — 48-Hour Feasibility Spike

M1a-0 is a mandatory go/no-go gate, not a product milestone and not a thirteenth M1a architecture task. Its clock starts before the first test command and ends only after the Codex transcript, regressions and task completion record exist. The Spike may prove protocol/host feasibility with one fixed equation, but none of its Python names, schemas or shortcuts may be promoted into `src/`; A1–A12 still build the approved production slice.

### Task M1a-0: Prove Codex → STDIO MCP → one real root-finding result

**Primary concern:** 在 48 小时内尽早消除“本地 MCP 能否启动、Codex 能否连接并收到真实数值结果”的集成风险。

**Attempt record (2026-07-22):** Attempt 1 is preserved at
`build/feasibility/m1a-0/attempt-1/closure.json` with `gate="FAIL"` and
`reason="timebox_exceeded"`. One and only one replacement, Attempt 2, is
authorized from its immutable `build/feasibility/m1a-0/attempt-2/started-at.txt`.
Attempt 2 uses `spikes/m1a_0/configure_codex.py` to materialize the checked-in
portable `codex-config.toml` template into ignored `.codex/config.toml`; it never
commits a machine-specific path or weakens `required`, timeouts, locked/no-sync
execution, or the single-tool approval configuration.

Attempt 2 adds exactly one materialization test alongside the two existing Spike
tests: `test_codex_config_materialization`, direct fixed-root execution, and the
real generic STDIO round trip. It must run the following fresh commands and keep
attempt-specific evidence at
`build/feasibility/m1a-0/attempt-2/codex-transcript.jsonl`,
`build/feasibility/m1a-0/attempt-2/timebox.json`, and
`build/feasibility/m1a-0/attempt-2/task-report.md`:

```powershell
uv lock --check
uv run --locked --no-sync pytest spikes/m1a_0/test_spike.py -q
uv run --locked --no-sync python -m compileall -q spikes/m1a_0
uv run --locked --no-sync python spikes/m1a_0/configure_codex.py
codex mcp list
$prompt = 'Use only the modeling_spike MCP server and do not run shell commands. Call root_finding exactly once with equation x*x-2, lower 0, upper 2, and tolerance 1e-10. Return the tool result without doing your own calculation.'
codex exec --ephemeral --json --sandbox read-only $prompt | Tee-Object -FilePath 'build/feasibility/m1a-0/attempt-2/codex-transcript.jsonl'
uv run --locked --no-sync python spikes/m1a_0/verify_codex_transcript.py build/feasibility/m1a-0/attempt-2/codex-transcript.jsonl
```

Only if every command and transcript verification succeeds within 172800 seconds
may Attempt 2 write `gate="PASS"`, stage only its authorized tracked files, and
make the one Spike commit. Otherwise it writes `gate="FAIL"`, records the blocker,
and stops without a commit.

**Files:**

- Track unchanged: `docs/superpowers/specs/2026-07-16-math-modeling-mcp-design.md`, `docs/superpowers/plans/2026-07-17-math-modeling-mcp-m1.md`
- Create: `.gitignore`, `.gitattributes`, `.python-version`, `pyproject.toml`, `uv.lock`
- Create: `spikes/m1a_0/README.md`, `spikes/m1a_0/server.py`, `spikes/m1a_0/test_spike.py`, `spikes/m1a_0/codex-config.toml`, `spikes/m1a_0/configure_codex.py`, `spikes/m1a_0/verify_codex_transcript.py`

**Interfaces consumed:** Python 3.11, uv 0.11.28, official MCP Python SDK `>=1.27,<2`, authenticated Codex CLI and normal trusted-project control.

**Interfaces produced:** only the disposable `solve_fixed_root`, `SpikeRootResult`, MCP `root_finding` tool and `verify_codex_transcript` interface listed above; generated evidence at `build/feasibility/m1a-0/`.

- [ ] **Step 1: Start the 48-hour clock and write the failing direct/STDIO test**

  The first action of the task is the time record; no source, test, dependency or configuration edit may precede it:

  ```powershell
  New-Item -ItemType Directory -Force -Path 'build/feasibility/m1a-0' | Out-Null
  (Get-Date).ToUniversalTime().ToString('O') | Set-Content -Encoding utf8NoBOM -NoNewline -LiteralPath 'build/feasibility/m1a-0/started-at.txt'
  ```

  Expected: `started-at.txt` contains one parseable UTC timestamp and is older than every subsequently created Spike file.

  Create `.python-version` with exactly `3.11`; create `.gitattributes` with exactly `* text=auto eol=lf`; create `.gitignore` with these entries:

  ```text
  .venv/
  .codex/
  __pycache__/
  *.py[cod]
  .pytest_cache/
  build/
  .modeling/
  ```

  Create the initial root `pyproject.toml` exactly as the non-package Spike environment:

  ```toml
  [project]
  name = "math-modeling-mcp"
  version = "0.0.0"
  requires-python = ">=3.11,<3.12"
  dependencies = ["mcp>=1.27,<2"]

  [dependency-groups]
  dev = ["pytest>=8.4,<10"]

  [tool.uv]
  required-version = "==0.11.28"
  package = false

  [tool.pytest.ini_options]
  testpaths = ["spikes/m1a_0"]
  ```

  `spikes/m1a_0/test_spike.py` must import `solve_fixed_root` and define one direct assertion plus one real generic-MCP subprocess round trip. The direct assertion uses exactly `equation="x*x-2"`, interval `[0.0, 2.0]`, tolerance `1e-10`, maximum 100 iterations and requires finite `root`, `abs(root * root - 2.0) <= 1e-9`, reported residual equal to the recomputed absolute residual, and `1 <= iterations <= 100`. The asynchronous round trip uses `StdioServerParameters(command=sys.executable, args=[str(SERVER)])`, `stdio_client`, `ClientSession.initialize()`, asserts `tools/list` returns only `root_finding`, calls it once with the same equation/bracket/tolerance, and applies the same result assertions to `CallToolResult.structuredContent`.

  Expected after authoring: no production package or server implementation exists; only the test/environment files and generated start timestamp are present.

- [ ] **Step 2: Run the tests and observe the missing Spike server**

  ```powershell
  uv lock
  uv sync --locked --group dev
  uv run --locked --no-sync pytest spikes/m1a_0/test_spike.py -q
  ```

  Expected: dependency setup succeeds, then pytest exits nonzero during collection with `ModuleNotFoundError: No module named 'server'`; the failure is caused by the absent implementation rather than authentication or network state.

- [ ] **Step 3: Implement the minimum fixed-equation server and transcript verifier**

  `spikes/m1a_0/server.py` must contain no import from `src/` and implement exactly this behavior:

  ```python
  from __future__ import annotations

  from dataclasses import asdict, dataclass
  import math
  from typing import Literal

  from mcp.server.fastmcp import FastMCP

  Equation = Literal["x*x-2"]

  @dataclass(frozen=True)
  class SpikeRootResult:
      root: float
      residual: float
      iterations: int
      equation: Equation

  def solve_fixed_root(
      equation: Equation,
      lower: float,
      upper: float,
      tolerance: float,
      max_iterations: int,
  ) -> SpikeRootResult:
      if equation != "x*x-2":
          raise ValueError("M1a-0 accepts only x*x-2")
      if not all(math.isfinite(value) for value in (lower, upper, tolerance)):
          raise ValueError("inputs must be finite")
      if lower >= upper or tolerance <= 0.0 or max_iterations != 100:
          raise ValueError("invalid M1a-0 bounds, tolerance, or iteration limit")
      f_lower = lower * lower - 2.0
      f_upper = upper * upper - 2.0
      if f_lower * f_upper > 0.0:
          raise ValueError("interval does not bracket a root")
      for iteration in range(1, max_iterations + 1):
          midpoint = lower + (upper - lower) / 2.0
          f_midpoint = midpoint * midpoint - 2.0
          if abs(f_midpoint) <= tolerance or (upper - lower) / 2.0 <= tolerance:
              return SpikeRootResult(midpoint, abs(f_midpoint), iteration, equation)
          if f_lower * f_midpoint <= 0.0:
              upper = midpoint
          else:
              lower = midpoint
              f_lower = f_midpoint
      raise RuntimeError("M1a-0 bisection did not converge")

  mcp = FastMCP("modeling-spike")

  @mcp.tool()
  def root_finding(
      equation: Equation,
      lower: float,
      upper: float,
      tolerance: float,
  ) -> dict[str, float | int | str]:
      return asdict(solve_fixed_root(equation, lower, upper, tolerance, 100))

  if __name__ == "__main__":
      mcp.run(transport="stdio")
  ```

  `spikes/m1a_0/codex-config.toml` must contain:

  ```toml
  [mcp_servers.modeling_spike]
  command = "uv"
  args = ["run", "--locked", "--no-sync", "python", "spikes/m1a_0/server.py"]
  cwd = "."
  required = true
  startup_timeout_sec = 10
  tool_timeout_sec = 30
  enabled_tools = ["root_finding"]
  ```

  `spikes/m1a_0/verify_codex_transcript.py` must expose `verify_codex_transcript(path: Path) -> SpikeTranscriptReport`. It parses every nonblank JSONL line, selects completed items whose item type is `mcp_tool_call`, requires exactly one call with server `modeling_spike` and tool `root_finding`, rejects any shell/command execution item, extracts the structured result, and independently asserts equation `x*x-2`, finite root/residual, recomputed residual equality within `1e-15`, residual at most `1e-9`, and iterations in `[1, 100]`. Its CLI accepts one transcript path, prints one JSON report, and exits 0 only on success.

  `spikes/m1a_0/README.md` records the 48-hour go/no-go rule, exact commands from this task, the non-production/no-reuse boundary, and that failure blocks A1 rather than triggering a custom MCP protocol or host-specific core abstraction.

  Initialize the single repository after the red test and before the first commit:

  ```powershell
  git init
  git branch -M main
  git status --short --branch
  ```

  Expected: the status header is `## No commits yet on main`; `.codex/` and `build/` remain ignored generated locations.

- [ ] **Step 4: Run the focused direct and real STDIO tests**

  ```powershell
  uv run --locked --no-sync pytest spikes/m1a_0/test_spike.py -q
  ```

  Expected: exactly two tests pass; the STDIO test starts a real child process, lists one tool, invokes it once and receives a finite root near `sqrt(2)` with independently recomputed residual at most `1e-9`.

- [ ] **Step 5: Connect Codex and verify one real root-finding call**

  Copy only the checked-in Spike template into ignored project-local configuration, establish normal trust manually, and run:

  ```powershell
  New-Item -ItemType Directory -Force -Path '.codex' | Out-Null
  Copy-Item -LiteralPath 'spikes/m1a_0/codex-config.toml' -Destination '.codex/config.toml' -Force
  $confirmation = Read-Host "Mark this repository trusted through Codex's normal trust control, then enter TRUSTED"
  if ($confirmation -ne 'TRUSTED') { throw 'trusted-project confirmation missing' }
  $mcpList = codex mcp list
  if ($LASTEXITCODE -ne 0 -or ($mcpList -join "`n") -notmatch 'modeling_spike') { throw 'modeling_spike MCP config was not loaded' }
  $prompt = 'Use only the modeling_spike MCP server and do not run shell commands. Call root_finding exactly once with equation x*x-2, lower 0, upper 2, and tolerance 1e-10. Return the tool result without doing your own calculation.'
  codex exec --ephemeral --json --sandbox read-only $prompt | Tee-Object -FilePath 'build/feasibility/m1a-0/codex-transcript.jsonl'
  if ($LASTEXITCODE -ne 0) { throw 'Codex M1a-0 smoke failed' }
  uv run --locked --no-sync python spikes/m1a_0/verify_codex_transcript.py build/feasibility/m1a-0/codex-transcript.jsonl
  ```

  Expected: MCP startup succeeds; Codex lists and connects to `modeling_spike`; transcript verification exits 0 and reports exactly one `root_finding` call, a finite root, residual at most `1e-9`, and no shell item.

- [ ] **Step 6: Run Spike regressions and enforce the 48-hour gate**

  ```powershell
  uv lock --check
  uv run --locked --no-sync pytest spikes/m1a_0/test_spike.py -q
  uv run --locked --no-sync python -m compileall -q spikes/m1a_0
  $startedAt = [DateTimeOffset]::Parse((Get-Content -Raw -LiteralPath 'build/feasibility/m1a-0/started-at.txt').Trim())
  $completedAt = [DateTimeOffset]::UtcNow
  $elapsed = $completedAt - $startedAt
  if ($elapsed.TotalHours -gt 48.0) { throw "M1a-0 exceeded 48 hours: $($elapsed.TotalHours)" }
  [pscustomobject]@{ started_at=$startedAt.ToString('O'); completed_at=$completedAt.ToString('O'); elapsed_seconds=[int]$elapsed.TotalSeconds; gate='PASS' } | ConvertTo-Json -Compress | Set-Content -Encoding utf8NoBOM -NoNewline -LiteralPath 'build/feasibility/m1a-0/timebox.json'
  ```

  Expected: lock check and tests exit 0, compilation reports no error, `timebox.json` records `gate="PASS"`, and elapsed seconds are at most 172800. If the time limit or any real Codex condition fails, stop the plan and report the actual failure; mocks, a direct Python call or a generic MCP client alone do not satisfy the gate.

- [ ] **Step 7: Capture diff evidence, commit, and publish the task completion record**

  ```powershell
  git add .gitignore .gitattributes .python-version pyproject.toml uv.lock spikes/m1a_0 docs/superpowers/specs/2026-07-16-math-modeling-mcp-design.md docs/superpowers/plans/2026-07-17-math-modeling-mcp-m1.md
  git status --short
  git diff --cached --stat
  git diff --cached --check
  git commit -m "spike: prove Codex MCP root-finding round trip"
  $taskCommit = (git rev-parse HEAD).Trim()
  if ($taskCommit -notmatch '^(?:[0-9a-f]{40}|[0-9a-f]{64})$') { throw 'task commit hash is not a full lowercase object ID' }
  git show --stat --oneline --no-renames $taskCommit
  git status --short
  ```

  Expected: the diff contains only the exact Files list; commit succeeds; full commit hash is printed; final status is empty because `.codex/`, `build/`, caches and the virtual environment are ignored. The handoff record reports both pytest/Codex results, the staged diff stat and the full commit hash using the four required Agent Execution Discipline fields.

**Acceptance:** within 48 hours, a real MCP child process starts, an authenticated/trusted Codex session connects, calls exactly one fixed `root_finding` tool and receives a real finite result with independently checked residual; the Spike stays outside `src/` and the wheel; test result, git diff summary and commit hash are all present. This evidence proves host/protocol feasibility only and cannot be cited as completion of A1–A12 or any stable contract.

## M1a-0 Hard Gate

**Supersession notice (2026-07-23):** 本节 Attempt 1/2 与 48 小时判定保留为历史记录，但不再授权重试。唯一现行宿主证据门是 `M1a-0R`：从 `build/feasibility/m1a-0/remediation-1/started-at.txt` 起 14,400 秒内，通用真实 STDIO 测试与一份官方 Codex CLI/Desktop/IDE 平台生成记录都必须独立通过，才允许首个基线提交和 A1。

All of the following must be true before A1 starts:

- `build/feasibility/m1a-0/remediation-1/timebox.json` validates elapsed seconds `<= 14400` and gate `PASS`, and `build/feasibility/m1a-0/remediation-1/closure.json` records the same PASS with the full baseline commit hash;
- the generic-STDIO test independently passes through the official MCP client and a real child process, and the complete Spike regression suite passes;
- `build/feasibility/m1a-0/remediation-1/evidence-manifest.json` hashes every raw host-evidence file, while `build/feasibility/m1a-0/remediation-1/host/normalized-host-evidence.json` is a verified `m1a0-host-evidence/1` record containing exactly one approved `modeling_spike/root_finding` call, exact arguments, zero shell/command calls, a finite result, equal recomputed residual and residual at most `1e-9`;
- the first repository commit has subject `spike: prove Codex-hosted MCP root-finding round trip`, and `build/feasibility/m1a-0/remediation-1/task-report.md` contains fresh RED/GREEN tests, generic STDIO and host-evidence results, staged diff/check evidence and the full commit hash;
- no Spike module is imported by, copied into or treated as an interface for the future formal packages.

Failure of any current condition blocks A1 and closes M1a-0R as failed; it does not authorize another attempt or remediation. Failure is not permission to couple the core to Codex, invent a private protocol, weaken evidence verification or widen the Spike into production architecture.

---

## M1a Plan — Functional Vertical Slice

### Work Package A-I — Repository entry and preview contracts

### Task A1: Promote the Spike environment into the locked production project and verification entry

**Primary concern:** 在不复用 Spike 代码的前提下，把唯一根环境扩为可重复构建的正式单发行物和唯一 CLI 验证入口。

**Files:**

- Modify: `.gitignore`, `pyproject.toml`, `uv.lock`
- Create: `README.md`
- Create: `src/modeling_core/__init__.py`, `src/modeling_core/version.py`
- Create: `src/modeling_cli/__init__.py`, `src/modeling_cli/__main__.py`, `src/modeling_cli/main.py`
- Create: `src/modeling_harness/__init__.py`, `src/modeling_harness/verify.py`
- Create: `tests/smoke/test_cli_entrypoints.py`, `tests/conftest.py`

**Interfaces produced:** `modeling --help`、`modeling verify --help`、`modeling-mcp` 的脚本名预留；`Milestone.M1A`/`Milestone.M1B`；`APPLICATION_VERSION="0.1.0"`。

- [ ] **Step 1: Write the failing entry-point smoke test**

  `tests/smoke/test_cli_entrypoints.py` must execute both modules and assert stable help text:

  ```python
  from pathlib import Path
  import subprocess
  import sys

  ROOT = Path(__file__).resolve().parents[2]

  def run_module(module: str, *args: str) -> subprocess.CompletedProcess[str]:
      return subprocess.run(
          [sys.executable, "-m", module, *args],
          cwd=ROOT,
          text=True,
          capture_output=True,
          check=False,
      )

  def test_modeling_help_exposes_three_m1a_commands() -> None:
      completed = run_module("modeling_cli", "--help")
      assert completed.returncode == 0
      assert "bootstrap" in completed.stdout
      assert "doctor" in completed.stdout
      assert "verify" in completed.stdout

  def test_verify_help_requires_a_milestone_for_evidence() -> None:
      completed = run_module("modeling_cli", "verify", "--help")
      assert completed.returncode == 0
      assert "--milestone {m1a,m1b}" in completed.stdout

  if __name__ == "__main__":
      test_modeling_help_exposes_three_m1a_commands()
      test_verify_help_requires_a_milestone_for_evidence()
  ```

- [ ] **Step 2: Run it and confirm the expected failure**

  Run:

  ```powershell
  python tests/smoke/test_cli_entrypoints.py
  python -m modeling_cli --help
  ```

  Expected: 第一条命令退出非零并包含 `AssertionError`；第二条命令退出非零并包含 `No module named modeling_cli`；不存在误通过。

- [ ] **Step 3: Add the minimum production package, tool configuration and CLI parser**

  Confirm the prerequisite Spike commit without modifying it:

  ```powershell
  git rev-parse --is-inside-work-tree
  git log -1 --format='%H %s'
  git status --short
  ```

  Expected: the first command prints `true`; the log names the M1a-0 Spike commit; status shows only the failing A1 test created in Step 1.

  Preserve `.gitattributes` and `.python-version` byte-for-byte. Extend `.gitignore` with `.ruff_cache/`, `.mypy_cache/`, `dist/` and wheel metadata. Replace the Spike-only root project configuration with the formal project: `pyproject.toml` must retain `requires-python = ">=3.11,<3.12"` and `[tool.uv] required-version = "==0.11.28"`, declare only Dependency Budget 中的包, package only modules under `src/`, explicitly exclude `spikes/` from both sdist and wheel, and define:

  ```toml
  [project.scripts]
  modeling = "modeling_cli.main:main"
  modeling-mcp = "modeling_mcp.__main__:main"

  [dependency-groups]
  dev = ["editables~=0.3", "mypy>=1.17,<2", "pytest>=8.4,<10", "ruff>=0.12,<1"]
  ```

  Windows/Python 3.11 非 ASCII checkout 必须启用 Hatchling
  `dev-mode-exact = true`，使 `.pth` 只包含 ASCII loader import；Hatchling
  动态生成的 loader 依赖 `editables~=0.3`，因此该包只加入 dev group，
  不加入 `[project].dependencies`。

  Configure pytest paths as `tests`, Ruff target `py311`, and mypy `strict = true` over `src`. `verify.py` must parse `m1a|m1b`, print the selected milestone on the first line, and return exit 2 with diagnostic `verification checks are not registered` until A11 registers checks. `bootstrap` and `doctor` parsers may return exit 2 with `command not implemented in this increment`; help itself must succeed.

- [ ] **Step 4: Lock, sync and run the focused test**

  Run:

  ```powershell
  uv lock
  uv sync --locked --group dev
  uv run --locked --no-sync pytest tests/smoke/test_cli_entrypoints.py -q
  ```

  Expected: lockfile is created, the environment resolves Python 3.11, and both smoke tests pass with exit 0.

- [ ] **Step 5: Run task regression gates**

  Run:

  ```powershell
  uv lock --check
  uv run --locked --no-sync ruff check src tests
  uv run --locked --no-sync mypy src
  uv run --locked --no-sync pytest tests/smoke -q
  ```

  Expected: four commands exit 0; no network access occurs in the three `uv run --locked --no-sync` commands.

- [ ] **Step 6: Commit the reviewable increment**

  ```powershell
  git add .gitignore .gitattributes .python-version pyproject.toml uv.lock README.md docs/superpowers/specs/2026-07-16-math-modeling-mcp-design.md docs/superpowers/plans/2026-07-17-math-modeling-mcp-m1.md src/modeling_core src/modeling_cli src/modeling_harness tests/conftest.py tests/smoke/test_cli_entrypoints.py
  git commit -m "build: establish locked Python project"
  ```

**Acceptance:** Fresh checkout can run `uv sync --locked --group dev`; CLI help is deterministic; dependency list contains no package outside the budget; the Spike files remain byte-identical and are absent from the built wheel; the A1 commit contains no new mathematical, SQLite or production MCP behavior and its completion record contains test result, git diff summary and commit hash.

### Task A2: Freeze strict 0.1 tool, error and stable-hash contracts

**Primary concern:** 六工具预览外壳、稳定错误和同环境可重复的统一 hash；本任务不建立 RFC 8785 完整符合性证据。

**Files:**

- Create: `src/modeling_core/contracts/__init__.py`, `src/modeling_core/contracts/versions.py`, `src/modeling_core/contracts/common.py`, `src/modeling_core/contracts/errors.py`, `src/modeling_core/contracts/tools.py`, `src/modeling_core/contracts/canonical_json.py`, `src/modeling_core/contracts/schema_catalog.py`
- Create: `src/modeling_core/contracts/schemas/tools/0.1.0/health_check.request.schema.json`, `src/modeling_core/contracts/schemas/tools/0.1.0/health_check.result.schema.json`, `src/modeling_core/contracts/schemas/tools/0.1.0/health_check.error.schema.json`
- Create: `src/modeling_core/contracts/schemas/tools/0.1.0/create_project.request.schema.json`, `src/modeling_core/contracts/schemas/tools/0.1.0/create_project.result.schema.json`, `src/modeling_core/contracts/schemas/tools/0.1.0/create_project.error.schema.json`
- Create: `src/modeling_core/contracts/schemas/tools/0.1.0/get_project_status.request.schema.json`, `src/modeling_core/contracts/schemas/tools/0.1.0/get_project_status.result.schema.json`, `src/modeling_core/contracts/schemas/tools/0.1.0/get_project_status.error.schema.json`
- Create: `src/modeling_core/contracts/schemas/tools/0.1.0/list_capabilities.request.schema.json`, `src/modeling_core/contracts/schemas/tools/0.1.0/list_capabilities.result.schema.json`, `src/modeling_core/contracts/schemas/tools/0.1.0/list_capabilities.error.schema.json`
- Create: `src/modeling_core/contracts/schemas/tools/0.1.0/run_experiment.request.schema.json`, `src/modeling_core/contracts/schemas/tools/0.1.0/run_experiment.result.schema.json`, `src/modeling_core/contracts/schemas/tools/0.1.0/run_experiment.error.schema.json`
- Create: `src/modeling_core/contracts/schemas/tools/0.1.0/validate_experiment.request.schema.json`, `src/modeling_core/contracts/schemas/tools/0.1.0/validate_experiment.result.schema.json`, `src/modeling_core/contracts/schemas/tools/0.1.0/validate_experiment.error.schema.json`
- Create: `src/modeling_core/contracts/schemas/common/0.1.0/modeling-error.schema.json`
- Create: `tests/contract/corpus/tools/0.1.0/health_check.json`, `tests/contract/corpus/tools/0.1.0/create_project.json`, `tests/contract/corpus/tools/0.1.0/get_project_status.json`, `tests/contract/corpus/tools/0.1.0/list_capabilities.json`, `tests/contract/corpus/tools/0.1.0/run_experiment.json`, `tests/contract/corpus/tools/0.1.0/validate_experiment.json`
- Create: `tests/unit/contracts/test_common_types.py`, `tests/contract/test_tool_schemas_v0.py`

**Interfaces consumed:** Pydantic 2, `jsonschema.Draft202012Validator`, `rfc8785.dumps`.

**Interfaces produced:** `VersionSet.m1a()`；严格公共 DTO；`strict_json_loads(bytes)`；`canonical_json_bytes(JsonValue)`；`sha256_json(JsonValue)`；`SchemaCatalog.load_packaged()`；`ModelingError`。

- [ ] **Step 1: Write failing strict-type and Schema corpus tests**

  The tests must enumerate these exact assertions:

  1. all lower-case UUID v4 IDs normalize and upper-case/non-v4 strings fail;
  2. Hash matches `sha256:` plus 64 lower-case hex characters;
  3. timestamps require UTC, millisecond precision and `Z`;
  4. every public model rejects unknown fields, coercion, NaN and Infinity;
  5. duplicate JSON keys, lone surrogates and invalid UTF-8 fail before DTO validation;
  6. the three fixed hashes from design §8.5 match exactly and repeated calls in a fresh Python subprocess return the same bytes/hash;
  7. all 18 tool Schema files pass Draft 2020-12 meta-validation;
  8. each corpus contains at least one valid request, valid result, valid error, unknown-field rejection and invalid-type rejection;
  9. each tool's error corpus contains only the error codes permitted by design §11.9.

  A representative fixed assertion is:

  ```python
  def test_fixed_empty_vectors() -> None:
      assert sha256_json([]) == "sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
      assert sha256_json({}) == "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
      assert canonical_json_bytes({"b": 1.0, "a": -0.0}) == b'{"a":0,"b":1}'
  ```

  These are stability smoke vectors only. No M1a test may vendor or iterate RFC Appendix B, the six upstream canonicalization corpus pairs or claim complete RFC 8785 conformance; those assets and claims belong exclusively to B2.

- [ ] **Step 2: Run tests and observe missing-contract failures**

  ```powershell
  uv run --locked --no-sync pytest tests/unit/contracts/test_common_types.py tests/contract/test_tool_schemas_v0.py -q
  ```

  Expected: collection fails with `ModuleNotFoundError: modeling_core.contracts`; exit is nonzero.

- [ ] **Step 3: Implement strict models, exact version axes and packaged Schema**

  `VersionSet.m1a()` must return these exact values: application `0.1.0`, protocol `2025-11-25`, tools/project/capability/error/result/report/canonical/root/canonical-input/residual versions from design §3.1, and database schema `1`.

  Use one strict base:

  ```python
  class StrictModel(BaseModel):
      model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
  ```

  `strict_json_loads` must use `object_pairs_hook` to reject duplicate decoded keys, `parse_constant` to reject non-finite constants, strict UTF-8 decoding, and a recursive lone-surrogate check. `canonical_json_bytes` must recursively NFC-normalize keys and strings, reject non-string keys and non-finite numbers, normalize `-0.0` to `0.0`, then call the pinned `rfc8785.dumps` primitive. `sha256_json` hashes those bytes and prepends `sha256:`. M1a verifies only the fixed/repeatability smoke contract above; using the pinned primitive is not itself a complete RFC conformance claim.

  Author all 18 schemas from design §11.2–11.9. M1a `get_project_status` has no cursor/limit; `run_experiment` accepts only `mode="new"`; result and validation responses have no Artifact fields; every nullable status field remains required where specified.

- [ ] **Step 4: Run focused tests and inspect schema IDs**

  ```powershell
  uv run --locked --no-sync pytest tests/unit/contracts/test_common_types.py tests/contract/test_tool_schemas_v0.py -q
  uv run --locked --no-sync python -c "from modeling_core.contracts.schema_catalog import SchemaCatalog; c=SchemaCatalog.load_packaged('0.1.0'); print(len(c.tool_schemas), c.fingerprint)"
  ```

  Expected: tests exit 0; second command prints `18` and one `sha256:` hash; no schema resolves from the network.

- [ ] **Step 5: Run regression and static gates**

  ```powershell
  uv run --locked --no-sync ruff check src/modeling_core tests/unit/contracts tests/contract
  uv run --locked --no-sync mypy src/modeling_core
  uv run --locked --no-sync pytest tests/smoke tests/unit/contracts tests/contract/test_tool_schemas_v0.py -q
  ```

  Expected: all commands exit 0.

- [ ] **Step 6: Commit**

  ```powershell
  git add src/modeling_core/contracts tests/unit/contracts tests/contract/test_tool_schemas_v0.py tests/contract/corpus/tools/0.1.0
  git commit -m "feat: define strict M1a public contracts"
  ```

**Acceptance:** 六工具都有独立 request/result/error Schema；Error details 是九码严格判别联合；三个固定 hash、跨新进程重复 hash、重复键、非有限数和未知字段测试通过；0.1 资产既不被宣称为兼容基线，也不被宣称为完整 RFC 8785 符合性基线。

### Work Package A-II — Core, SQLite and Built-in Capability

### Task A3: Define domain invariants, explicit ports and the Application Facade

**Primary concern:** 宿主无关稳定核心及其最小端口。

**Files:**

- Create: `src/modeling_core/domain/__init__.py`, `src/modeling_core/domain/models.py`, `src/modeling_core/domain/states.py`, `src/modeling_core/domain/transitions.py`
- Create: `src/modeling_core/ports/__init__.py`, `src/modeling_core/ports/project_store.py`, `src/modeling_core/ports/clock.py`, `src/modeling_core/ports/ids.py`
- Create: `src/modeling_core/application/__init__.py`, `src/modeling_core/application/facade.py`
- Create: `tests/fixtures/fakes.py`, `tests/unit/domain/test_state_models.py`
- Create: `tests/architecture/test_dependency_boundaries.py`

**Interfaces produced:** Exact Application Facade and Core ports listed above; immutable domain records; `validate_attempt_transition` and `validate_validation_transition`.

- [ ] **Step 1: Write failing domain and boundary tests**

  Tests must cover every legal edge from design §8.6/§8.7, reject all other edges, and assert the terminal matrix:

  - SUCCEEDED/NUMERICAL_FAILURE require exactly one ResultSnapshot payload;
  - ERRORED requires system/operational error and forbids result/report;
  - TIMED_OUT requires `deadline_exceeded`;
  - ABANDONED requires `host_cancelled` or `server_recovery`;
  - Validation outcome exists only when status is SUCCEEDED;
  - `randomness="not_used"` requires `seed is None`.

  Boundary test must parse imports under `src/modeling_core` and fail if any module imports `mcp`, `sqlite3`, `modeling_infrastructure`, `modeling_mcp` or `modeling_capabilities`; it must also reject host-name tokens `Codex`, `Claude Code` and `TRAE` in core module names, annotations, DTO fields and persisted domain-field declarations.

- [ ] **Step 2: Run and confirm failure**

  ```powershell
  uv run --locked --no-sync pytest tests/unit/domain/test_state_models.py tests/architecture/test_dependency_boundaries.py -q
  ```

  Expected: collection fails because domain modules do not exist.

- [ ] **Step 3: Implement the immutable records and six-method Protocol**

  `ApplicationFacade` must expose exactly the six signatures in “Exact Public Interfaces”; no host name appears in its types. Domain records use frozen dataclasses and validated contract value objects. `ProjectStore` contains only the explicit methods listed in this plan; no `Repository[T]`, `save(entity)` or dynamic query method is allowed.

  `FakeClock` advances only through explicit `advance(seconds)` and never sleeps. `FixedIdGenerator` consumes a supplied sequence and fails when exhausted, preventing accidental random IDs in deterministic tests.

- [ ] **Step 4: Run focused tests**

  ```powershell
  uv run --locked --no-sync pytest tests/unit/domain/test_state_models.py tests/architecture/test_dependency_boundaries.py -q
  ```

  Expected: all transition cases and import rules pass.

- [ ] **Step 5: Run regression and type consistency**

  ```powershell
  uv run --locked --no-sync mypy src/modeling_core tests/fixtures/fakes.py
  uv run --locked --no-sync pytest tests/unit/contracts tests/unit/domain tests/architecture/test_dependency_boundaries.py -q
  ```

  Expected: both commands exit 0; all six Facade annotations resolve to concrete DTO classes.

- [ ] **Step 6: Commit**

  ```powershell
  git add src/modeling_core/domain src/modeling_core/ports src/modeling_core/application tests/fixtures/fakes.py tests/unit/domain tests/architecture/test_dependency_boundaries.py
  git commit -m "feat: define host-independent core boundaries"
  ```

**Acceptance:** Core imports no adapter, database or capability implementation; status/output invariants are executable; every port has a current caller and concrete implementation named in the abstraction budget.

### Task A4: Implement atomic storage bootstrap and SQLite schema 1

**Primary concern:** Project 生命周期、单写入锁与基础可追踪持久化。

**Files:**

- Create: `src/modeling_infrastructure/__init__.py`, `src/modeling_infrastructure/project_paths.py`, `src/modeling_infrastructure/project_lock.py`, `src/modeling_infrastructure/storage.py`
- Create: `src/modeling_infrastructure/sqlite/__init__.py`, `src/modeling_infrastructure/sqlite/schema_v1.sql`, `src/modeling_infrastructure/sqlite/store.py`
- Create: `src/modeling_core/contracts/schemas/common/0.1.0/modeling-project.schema.json`
- Modify: `pyproject.toml`, `src/modeling_cli/main.py`
- Create: `tests/contract/test_project_store.py`, `tests/integration/test_bootstrap_sqlite.py`

**Interfaces consumed:** `ProjectStore`, `Clock`, `IdGenerator`, `VersionSet.m1a()`.

**Interfaces produced:** `bootstrap_storage(project_root: Path, versions: VersionSet) -> StorageMetadata`；`SQLiteProjectStore`；CLI `bootstrap`。A4 production composition passes `VersionSet.m1a()` explicitly; no default “latest” version exists.

- [ ] **Step 1: Write failing real-disk tests**

  Required cases:

  1. UNINITIALIZED bootstrap creates only `.modeling/project.json`, `state.sqlite3`, `project.lock` and returns STORAGE_READY;
  2. repeated bootstrap returns the same `storage_instance_id` and changes no bytes;
  3. no Project row exists before `create_project`;
  4. `foreign_keys=ON`, `journal_mode=WAL`, `synchronous=FULL`, `busy_timeout=250`, `user_version=1`;
  5. every minimum M1a table and foreign key in design §8.4 exists;
  6. higher `user_version` and mismatched project metadata fail closed without overwrite;
  7. a `.modeling` symlink/junction/reparse point is rejected;
  8. two writers cannot hold `project.lock`; loser receives retryable `CONFLICT/project_busy`;
  9. initialization leaves no referenced partial directory when atomic publish loses a race;
  10. original non-`.modeling` files remain byte-identical.

- [ ] **Step 2: Run and observe failure**

  ```powershell
  uv run --locked --no-sync pytest tests/contract/test_project_store.py tests/integration/test_bootstrap_sqlite.py -q
  ```

  Expected: collection fails with missing `modeling_infrastructure`.

- [ ] **Step 3: Implement schema and atomic bootstrap**

  Add `src/modeling_infrastructure` to Hatchling's explicit wheel package list in `pyproject.toml`. After the directory exists, run the one permitted `uv sync --locked --group dev` editable-install refresh before the prescribed `--no-sync` GREEN gates. `uv.lock` and all dependency declarations must remain byte-identical; generated editable-loader or `PYTHONPATH` hacks are prohibited.

  `schema_v1.sql` must create `metadata`, `projects`, `experiments`, `attempts`, `result_snapshots`, `validations`, and `idempotency_records` with foreign keys and unique `(scope_id, tool_name, operation_id)`. JSON payload columns are UTF-8 text; all entity IDs and hashes have CHECK constraints for length/prefix; timestamps remain RFC 3339 text.

  Bootstrap sequence is exact:

  ```text
  validate bound root and absence of reparse points
  -> create sibling .modeling.tmp.{uuid4}
  -> create project.lock, project.json and schema-1 SQLite database there
  -> fsync each file and the temporary directory where supported
  -> atomically rename the directory to .modeling
  -> reopen and verify project.json plus PRAGMA user_version
  ```

  Do not create `staging/`, `artifacts/`, Project domain rows or a migration framework. `project.json` contains only project format, canonicalization version and storage_instance_id, never an absolute path.

- [ ] **Step 4: Implement the bootstrap CLI and run focused tests**

  ```powershell
  uv run --locked --no-sync pytest tests/contract/test_project_store.py tests/integration/test_bootstrap_sqlite.py -q
  if (Test-Path -LiteralPath tests/.tmp/manual-project) { throw 'manual project already exists; inspect it instead of overwriting it' }
  New-Item -ItemType Directory -Path tests/.tmp/manual-project | Out-Null
  uv run --locked --no-sync modeling bootstrap --project-root tests/.tmp/manual-project
  uv run --locked --no-sync modeling bootstrap --project-root tests/.tmp/manual-project
  ```

  Expected: tests pass; first CLI call reports `STORAGE_READY` and `created=true`; second reports the same storage ID and `created=false`; both exit 0.

- [ ] **Step 5: Run storage regressions**

  ```powershell
  uv run --locked --no-sync ruff check src/modeling_infrastructure src/modeling_cli tests/contract/test_project_store.py tests/integration/test_bootstrap_sqlite.py
  uv run --locked --no-sync mypy src/modeling_infrastructure src/modeling_cli
  uv run --locked --no-sync pytest tests/unit/domain tests/contract/test_project_store.py tests/integration/test_bootstrap_sqlite.py -q
  ```

  Expected: all commands exit 0; tests use real disk and no long sleeps.

- [ ] **Step 6: Commit**

  ```powershell
  git add pyproject.toml src/modeling_infrastructure src/modeling_cli/main.py src/modeling_core/contracts/schemas/common/0.1.0/modeling-project.schema.json tests/contract/test_project_store.py tests/integration/test_bootstrap_sqlite.py
  git commit -m "feat: add atomic SQLite project storage"
  ```

**Acceptance:** Bootstrap is idempotent and atomic, state is STORAGE_READY without a Project row, SQLite pragmas and schema version are verified, unknown/corrupt state is never overwritten, and M1a creates no Artifact abstraction or directories.

### Task A5: Implement the sealed explicit Built-in Capability registry

**Primary concern:** 内置能力与 validator 的统一、确定性、无动态发现注册契约。

**Files:**

- Create: `src/modeling_core/contracts/capability.py`, `src/modeling_core/registry.py`
- Create: `src/modeling_capabilities/__init__.py`
- Create: `src/modeling_core/contracts/schemas/common/0.1.0/modeling-capability.schema.json`, `src/modeling_core/contracts/schemas/common/0.1.0/modeling-validator.schema.json`
- Create: `tests/unit/test_registry.py`, `tests/contract/test_capability_schemas_v0.py`

**Interfaces consumed:** `SchemaCatalog`, `VersionSet.m1a()`, canonical JSON hashing.

**Interfaces produced:** `BuiltInCapability`, `CapabilityValidator`, descriptors, contexts and `CapabilityRegistry` listed above.

- [ ] **Step 1: Write failing registry and descriptor tests**

  Tests must prove:

  - a capability and compatible validator can be registered before sealing;
  - duplicate capability key, duplicate validator/policy key and duplicate implementation identity fail with `CONFLICT/duplicate_registration`;
  - incompatible Capability API or validator contract range fails with `UNSUPPORTED_VERSION`;
  - missing required `numerical.root_finding/0.1.0` prevents seal;
  - sealing validates every referenced Schema and its declared hash;
  - after seal, registration fails and list/resolve ordering is deterministic;
  - exact resolve never chooses a latest version;
  - fingerprint is SHA-256 of the ordered, versioned, hash-bearing descriptor projection;
  - M1a artifact roles are an empty tuple.

- [ ] **Step 2: Run and confirm missing registry**

  ```powershell
  uv run --locked --no-sync pytest tests/unit/test_registry.py tests/contract/test_capability_schemas_v0.py -q
  ```

  Expected: collection fails because `modeling_core.registry` and capability contract types are absent.

- [ ] **Step 3: Implement only explicit registration and sealing**

  `CapabilityDescriptor` must carry every field in design §9.2, including separate API/contract/implementation axes, four capability Schema references and hashes, limits, determinism/randomness, validator summaries and `context_ref`. `ValidatorDescriptor` must carry supported capability versions, implementation identity, policy/report Schema versions and hashes.

  Registry storage is two dictionaries keyed by exact immutable keys. `seal()` validates, sorts, fingerprints and flips one boolean. No filesystem, Python entry point, module-name import, package install or External Plugin type is added.

- [ ] **Step 4: Run focused tests**

  ```powershell
  uv run --locked --no-sync pytest tests/unit/test_registry.py tests/contract/test_capability_schemas_v0.py -q
  ```

  Expected: all explicit registration, failure and fingerprint cases pass.

- [ ] **Step 5: Run core regressions**

  ```powershell
  uv run --locked --no-sync mypy src/modeling_core src/modeling_capabilities
  uv run --locked --no-sync pytest tests/unit/contracts tests/unit/domain tests/unit/test_registry.py tests/contract/test_capability_schemas_v0.py tests/architecture/test_dependency_boundaries.py -q
  ```

  Expected: exit 0; architecture test confirms core does not import the concrete capability package.

- [ ] **Step 6: Commit**

  ```powershell
  git add src/modeling_core/contracts/capability.py src/modeling_core/contracts/schemas/common/0.1.0/modeling-capability.schema.json src/modeling_core/contracts/schemas/common/0.1.0/modeling-validator.schema.json src/modeling_core/registry.py src/modeling_capabilities/__init__.py tests/unit/test_registry.py tests/contract/test_capability_schemas_v0.py
  git commit -m "feat: add sealed built-in capability registry"
  ```

**Acceptance:** Registry is sealed before use, all versions and Schema hashes are captured, duplicate/ambiguous states fail, and production registration is explicit code only.

### Task A6: Parse math-expr-v1 and create canonical root-finding input

**Primary concern:** 不可信表达式安全边界与语义等价输入的唯一规范形式。

**Files:**

- Create: `src/modeling_capabilities/root_finding/__init__.py`, `src/modeling_capabilities/root_finding/contracts.py`, `src/modeling_capabilities/root_finding/context.md`
- Create: `src/modeling_capabilities/root_finding/expression/__init__.py`, `src/modeling_capabilities/root_finding/expression/syntax.py`, `src/modeling_capabilities/root_finding/expression/solver_evaluator.py`, `src/modeling_capabilities/root_finding/expression/validator_evaluator.py`
- Create: `src/modeling_capabilities/root_finding/schemas/0.1.0/input.schema.json`, `src/modeling_capabilities/root_finding/schemas/0.1.0/canonical-input.schema.json`
- Create: `tests/unit/expression/test_syntax.py`, `tests/unit/expression/test_canonicalization.py`
- Create: `tests/contract/corpus/root-finding/0.1.0.json`

**Interfaces produced:**

```text
parse_expression(source: str, limits: ExpressionLimits) -> ExpressionAst
ast_to_canonical_json(ast: ExpressionAst) -> JsonObject
SolverEvaluator.evaluate(ast: ExpressionAst, x: float, budget: EvaluationBudget) -> float
ValidatorEvaluator.evaluate(ast: ExpressionAst, x: float, budget: EvaluationBudget) -> float
normalize_root_finding_input(raw_payload: JsonObject) -> CanonicalInputRecord
```

- [ ] **Step 1: Write failing syntax, security and canonicalization tests**

  Exact accepted syntax: `x`, finite literals, `pi`, `e`, `+ - * / **`, parentheses, unary signs, and one-argument `abs sqrt exp log sin cos tan`.

  Exact rejection classes: implicit multiplication; attributes; subscripts; imports; lambdas; comprehensions; assignment; comma; strings; unknown variables/functions/operators; variable or compound exponent; exponent outside `[-1024,1024]`; 4097 UTF-8 bytes; 65-character literal; 257 AST nodes; depth 33.

  Canonical tests must assert:

  - `" x * x - 2 "` and `"x*x-2"` produce identical AST bytes and hashes;
  - omitted tolerances/max_iterations equal explicit `1e-10,1e-10,1e-10,100`;
  - `-0.0` becomes numeric zero and NFC-equivalent strings hash equally;
  - integer Schema values stay integers; number values are finite binary64;
  - canonical root has exactly the eight fields listed in design §8.5.

- [ ] **Step 2: Run and observe failure**

  ```powershell
  uv run --locked --no-sync pytest tests/unit/expression/test_syntax.py tests/unit/expression/test_canonicalization.py -q
  ```

  Expected: collection fails because root-finding expression modules do not exist.

- [ ] **Step 3: Implement tokenizer, Pratt parser and immutable AST**

  Do not call `eval`, `exec`, `compile` or Python AST evaluation. Tokenizer counts UTF-8 bytes and literal characters before float conversion. Pratt parser emits only the six node kinds and fixed fields from design §8.5, preserves operand order, folds a direct unary sign into a number node, and does no algebraic simplification.

  Both evaluator classes traverse the shared immutable AST but contain separate numerical dispatch functions. Every node checks cancellation/deadline; every top-level evaluation consumes one of at most 20,000 evaluations. `pi` and `e` are constructed from the exact hex values in design §10.2.

- [ ] **Step 4: Implement strict input normalization and schemas**

  Validate raw shape first, materialize defaults, parse expression, check `upper>lower`, tolerance ranges and max iterations, replace expression text with canonical AST, set `canonical_input_schema_version`, compute canonical/model/empty-data hashes, and return a frozen `CanonicalInputRecord`. Preserve no raw expression text in that record.

- [ ] **Step 5: Run focused tests**

  ```powershell
  uv run --locked --no-sync pytest tests/unit/expression/test_syntax.py tests/unit/expression/test_canonicalization.py tests/contract/test_capability_schemas_v0.py -q
  ```

  Expected: all grammar/limit/Schema tests pass; expression whitespace and default materialization produce stable hashes matching repeat executions. This remains a semantic stability smoke, not an RFC corpus run.

- [ ] **Step 6: Run security and independence regressions**

  ```powershell
  uv run --locked --no-sync ruff check src/modeling_capabilities/root_finding tests/unit/expression
  uv run --locked --no-sync mypy src/modeling_capabilities/root_finding
  uv run --locked --no-sync pytest tests/unit/contracts tests/unit/expression tests/contract/test_capability_schemas_v0.py -q
  ```

  Expected: exit 0; a source search in the test confirms no forbidden dynamic evaluation call appears.

- [ ] **Step 7: Commit**

  ```powershell
  git add src/modeling_capabilities/root_finding tests/unit/expression tests/contract/corpus/root-finding/0.1.0.json tests/contract/test_capability_schemas_v0.py
  git commit -m "feat: add safe canonical math expression input"
  ```

**Acceptance:** All expression limits fail before Attempt creation, semantic whitespace/default equivalence hashes identically, the two evaluators share only syntax/AST types, and raw formatting is not persisted.

### Task A7: Implement the deterministic bisection Built-in Capability

**Primary concern:** 一个真实执行、版本化、可验证的数值能力。

**Files:**

- Create: `src/modeling_capabilities/root_finding/solver.py`, `src/modeling_capabilities/root_finding/descriptor.py`
- Create: `src/modeling_capabilities/root_finding/schemas/0.1.0/success-data.schema.json`, `src/modeling_capabilities/root_finding/schemas/0.1.0/failure-data.schema.json`, `src/modeling_core/contracts/schemas/common/0.1.0/modeling-result.schema.json`
- Create: `tests/unit/root_finding/test_solver.py`, `tests/math/test_root_finding_metamorphic.py`
- Modify: `tests/contract/test_capability_schemas_v0.py`

**Interfaces consumed:** `CanonicalInputRecord`, `ExecutionContext`, `SolverEvaluator`.

**Interfaces produced:** `BisectionRootFindingCapability` with ID `numerical.root_finding`, contract `0.1.0`, implementation `builtin.numerical.root_finding.bisection/0.1.0`.

- [ ] **Step 1: Write failing solver cases**

  Required exact cases:

  - `x*x-2` on `[0,2]` succeeds, residual `<=1e-10`, root error `<=1e-8`;
  - lower endpoint root and upper endpoint root return `endpoint_root` in lower-then-upper priority;
  - `x*x+1` on `[-1,1]` returns `NUMERICAL_FAILURE/no_sign_change`;
  - `1/x` over a path that evaluates at zero returns `domain_error`;
  - overflow/non-finite intermediate returns `non_finite_evaluation`;
  - max_iterations exhaustion and midpoint collapse return `non_convergence`;
  - residual is checked before interval tolerance;
  - `monotonic_now >= deadline` yields TIMED_OUT and no result payload;
  - iterations and evaluations obey the exact counting rules;
  - result data has no extra keys and all numbers are finite.

- [ ] **Step 2: Run and confirm missing solver**

  ```powershell
  uv run --locked --no-sync pytest tests/unit/root_finding/test_solver.py tests/math/test_root_finding_metamorphic.py -q
  ```

  Expected: collection fails because `solver.py` is absent.

- [ ] **Step 3: Implement the minimum bisection algorithm**

  Implement the exact order from design §10.3. Sign comparison uses `math.copysign`, never multiplication. Opposite-sign coordinate midpoint and half-width use `lower/2 + upper/2` and `upper/2 - lower/2`; same-sign coordinates use `lower + (upper-lower)/2` and `(upper-lower)/2`. Check deadline/cancellation before every AST node, evaluation, loop and final return.

  `execute` returns only `ExecutionOutcome.success(ResultPayload)` or `ExecutionOutcome.numerical_failure(ResultPayload)`; pre-execution contract errors are already rejected by normalization, and unexpected internal exceptions are left for Application orchestration to map to ERRORED.

- [ ] **Step 4: Add fixed descriptors and strict result schemas**

  Success data fields are exactly `root,function_value,iterations,evaluations,termination_reason`; failure data fields exactly `failure_code,iterations,evaluations`. Descriptor defaults are timeout 10000 ms, iterations 100, evaluations 20000; maxima 60000, 10000, 20000; randomness is `not_used`; artifact roles are empty.

- [ ] **Step 5: Run focused and metamorphic tests**

  ```powershell
  uv run --locked --no-sync pytest tests/unit/root_finding/test_solver.py tests/math/test_root_finding_metamorphic.py tests/contract/test_capability_schemas_v0.py -q
  ```

  Expected: internal root, endpoints, four failure types, deadline, translation, nonzero scale, sign flip and narrowed bracket pass using contract tolerances.

- [ ] **Step 6: Run regression**

  ```powershell
  uv run --locked --no-sync mypy src/modeling_capabilities/root_finding
  uv run --locked --no-sync pytest tests/unit/expression tests/unit/root_finding/test_solver.py tests/math/test_root_finding_metamorphic.py tests/contract/test_capability_schemas_v0.py -q
  ```

  Expected: exit 0; no test asserts a fixed iteration count.

- [ ] **Step 7: Commit**

  ```powershell
  git add src/modeling_capabilities/root_finding/solver.py src/modeling_capabilities/root_finding/descriptor.py src/modeling_capabilities/root_finding/schemas/0.1.0/success-data.schema.json src/modeling_capabilities/root_finding/schemas/0.1.0/failure-data.schema.json src/modeling_core/contracts/schemas/common/0.1.0/modeling-result.schema.json tests/unit/root_finding/test_solver.py tests/math/test_root_finding_metamorphic.py tests/contract/test_capability_schemas_v0.py
  git commit -m "feat: execute bisection root finding"
  ```

**Acceptance:** All numerical values come from actual evaluation, expected math failures are versioned payloads, overflow-safe formulas and cooperative deadlines are exercised, and the descriptor is resolvable only by exact ID/version.

### Task A8: Implement the independent residual validator

**Primary concern:** 求解器之外独立重算、独立判定、可追踪报告。

**Files:**

- Create: `src/modeling_capabilities/root_finding/validator.py`
- Create: `src/modeling_capabilities/root_finding/schemas/0.1.0/policy.schema.json`, `src/modeling_capabilities/root_finding/schemas/0.1.0/report.schema.json`, `src/modeling_core/contracts/schemas/common/0.1.0/modeling-validation-report.schema.json`
- Modify: `src/modeling_capabilities/root_finding/descriptor.py`
- Create: `tests/fixtures/forged_results.py`, `tests/unit/root_finding/test_validator.py`
- Create: `tests/architecture/test_solver_validator_independence.py`

**Interfaces consumed:** `ValidatorEvaluator`, committed `ResultSnapshotView`, `ValidationContext`.

**Interfaces produced:** `ResidualRootFindingValidator` with validator ID `numerical.root_finding.residual`, implementation ID `builtin.numerical.root_finding.residual`, implementation/policy `0.1.0`.

- [ ] **Step 1: Write failing validator and architecture tests**

  Required assertions:

  - valid golden result returns PASSED and empty `failed_checks`;
  - root below/above interval adds `root_out_of_interval` first;
  - undefined/non-finite reevaluation uses null recomputed metrics and ordered failure codes;
  - forged reported function value adds `reported_value_mismatch`;
  - excessive residual adds `residual_exceeds_tolerance`;
  - hash-self-consistent forged root/value fixtures still fail mathematically;
  - interval-tolerance solver success can legitimately validate FAILED;
  - strict empty policy rejects every key;
  - validator timeout produces Validation TIMED_OUT outside the validator report path;
  - import graph allows only contracts, Schema and `expression.syntax`; it rejects `solver`, `solver_evaluator`, search, termination and result construction imports.

- [ ] **Step 2: Run and observe failure**

  ```powershell
  uv run --locked --no-sync pytest tests/unit/root_finding/test_validator.py tests/architecture/test_solver_validator_independence.py -q
  ```

  Expected: missing validator module causes nonzero collection failure.

- [ ] **Step 3: Implement independent reevaluation and report construction**

  Run checks in the six-step order from design §10.5. Report metrics have exactly seven fields. `failed_checks` is an ordered enum array and outcome is PASSED only when empty; M1 returns no INCONCLUSIVE. Policy is `{}` and hashes to the fixed empty-object hash. The validator must use only `ValidatorEvaluator`; do not factor a shared numerical helper out of the two evaluator files.

- [ ] **Step 4: Run focused tests**

  ```powershell
  uv run --locked --no-sync pytest tests/unit/root_finding/test_validator.py tests/architecture/test_solver_validator_independence.py tests/contract/test_capability_schemas_v0.py -q
  ```

  Expected: all mathematical, null-metric, policy, ordering and import tests pass.

- [ ] **Step 5: Run root capability regression**

  ```powershell
  uv run --locked --no-sync ruff check src/modeling_capabilities/root_finding tests/unit/root_finding tests/architecture/test_solver_validator_independence.py
  uv run --locked --no-sync mypy src/modeling_capabilities/root_finding
  uv run --locked --no-sync pytest tests/unit/expression tests/unit/root_finding tests/math tests/architecture/test_solver_validator_independence.py -q
  ```

  Expected: all commands exit 0.

- [ ] **Step 6: Commit**

  ```powershell
  git add src/modeling_capabilities/root_finding/validator.py src/modeling_capabilities/root_finding/descriptor.py src/modeling_capabilities/root_finding/schemas/0.1.0/policy.schema.json src/modeling_capabilities/root_finding/schemas/0.1.0/report.schema.json src/modeling_core/contracts/schemas/common/0.1.0/modeling-validation-report.schema.json tests/fixtures/forged_results.py tests/unit/root_finding/test_validator.py tests/architecture/test_solver_validator_independence.py
  git commit -m "feat: add independent residual validation"
  ```

**Acceptance:** Validator cannot import solver numerical implementation, independently rereads and reevaluates a ResultSnapshot, rejects forged results, and never conflates FAILED with operational error.

### Task A9: Orchestrate project, experiment, validation and inline trace in the Facade

**Primary concern:** 从宿主无关用例到 SQLite 的完整 M1a 状态和幂等事务。

**Files:**

- Create: `src/modeling_core/application/idempotency.py`, `src/modeling_core/application/service.py`
- Create: `src/modeling_infrastructure/environment.py`
- Modify: `src/modeling_infrastructure/sqlite/store.py`
- Create: `tests/integration/test_application_workflow.py`, `tests/reproducibility/test_m1a_repeatability.py`

**Interfaces consumed:** all six Facade DTOs, sealed registry, ProjectStore, Clock, IdGenerator, root solver/validator.

**Interfaces produced:** concrete `ModelingApplication` implementing every Facade method.

- [ ] **Step 1: Write failing direct-Facade workflow tests**

  Test one fresh project through:

  ```text
  health UNINITIALIZED -> create project -> health READY -> status summary
  -> list summary/contract -> run x*x-2 -> validate residual -> status experiment trace
  ```

  Assert exact M1a relations and payload/hash fields from design §8.4/§16.4. Add tests for no-sign-change, invalid expression before Attempt, completed replay returning the same IDs with `replayed=true`, same key/different request mismatch, existing IN_PROGRESS conflict, concurrent write `project_busy`, cooperative timeout, unexpected solver error -> Attempt ERRORED, and expected-result three-way hash mismatch creating no Validation.

  Repeatability test executes two distinct new experiments in one Session and compares classification, all versions, canonical/model/data hashes and root within declared tolerance.

- [ ] **Step 2: Run and observe missing concrete Facade**

  ```powershell
  uv run --locked --no-sync pytest tests/integration/test_application_workflow.py tests/reproducibility/test_m1a_repeatability.py -q
  ```

  Expected: collection fails because `ModelingApplication` is not defined.

- [ ] **Step 3: Implement create/read/list use cases and one nonblocking write gate**

  `health_check`, `get_project_status` and `list_capabilities` read only committed state. `create_project` materializes display name after locking and commits Project plus COMPLETED idempotency record atomically. A single `threading.Lock.acquire(blocking=False)` admission gate guards all three write tools; a losing different operation returns retryable `CONFLICT/project_busy` without an entity.

- [ ] **Step 4: Implement run and validate short-transaction orchestration**

  Run order must match design §8.10. M1a first transaction creates IN_PROGRESS + Experiment + Attempt(PENDING); status moves to RUNNING before real execution; final transaction writes inline canonical Result payload, hash, Attempt terminal state, response references and COMPLETED. Validation rereads committed input/result, verifies the three hashes, creates PENDING/RUNNING, runs the independent validator, then atomically writes inline report/hash/outcome and COMPLETED.

  Capture environment only from the allowlist. Set `randomness="not_used"`, `seed=None`, Session UUID, warnings list, all version axes and schema hashes. If startup finds PENDING/RUNNING/IN_PROGRESS, report DEGRADED and refuse writes; do not recover in M1a.

- [ ] **Step 5: Run focused integration tests**

  ```powershell
  uv run --locked --no-sync pytest tests/integration/test_application_workflow.py tests/reproducibility/test_m1a_repeatability.py -q
  ```

  Expected: golden direct workflow, math failure, pre-record rejection, terminal errors, timeout, replay/conflict and repeatability pass.

- [ ] **Step 6: Run all core/capability/storage regressions**

  ```powershell
  uv run --locked --no-sync mypy src
  uv run --locked --no-sync pytest tests/unit tests/contract tests/integration/test_bootstrap_sqlite.py tests/integration/test_application_workflow.py tests/math tests/reproducibility/test_m1a_repeatability.py tests/architecture -q
  ```

  Expected: exit 0; no test leaves a PENDING/RUNNING row unless it is an explicit degraded-state fixture.

- [ ] **Step 7: Commit**

  ```powershell
  git add src/modeling_core/application src/modeling_infrastructure/environment.py src/modeling_infrastructure/sqlite/store.py tests/integration/test_application_workflow.py tests/reproducibility/test_m1a_repeatability.py
  git commit -m "feat: orchestrate traceable M1a experiments"
  ```

**Acceptance:** Direct core use completes the full golden chain, M1a inline trace is reconstructable, completed idempotency is atomic, no math runs inside a database transaction, and the core remains host-independent.

### Work Package A-III — STDIO adapter and golden chain

### Task A10: Expose exactly six tools through strict low-level STDIO MCP

**Primary concern:** 薄协议适配、真实 MCP 会话和 STDOUT 纯净性。

**Files:**

- Create: `src/modeling_bootstrap/__init__.py`, `src/modeling_bootstrap/composition.py`
- Create: `src/modeling_mcp/__init__.py`, `src/modeling_mcp/strict_stdio.py`, `src/modeling_mcp/adapter.py`, `src/modeling_mcp/server.py`, `src/modeling_mcp/__main__.py`
- Modify: `src/modeling_core/application/service.py`, `src/modeling_infrastructure/project_lock.py`, `src/modeling_infrastructure/sqlite/store.py`
- Create: `tests/contract/test_mcp_adapter.py`, `tests/architecture/test_composition_root.py`, `tests/integration/test_mcp_lifecycle.py`
- Modify: `pyproject.toml` to add `src/modeling_mcp` and `src/modeling_bootstrap` to the Hatch wheel package list and preserve the existing `modeling-mcp` entry point; modify `uv.lock` only if the already declared MCP dependency resolves differently; no new dependency is allowed

**Interfaces consumed:** `ApplicationFacade`, packaged tool schemas, official MCP SDK low-level `Server`, `Tool`, `CallToolResult` and protocol types.

**Interfaces produced:** STDIO process `modeling-mcp --project-root tests/.tmp/manual-project`; six MCP tool names and no Prompt/Resource/Sampling/Elicitation surface.

- [ ] **Step 1: Write failing adapter and composition tests**

  Assert:

  - `tools/list` names are exactly the six approved names in that order;
  - each Tool input/output Schema equals the packaged request/success Schema semantically;
  - valid calls invoke the matching Facade method once;
  - `ModelingError` becomes `CallToolResult(isError=True)` whose structured content is exactly ErrorResponse;
  - normal terminal states, NUMERICAL_FAILURE and validation FAILED use `isError=False`;
  - response structured content is independently validated before return and limited to 262144 UTF-8 bytes;
  - composition root registers exactly root solver and residual validator, seals registry, and supplies the only concrete store;
  - no concrete imports occur outside `modeling_bootstrap` except tests.
  - `uv run --locked --no-sync` imports both new packages without a `PYTHONPATH` override, and the built wheel contains both packages;
  - constructing or starting on a true `UNINITIALIZED` root is byte-for-byte side-effect free; health reports `UNINITIALIZED`, `OK`, and `ready_for_project_creation=true`;
  - first create atomically bootstraps, acquires the published winner's `project.lock`, then re-inspects state before any SQLite mutation; the lock remains held until server lifespan exit and is acquirable afterward;
  - existing `STORAGE_READY` and `READY` storage obtains a nonblocking OS writer lease before readiness, while a contending process receives retryable `CONFLICT/project_busy` without a Project or idempotency row;
  - two independent processes racing first create leave one complete storage instance, one Project and one create idempotency record, with no referenced loser temporary directory;
  - a publish-to-lock handoff interleaving cannot open a transaction or create duplicate rows when the competing process acquires the published lock first;
  - every create, run and validate mutation holds `ProjectLock`; failed acquisition opens no transaction; normal shutdown, cancellation and adapter errors release only a held lease;
  - health asserts the four-state truth table: `ready_for_project_creation` is true only for `UNINITIALIZED` and `STORAGE_READY`, and false for `READY` and `DEGRADED`.

- [ ] **Step 2: Run and observe failure**

  ```powershell
  uv run --locked --no-sync pytest tests/contract/test_mcp_adapter.py tests/architecture/test_composition_root.py -q
  ```

  Expected: collection fails because MCP and bootstrap packages do not exist.

- [ ] **Step 3: Implement a strict STDIO boundary around the pinned SDK**

  Mirror only the pinned SDK 1.x stdio stream contract in `strict_stdio.py`. Read one newline-delimited frame as bytes; reject BOM, invalid UTF-8, requests above 1048576 bytes, duplicate keys, lone surrogates and NaN/Infinity before constructing `JSONRPCMessage`; write `model_dump_json(by_alias=True, exclude_none=True)` plus one newline. All diagnostics use `logging.StreamHandler(sys.stderr)`.

  The public coroutine is:

  ```text
  strict_stdio_server(max_request_bytes: int = 1048576)
    -> async context manager of SDK receive/send streams
  ```

  Pinning test must import every SDK class used so an incompatible lock update fails immediately.

- [ ] **Step 4: Implement low-level tool registration and error mapping**

  `adapter.py` constructs six `mcp.types.Tool` objects using packaged input/output Schema. A single dispatch dictionary maps names to six typed conversion functions. It validates arguments against the request Schema, builds the strict DTO, calls the Facade, validates the result Schema, checks inline size, then returns `CallToolResult` with both machine structured content and one short JSON TextContent compatibility block. Errors use the tool-specific error Schema and no success fields.

  `server.py` declares application `0.1.0`, protocol negotiation `2025-11-25`, and only tool capabilities. `composition.py` is the sole concrete assembly location and performs registry seal before the server reports ready.

  Writer-lease lifecycle is concrete infrastructure behavior, not an adapter or core port: process construction leaves a true `UNINITIALIZED` root untouched. For existing storage, composition starts one nonblocking OS writer lease before readiness and re-inspects the held storage; it retains the lease for the server lifetime and releases it in the lifespan `finally` path. On first create, the application admission gate remains the same-process gate, then the store atomically bootstraps lock-free, acquires the published winner's `project.lock`, re-inspects state, and only then opens the Project SQLite transaction. A cross-process lease conflict returns retryable `CONFLICT/project_busy` with no entity or idempotency row. SQLite remains defense in depth under the lease.

- [ ] **Step 5: Run focused tests and process help**

  ```powershell
  uv run --locked --no-sync pytest tests/contract/test_mcp_adapter.py tests/architecture/test_composition_root.py tests/integration/test_mcp_lifecycle.py -q
  uv run --locked --no-sync modeling-mcp --help
  ```

  Expected: tests pass; help lists only `--project-root`; help goes to stdout only because the MCP session has not started.

- [ ] **Step 6: Run architecture and contract regressions**

  ```powershell
  uv run --locked --no-sync ruff check src/modeling_mcp src/modeling_bootstrap src/modeling_core/application/service.py src/modeling_infrastructure/project_lock.py src/modeling_infrastructure/sqlite/store.py tests/contract/test_mcp_adapter.py tests/architecture tests/integration/test_mcp_lifecycle.py
  uv run --locked --no-sync mypy src
  uv run --locked --no-sync pytest tests/contract tests/architecture tests/integration/test_application_workflow.py tests/integration/test_mcp_lifecycle.py -q
  ```

  Expected: exit 0; no host brand appears under `src/modeling_core`.

- [ ] **Step 7: Commit**

  ```powershell
  git add pyproject.toml uv.lock src/modeling_bootstrap src/modeling_mcp src/modeling_core/application/service.py src/modeling_infrastructure/project_lock.py src/modeling_infrastructure/sqlite/store.py tests/contract/test_mcp_adapter.py tests/architecture/test_composition_root.py tests/integration/test_mcp_lifecycle.py
  git commit -m "feat: expose six tools over strict STDIO MCP"
  ```

**Acceptance:** MCP layer has no numerical algorithm or SQLite call, both new packages import and ship through the normal locked Hatch/uv environment without `PYTHONPATH`, only six tools are advertised, malformed raw JSON is rejected before use, and STDOUT after session start can contain only protocol frames. Server construction is side-effect free for a true `UNINITIALIZED` root; existing storage is writer-leased before readiness, first create publishes storage atomically then acquires and re-inspects under the published winner's lease before any SQLite mutation, and the lease is released in `finally` on normal or error shutdown. Cross-process contention is retryable `CONFLICT/project_busy` without a Project or idempotency row; application admission remains the same-process gate and SQLite remains defense in depth.

### Task A11: Prove the real STDIO golden chain and assemble the M1a test harness

**Primary concern:** 真实进程端到端证据和单一自动验证编排。

**2026-08-09 preflight closure:** A10 parent remediation is closed by
`1cc7a8d8853d737beef42532de9863742eca7399`; the official-client offline
Schema correction is closed by `d879bc8e909953cc45a55adc3b344dedc15ae967`;
and the whole-tree Ruff formatting baseline is closed by
`7ff1419eac4c79ccfcf48c17095e6934a40aab27`. A11 must resolve the uv
executable only from `os.environ["UV"]`, require an absolute existing regular
file, run `--version`, and require exactly uv `0.11.28`. It must never resolve
uv through PATH or `shutil.which`. Every Harness subprocess receives an
explicit environment containing `UV_OFFLINE=1`; every MCP
`StdioServerParameters` receives `env={"UV_OFFLINE": "1"}` so the pinned SDK
can merge it with its safe platform environment.

**Files:**

- Create: `tests/integration/test_stdio_golden_m1a.py`, `tests/security/test_m1a_boundaries.py`
- Modify: `tests/architecture/test_dependency_boundaries.py`, `tests/architecture/test_composition_root.py`, `tests/architecture/test_solver_validator_independence.py`, `tests/reproducibility/test_m1a_repeatability.py`
- Modify: `src/modeling_harness/verify.py`
- Create: `src/modeling_harness/evidence.py`

**Interfaces consumed:** official generic MCP `ClientSession` and `stdio_client`; all M1a tests.

**Interfaces produced:** M1a check registry and atomic evidence output at `build/verification/m1a/{source_fingerprint_hex}/`, where the final component is the computed 64-character lowercase hex digest.

- [ ] **Step 1: Write the failing real-subprocess golden test**

  The test must validate the absolute uv executable from `os.environ["UV"]`
  as specified above, then construct `StdioServerParameters` with that path as
  `command`, arguments `run --locked --no-sync modeling-mcp --project-root`
  followed by `str(tmp_path / "stdio-golden-project")`, repository root as
  `cwd`, and `env={"UV_OFFLINE": "1"}`. It then executes this exact sequence:

  ```text
  initialize
  -> tools/list
  -> health_check UNINITIALIZED
  -> create_project
  -> health_check READY
  -> get_project_status summary
  -> list_capabilities summary and exact contract
  -> run_experiment x*x-2
  -> validate_experiment residual
  -> get_project_status experiment and reconstruct trace
  ```

  Add separate calls for `x*x+1`, forbidden expression, completed replay and idempotency mismatch. Capture child stdout at the MCP parser boundary and child stderr separately. Assert no BOM, prompt, logging line or non-frame byte reaches stdout; close session, both pipes and process; on Windows assert the process handle becomes signaled within 5 seconds.

- [ ] **Step 2: Write failing security tests**

  Cover 1 MiB request, 256 KiB structured content, all expression budgets, 50 warnings, project lock, symlink/junction/reparse point, parent/absolute/cross-drive/UNC/NUL/ADS/reserved-name/trailing-dot/trailing-space paths, cooperative deadline boundary, stdout pollution fixture, higher SQLite/project version and degraded fail-closed behavior.

- [ ] **Step 3: Run and observe the missing evidence/Harness failure**

  ```powershell
  uv run --locked --no-sync pytest tests/integration/test_stdio_golden_m1a.py tests/security/test_m1a_boundaries.py -q
  ```

  Expected: collection or the final transcript assertion fails because `modeling_harness.evidence` and the M1a check registry do not exist; exit is nonzero. The test must not be marked skipped on Windows. If it instead exposes a transport, schema, core, persistence, numerical or path defect, stop A11, add a focused failing regression to the owning A2–A10 task, commit that correction separately, and rerun this step until the only red reason is the missing A11 Harness/evidence surface.

- [ ] **Step 4: Implement transcript capture without changing product behavior**

  Add redacted transcript/trace capture to `src/modeling_harness/evidence.py` and test fixtures only. The recorder accepts parsed MCP direction/tool/result metadata, entity IDs, versions, statuses and hashes; it excludes raw request payloads, full results, absolute paths and stderr secrets. A11 must not edit adapter, core, SQLite, capability or path production modules; any such defect follows the corrective path in Step 3. Do not add retry loops or relax assertions.

- [ ] **Step 5: Implement Harness checks and atomic evidence output**

  `verify.py` M1a profile runs, in order:

  1. the validated absolute uv 0.11.28 executable with
     `lock --check --offline` and subprocess environment `UV_OFFLINE=1`;
  2. `ruff check src tests` and `ruff format --check src tests`;
  3. `mypy src`;
  4. pytest unit, contract, math, architecture, integration, reproducibility, security, acceptance groups;
  5. package asset inventory and source fingerprint;
  6. a dedicated fresh golden STDIO run.

  Item 5 reuses B11's exact source-inventory algorithm now. Invoke
  `git ls-files --cached --others --exclude-standard -z` through the direct
  argument array
  `["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]`
  with `shell=False`. This is the sole authorized direct non-uv subprocess in
  A11: it is a support inventory call, not a verification check, so it is
  explicitly exempt from the rule that every check subprocess starts with the
  validated absolute uv executable. Decode each NUL-delimited path as strict
  UTF-8, NFC-normalize it to a repository-relative POSIX path, and reject an
  absolute path, `.` or `..` component, duplicate normalized path, NFC
  collision, non-file entry, or listed-but-missing file. Hash each file's raw
  bytes with SHA-256; sort records by the UTF-8 bytes of the normalized path;
  construct the complete JSON array whose objects contain exactly `path` and
  `sha256`; then compute `source_fingerprint = sha256_json(array)` without
  truncation. Git's cached-plus-nonignored-untracked inventory therefore
  includes in-progress task files while excluding ignored environments,
  caches, project state and `build/` evidence.

  No subprocess may shell through Bash, PowerShell or `cmd`. Every subprocess
  other than the single source-inventory support call above must use a
  `subprocess.run` argument array whose first element is the already validated
  absolute uv executable.
  Set `UV_OFFLINE=1` for the entire verification process after the explicit
  environment sync and pass the offline environment to every child; any
  missing/mismatched uv executable or network attempt is a Harness failure.
  Evidence records the validated uv version and optional executable digest,
  never its absolute path. Evidence writes to a sibling temporary directory,
  closes files, then atomically renames. JSON contains schema version, source
  fingerprint, Python/uv/OS/lock summary, every check status/duration/test
  count, architecture report, golden IDs and paths to redacted
  transcript/trace. Failure returns nonzero and preserves a diagnostic report.

- [ ] **Step 6: Run focused tests and pre-document verification**

  ```powershell
  uv run --locked --no-sync pytest tests/integration/test_stdio_golden_m1a.py tests/security/test_m1a_boundaries.py tests/reproducibility/test_m1a_repeatability.py tests/architecture -q
  uv run --locked --no-sync modeling verify --milestone m1a
  ```

  Expected: test command exits 0. Verify runs all registered checks but exits 2 with one explicit missing-deliverables group for A12 documents/doctor/acceptance map; every implemented check is PASS and none is skipped.

- [ ] **Step 7: Run full existing regression**

  ```powershell
  uv run --locked --no-sync pytest tests -q
  uv run --locked --no-sync ruff check src tests
  uv run --locked --no-sync mypy src
  ```

  Expected: all existing tests pass; only the intentional incomplete verify command from Step 6 remains nonzero.

- [ ] **Step 8: Commit**

  ```powershell
  git add src/modeling_harness/verify.py src/modeling_harness/evidence.py tests/integration/test_stdio_golden_m1a.py tests/security/test_m1a_boundaries.py tests/reproducibility/test_m1a_repeatability.py tests/architecture/test_dependency_boundaries.py tests/architecture/test_composition_root.py tests/architecture/test_solver_validator_independence.py
  git commit -m "test: prove the M1a STDIO golden chain"
  ```

**Acceptance:** A real byte pipe and generic MCP client traverse all six tools, error and math-failure branches are distinct, Windows process handles close, stdout is protocol-pure, and one cross-platform Python command orchestrates the checks.

### Work Package A-IV — Minimal context, diagnostics and evidence

### Task A12: Add doctor, basic context, Codex template and the M1a acceptance gate

> **Binding supersession (2026-08-11):** Implement Task A12 under
> [`2026-08-11-m1a-a12-interface-resolution.md`](../specs/2026-08-11-m1a-a12-interface-resolution.md).
> That addendum resolves all three preflight interfaces and supersedes this
> task where file ownership, source-diagnostic call paths, doctor report shape,
> acceptance-map construction, Harness transition, TDD slices, reviews, or
> commit boundaries differ. Unaffected M1a constraints and the Hard Gate below
> remain binding.
> In particular, its A12.1 WAL remediation supersedes every direct-source
> SQLite `mode=ro`/`query_only` or zero-sidecar reading requirement here:
> doctor captures stable raw DB/WAL files without SQLite or `ProjectLock` and
> never opens/reads/hashes the source `project.lock`; it binds composition only
> to a normalized owned root. The binding Windows probe correction dated
> 2026-08-11 also supersedes the earlier copied-input read/write checkpoint
> design: copied raw DB, an always-present owned-input WAL form, and an
> always-present zero-byte owned-input SHM sentinel each remain under
> `GENERIC_READ` plus `FILE_SHARE_READ` guards, SQLite opens them only with URI
> `mode=ro` plus
> verified connection-local `query_only`, and `Connection.backup` copies their
> committed logical state into a distinct normalized output. SQLite never
> writes or checkpoints the copied raw DB/WAL; their complete hashes must be
> unchanged after backup. When source WAL is absent, the owned-input WAL form
> is a zero-byte SHA(empty) sentinel created before SQLite open, guarded by the
> same read/no-writer share contract, held through input close, then removed
> only by identity-bound verified delete. An absent-name recheck is forbidden
> because it leaves a create race. Source SHM is never copied: the guarded
> empty SHM sentinel is held through input close, forcing the read-only SQLite
> connection to use a private heap WAL-index while retaining committed copied
> WAL state, then it is identity-bound deleted. No SQLite-created input member
> is allowed. On the fresh normalized DB, the validated raw-header page size is
> set and queried back before `journal_mode=WAL`; before backup,
> `max_page_count=floor(134,217,728/page_size)` is set and verified and output
> WAL absence is proved. Only normalized output may be opened read/write and
> checkpointed. Backup success grammar is exactly `SQLITE_OK* -> exactly one
> SQLITE_DONE` (DONE-only allowed), with fixed `total`, monotonically
> non-increasing bounded `remaining`, no post-DONE callback, and the addendum's
> finite status-family map.
> Store exclusively performs quick/integrity/FK/legacy
> diagnostics, including logical findings preserved by backup. Regular live
> Store connection, metadata, writer-lock, and transient-sidecar behavior stays
> unchanged while the addendum's explicit `inspect_integrity` result semantics
> change. Five typed finite snapshot failures, render-after-cleanup sequencing,
> the fixed 10-second/1,025-callback bounds, literal 140,509,216-byte output-WAL
> cap, covered 16,783,392-byte largest first callback step, and literal
> 425,787,488-byte owned peak for raw input, zero-byte input SHM sentinel,
> normalized output and sidecars are binding; limits or inventories must never
> be derived dynamically.
>
> This correction is authorized within A12.1 only; it does not create another
> remediation, slice, package member, or commit boundary. Before production
> changes, TDD must record these exact RED nodes:
> `test_read_only_backup_guards_block_raw_input_write_and_truncate_after_open`,
> `test_absent_source_wal_uses_guarded_empty_sentinel_that_blocks_create_write_and_truncate`,
> `test_guarded_empty_wal_sentinel_preserves_committed_main_database_state`,
> `test_guarded_empty_shm_sentinel_forces_private_wal_index_and_blocks_raw_mutation`,
> `test_read_only_backup_leaves_raw_input_database_and_wal_bytes_unchanged`,
> `test_read_only_backup_preserves_latest_committed_wal_state`,
> `test_read_only_backup_preserves_non_default_source_page_size`,
> `test_output_wal_frame_overhead_and_256_page_step_respect_literal_caps`,
> `test_owned_peak_limit_is_literal_425787488_bytes`,
> `test_backup_progress_accepts_done_only_and_ok_star_done`,
> `test_backup_progress_rejects_duplicate_post_done_and_unknown_status_with_finite_codes`,
> `test_normalized_max_page_count_is_set_and_verified_before_backup`,
> `test_read_only_backup_failure_uses_finite_redacted_snapshot_code`,
> `test_normalized_backup_publishes_exact_owned_layout_without_sidecars`,
> `test_checkpointable_foreign_key_violation_reaches_store_foreign_key_report`,
> and `test_checkpointable_non_ok_integrity_reaches_store_check_failed` in
> `tests/integration/test_read_only_diagnostics.py`. The addendum's complete
> input/output SQL allowlists, deadline, finite-code and cleanup semantics are
> binding.
> Each A12.1-A12.4 slice owns a literal package-inventory update in
> `tests/reproducibility/test_m1a_repeatability.py` and must leave the complete
> test suite GREEN; expected counts/paths/hashes are never derived dynamically.

**Primary concern:** 可安全维护和可声明的最小 Context/Harness 交付。

**Files:**

- Create: `AGENTS.md`, `src/modeling_core/AGENTS.md`, `src/modeling_capabilities/AGENTS.md`, `src/modeling_mcp/AGENTS.md`, `tests/AGENTS.md`, `docs/context/index.md`, `docs/product/m1-scope.md`, `docs/architecture/overview.md`, `docs/contracts/mcp-tools-v0.md`, `docs/contracts/capability-api-v0.md`, `docs/contracts/root-finding-v0.md`, `docs/operations/bootstrap-and-doctor.md`, `docs/templates/codex/config.toml`
- Create: `src/modeling_cli/doctor.py`, `tests/unit/test_doctor.py`, `tests/acceptance/test_m1a_acceptance_map.py`
- Modify: `src/modeling_cli/main.py`, `src/modeling_harness/verify.py`, `src/modeling_harness/evidence.py`, `README.md`
- A12 addendum expansion — Create: `src/modeling_cli/schemas/doctor/0.1.0/report.schema.json`, `src/modeling_cli/templates/codex/config.toml`, `src/modeling_infrastructure/diagnostic_snapshot.py`, `tests/integration/test_read_only_diagnostics.py`
- A12 addendum expansion — Modify: `src/modeling_core/ports/project_store.py`, `src/modeling_infrastructure/sqlite/store.py`, `tests/contract/test_project_store.py`, `tests/security/test_m1a_boundaries.py`, `tests/architecture/test_dependency_boundaries.py`, `tests/reproducibility/test_m1a_repeatability.py`
- A12 addendum exclusion — `src/modeling_infrastructure/storage.py` is not modified for the diagnostic snapshot; regular live Store connection, metadata, writer-lock, and transient-sidecar paths retain their existing behavior.
- A12 slice ownership — A12.1 adds only package member `modeling_infrastructure/diagnostic_snapshot.py`; A12.2 adds `modeling_cli/doctor.py`, the doctor Schema, and packaged Codex template; A12.3 adds the three `src` package-root `AGENTS.md` files; A12.4 adds no package member and freezes final hashes.
- A12 package gates — A11 baseline `85 = 53 Python + 32 non-Python`; A12.1 `86 = 54 + 32`; A12.2 `89 = 55 + 34`; A12.3 `92 = 55 + 37`; A12.4 remains `92 = 55 + 37`. Every slice may modify `tests/reproducibility/test_m1a_repeatability.py` for its own literal row and exact new paths, must run the full suite GREEN, and may not derive expected counts from the built wheel. A12.4 fixes raw hashes for the five final non-Python assets.

**Interfaces produced:** `modeling doctor --project-root tests/.tmp/manual-project [--deep] [--json]`; complete M1a context router; usable production Codex project config; M1a-0 historical-feasibility link; A-01 through A-10 evidence map.

- [ ] **Step 1: Write failing doctor and context acceptance tests**

  Doctor tests require:

  - UNINITIALIZED and STORAGE_READY are not corrupt;
  - READY with healthy DB/registry/schemas exits 0;
  - warnings exit 1 and unsafe/degraded state exits 2;
  - legacy PENDING/RUNNING/IN_PROGRESS IDs are reported, never changed;
  - `--json` follows a strict versioned output Schema and omits absolute paths/secrets;
  - ordinary diagnosis uses a verified owned base snapshot; `--deep` uses a distinct second temp project for lock and real root smoke; both clean before output;
  - doctor never repairs, migrates or writes authoritative state.

  Acceptance test requires every M1a document/link, root plus four nested rules, all six tool/capability/root contract assets, Codex template and generated evidence keys. It must verify exactly one `Task M1a-0` heading plus exactly 12 Task A headings, ensure the Spike is excluded from packaging/formal imports, assert M1a documentation promises stable hash smoke only, and find the three mandatory task-completion fields `Test result`, `Git diff summary`, `Commit hash` in root execution rules.

- [ ] **Step 2: Run and observe missing deliverables**

  ```powershell
  uv run --locked --no-sync pytest tests/unit/test_doctor.py tests/acceptance/test_m1a_acceptance_map.py -q
  ```

  Expected: collection fails for missing doctor module and then reports every absent document when the module exists.

- [ ] **Step 3: Implement snapshot-backed doctor**

  Doctor first performs the addendum's one-attempt raw stable capture without opening the source lock. It holds copied DB, an always-present copied-or-synthetic WAL, and an always-present empty SHM sentinel under read-only Windows guards, opens that input only with SQLite URI `mode=ro` plus verified `query_only`, and uses bounded `Connection.backup` to a distinct normalized output; copied input DB/WAL and sentinel identities/hashes must remain exact. If source WAL is absent, an identity-bound empty sentinel occupies the owned-input WAL name. The always-empty guarded SHM name forces SQLite to use its private heap WAL-index while retaining committed WAL state. Both synthetic sentinels block create/write/truncate through input close and are then safely removed through verified bound-delete handles. The fresh output receives and verifies the validated source-header page size before entering WAL mode; before backup it sets/verifies the fixed logical max-page count and proves output WAL absence. Only normalized output is checkpointed. Backup progress uses the addendum's finite status map and exact `OK* -> one DONE` grammar. Literal output-WAL and total-owned caps are 140,509,216 and 425,787,488 bytes. It then composes against the exact published owned root. The same `ApplicationFacade.health_check` and `ApplicationFacade.list_capabilities` used by MCP run there; `ProjectStore.inspect_integrity` alone owns SQLite `quick_check` by default/`integrity_check` in deep mode, FK and legacy queries. Build and Schema-validate the report in memory, close the distinct deep root and base snapshot, then render exactly once. Cleanup failure discards READY and maps to finite `snapshot_cleanup_failed` UNSAFE/2 with no earlier stdout. Exit mapping remains 0 ready, 1 warnings, 2 unsafe; no doctor-only Facade business branch is added.

- [ ] **Step 4: Write minimal stable context and contract documents**

  Root `AGENTS.md` is 100–150 lines and contains only mission, reading order, dependency direction, MCP/math separation, Schema/version/ADR rules, real execution, independent validation, read-only inputs, traceability, STDOUT/path/secrets safety, single verify command, current spec link, Spike non-production boundary, M1a-stable/M1b-RFC ownership, and the required per-task test/diff/commit completion record. Nested files contain only their directory-specific rules.

  `docs/context/index.md` includes current milestone/spec, product/architecture/contract/operations routes, task-to-minimum-context matrix, ability discovery, conflict authority and deprecation section. M1a docs link the versioned Schema assets instead of duplicating JSON. `root_finding/context.md` stays capability-local.

- [ ] **Step 5: Add the exact Codex template**

  `src/modeling_cli/templates/codex/config.toml` is the installed canonical file; `docs/templates/codex/config.toml` is its mandatory byte-identical user mirror and must be directly copyable to `.codex/config.toml` in a trusted project:

  ```toml
  [mcp_servers.modeling]
  command = "uv"
  args = ["run", "--locked", "--no-sync", "modeling-mcp", "--project-root", "."]
  cwd = "."
  required = true
  startup_timeout_sec = 10
  tool_timeout_sec = 65
  enabled_tools = [
    "health_check",
    "create_project",
    "get_project_status",
    "list_capabilities",
    "run_experiment",
    "validate_experiment",
  ]
  ```

  Document that project-scoped config is loaded only for a trusted project and that it is a thin host adapter, not a core dependency.

- [ ] **Step 6: Complete A-01 through A-10 mapping and make verify pass**

  Each acceptance ID maps to one or more exact pytest node IDs plus evidence JSON pointers. Harness must reject duplicate/missing IDs, a skipped required test, stale source fingerprint or missing transcript/trace. Wheel evidence proves 37 non-Python and 92 total members, literal presence of both new Python modules, and fixed raw hashes for the five new non-Python assets. Update README with the historical M1a-0 feasibility checkpoint, bootstrap, doctor, M1a verify, explicit “stable hash smoke only” wording and the M1a-only completion wording.

- [ ] **Step 7: Run focused tests**

  ```powershell
  uv run --locked --no-sync pytest tests/unit/test_doctor.py tests/acceptance/test_m1a_acceptance_map.py -q
  uv run --locked --no-sync modeling doctor --project-root tests/.tmp/manual-project --deep --json
  ```

  Expected: tests pass; doctor emits one JSON object with exit 0 for the healthy manual project.

- [ ] **Step 8: Run the M1a completion and full regression command**

  ```powershell
  uv run --locked --no-sync modeling verify --milestone m1a
  ```

  Expected: exit 0; first line names `m1a`; required skip count is 0; A-01 through A-10 all PASS; output prints the exact evidence directory and source fingerprint.

- [ ] **Step 9: Inspect the evidence and commit**

  ```powershell
  git status --short
  git add AGENTS.md README.md docs src/modeling_core/AGENTS.md src/modeling_capabilities/AGENTS.md src/modeling_mcp/AGENTS.md src/modeling_cli tests/AGENTS.md tests/unit/test_doctor.py tests/acceptance/test_m1a_acceptance_map.py
  git commit -m "docs: establish the M1a context and evidence gate"
  ```

  Expected: `build/verification/` is absent from staged files; commit includes only source/config/docs/tests.

**Acceptance:** `verify --milestone m1a` is zero with no required skip, doctor is source-nonmutating through the addendum's verified stable snapshot, all M1a context/config assets exist and link correctly, and A-01 through A-10 have source-fingerprint-matched evidence.

## M1a Hard Gate

Do not begin C1 until all commands below succeed on Windows from a clean checkout:

```powershell
uv sync --locked --group dev
if (Test-Path -LiteralPath tests/.tmp/m1a-gate-project) { throw 'm1a gate project already exists; inspect it instead of overwriting it' }
New-Item -ItemType Directory -Path tests/.tmp/m1a-gate-project | Out-Null
uv run --locked --no-sync modeling bootstrap --project-root tests/.tmp/m1a-gate-project
uv run --locked --no-sync modeling doctor --project-root tests/.tmp/m1a-gate-project --deep --json
uv run --locked --no-sync modeling verify --milestone m1a
git status --short
```

Expected:

- the M1a-0 Hard Gate previously passed within 48 hours and its completion record still identifies the immutable Spike commit;
- bootstrap is idempotent on a repeated call;
- doctor is ready with exit 0;
- verify exits 0, required skips 0 and A-01 through A-10 PASS;
- the M1a profile runs only fixed/repeatability hash smoke checks and makes no complete RFC 8785 conformance claim;
- golden root and residual criteria from design §16.1 hold;
- `git status --short` is empty because verification output is ignored;
- the evidence package contains report JSON, human summary, Windows/uv/lock summary, architecture report, redacted STDIO transcript, golden IDs, trace export and A mapping;
- every A1–A12 task handoff contains fresh test result, staged git diff summary and full commit hash, with no failed or required-skipped test.

If any condition fails, fix the owning M1a task with a new failing regression test and a separate corrective commit. Do not weaken the gate and do not start ArtifactStore, recovery, rerun, compatibility baseline, CI matrix, Skills or ADR work.

After PASS, execute
`docs/superpowers/plans/2026-07-23-cumcm-2022-a-q1-contest-vertical-slice.md`
before the deferred remainder of M1b. C1 does not claim any deferred M1b stable
contract, RFC 8785, recovery, compatibility, or cross-platform release gate.

---



## M1b Plan — Trusted Hardening

The deferred remainder of M1b starts only after the M1a Hard Gate and the approved C1 contest-preview gate pass. C1's explicit preview additions do not imply that any M1b stable-contract, RFC 8785, recovery, compatibility, or cross-platform requirement has passed.

### Work Package B-I — Stable contracts, canonicalization and extension proof

### Task B1: Promote the proven slice to the stable 1.0 contract family

**Primary concern:** 将已运行的 0.1 形状一次性提升为内部一致的 1.0 首发基线，并让六工具、求根能力、验证器和 Application Release 使用同一版本集合。

**Files:**

- Modify: `src/modeling_core/version.py`, `src/modeling_core/contracts/versions.py`, `src/modeling_core/contracts/tools.py`, `src/modeling_core/contracts/schema_catalog.py`
- Modify: `src/modeling_core/application/service.py`, `src/modeling_mcp/adapter.py`
- Modify: `src/modeling_capabilities/root_finding/contracts.py`, `src/modeling_capabilities/root_finding/descriptor.py`, `src/modeling_capabilities/root_finding/solver.py`, `src/modeling_capabilities/root_finding/validator.py`
- Create: `src/modeling_core/contracts/schemas/common/1.0.0/modeling-error.schema.json`, `src/modeling_core/contracts/schemas/common/1.0.0/modeling-project.schema.json`, `src/modeling_core/contracts/schemas/common/1.0.0/modeling-capability.schema.json`, `src/modeling_core/contracts/schemas/common/1.0.0/modeling-validator.schema.json`, `src/modeling_core/contracts/schemas/common/1.0.0/modeling-result.schema.json`, `src/modeling_core/contracts/schemas/common/1.0.0/modeling-validation-report.schema.json`
- Create: `src/modeling_core/contracts/schemas/tools/1.0.0/health_check.request.schema.json`, `src/modeling_core/contracts/schemas/tools/1.0.0/health_check.result.schema.json`, `src/modeling_core/contracts/schemas/tools/1.0.0/health_check.error.schema.json`
- Create: `src/modeling_core/contracts/schemas/tools/1.0.0/create_project.request.schema.json`, `src/modeling_core/contracts/schemas/tools/1.0.0/create_project.result.schema.json`, `src/modeling_core/contracts/schemas/tools/1.0.0/create_project.error.schema.json`
- Create: `src/modeling_core/contracts/schemas/tools/1.0.0/get_project_status.request.schema.json`, `src/modeling_core/contracts/schemas/tools/1.0.0/get_project_status.result.schema.json`, `src/modeling_core/contracts/schemas/tools/1.0.0/get_project_status.error.schema.json`
- Create: `src/modeling_core/contracts/schemas/tools/1.0.0/list_capabilities.request.schema.json`, `src/modeling_core/contracts/schemas/tools/1.0.0/list_capabilities.result.schema.json`, `src/modeling_core/contracts/schemas/tools/1.0.0/list_capabilities.error.schema.json`
- Create: `src/modeling_core/contracts/schemas/tools/1.0.0/run_experiment.request.schema.json`, `src/modeling_core/contracts/schemas/tools/1.0.0/run_experiment.result.schema.json`, `src/modeling_core/contracts/schemas/tools/1.0.0/run_experiment.error.schema.json`
- Create: `src/modeling_core/contracts/schemas/tools/1.0.0/validate_experiment.request.schema.json`, `src/modeling_core/contracts/schemas/tools/1.0.0/validate_experiment.result.schema.json`, `src/modeling_core/contracts/schemas/tools/1.0.0/validate_experiment.error.schema.json`
- Create: `src/modeling_capabilities/root_finding/schemas/1.0.0/input.schema.json`, `src/modeling_capabilities/root_finding/schemas/1.0.0/canonical-input.schema.json`, `src/modeling_capabilities/root_finding/schemas/1.0.0/success-data.schema.json`, `src/modeling_capabilities/root_finding/schemas/1.0.0/failure-data.schema.json`, `src/modeling_capabilities/root_finding/schemas/1.0.0/policy.schema.json`, `src/modeling_capabilities/root_finding/schemas/1.0.0/report.schema.json`
- Create: `tests/contract/test_tool_schemas_v1.py`, `tests/contract/corpus/tools/1.0.0/health_check.json`, `tests/contract/corpus/tools/1.0.0/create_project.json`, `tests/contract/corpus/tools/1.0.0/get_project_status.json`, `tests/contract/corpus/tools/1.0.0/list_capabilities.json`, `tests/contract/corpus/tools/1.0.0/run_experiment.json`, `tests/contract/corpus/tools/1.0.0/validate_experiment.json`, `tests/contract/corpus/root-finding/1.0.0.json`
- Create: `tests/contract/baselines/modeling-tools-1.0.0.json`, `tests/contract/baselines/modeling-capability-1.0.0.json`

**Interfaces produced:** `M1B_APPLICATION_VERSION="0.2.0"`; `VersionSet.m1b()` with tools/project/capability/error/result/report/canonical/root/canonical-input/residual `1.0.0` and database schema `2`; `SchemaCatalog.load_packaged("1.0.0")`; `get_project_status` cursor/limit request fields; `run_experiment.mode: Literal["new", "rerun"]`; stable ArtifactManifest-bearing result DTOs. Production composition remains coherently on `VersionSet.m1a()` until B6 can switch contracts, schema 2, artifacts, rerun and recovery together.

- [ ] **Step 1: Write the failing stable-contract corpus test**

  In `tests/contract/test_tool_schemas_v1.py`, enumerate all 30 stable Schema `$id` values, validate the seven exact corpus files, assert that every model and Schema version equals `1.0.0`, assert `VersionSet.m1b().application_release == M1B_APPLICATION_VERSION == "0.2.0"`, and assert the six tool names remain unchanged. Add these boundary cases:

  - `get_project_status.limit` accepts 1 and 100, rejects 0 and 101;
  - a cursor is an opaque nonempty string and is rejected for `view="summary"`;
  - `mode="rerun"` requires `experiment_id`, while `mode="new"` forbids it;
  - stable run and validation terminal results require an ArtifactManifest with lowercase SHA-256, nonnegative byte size, media type `application/json`, and role `result` or `validation_report`;
  - 0.1 Schema assets remain loadable as archival preview contracts; an adapter explicitly constructed with `VersionSet.m1b()` advertises only 1.0, while the production composition remains entirely M1a in this intermediate commit.

- [ ] **Step 2: Run and confirm the absent-1.0 failure**

  ```powershell
  uv run --locked --no-sync pytest tests/contract/test_tool_schemas_v1.py -q
  ```

  Expected: collection succeeds, then the first catalog lookup fails with `SchemaVersionNotFound: 1.0.0`; exit is nonzero.

- [ ] **Step 3: Add the minimum stable DTOs, Schema assets and version switch**

  Copy no generated Pydantic Schema into the asset tree. Author the 30 Draft 2020-12 assets as the public authority, keep `additionalProperties: false`, and use exact `$ref` URIs resolved only by `SchemaCatalog`. Generate the two baseline manifests from sorted relative paths; each entry contains exactly `path`, `$id`, `sha256`, and `kind`. The baseline manifest itself is canonicalized with `canonical_json_bytes` before hashing.

  `VersionSet.m1b()` must return protocol `2025-11-25`, database schema `2`, and every public schema axis `1.0.0`. Registry, Facade and MCP adapter constructors must accept one injected VersionSet; no component may read a global “latest” version. In the stable adapter contract fixture, `tools/list` exposes the 1.0 input/output schemas without changing tool names. Do not switch production composition in B1.

- [ ] **Step 4: Run stable contract tests and inspect the catalog**

  ```powershell
  uv run --locked --no-sync pytest tests/contract/test_tool_schemas_v1.py -q
  uv run --locked --no-sync python -c "from modeling_core.contracts.schema_catalog import SchemaCatalog; c=SchemaCatalog.load_packaged('1.0.0'); print(len(c.tool_schemas), len(c.common_schemas), c.fingerprint)"
  ```

  Expected: tests exit 0; the inspection prints `18 6 sha256:` followed by 64 lowercase hexadecimal characters.

- [ ] **Step 5: Run contract and M1a regression gates**

  ```powershell
  uv run --locked --no-sync ruff check src/modeling_core src/modeling_capabilities src/modeling_mcp tests/contract
  uv run --locked --no-sync mypy src/modeling_core src/modeling_capabilities src/modeling_mcp
  uv run --locked --no-sync pytest tests/contract/test_tool_schemas_v0.py tests/contract/test_tool_schemas_v1.py tests/contract/test_capability_schemas_v0.py tests/unit/root_finding tests/contract/test_mcp_adapter.py -q
  ```

  Expected: all commands exit 0; 0.1 preview tests and 1.0 stable tests both pass; stable adapter fixtures advertise only 1.0; the production composition is still a coherent M1a vertical slice.

- [ ] **Step 6: Commit**

  ```powershell
  git add src/modeling_core src/modeling_capabilities/root_finding src/modeling_mcp/adapter.py tests/contract/test_tool_schemas_v1.py tests/contract/corpus/tools/1.0.0 tests/contract/corpus/root-finding/1.0.0 tests/contract/baselines
  git commit -m "feat: freeze stable M1 contract family"
  ```

**Acceptance:** 六工具仍是唯一 MCP 表面；30 个公共 1.0 Schema、6 个求根 1.0 Schema、两个基线 manifest 和严格 DTO 互相一致；任何单个构造实例都只接受一个 VersionSet；生产入口仍完整运行 M1a，稳定构造 fixture 完整运行 1.0，二者都不存在轴间混搭。

### Task B2: Complete RFC 8785 vectors and enforce Schema compatibility baselines

**Primary concern:** 用完整外部向量证明规范 JSON，并以基线比较阻止稳定 Schema 的无版本破坏。

**Files:**

- Modify: `src/modeling_core/contracts/canonical_json.py`, `src/modeling_harness/verify.py`
- Create: `src/modeling_harness/schema_compat.py`, `tests/contract/test_rfc8785_vectors.py`, `tests/contract/test_schema_compatibility.py`
- Create: `tests/contract/corpus/rfc8785/PROVENANCE.md`, `tests/contract/corpus/rfc8785/appendix-b.json`, `tests/contract/corpus/rfc8785/project-vectors.json`
- Create: `tests/contract/corpus/rfc8785/arrays.input.json`, `tests/contract/corpus/rfc8785/arrays.output.json`, `tests/contract/corpus/rfc8785/french.input.json`, `tests/contract/corpus/rfc8785/french.output.json`
- Create: `tests/contract/corpus/rfc8785/structures.input.json`, `tests/contract/corpus/rfc8785/structures.output.json`, `tests/contract/corpus/rfc8785/unicode.input.json`, `tests/contract/corpus/rfc8785/unicode.output.json`
- Create: `tests/contract/corpus/rfc8785/values.input.json`, `tests/contract/corpus/rfc8785/values.output.json`, `tests/contract/corpus/rfc8785/weird.input.json`, `tests/contract/corpus/rfc8785/weird.output.json`

**Interfaces produced:** `compare_schema_sets(baseline: SchemaSet, candidate: SchemaSet) -> CompatibilityReport`; `CompatibilityIssue(path, rule, baseline_value, candidate_value)`; M1b Harness check IDs `canonical-json-conformance` and `schema-compatibility`; development-only selectors for each check.

- [ ] **Step 1: Add failing canonicalization and compatibility mutation tests**

  `tests/contract/test_rfc8785_vectors.py` has two explicit lanes. The dependency-conformance lane parses I-JSON and calls pinned `rfc8785.dumps` directly for every Appendix B number row and all six upstream input/output pairs byte-for-byte; it applies no project normalization because RFC 8785 itself does not normalize Unicode. The project lane calls public `canonical_json_bytes` and covers UTF-16 property ordering after NFC preprocessing, `1` versus `1.0`, negative zero, materialized defaults and whitespace-equivalent expression ASTs. The project lane must reject NaN, both infinities, lone surrogates and duplicate keys created by NFC normalization.

  `tests/contract/test_schema_compatibility.py` must use in-memory mutations of the checked-in 1.0 baseline and assert:

  - accepted: changing only annotation keywords such as `description`; widening an existing request enum or numeric range without adding a property; making an existing required request property optional;
  - rejected: adding any property to a strict root object, removing/renaming a property, adding a required request property, changing a type, narrowing a request bound/enum, widening a response bound/enum, changing a discriminator, changing `$id`, making `additionalProperties` permissive, or changing an existing error-code branch;
  - any accepted public shape change still requires a new candidate version directory and regenerated baseline; modifying files under `1.0.0` makes the hash baseline fail.

- [ ] **Step 2: Run and observe both missing-harness failures**

  ```powershell
  uv run --locked --no-sync pytest tests/contract/test_rfc8785_vectors.py tests/contract/test_schema_compatibility.py -q
  ```

  Expected: the RFC test fails because `appendix-b.json` is absent or incomplete; compatibility collection fails with `ModuleNotFoundError: modeling_harness.schema_compat`; exit is nonzero.

- [ ] **Step 3: Vendor provenance-bound vectors and implement the narrow comparator**

  Populate `PROVENANCE.md` with RFC 8785 and `cyberphone/json-canonicalization` source URLs, upstream file paths, retrieval date, license notice, and SHA-256 of every vendored byte file. `appendix-b.json` must encode every table row from RFC 8785 Appendix B as the 16-hex-digit IEEE-754 bit pattern plus expected JSON token; tests construct the float with `struct.unpack` so source-language parsing cannot alter the input. `canonical_json_bytes` remains the sole public project-hash entry: it performs the approved NFC/finite/negative-zero preprocessing exactly once and then delegates to `rfc8785.dumps`; it never substitutes the direct dependency-conformance lane for project semantics.

  `schema_compat.py` must dereference only local `$ref` targets through the catalog, track request versus response variance, return all deterministic issues sorted by JSON Pointer, and fail closed on unsupported keywords or reference cycles. It is a release comparator, not a general JSON Schema theorem prover. Register the complete vector suite as `canonical-json-conformance` and the comparator/baseline suite as `schema-compatibility`, both M1b-only required checks. Extend the existing verify parser with repeatable `--only` choices validated against the selected milestone's registered check IDs; focused mode prints `completion_evidence=false`, and an unknown or cross-milestone check exits 2 before a subprocess runs.

- [ ] **Step 4: Run the complete contract pair**

  ```powershell
  uv run --locked --no-sync pytest tests/contract/test_rfc8785_vectors.py tests/contract/test_schema_compatibility.py -q
  uv run --locked --no-sync python -m modeling_cli verify --milestone m1b --only canonical-json-conformance
  uv run --locked --no-sync python -m modeling_cli verify --milestone m1b --only schema-compatibility
  ```

  Expected: all vector and mutation tests pass; the focused Harness checks print `canonical-json-conformance PASS` and `schema-compatibility PASS`, then exit 0. No M1a profile or A-task command runs the complete vector corpus.

- [ ] **Step 5: Run canonical JSON and all Schema regressions**

  ```powershell
  uv run --locked --no-sync ruff check src/modeling_core/contracts src/modeling_harness/schema_compat.py tests/contract
  uv run --locked --no-sync mypy src/modeling_core/contracts src/modeling_harness/schema_compat.py
  uv run --locked --no-sync pytest tests/unit/contracts tests/contract -q
  ```

  Expected: all commands exit 0; fixed M1a hashes, RFC vectors, baseline hashes and compatibility mutations pass without network access.

- [ ] **Step 6: Commit**

  ```powershell
  git add src/modeling_core/contracts/canonical_json.py src/modeling_harness/schema_compat.py src/modeling_harness/verify.py tests/contract
  git commit -m "test: enforce canonical JSON and schema compatibility"
  ```

**Acceptance:** RFC Appendix B is complete; six reference corpus pairs match exact UTF-8 bytes; project normalization vectors pass; stable Schema edits are checked against immutable hashes and semantic mutations; verification never downloads a reference asset.

### Task B3: Prove Built-in Capability extension with a guarded scaffold

**Primary concern:** 证明新增内置能力不修改 Stable Core，同时给维护者一个拒绝覆盖、明确注册的最小脚手架流程。

**Files:**

- Modify: `src/modeling_core/contracts/capability.py`, `src/modeling_core/registry.py`, `src/modeling_cli/main.py`, `src/modeling_harness/verify.py`
- Create: `src/modeling_harness/capability_scaffold.py`, `tests/fixtures/test_echo_capability.py`, `tests/architecture/test_echo_extension.py`

**Interfaces produced:** `scaffold_builtin_capability(capability_id: str, destination_root: Path, tests_root: Path) -> ScaffoldResult`; concrete CLI example `modeling capability scaffold numerical.secant --destination src/modeling_capabilities --tests-destination tests/capabilities`; focused `modeling verify --capability numerical.root_finding`; test-only `EchoCapability` and `EchoValidator` registered only by a test composition function.

- [ ] **Step 1: Write failing extension and scaffold tests**

  `tests/architecture/test_echo_extension.py` must assert:

  1. a sealed registry composed with `test.echo/1.0.0` lists and resolves it deterministically;
  2. the fixture executes and its independent validator passes without editing any file below `src/modeling_core/`;
  3. a sorted `(relative_path, raw_byte_sha256)` manifest of `src/modeling_core` is identical immediately before and after test.echo composition/execution and scaffold generation in `tmp_path`;
  4. the capability output contains exactly `__init__.py`, `context.md`, `contracts.py`, `descriptor.py`, `solver.py`, `validator.py`, and six individually named `input`, `canonical-input`, `success-data`, `failure-data`, `policy`, `report` Schema assets under `schemas/1.0.0/`; the test output contains exactly `test_contract.py`, `test_solver.py`, `test_validator.py`, and `test_metamorphic.py` under the matching capability ID path;
  5. invalid IDs, `external.*`, mixed case, path separators, an existing destination, and a partially existing destination fail without writing any file;
  6. generated registration instructions name `modeling_bootstrap/composition.py` and never mention entry points or directory scanning.
  7. `modeling verify --capability numerical.root_finding` runs only its contract, parser, solver, validator, metamorphic and architecture checks and exits 0; an unregistered capability ID exits 2 without running tests.

- [ ] **Step 2: Run and confirm the missing scaffold failure**

  ```powershell
  uv run --locked --no-sync pytest tests/architecture/test_echo_extension.py -q
  ```

  Expected: collection fails with `ModuleNotFoundError: modeling_harness.capability_scaffold`; exit is nonzero.

- [ ] **Step 3: Implement only the tested scaffold and test fixture extension**

  Use standard-library `string.Template` constants inside `capability_scaffold.py`; stage both the capability and test trees, fsync each file, and publish only when neither destination exists. If the second rename fails, remove only the first directory created by this invocation after verifying its recorded file manifest; never touch a pre-existing path. The command must not edit composition automatically. Generated contract tests validate descriptor and Schema structure; solver, validator and metamorphic tests begin red with the exact message `capability behavior must be specified before registration`, so a new capability cannot be registered on structural scaffolding alone. Stdout prints the exact import/register edit required in `modeling_bootstrap/composition.py` and the focused acceptance command. Add the focused verify selector to the existing Harness: it resolves the sealed descriptor and runs only check IDs declared for that capability; it is a development feedback mode and cannot produce milestone completion evidence. `test_echo_capability.py` is excluded from the production wheel and returns its canonical input unchanged; its validator computes a fresh equality check without invoking the capability.

  Tighten `CapabilityDescriptor` so `kind` is exactly `built_in`, every capability declares an explicit `contract_version`, and registry sealing rejects duplicate capability/validator keys and missing required validators. No External Plugin model or installer is added.

- [ ] **Step 4: Run the extension proof and inspect generated paths**

  ```powershell
  uv run --locked --no-sync pytest tests/architecture/test_echo_extension.py -q
  uv run --locked --no-sync modeling verify --capability numerical.root_finding
  uv run --locked --no-sync modeling capability scaffold numerical.secant --destination tests/.tmp/scaffold-proof/src --tests-destination tests/.tmp/scaffold-proof/tests
  Get-ChildItem -LiteralPath tests/.tmp/scaffold-proof/src/numerical/secant -Recurse -File | Sort-Object FullName | Select-Object -ExpandProperty FullName
  Get-ChildItem -LiteralPath tests/.tmp/scaffold-proof/tests/numerical/secant -Recurse -File | Sort-Object FullName | Select-Object -ExpandProperty FullName
  ```

  Expected: architecture tests, focused verify and scaffold CLI exit 0; focused verify names only `numerical.root_finding` check IDs; scaffold stdout prints one explicit registration instruction and one focused acceptance command; the two listings contain exactly the 12 capability files and 4 red-first test files asserted by the architecture test. Remove `tests/.tmp/scaffold-proof` with `Remove-Item -LiteralPath tests/.tmp/scaffold-proof -Recurse` after verifying its resolved path is below the repository's `tests/.tmp` directory.

- [ ] **Step 5: Run registry, architecture and contract regressions**

  ```powershell
  uv run --locked --no-sync ruff check src/modeling_core src/modeling_harness/capability_scaffold.py tests/fixtures/test_echo_capability.py tests/architecture
  uv run --locked --no-sync mypy src/modeling_core src/modeling_harness/capability_scaffold.py tests/fixtures/test_echo_capability.py
  uv run --locked --no-sync pytest tests/unit/test_registry.py tests/architecture tests/contract/test_capability_schemas_v0.py tests/contract/test_tool_schemas_v1.py -q
  ```

  Expected: all commands exit 0; production composition still registers only `numerical.root_finding` and its residual validator.

- [ ] **Step 6: Commit**

  ```powershell
  git add src/modeling_core/contracts/capability.py src/modeling_core/registry.py src/modeling_cli/main.py src/modeling_harness/capability_scaffold.py src/modeling_harness/verify.py tests/fixtures/test_echo_capability.py tests/architecture/test_echo_extension.py
  git commit -m "feat: add guarded built-in capability scaffold"
  ```

**Acceptance:** test.echo 证明扩展点而不进入发行物；脚手架只生成一个 Built-in Capability 边界和对应红测试且不自动注册；Stable Core 的逐文件字节 manifest 在扩展操作前后相同；生产系统仍无动态发现或 External Plugin 安装语义。

### Work Package B-II — Content-addressed state and complete recovery

### Task B4: Create fresh SQLite schema 2 and the content-addressed ArtifactStore

**Primary concern:** 建立 M1b 稳定项目的不可变制品层和关系完整的 SQLite v2，不实现预览状态迁移器。

**Files:**

- Modify: `src/modeling_infrastructure/project_paths.py`, `src/modeling_infrastructure/storage.py`, `src/modeling_infrastructure/sqlite/store.py`, `src/modeling_bootstrap/composition.py`
- Modify: `src/modeling_core/ports/project_store.py`
- Create: `src/modeling_infrastructure/sqlite/schema_v2.sql`, `src/modeling_core/ports/artifact_store.py`, `src/modeling_infrastructure/artifacts/__init__.py`, `src/modeling_infrastructure/artifacts/store.py`
- Create: `tests/contract/test_artifact_store.py`, `tests/contract/test_sqlite_schema_v2.py`

**Interfaces produced:** `ArtifactStore.publish_json(role, payload, schema_id) -> ArtifactManifest`; `ArtifactStore.read_verified(artifact_id, expected_size, expected_sha256) -> bytes`; `ArtifactStore.inspect(referenced_artifact_ids) -> ArtifactInspectionReport`; fresh bootstrap creates `PRAGMA user_version=2`, `.modeling/staging/`, and `.modeling/artifacts/sha256/`.

- [ ] **Step 1: Write failing storage contracts**

  `tests/contract/test_artifact_store.py` must assert exact path derivation `.modeling/artifacts/sha256/{first_two_hex}/{full_hex}.json`, where `full_hex` is the 64-character lowercase Artifact SHA-256 suffix and `first_two_hex` is its first two characters; `artifact_id == sha256 == "sha256:" + full_hex`; canonical byte size; role/media type; and these cases: first publish, identical reuse, concurrent same-byte publish, existing-byte mismatch, invalid Schema, noncanonical JSON, staging interruption, tampered read, unexpected symlink/reparse point, and an unreferenced file reported as an orphan but never deleted.

  `tests/contract/test_sqlite_schema_v2.py` must create a fresh project and inspect `sqlite_master`, foreign keys, unique constraints and `PRAGMA user_version`. It must prove that schema 2 contains exactly `metadata`, `projects`, `input_snapshots`, `experiments`, `environment_snapshots`, `attempts`, `result_snapshots`, `artifacts`, `validations` and `idempotency_records`; `attempts.session_id` stores the diagnostic Session UUID without a separate Session entity; `result_snapshots.result_artifact_id` and `validations.report_artifact_id` are direct foreign keys to `artifacts`; dangling references are rejected; WAL, foreign keys, `synchronous=FULL`, and `busy_timeout=250` are enabled; user_version 1 and 3 are rejected without altering either database.

- [ ] **Step 2: Run and confirm missing v2 ports and schema**

  ```powershell
  uv run --locked --no-sync pytest tests/contract/test_artifact_store.py tests/contract/test_sqlite_schema_v2.py -q
  ```

  Expected: collection fails on `modeling_core.ports.artifact_store` or fresh bootstrap reports that `schema_v2.sql` is absent; exit is nonzero.

- [ ] **Step 3: Implement fresh v2 storage and no-clobber publishing**

  `schema_v2.sql` must create all tested tables in one `BEGIN IMMEDIATE` transaction and finish with `PRAGMA user_version=2`. Do not add a `schema_v1_to_v2.sql`; when a bound project has user_version 1, bootstrap and server start must return `UNSUPPORTED_VERSION` and leave every byte unchanged.

  `ContentAddressedArtifactStore.publish_json` must apply this exact order: enforce the closed role set and reject any single payload above 64 MiB; write canonical bytes under `.modeling/staging/` on the same volume; flush and `os.fsync` the file before closing its handle; calculate SHA-256; validate decoded content with the packaged `schema_id`; derive the destination; create the first-two-hex directory; acquire the OS project write lock; if the destination exists, reread and verify size/hash and reuse it; otherwise call same-volume `os.rename(staging, destination)` while the lock remains held; release the lock only after reopening and verifying the published destination. `os.replace` is forbidden. A platform collision error enters the existing-target verification branch; any other rename failure leaves an unreferenced staging file and fails closed. Remove only the current call's staging name after verified reuse. Existing mismatched content raises `INTEGRITY_FAILURE` and is never replaced. Database references are outside this method and therefore cannot precede publication. B5's attempt-scoped ArtifactSink enforces the cross-file count and cumulative-byte budget because the path-only store has no Attempt identity.

  `ProjectPaths` must resolve the bound root once, require every internal path to remain beneath it with `Path.relative_to`, and reject symlinks, junctions and other reparse points at every existing path component. Artifact manifests contain project-relative POSIX-style paths only.

- [ ] **Step 4: Run storage contracts and inspect a real artifact**

  ```powershell
  uv run --locked --no-sync pytest tests/contract/test_artifact_store.py tests/contract/test_sqlite_schema_v2.py -q
  if (Test-Path -LiteralPath tests/.tmp/m1b-storage-proof) { throw 'M1b storage proof already exists; inspect it instead of overwriting it' }
  New-Item -ItemType Directory -Path tests/.tmp/m1b-storage-proof | Out-Null
  uv run --locked --no-sync python -c "from pathlib import Path; from modeling_core.contracts.versions import VersionSet; from modeling_infrastructure.storage import bootstrap_storage; print(bootstrap_storage(Path('tests/.tmp/m1b-storage-proof'), VersionSet.m1b()).database_schema_version)"
  ```

  Expected: tests exit 0; the explicit M1b bootstrap prints `2`; store inspection in the contract test reports empty staging, zero referenced artifacts, zero orphan artifacts and SQLite integrity `ok`. Production CLI bootstrap remains schema 1 until the coherent B5 switch. Remove `tests/.tmp/m1b-storage-proof` only after resolving it beneath `tests/.tmp`.

- [ ] **Step 5: Run storage, path and bootstrap regressions**

  ```powershell
  uv run --locked --no-sync ruff check src/modeling_core/ports src/modeling_infrastructure src/modeling_bootstrap tests/contract
  uv run --locked --no-sync mypy src/modeling_core/ports src/modeling_infrastructure src/modeling_bootstrap
  uv run --locked --no-sync pytest tests/contract/test_project_store.py tests/contract/test_artifact_store.py tests/contract/test_sqlite_schema_v2.py tests/integration/test_bootstrap_sqlite.py tests/security/test_m1a_boundaries.py -q
  ```

  Expected: all commands exit 0. M1a schema 1 creation remains directly testable as a preview fixture, while current application bootstrap creates only schema 2.

- [ ] **Step 6: Commit**

  ```powershell
  git add src/modeling_core/ports src/modeling_infrastructure src/modeling_bootstrap/composition.py tests/contract/test_artifact_store.py tests/contract/test_sqlite_schema_v2.py tests/integration/test_bootstrap_sqlite.py
  git commit -m "feat: add sqlite v2 and immutable artifacts"
  ```

**Acceptance:** an explicitly composed M1b fresh project is schema 2; preview schema 1 and unknown future versions fail closed without migration; a published Artifact is canonical, Schema-valid, content addressed and immutable; SQLite cannot reference a missing Artifact through normal APIs; no-clobber behavior is tested on the current OS; the production M1a entry remains runnable until B6.

### Task B5: Persist input and environment snapshots and publish result/report artifacts

**Primary concern:** 把求根纵向链路从 M1a 内联记录升级为完整命名哈希、独立快照和文件先于引用的 M1b 溯源链。

**Files:**

- Modify: `src/modeling_core/domain/models.py`, `src/modeling_core/contracts/capability.py`, `src/modeling_core/ports/project_store.py`, `src/modeling_core/application/service.py`
- Modify: `src/modeling_infrastructure/environment.py`, `src/modeling_infrastructure/sqlite/store.py`, `src/modeling_bootstrap/composition.py`
- Create: `tests/integration/test_artifact_workflow.py`
- Modify: `tests/integration/test_application_workflow.py`, `tests/unit/root_finding/test_validator.py`, `tests/contract/test_project_store.py`

**Interfaces produced:** immutable `InputSnapshot`, `EnvironmentSnapshot`, and `Artifact` domain records; write-only `ArtifactSink` role view in `ExecutionContext`; `ProjectStore.begin_run` persists new-mode snapshots atomically; `ProjectStore.load_verified_result` returns bytes only after artifact identity, size, hash and Schema checks.

- [ ] **Step 1: Write the failing artifact-backed workflow test**

  `tests/integration/test_artifact_workflow.py` must execute create → new run → validate through the Facade and assert:

  1. new mode creates one InputSnapshot, Experiment, EnvironmentSnapshot and Attempt in the first transaction;
  2. `canonical_request_hash`, `canonical_payload_hash`, `model_snapshot_hash`, `data_snapshot_set_hash`, `result_hash`, `validation_policy_hash` and `validation_report_hash` are separately named and recompute from the exact canonical byte domains in design §8.5;
  3. model snapshot hash, data snapshot set hash, capability/implementation/Schema hashes, randomness declaration and seed are persisted before execution;
  4. a successful run has exactly one `role=result` Artifact and the successful Validation has exactly one `role=validation_report` Artifact;
  5. each manifest, Artifact row, direct ResultSnapshot/Validation foreign-key reference and physical file agrees on ID, relative path, media type, byte size and hash;
  6. no result/report payload is duplicated inline in SQLite v2;
  7. validator rereads the committed result through verified storage and rejects a forged, missing or tampered Artifact before doing mathematics;
  8. the environment allowlist has Python, uv/lock digest, OS/architecture, package/capability/validator versions, numeric library versions and locale, and excludes username, hostname, absolute paths, secrets and the full process environment.
  9. stable `get_project_status(view="experiment", limit=1)` follows design §11.5 ordering/cursor rules across every Attempt/Validation record with no duplicate or omission; malformed, wrong-project and wrong-view cursors fail before a write and summary view rejects cursor/limit combinations forbidden by Schema.

- [ ] **Step 2: Run and observe the missing snapshot/artifact assertions**

  ```powershell
  uv run --locked --no-sync pytest tests/integration/test_artifact_workflow.py -q
  ```

  Expected: the test reaches the current M1a-style application workflow, then fails because `input_snapshot_id`, `environment_snapshot_id` and artifact manifests are absent; exit is nonzero.

- [ ] **Step 3: Implement the minimum M1b persistence sequence**

  Extend `ExecutionContext` with an `ArtifactSink` that exposes only attempt-scoped JSON publication and no path, read, delete or database method. `AttemptArtifactSink` queries already referenced Artifact count/bytes for its Attempt, reserves the next role under the application admission gate, and rejects a seventeenth Artifact or cumulative bytes above 64 MiB before staging. The current root-finding capability continues to return `ExecutionOutcome`; an explicitly constructed M1b `ModelingApplication` canonicalizes and Schema-validates the Result payload, uses the attempt-scoped sink to publish it, performs the post-publish deadline check, then calls one `complete_attempt` transaction that inserts ResultSnapshot/Artifact references, sets the terminal state, stores the replay response references and marks idempotency COMPLETED. Keep the production composition on M1a until B6 also implements every advertised rerun/recovery behavior.

  Validation must independently call `load_verified_result`, revalidate the result envelope and root-finding success Schema, compare `expected_result_hash`, execute the independent validator, publish the report, then complete Validation and idempotency in one transaction. An Artifact published before a failed final transaction remains an unreferenced orphan; the application must never delete it during error handling. Complete the stable status projection in the same Application service: query committed trace rows in design §11.5's total order, encode/decode only the specified opaque cursor fields, bind a cursor to project and view, apply both item-count and 262144-byte response limits, and derive `next_cursor` from the last emitted row.

- [ ] **Step 4: Run the workflow and inspect its trace**

  ```powershell
  uv run --locked --no-sync pytest tests/integration/test_artifact_workflow.py -q
  uv run --locked --no-sync pytest tests/integration/test_application_workflow.py tests/unit/root_finding/test_validator.py tests/contract/test_project_store.py -q
  ```

  Expected: all tests exit 0; the artifact workflow asserts one result file and one report file, and every recomputed hash matches its named field.

- [ ] **Step 5: Run domain, solver/validator and storage regressions**

  ```powershell
  uv run --locked --no-sync ruff check src/modeling_core src/modeling_infrastructure tests/integration/test_artifact_workflow.py
  uv run --locked --no-sync mypy src/modeling_core src/modeling_infrastructure
  uv run --locked --no-sync pytest tests/unit/domain tests/unit/root_finding tests/contract/test_artifact_store.py tests/contract/test_sqlite_schema_v2.py tests/integration -q
  ```

  Expected: all commands exit 0; validator-independence architecture tests remain green; no SQLite transaction spans numerical execution or file publication.

- [ ] **Step 6: Commit**

  ```powershell
  git add src/modeling_core src/modeling_infrastructure src/modeling_bootstrap/composition.py tests/integration/test_artifact_workflow.py tests/integration/test_application_workflow.py tests/unit/root_finding/test_validator.py tests/contract/test_project_store.py
  git commit -m "feat: persist traceable artifact workflow"
  ```

**Acceptance:** an explicit M1b composition captures immutable input and environment snapshots; result and validation bytes are published before their database references; the validator never trusts a caller-supplied or solver-held payload; every §8.5 hash remains correctly named and recomputable; Artifact ID, artifact byte SHA-256, stored `result_hash` and caller `expected_result_hash` agree; secrets and absolute paths do not enter persisted snapshots; production remains the coherent M1a slice until B6.

### Task B6: Complete idempotent recovery, restart convergence and rerun

**Primary concern:** 让响应丢失和进程重启都收敛到一个可重放的终态，并让 rerun 只新增 Attempt。

**Files:**

- Modify: `src/modeling_core/version.py`, `src/modeling_core/ports/project_store.py`, `src/modeling_core/application/idempotency.py`, `src/modeling_core/application/service.py`
- Create: `src/modeling_core/application/recovery.py`
- Modify: `src/modeling_infrastructure/project_lock.py`, `src/modeling_infrastructure/sqlite/store.py`, `src/modeling_bootstrap/composition.py`
- Create: `tests/integration/test_recovery_and_rerun.py`
- Modify: `tests/integration/test_application_workflow.py`, `tests/contract/test_project_store.py`

**Interfaces produced:** `RecoveryService.recover_previous_session(current_session_id: str, recovered_at: datetime) -> RecoveryReport`; `ProjectStore.recover_previous_session(current_session_id: str, recovered_at: datetime) -> RecoveryReport`; `RunExperimentRequest` with `mode="rerun"`, required non-null `experiment_id: str`, and a fresh `operation_id: str`; integrity-checked replay for all three write tools.

- [ ] **Step 1: Write a failing recovery state-table test**

  `tests/integration/test_recovery_and_rerun.py` must build committed database fixtures through `ProjectStore` APIs and cover every row of this table:

  | Pre-restart state | Recovery result | Same-key replay |
  |---|---|---|
  | Attempt PENDING/RUNNING + run IN_PROGRESS | Attempt ABANDONED with `server_recovery`; idempotency COMPLETED in the same transaction | same Experiment/Attempt, `replayed=true`, ABANDONED |
  | Validation PENDING/RUNNING + validate IN_PROGRESS | Validation ABANDONED with `server_recovery`; idempotency COMPLETED in the same transaction | same Validation, `replayed=true`, ABANDONED |
  | terminal entity + COMPLETED | unchanged | exact persisted response after referential/artifact verification |
  | terminal entity + IN_PROGRESS, or IN_PROGRESS with an impossible entity/reference graph | project DEGRADED; no mutation of evidence because the required atomic transaction invariant was violated | `INTEGRITY_FAILURE` |

  Add assertions that a different request hash for the same key yields `CONFLICT/idempotency_mismatch`, a live matching IN_PROGRESS yields `CONFLICT/operation_in_progress`, create_project never leaves IN_PROGRESS, and response loss after commit creates no duplicate entity. For rerun, assert a fresh operation ID creates one new EnvironmentSnapshot and Attempt, reuses Experiment and InputSnapshot, uses the recorded implementation/contract, and rejects a missing implementation with `UNSUPPORTED_VERSION`.

- [ ] **Step 2: Run and confirm current recovery is incomplete**

  ```powershell
  uv run --locked --no-sync pytest tests/integration/test_recovery_and_rerun.py -q
  ```

  Expected: collection fails because `modeling_core.application.recovery` is absent or the first legacy IN_PROGRESS remains unrecoverable; exit is nonzero.

- [ ] **Step 3: Implement startup recovery and full replay checks**

  After acquiring the OS project lock and opening schema 2, composition creates a new Session UUID and calls `RecoveryService` before accepting MCP calls. The store must recover all prior-session rows in one `BEGIN IMMEDIATE` transaction: PENDING/RUNNING entities become ABANDONED with `terminal_reason=server_recovery`; corresponding idempotency rows become COMPLETED and point to a persisted ABANDONED response. Because normal finalization commits terminal entity and COMPLETED idempotency together, any terminal + IN_PROGRESS pair is an integrity violation: mark the in-memory project state DEGRADED, preserve bytes, reject writes and let doctor report exact entity IDs.

  Replay must rerun reference, byte-size, SHA-256 and Schema checks before returning a completed result. It never re-executes. `rerun` loads the existing Experiment intent, canonical InputSnapshot and captured capability version, requires a fresh operation ID, then enters the normal begin/execute/publish/complete path with a new Attempt. Recovery and rerun acquire the same single-writer admission gate; reads see only committed state. After all focused recovery/rerun tests pass, set `APPLICATION_VERSION="0.2.0"` and switch production composition once to `VersionSet.m1b()`, schema 2, stable adapter schemas and Artifact-backed results; no earlier B task changes the production version set.

- [ ] **Step 4: Run restart, replay and rerun tests**

  ```powershell
  uv run --locked --no-sync pytest tests/integration/test_recovery_and_rerun.py -q
  uv run --locked --no-sync pytest tests/integration/test_application_workflow.py tests/contract/test_project_store.py -q
  ```

  Expected: all tests exit 0; every recovery is idempotent when invoked twice; row counts prove no duplicate Project, Experiment, Attempt, Validation or Artifact reference.

- [ ] **Step 5: Run state, integrity and STDIO regressions**

  ```powershell
  uv run --locked --no-sync ruff check src/modeling_core/application src/modeling_core/ports src/modeling_infrastructure tests/integration/test_recovery_and_rerun.py
  uv run --locked --no-sync mypy src/modeling_core/application src/modeling_core/ports src/modeling_infrastructure
  uv run --locked --no-sync pytest tests/unit/domain tests/contract/test_project_store.py tests/contract/test_artifact_store.py tests/contract/test_mcp_adapter.py tests/integration/test_artifact_workflow.py tests/integration/test_recovery_and_rerun.py tests/integration/test_stdio_golden_m1a.py -q
  ```

  Expected: all commands exit 0; state transitions remain legal, M1a golden calls still work through the now-stable interface, and restart recovery adds no protocol bytes to STDOUT.

- [ ] **Step 6: Commit**

  ```powershell
  git add src/modeling_core/version.py src/modeling_core/application src/modeling_core/ports/project_store.py src/modeling_infrastructure/project_lock.py src/modeling_infrastructure/sqlite/store.py src/modeling_bootstrap/composition.py tests/integration/test_recovery_and_rerun.py tests/integration/test_application_workflow.py tests/contract/test_project_store.py
  git commit -m "feat: make operations recoverable and rerunnable"
  ```

**Acceptance:** production switches coherently to application 0.2.0, public 1.0 and database schema 2 only after all stable behaviors exist; all previous-session active writes converge atomically to replayable terminal records; committed success survives response loss without duplication; corrupt graphs fail closed; rerun reuses immutable intent and creates only a new execution attempt; startup performs recovery before serving tools.

### Task B7: Inject the five crash windows and close filesystem safety boundaries

**Primary concern:** 用真实进程退出证明发布/事务顺序，并验证 M1b 的制品、路径、限额和孤儿策略。

**Files:**

- Create: `src/modeling_core/ports/faults.py`, `tests/fixtures/fault_server.py`, `tests/integration/test_fault_recovery.py`, `tests/security/test_m1b_artifact_boundaries.py`
- Modify: `src/modeling_core/application/service.py`, `src/modeling_infrastructure/artifacts/store.py`, `src/modeling_bootstrap/composition.py`

**Interfaces produced:** `FaultPoint` closed enum with `AFTER_ATTEMPT_CREATED`, `AFTER_ATTEMPT_RUNNING`, `DURING_ARTIFACT_STAGING`, `AFTER_ARTIFACT_PUBLISHED`, `AFTER_DATABASE_COMMIT`; `FaultInjector.check(point, context) -> None`; production `NoFaults`; test-only `ScriptedProcessExitFaults` using an externally selected single point.

- [ ] **Step 1: Write failing subprocess crash and safety tests**

  `tests/integration/test_fault_recovery.py` must launch `tests/fixtures/fault_server.py` as a fresh subprocess for each exact FaultPoint, send one run request through a real byte pipe, require the process to exit before a response, restart the normal server on the same project, and assert:

  - after Attempt creation and after RUNNING: one ABANDONED Attempt, one COMPLETED replay record, no ResultSnapshot and no result Artifact;
  - during staging: no database Artifact reference; partial staging belongs to the dead Session and doctor reports it; replay returns the recovered ABANDONED Attempt;
  - after file publication and before database commit: one verified orphan Artifact, no database reference, recovered ABANDONED Attempt;
  - after database commit and before response: replay returns the original SUCCEEDED Attempt and the same Artifact manifest with `replayed=true`; row and file counts remain one;
  - a second restart changes no terminal state or count.

  `tests/security/test_m1b_artifact_boundaries.py` must cover project-root escape, symlink/junction/reparse traversal, noncanonical JSON, wrong Schema, a seventeenth Artifact, cumulative size above 64 MiB through an AttemptArtifactSink fixture whose underlying store returns fixed-size manifests, one real-store 64 MiB + 1 byte pre-staging rejection, tampered existing content, artifact-relative paths with backslash or `..`, unexpected staging ownership, and cleanup restricted to the current Session's known staging files. Each failure asserts its exact error code/details and that original bytes remain unchanged.

- [ ] **Step 2: Run and observe the absent fault seam**

  ```powershell
  uv run --locked --no-sync pytest tests/integration/test_fault_recovery.py tests/security/test_m1b_artifact_boundaries.py -q
  ```

  Expected: collection fails on `modeling_core.ports.faults` or every subprocess incorrectly returns a response; exit is nonzero.

- [ ] **Step 3: Add only named checkpoints and fail-closed boundaries**

  Insert `FaultInjector.check` exactly at the five specified boundaries. Production composition always supplies `NoFaults`; no environment variable, MCP field or CLI option may activate faults in the production entry point. The fixture composition is the sole place that constructs `ScriptedProcessExitFaults`, and it terminates with `os._exit(91)` so ordinary exception handling cannot disguise a crash.

  Staging filenames include Session ID and an unguessable UUID. Restart inspection never deletes an unknown or previous-session file automatically; it reports it. Enforce 16 files and 64 MiB before final database commit, recheck the cooperative deadline after publication, and treat a post-publish timeout as an orphan plus TIMED_OUT terminal record. All path and integrity violations fail closed without repair.

- [ ] **Step 4: Run the five real crash windows**

  ```powershell
  uv run --locked --no-sync pytest tests/integration/test_fault_recovery.py -q
  uv run --locked --no-sync pytest tests/security/test_m1b_artifact_boundaries.py -q
  ```

  Expected: both commands exit 0; each crash subprocess exits 91; restart and replay assertions establish no missing-file database reference and no duplicate execution entity.

- [ ] **Step 5: Run full storage/recovery/security regression**

  ```powershell
  uv run --locked --no-sync ruff check src/modeling_core/ports/faults.py src/modeling_core/application src/modeling_infrastructure tests/fixtures/fault_server.py tests/integration/test_fault_recovery.py tests/security
  uv run --locked --no-sync mypy src/modeling_core/ports/faults.py src/modeling_core/application src/modeling_infrastructure tests/fixtures/fault_server.py
  uv run --locked --no-sync pytest tests/contract/test_artifact_store.py tests/contract/test_sqlite_schema_v2.py tests/integration/test_artifact_workflow.py tests/integration/test_recovery_and_rerun.py tests/integration/test_fault_recovery.py tests/security -q
  ```

  Expected: all commands exit 0; no test retry or timing sleep is used; fault assertions rely on committed state and bounded subprocess timeouts.

- [ ] **Step 6: Commit**

  ```powershell
  git add src/modeling_core/ports/faults.py src/modeling_core/application/service.py src/modeling_infrastructure/artifacts/store.py src/modeling_bootstrap/composition.py tests/fixtures/fault_server.py tests/integration/test_fault_recovery.py tests/security/test_m1b_artifact_boundaries.py
  git commit -m "test: prove crash-safe artifact recovery"
  ```

**Acceptance:** all five approved fault windows are exercised by process death; database references never precede files; an orphan is safe, immutable and reportable; response loss replays one committed success; limits and path boundaries return structured failures without overwriting evidence.

### Work Package B-III — Reproducibility and maintainability

### Task B8: Deepen doctor and prove mathematical/restart reproducibility

**Primary concern:** 让诊断能解释 M1b 溯源与制品状态，并用固定种子数学变形和 rerun 审计证明“可复现”的准确边界。

**Files:**

- Modify: `src/modeling_cli/doctor.py`, `tests/unit/test_doctor.py`, `docs/operations/bootstrap-and-doctor.md`
- Create: `src/modeling_harness/reproducibility.py`, `tests/math/test_root_finding_affine_v1.py`, `tests/reproducibility/test_m1b_rerun.py`

**Interfaces produced:** `ReproducibilityAuditor.audit(project_root, experiment_id, attempts) -> ReproducibilityReport`; doctor check IDs `artifact_references`, `input_drift`, `recovery_state`, `orphan_artifacts`, `staging_files`, `reproducibility_metadata`; versioned doctor JSON fields `status`, `exit_code`, `checks`, `warnings`, `unsafe_findings`.

- [ ] **Step 1: Write failing deep-doctor, affine and rerun tests**

  Extend `tests/unit/test_doctor.py` to require default mode to be read-only and deep mode to use only a separate temporary diagnostic project. Cover healthy references, missing/tampered result, missing report, orphan, previous-session staging, input drift, recovered ABANDONED entities, unknown Schema version and project lock conflict. Exact exits remain 0 ready, 1 warning-only, 2 unsafe; orphan and prior staging are warnings when all authoritative references verify, while missing/tampered references, drift, unknown versions and lock ambiguity are unsafe.

  `tests/math/test_root_finding_affine_v1.py` must use `random.Random(20260716)` to generate exactly 200 finite cases. Draw `r,c` uniformly from `[-10,10]`; draw `a,b` uniformly from `[-8,-0.125] ∪ [0.125,8]`; draw `d` uniformly from `[0.5,5]`; define `g(x)=a*(b*x+c-r)`, analytical root `x_star=(r-c)/b`, and bracket `[x_star-d,x_star+d]`. Serialize finite coefficients with Python's round-trip `repr`, use absolute/relative/function tolerances `1e-10` and `max_iterations=1000`, and assert the solver root and independently recomputed residual against the declared criteria. Add fixed expressions that separately trigger overflow, underflow-to-zero, domain error and nonfinite intermediate outcomes, and assert their exact structured numerical-failure classification. Persist and print seed `20260716` and the generated case index on failure.

  `tests/reproducibility/test_m1b_rerun.py` must compare new run, completed replay, rerun and post-restart rerun of one Experiment. It asserts identical immutable input/model/data/Schema/implementation identifiers, fresh EnvironmentSnapshot and Attempt for each rerun, `randomness=not_used`, `seed=null`, identical terminal classification, roots/residuals within contract tolerance, validation conclusions equal, and valid artifact relationships. It must not require byte identity because root finding does not declare bitwise reproducibility.

- [ ] **Step 2: Run and confirm missing auditor and M1b checks**

  ```powershell
  uv run --locked --no-sync pytest tests/unit/test_doctor.py tests/math/test_root_finding_affine_v1.py tests/reproducibility/test_m1b_rerun.py -q
  ```

  Expected: collection fails on `modeling_harness.reproducibility` or doctor lacks the first artifact check; exit is nonzero.

- [ ] **Step 3: Implement read-only inspection and declared-tolerance audit**

  Doctor must call `ProjectStore.inspect_integrity(deep)` and `ArtifactStore.inspect` without mutating authoritative state. Deep lock/no-clobber/recovery smoke creates a separate `TemporaryDirectory`, exercises create/run/validate/restart there, and removes only that directory. Its JSON contains relative paths or entity IDs, never full payloads, usernames, hostnames, secrets or absolute paths.

  `ReproducibilityAuditor` compares named invariants rather than whole response JSON. It distinguishes `equal`, `within_tolerance`, `not_comparable`, and `mismatch`, obtains tolerance and reproducibility claims from the sealed descriptor, and emits sorted mismatches with no raw secret-bearing environment. It fails when a supposedly immutable hash/version changes or a numeric result exceeds tolerance.

- [ ] **Step 4: Run focused diagnosis, math and reproducibility tests**

  ```powershell
  uv run --locked --no-sync pytest tests/unit/test_doctor.py tests/math/test_root_finding_affine_v1.py tests/reproducibility/test_m1b_rerun.py -q
  uv run --locked --no-sync modeling doctor --project-root tests/.tmp/manual-project --deep --json
  ```

  Expected: tests exit 0; a previously created healthy schema 2 project yields one versioned JSON object and exit 0; the affine suite reports seed `20260716` in its test metadata.

- [ ] **Step 5: Run all math, validation, recovery and privacy regressions**

  ```powershell
  uv run --locked --no-sync ruff check src/modeling_cli/doctor.py src/modeling_harness/reproducibility.py tests/unit/test_doctor.py tests/math tests/reproducibility
  uv run --locked --no-sync mypy src/modeling_cli/doctor.py src/modeling_harness/reproducibility.py
  uv run --locked --no-sync pytest tests/unit/root_finding tests/unit/test_doctor.py tests/math tests/reproducibility tests/integration/test_recovery_and_rerun.py tests/security -q
  ```

  Expected: all commands exit 0; required tests have zero skips and contain no retry decorator or unbounded sleep.

- [ ] **Step 6: Commit**

  ```powershell
  git add src/modeling_cli/doctor.py src/modeling_harness/reproducibility.py tests/unit/test_doctor.py tests/math/test_root_finding_affine_v1.py tests/reproducibility/test_m1b_rerun.py docs/operations/bootstrap-and-doctor.md
  git commit -m "test: audit M1b integrity and reproducibility"
  ```

**Acceptance:** doctor explains every authoritative/reference/orphan condition without repairing it; unsafe states stop writes; 200 fixed-seed affine cases and nonfinite branches pass; rerun/restart comparisons honor declared tolerance and do not claim unsupported bitwise reproducibility.

### Task B9: Complete progressive context routing and Built-in Capability Skills

**Primary concern:** 让维护者按任务只加载最小规则与数学上下文，并让新能力经摘要目录和按需 Skill 被发现。

**Required implementation sub-skill:** `superpowers:writing-skills` must be read before creating or editing any `SKILL.md` in this task.

**Files:**

- Modify: `docs/context/index.md`
- Create: `src/modeling_infrastructure/AGENTS.md`, `src/modeling_bootstrap/AGENTS.md`, `docs/AGENTS.md`, `.agents/skills/AGENTS.md`
- Create: `.agents/skills/add-capability/SKILL.md`, `.agents/skills/numerical-validation/SKILL.md`, `.agents/skills/stdio-diagnostics/SKILL.md`, `.agents/skills/reproducibility-audit/SKILL.md`, `.agents/skills/release-verification/SKILL.md`
- Create: `docs/capabilities/index.md`, `tests/architecture/test_context_boundaries.py`

**Interfaces produced:** task-to-context routing table; capability catalog row schema `capability_id | contract_version | status | summary | context | contract | tests`; five triggerable repository Skills with progressive disclosure.

- [ ] **Step 1: Write the failing context-boundary test**

  `tests/architecture/test_context_boundaries.py` must assert:

  1. root plus all eight nested `AGENTS.md` files exist and apply only to their directory scope;
  2. root `AGENTS.md` remains 100–150 lines and does not duplicate tool field tables, SQL DDL, mathematical derivations or full test commands;
  3. every task row in `docs/context/index.md` names root rules, the nearest nested rules, one product/architecture/contract route, optional Skill trigger and capability context only when needed;
  4. code change, Schema change, SQLite/recovery, MCP/STDIO, numerical method, validator, release and documentation tasks each have a distinct minimum route;
  5. each Skill has valid frontmatter, a precise trigger, procedure, verification and links, but does not copy the normative contract body;
  6. `docs/capabilities/index.md` lists only summary metadata and links `numerical.root_finding/1.0.0` to its local `context.md`, descriptor, contract docs, Schema directory and focused verify command;
  7. no catalog or Skill describes Built-in Capability as an External Plugin or claims dynamic discovery/install.

- [ ] **Step 2: Run and observe the absent context files**

  ```powershell
  uv run --locked --no-sync pytest tests/architecture/test_context_boundaries.py -q
  ```

  Expected: the test reports the four missing nested rule files, five missing Skills and missing capability index; exit is nonzero.

- [ ] **Step 3: Write narrow nested rules and the routing index**

  `src/modeling_infrastructure/AGENTS.md` owns SQLite, paths, atomicity, locks and recovery; `src/modeling_bootstrap/AGENTS.md` owns the unique composition root; `docs/AGENTS.md` owns authority boundaries, links and ADR lifecycle; `.agents/skills/AGENTS.md` owns triggers, progressive disclosure and prohibition on contract duplication. Each links upward and states only local invariants.

  `docs/context/index.md` must define conflict authority in this order: approved spec/accepted ADR for decisions, versioned JSON Schema for shape, contract docs for semantics, tests for executable examples, code for implementation; conflicts stop the task and are resolved by changing all lower authorities in the same increment. It must also state the minimum read set before each task category and forbid loading unrelated capability mathematics.

- [ ] **Step 4: Author and pressure-test the five Skills**

  Each Skill must be self-contained at the procedure level while linking normative details. `add-capability` ends in explicit composition registration and passes its normalized `capability_id: str` to the focused verify option; its executable example is `uv run --locked --no-sync modeling verify --capability numerical.root_finding`. `numerical-validation` enforces independent evaluator/search logic; `stdio-diagnostics` protects STDOUT; `reproducibility-audit` compares declared invariants; `release-verification` requires both platform results and evidence fingerprint. Run every validation script prescribed by `superpowers:writing-skills` for each created Skill.

- [ ] **Step 5: Run the focused context-boundary test**

  ```powershell
  uv run --locked --no-sync pytest tests/architecture/test_context_boundaries.py -q
  ```

  Expected: the focused test exits 0; all declared minimum-read routes, nested-rule links, Skill triggers and capability-discovery links resolve without loading unrelated mathematics.

- [ ] **Step 6: Run context, architecture and link regressions**

  ```powershell
  uv run --locked --no-sync pytest tests/architecture/test_dependency_boundaries.py tests/architecture/test_composition_root.py tests/architecture/test_solver_validator_independence.py tests/architecture/test_echo_extension.py -q
  uv run --locked --no-sync ruff check tests/architecture/test_context_boundaries.py
  ```

  Expected: both commands exit 0; architectural dependency, composition, solver/validator independence and extension proofs remain green; no test loads network content.

- [ ] **Step 7: Commit**

  ```powershell
  git add docs/context/index.md docs/capabilities/index.md docs/AGENTS.md src/modeling_infrastructure/AGENTS.md src/modeling_bootstrap/AGENTS.md .agents/skills tests/architecture/test_context_boundaries.py
  git commit -m "docs: add progressive project context"
  ```

**Acceptance:** every task class has a deterministic minimum read set; new capabilities are discoverable from one summary row and disclose mathematics only on demand; five Skills route procedures without becoming competing contract sources; all nested rules are scope-specific.

### Task B10: Publish stable architecture, contract, operations and ADR documentation

**Primary concern:** 把已实现的稳定边界、状态、恢复、安全和决策写成互相链接但不重复争夺权威的维护文档。

**Files:**

- Modify: `AGENTS.md`, `README.md`, `docs/context/index.md`, `docs/architecture/overview.md`, `src/modeling_capabilities/root_finding/context.md`
- Create: `docs/product/vision.md`, `docs/architecture/state-model.md`, `docs/architecture/security.md`
- Create: `docs/contracts/mcp-tools-v1.md`, `docs/contracts/capability-api-v1.md`, `docs/contracts/root-finding-v1.md`
- Create: `docs/operations/recovery.md`, `docs/operations/schema-evolution.md`, `docs/operations/release-verification.md`
- Create: `docs/adr/0001-modular-monolith.md`, `docs/adr/0002-ports-adapters-composition-root.md`, `docs/adr/0003-sqlite-content-addressed-artifacts.md`, `docs/adr/0004-explicit-built-in-capabilities.md`, `docs/adr/0005-local-stdio-mcp.md`, `docs/adr/0006-schema-semver-policy.md`, `docs/adr/0007-independent-solver-validator.md`, `docs/adr/0008-single-writer-lock-recovery.md`
- Create: `tests/acceptance/test_documentation_consistency.py`

**Interfaces produced:** stable human contract family v1; eight Accepted ADRs; release/operator routes; explicit roadmap M2, M2.5 and M3.

- [ ] **Step 1: Write the failing documentation consistency test**

  `tests/acceptance/test_documentation_consistency.py` must parse every listed Markdown file and assert:

  - all relative links and heading anchors resolve;
  - stable docs say application `0.2.0`, protocol `2025-11-25`, public contract axes `1.0.0` and database schema `2` exactly where relevant;
  - tool docs name exactly six tools and link every 1.0 request/result/error Schema;
  - capability/root docs link all six 1.0 root-finding Schema assets and distinguish API, contract, implementation, policy and report versions;
  - state docs contain every Project/Attempt/Validation transition, idempotency key and file-before-reference ordering;
  - security docs contain trust boundaries, 1 MiB request, 256 KiB inline response, 16 Artifact/64 MiB Attempt, 10-second default/60-second maximum cooperative deadline, path/reparse, lock, STDOUT and secret rules;
  - every ADR has title, Status `Accepted`, Date `2026-07-17`, Context, Decision, Consequences and Rejected Alternatives;
  - Built-in Capability and External Plugin meanings never overlap;
  - architecture names Codex as the first thin adapter and Claude Code/TRAE only as future thin adapters, while no core module, DTO or persisted field contains any host name;
  - M1a-0 is described only as a 48-hour non-production feasibility probe, never as a stable contract, formal capability or M1a completion substitute;
  - M1a documentation claims fixed/repeatability hash smoke only, while complete RFC 8785 conformance, provenance and vectors are owned exclusively by B2/M1b;
  - root execution rules require `Test result`, `Git diff summary` and `Commit hash` before any task is marked complete;
  - roadmap order is M1 trusted synchronous short tasks → M2 files/MMIR → M2.5 controlled worker/hard timeout/resource limits → M3 ODE/optimization/statistics;
  - the design risk register has an explicit owning mitigation and automated gate for scope growth, host coupling, solver/validator coupling, state/artifact inconsistency, cooperative-timeout limits, Schema drift, Windows path/process behavior and unreproducible evidence;
  - every external normative baseline used by contracts, packaging, canonicalization, Codex configuration or CI is linked from the owning document with the exact version, branch or protocol identifier consumed by the implementation;
  - no document claims M1 has hard process isolation, OCR, UI, multi-user service, automatic paper writing, dynamic plugin install or additional mathematics.

- [ ] **Step 2: Run and observe the missing stable document set**

  ```powershell
  uv run --locked --no-sync pytest tests/acceptance/test_documentation_consistency.py -q
  ```

  Expected: the test lists every absent stable document and ADR, then exits nonzero.

- [ ] **Step 3: Write product, architecture and contract documents at their authority boundaries**

  `vision.md` states users/outcomes/non-goals and roadmap. Architecture documents explain dependency direction, state/transaction flow and security boundaries. Contract documents define field semantics, invariants, error meaning, compatibility and worked valid/invalid examples, while linking Schema rather than duplicating JSON definitions. `root_finding/context.md` contains only method-specific math, conditioning limits, transformations and focused tests.

- [ ] **Step 4: Write operations manuals and eight decision records**

  Recovery documentation must enumerate each crash window, automatic convergence and manual no-repair policy. Schema evolution must describe immutable baselines, request contravariance/response compatibility, SemVer and baseline update review. Release verification must separate automated M1b verification, two-platform evidence and the release-only Codex smoke. Each ADR captures one decision from its filename, names the current callers it enables, and records why more general alternatives were rejected for M1.

- [ ] **Step 5: Run the focused documentation consistency test**

  ```powershell
  uv run --locked --no-sync pytest tests/acceptance/test_documentation_consistency.py -q
  uv run --locked --no-sync python -c "from pathlib import Path; files=list(Path('docs').rglob('*.md')); print(len(files)); assert all(p.read_text(encoding='utf-8').strip() for p in files)"
  ```

  Expected: both commands exit 0; the printed document count equals the checked-in Markdown inventory asserted by the consistency test; no broken local link, version mismatch, authority conflict, missing risk owner or empty document exists.

- [ ] **Step 6: Run contract and context regressions**

  ```powershell
  uv run --locked --no-sync pytest tests/architecture/test_context_boundaries.py tests/contract/test_tool_schemas_v1.py tests/contract/test_schema_compatibility.py -q
  ```

  Expected: command exits 0; documentation changes preserve context routing, stable Schema shape and the compatibility baseline.

- [ ] **Step 7: Commit**

  ```powershell
  git add AGENTS.md README.md docs src/modeling_capabilities/root_finding/context.md tests/acceptance/test_documentation_consistency.py
  git commit -m "docs: publish stable M1 architecture and decisions"
  ```

**Acceptance:** product, architecture, contract and operations boundaries are explicit; all 8 ADRs are Accepted and decision-specific; all versions/limits/tool names match executable assets; M2.5 process isolation is visible on the roadmap but no worker abstraction appears in M1.

### Work Package B-IV — Cross-platform release evidence

### Task B11: Make M1b verification a strict superset and run it identically on Windows and Ubuntu

**Primary concern:** 用一个跨平台 Python Harness 证明所有自动化验收，并让两种操作系统执行完全相同的完成命令。

**Files:**

- Modify: `src/modeling_harness/verify.py`, `src/modeling_harness/evidence.py`
- Create: `tests/integration/test_stdio_restart_m1b.py`, `tests/acceptance/test_m1b_acceptance_map.py`, `.github/workflows/verify.yml`

**Interfaces produced:** `M1B_CHECK_IDS` as a strict ordered superset of `M1A_CHECK_IDS`; `modeling verify --milestone m1b`; focused developer feedback `modeling verify --capability numerical.root_finding`; per-platform evidence report; GitHub Actions matrix `windows-latest` and `ubuntu-latest`.

- [ ] **Step 1: Write failing restart, profile and acceptance-map tests**

  `tests/integration/test_stdio_restart_m1b.py` must use the generic MCP client and real subprocesses to execute this stable sequence on fresh projects:

  ```text
  initialize → tools/list → health_check → create_project → run_experiment(new)
  → close process → restart → replay same operation → run_experiment(rerun)
  → validate_experiment → get_project_status paginated trace → clean close
  ```

  It must assert six tool names, 1.0 Schema, one result Artifact per successful Attempt, one report Artifact, replay identity, a new Attempt for rerun, stable pagination with no duplicate/omitted trace records, protocol-pure stdout and bounded process-handle closure on both OS families. A separate fresh project is tampered after shutdown; restart plus replay must return `INTEGRITY_FAILURE` and never a stale success.

  `tests/acceptance/test_m1b_acceptance_map.py` must assert exactly A-01 through A-10 and B-01 through B-10, with each ID mapped to existing exact pytest node IDs and evidence JSON Pointers. It must also assert `set(M1A_CHECK_IDS) < set(M1B_CHECK_IDS)`, every M1a check keeps the same implementation, required skip count is zero, and `.github/workflows/verify.yml` contains only Python 3.11 with OS matrix `windows-latest, ubuntu-latest` and the identical command `uv run --locked --no-sync modeling verify --milestone m1b`.

- [ ] **Step 2: Run and observe missing restart/profile coverage**

  ```powershell
  uv run --locked --no-sync pytest tests/integration/test_stdio_restart_m1b.py tests/acceptance/test_m1b_acceptance_map.py -q
  ```

  Expected: restart behavior may pass partially, but acceptance fails because the M1b profile, B evidence map and workflow are absent; exit is nonzero.

- [ ] **Step 3: Register the ordered M1b check profile**

  Preserve every M1a check object and append these deterministic groups: stable Schema/corpus and baseline compatibility; complete RFC vectors; ArtifactStore/SQLite v2; artifact workflow; recovery/rerun; five fault windows; M1b security; affine mathematics; restart reproducibility; test.echo/scaffold; context boundaries; stable documents/ADRs; stable STDIO restart; A/B acceptance map; packaged asset inventory. Run pytest groups as subprocess argument arrays, never through a platform shell. A skipped required test, retry marker, missing corpus, changed baseline, stale source fingerprint or unsupported platform makes the profile fail.

  Evidence JSON records report Schema version, milestone, OS family/distribution/version/architecture, Python and uv versions, lock hash, source fingerprint, check ID/status/duration/test/pass/fail/skip counts, redacted diagnostics and referenced report paths. Linux distribution comes from an allowlisted parse of `/etc/os-release`; Windows version comes from `platform`, and neither includes hostname or username. Write the JSON and its Markdown summary through a sibling staging directory and atomic rename. Build the source inventory from NUL-delimited `git ls-files --cached --others --exclude-standard`; reject a listed-but-missing file; NFC-normalize each repository-relative POSIX path; hash each file's raw bytes; sort records by UTF-8 path bytes; construct the complete JSON array whose every object has exactly `path` and `sha256`, then compute `source_fingerprint = sha256_json(source_file_digest_array)` without truncation. This includes not-yet-committed task files during focused development but excludes ignored `.venv`, `.modeling`, caches and `build/`. Use the 64-hex suffix after `sha256:` as the Windows-safe evidence-directory component.

- [ ] **Step 4: Add the exact two-platform workflow**

  `.github/workflows/verify.yml` must trigger on pull requests, pushes to `main`, and manual dispatch; grant only `contents: read`; use a fail-fast false matrix with `windows-latest` and `ubuntu-latest`; and contain these exact functional steps:

  ```yaml
  - uses: actions/checkout@v6
  - uses: astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990 # v8.3.2
    with:
      version: "0.11.28"
      python-version: "3.11"
      enable-cache: false
  - run: uv sync --locked --group dev
  - run: uv run --locked --no-sync modeling verify --milestone m1b
  - uses: actions/upload-artifact@v7
    if: always()
    with:
      name: m1b-${{ runner.os }}-${{ github.sha }}
      path: build/verification/m1b/
      if-no-files-found: error
  ```

  Do not place OS-conditional test commands in the workflow. Platform-specific behavior belongs inside production adapters or tests, while the verification interface remains identical.

- [ ] **Step 5: Run the full automated M1b gate locally**

  ```powershell
  uv run --locked --no-sync pytest tests/integration/test_stdio_restart_m1b.py tests/acceptance/test_m1b_acceptance_map.py -q
  uv run --locked --no-sync modeling verify --milestone m1b
  ```

  Expected: both commands exit 0; verify's first line is `milestone=m1b`; required skips are 0; A-01 through A-10 and B-01 through B-10 have automated evidence entries; the printed evidence directory is `build/verification/m1b/{source_fingerprint_hex}` with the final component replaced by the computed 64-character lowercase hex suffix of report field `source_fingerprint`.

- [ ] **Step 6: Run M1a-superset and packaging regression**

  ```powershell
  uv run --locked --no-sync modeling verify --milestone m1a
  uv build
  uv run --locked --no-sync python -c "from zipfile import ZipFile; from pathlib import Path; w=next(Path('dist').glob('*.whl')); names=ZipFile(w).namelist(); assert any(n.endswith('.schema.json') for n in names); assert any(n.endswith('schema_v2.sql') for n in names); print(w.name, len(names))"
  ```

  Expected: M1a still exits 0; wheel build exits 0; the inspection prints one wheel name and positive member count, proving stable Schema and SQL assets are packaged. `dist/` remains ignored and unstaged.

- [ ] **Step 7: Commit**

  ```powershell
  git add src/modeling_harness tests/integration/test_stdio_restart_m1b.py tests/acceptance/test_m1b_acceptance_map.py .github/workflows/verify.yml
  git commit -m "ci: verify M1b on Windows and Ubuntu"
  ```

**Acceptance:** M1b is a strict programmatic superset of M1a; one command passes locally and is the sole CI verification command on both OSes; real restart/tamper behavior is exercised; reports are atomic, fingerprinted and have zero required skips; packaged assets are present.

### Task B12: Assemble completion evidence and run the Codex-hosted golden chain

**Primary concern:** 将自动测试、双平台结果、可追溯黄金实验和正式六工具 Codex 宿主烟测汇成可验证且脱敏的最终完成证据包；它取代而不是复用 M1a-0 的单工具证明。

**Files:**

- Modify: `src/modeling_harness/evidence.py`, `src/modeling_harness/verify.py`, `src/modeling_cli/main.py`, `docs/operations/release-verification.md`
- Create: `tests/acceptance/test_release_evidence.py`
- Modify: `tests/acceptance/test_m1b_acceptance_map.py`

**Interfaces produced:** `assemble_release_bundle(inputs: ReleaseEvidenceInputs, destination: Path) -> ReleaseBundleManifest`; `validate_release_bundle(path: Path, expected_source_fingerprint: str) -> ReleaseValidationReport`; CLI subcommands `modeling evidence assemble` with required Path options `--windows-report`, `--ubuntu-report`, `--codex-transcript`, `--destination`, and `modeling evidence validate` with required `--bundle` Path and `--source-fingerprint` Hash.

- [ ] **Step 1: Write the failing release-evidence contract test**

  `tests/acceptance/test_release_evidence.py` must create synthetic but Schema-valid Windows, Ubuntu, STDIO, trace, compatibility, math/reproducibility, recovery, security and Codex records under `tmp_path`. It must assert that assembly accepts only one common source fingerprint and commit, both distinct required platforms, all A/B IDs, zero required skips, all PASS, valid artifact hashes and a Codex transcript containing calls to exactly the six enabled modeling tools. It must reject a stale fingerprint, missing platform, duplicate platform, failed/skipped check, missing B ID, absolute path, secret-shaped value, raw environment, unredacted payload, altered evidence byte or Codex shell/tool use outside the allowlist.

- [ ] **Step 2: Run and confirm the missing assembler failure**

  ```powershell
  uv run --locked --no-sync pytest tests/acceptance/test_release_evidence.py -q
  ```

  Expected: collection fails because `assemble_release_bundle` and `validate_release_bundle` are absent; exit is nonzero.

- [ ] **Step 3: Implement deterministic evidence assembly and validation**

  Extend `evidence.py` with strict frozen input models. Copy evidence by verified bytes into a staging bundle, redact diagnostics through an allowlist, canonicalize every JSON file, compute a SHA-256 inventory, write `release-manifest.json` last, fsync, then atomically rename the bundle. Validation recomputes every hash, checks source/commit/platform/check/acceptance relationships and never trusts filenames alone. It does not fetch CI data, invoke Codex or update baselines; those remain explicit operator inputs.

  The final bundle contains exactly: `release-manifest.json`, `verification/windows/`, `verification/ubuntu/`, `schema/compatibility-report.json`, `math/reproducibility-report.json`, `recovery/fault-report.json`, `security/security-report.json`, `trace/golden-trace.json`, `trace/artifact-hashes.json`, `stdio/generic-mcp-transcript.json`, `hosts/codex-transcript.jsonl`, `acceptance/coverage-map.json`, and `SUMMARY.md`.

- [ ] **Step 4: Run the focused evidence test**

  ```powershell
  uv run --locked --no-sync pytest tests/acceptance/test_release_evidence.py -q
  ```

  Expected: command exits 0; synthetic valid bundles pass, every mutation fails for its asserted reason, and no generated fixture escapes `tmp_path`.

- [ ] **Step 5: Run acceptance, lint and type regressions**

  ```powershell
  uv run --locked --no-sync pytest tests/acceptance/test_m1b_acceptance_map.py -q
  uv run --locked --no-sync ruff check src/modeling_harness/evidence.py src/modeling_cli/main.py tests/acceptance
  uv run --locked --no-sync mypy src/modeling_harness/evidence.py src/modeling_cli/main.py
  ```

  Expected: all commands exit 0; the release bundle remains linked to every M1b acceptance ID and the changed Harness/CLI surfaces remain lint- and type-clean.

- [ ] **Step 6: Commit the evidence implementation and establish a clean candidate**

  ```powershell
  git add src/modeling_harness/evidence.py src/modeling_harness/verify.py src/modeling_cli/main.py docs/operations/release-verification.md tests/acceptance/test_release_evidence.py tests/acceptance/test_m1b_acceptance_map.py
  git commit -m "test: assemble the M1 completion evidence"
  uv run --locked --no-sync modeling verify --milestone m1a
  uv run --locked --no-sync modeling verify --milestone m1b
  git status --short
  ```

  Expected: commit succeeds; both profiles exit 0 with zero required skips; generated evidence remains ignored; `git status --short` is empty. From this point, any source/config/docs/test edit invalidates the candidate and requires repeating Steps 6–10 from a new commit.

- [ ] **Step 7: Obtain both CI reports for the exact release commit**

  Push or open a pull request containing the exact commit intended for review, wait for both matrix jobs, then run from a checkout of that same commit:

  ```powershell
  $commit = (git rev-parse HEAD).Trim()
  if (Test-Path -LiteralPath 'build/ci-evidence') { throw 'build/ci-evidence already exists; inspect it instead of mixing runs' }
  $run = gh run list --workflow verify.yml --commit $commit --status completed --json databaseId,conclusion,headSha --limit 1 | ConvertFrom-Json
  if ($run.Count -ne 1 -or $run[0].conclusion -ne 'success' -or $run[0].headSha -ne $commit) { throw 'matching successful verify run not found' }
  gh run download $run[0].databaseId --dir build/ci-evidence
  ```

  Expected: commands exit 0; `build/ci-evidence` contains one Windows and one Ubuntu artifact; both reports have the exact `$commit`, identical source fingerprint, milestone `m1b`, zero required skips and all required checks PASS. A local-only equivalent is insufficient for B-09 because it cannot prove the second OS.

- [ ] **Step 8: Run the Codex smoke from a disposable trusted checkout**

  Create a fresh checkout outside the authoritative project state, copy the reviewed template to `.codex/config.toml`, establish that checkout as trusted through Codex's normal trust control, and execute:

  ```powershell
  $commit = (git rev-parse HEAD).Trim()
  $sourceRoot = (Get-Location).Path
  $smokeRoot = Join-Path ([IO.Path]::GetTempPath()) 'math-modeling-mcp-codex-release-smoke'
  if (Test-Path -LiteralPath $smokeRoot) { throw 'Codex smoke checkout already exists; inspect it instead of overwriting it' }
  git clone --no-local $sourceRoot $smokeRoot
  git -C $smokeRoot checkout --detach $commit
  if ((git -C $smokeRoot rev-parse HEAD).Trim() -ne $commit) { throw 'smoke checkout commit mismatch' }
  Push-Location $smokeRoot
  try {
    uv sync --locked --group dev
    New-Item -ItemType Directory -Path '.codex' | Out-Null
    New-Item -ItemType Directory -Path 'build' | Out-Null
    Copy-Item -LiteralPath 'docs/templates/codex/config.toml' -Destination '.codex/config.toml'
    $confirmation = Read-Host "Mark $smokeRoot trusted through Codex's normal trust control, then enter TRUSTED"
    if ($confirmation -ne 'TRUSTED') { throw 'trusted-project confirmation missing' }
    $mcpList = codex mcp list
    if ($LASTEXITCODE -ne 0 -or ($mcpList -join "`n") -notmatch 'modeling') { throw 'project modeling MCP config was not loaded' }
    $prompt = 'Use only the project modeling MCP tools; do not run shell commands. Call all six enabled tools. First call health_check. Call create_project with operation_id 10000000-0000-4000-8000-000000000001. Call get_project_status summary. Call list_capabilities for the exact numerical.root_finding contract. Call run_experiment new with operation_id 10000000-0000-4000-8000-000000000002 for x*x-2 on [0,2], absolute_tolerance 1e-10, the advertised 1.0 contract, and the capability declared randomness policy without inventing a seed. Call validate_experiment with operation_id 10000000-0000-4000-8000-000000000003 and the residual validator. Finally call get_project_status for the returned experiment and reconstruct its trace. Report returned entity IDs, hashes, root, residual and validation outcome; perform no extra computation.'
    codex exec --ephemeral --json --sandbox workspace-write $prompt | Tee-Object -FilePath 'build/codex-transcript.jsonl'
    if ($LASTEXITCODE -ne 0) { throw 'Codex smoke failed' }
  }
  finally {
    Pop-Location
  }
  ```

  Expected: Codex exits 0; the transcript shows only modeling MCP tool calls, all six enabled tools appear at least once, the numerical result satisfies design §16.1, validation is PASSED, and no shell call appears. The trust action is an explicit release prerequisite because Codex loads project-scoped `.codex/config.toml` only for trusted projects; the Harness must not edit global Codex trust settings.

- [ ] **Step 9: Assemble and validate the real completion bundle**

  Discover the two downloaded reports by their validated contents, not by archive directory naming, and run:

  ```powershell
  $commit = (git rev-parse HEAD).Trim()
  $smokeRoot = Join-Path ([IO.Path]::GetTempPath()) 'math-modeling-mcp-codex-release-smoke'
  $windowsReport = $null
  $ubuntuReport = $null
  $fingerprint = $null
  $reportFiles = @(Get-ChildItem -LiteralPath 'build/ci-evidence' -Recurse -Filter 'verification-report.json' -File)
  if ($reportFiles.Count -ne 2) { throw "expected two CI reports, found $($reportFiles.Count)" }
  foreach ($file in $reportFiles) {
    $report = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json
    if ($report.commit -ne $commit) { throw 'CI report commit mismatch' }
    if ($null -eq $fingerprint) { $fingerprint = $report.source_fingerprint }
    elseif ($fingerprint -ne $report.source_fingerprint) { throw 'CI source fingerprint mismatch' }
    if ($report.platform.os_family -eq 'Windows') { $windowsReport = $file.FullName }
    elseif ($report.platform.os_family -eq 'Linux' -and $report.platform.distribution -eq 'Ubuntu') { $ubuntuReport = $file.FullName }
    else { throw "unexpected CI platform $($report.platform.os_family)" }
  }
  if ($null -eq $windowsReport -or $null -eq $ubuntuReport) { throw 'Windows or Ubuntu report missing' }
  uv run --locked --no-sync modeling evidence assemble --windows-report $windowsReport --ubuntu-report $ubuntuReport --codex-transcript "$smokeRoot/build/codex-transcript.jsonl" --destination "build/release-evidence/$commit"
  uv run --locked --no-sync modeling evidence validate --bundle "build/release-evidence/$commit" --source-fingerprint $fingerprint
  ```

  Expected: assembly and validation exit 0; all inventory hashes verify; the bundle has both platforms, generic MCP and Codex transcripts, golden IDs/trace, all §8.5 named hashes plus the four-way result-integrity comparison, compatibility/math/recovery/security reports, A-01 through B-10 coverage and no absolute path or secret finding.

- [ ] **Step 10: Run the final clean-tree and bundle gate**

  ```powershell
  $commit = (git rev-parse HEAD).Trim()
  $fingerprint = (Get-Content -LiteralPath "build/release-evidence/$commit/release-manifest.json" -Raw | ConvertFrom-Json).source_fingerprint
  uv run --locked --no-sync modeling verify --milestone m1a
  uv run --locked --no-sync modeling verify --milestone m1b
  uv run --locked --no-sync pytest tests/acceptance/test_release_evidence.py -q
  uv run --locked --no-sync modeling evidence validate --bundle "build/release-evidence/$commit" --source-fingerprint $fingerprint
  git status --short
  ```

  Expected: both milestone profiles, the focused evidence test and real bundle validation exit 0; the manifest commit equals `$commit`; generated `build/` content is ignored; `git status --short` is empty.

**Acceptance:** the exact reviewed source has successful Windows and Ubuntu reports, a real generic MCP transcript, a real Codex-hosted six-tool trace, verified result/report artifacts, complete A/B mapping and a canonical tamper-evident evidence bundle; only then may the release be called “M1 complete.”

## M1 Final Hard Gate

M1 completion requires all of the following for one source fingerprint and one commit:

- M1a-0's timeboxed feasibility record identifies its earlier Spike commit and is explicitly distinguished from the production completion evidence;
- M1a and M1b verification each exit 0 with zero required skips;
- Windows and Ubuntu ran the same M1b command and their uploaded reports validate;
- B-01 through B-10 and retained A-01 through A-10 all have exact test node IDs and evidence JSON Pointers;
- the golden result is from real execution, the residual validator is independent and PASSED, and all persisted hashes recompute;
- all five crash windows, compatibility mutations, complete RFC vectors, fixed-seed affine set, rerun/restart, no-clobber and security matrices pass;
- root/nested AGENTS, five Skills, stable contracts, operations manuals and eight ADRs pass link/version/authority checks;
- the Codex smoke used the checked-in template from a trusted disposable checkout and the core contains no Codex type or import;
- all 25 task handoffs (M1a-0, A1–A12, B1–B12) contain test result, staged git diff summary and full commit hash;
- the release evidence inventory validates and `git status --short` is empty.

Failure of any item blocks the completion claim. It does not authorize baseline regeneration, test relaxation, automatic repair, evidence deletion or implementation of M2/M2.5/M3 work.

---

## Specification Coverage Matrix

| Required area | Implementing tasks | Primary automated evidence |
|---|---|---|
| 48-hour host/protocol feasibility | M1a-0 | direct + real STDIO tests, verified Codex single-call transcript, timebox record |
| Project infrastructure, uv, bootstrap, single verify | M1a-0, A1, A4, A11, A12, B11 | root lock, CLI smoke, bootstrap integration, both milestone profiles |
| Core domain and Application Facade | A3, A9, B5, B6 | domain unit tests, direct Facade workflow, recovery/rerun |
| SQLite state and traceability | A4, A9, B4–B6 | ProjectStore contract, schema v1/v2, artifact workflow |
| Built-in Capability contract and explicit registry | A5, B1, B3 | registry unit/contract tests, test.echo extension proof |
| Root finding and canonical input | M1a-0, A6, A7, B1, B2, B8 | disposable round trip, parser/stable-hash smoke, solver, RFC/affine tests |
| Independent validator | A8, A9, B5 | forged-result rejection, import boundary, artifact-backed validation |
| Six-tool local STDIO MCP | A10, A11, B1, B11 | adapter contract, real M1a golden pipe, stable restart/tamper pipe |
| CLI doctor and diagnostics | A12, B8 | four-state unit tests, deep artifact/recovery diagnostics |
| Codex MCP configuration | M1a-0, A12, B12 | feasibility config/transcript, production template acceptance, release transcript |
| Unit, contract, integration, architecture tests | M1a-0, A2–A12, B1–B11 | Spike smoke plus layer-specific pytest groups in strict-superset Harness |
| Mathematical metamorphic tests | A7, A8, B8 | basic transformations, forged result, 200-case affine set |
| Schema compatibility | B1, B2 | immutable manifests, mutation comparator, complete corpus |
| Canonical JSON phase boundary | A2, A6, B2 | M1a fixed/repeatability hash smoke; M1b-only complete RFC 8785 conformance check |
| Reproducibility and fault recovery | A11, B6–B8 | repeatability, rerun/restart, five process-exit windows |
| Context Engineering and capability discovery | A12, B9 | context boundary and link tests |
| Documentation and eight ADRs | A12, B10 | documentation consistency test |
| Risk register and owning mitigations | A11, B2, B4, B6–B8, B10–B12 | security, recovery, compatibility, cross-platform and release-evidence gates |
| External normative baselines and provenance | M1a-0, A1, A2, A10, A12, B2, B10–B12 | dependency lock, protocol tests, canonical vectors, config acceptance and CI provenance |
| Agent task completion discipline | M1a-0, A1–A12, B1–B12 | fresh test result, staged diff stat/check and full commit object ID per task |
| Windows/Ubuntu and completion evidence | B11, B12 | CI matrix reports, release bundle validator |
| Explicit M1 exclusions and M2.5 worker route | A12, B10 | scope/roadmap documentation assertions |

### Approved design §1–§23 trace

| Design section | Plan location / implementing tasks | Reviewable evidence |
|---|---|---|
| §1 文档目的 | Goal, Global Constraints, M1a-0/M1a/M1b gates, planning-only stop boundary | plan structure and final stop assertion |
| §2 仓库探索结论 | Repository Baseline, M1a-0 | baseline file inventory, Git initialization precondition |
| §3 术语 | Global Constraints, Exact Public Interfaces, A5, B3, B9, B10 | terminology assertions and documentation consistency test |
| §4 产品边界 | Goal, Global Constraints, M1a-0, A12, B10 | timeboxed feasibility boundary, M1 scope and explicit exclusions |
| §5 架构方案比较 | approved modular-monolith choice, A3, A10, B10 | ADR 0001 preserves the approved choice and rejected alternatives without reopening Phase 0 |
| §6 系统架构 | Architecture summary, Abstraction Budget, A3, A9, A10, B4–B7 | dependency/composition tests and direct/STDIO workflows |
| §7 模块职责 | Complete File Map, A3, A10, B9, B10 | one responsibility per file plus architecture/context tests |
| §8 数据流与状态模型 | A3, A4, A9, B4–B8 | transition, store, artifact, recovery and rerun tests |
| §9 Built-in Capability 契约 | A5, B1, B3, B5 | registry/Schema contracts and test.echo extension proof |
| §10 numerical.root_finding | M1a-0, A6–A8, B1, B2, B8 | disposable call, parser, solver, independent validator, RFC and affine tests |
| §11 MCP 工具边界 | M1a-0, A2, A10, A11, B1, B6, B11 | feasibility and formal six-tool Schema/adapter/STDIO evidence |
| §12 项目状态、SQLite 与制品 | A4, A9, B4–B7 | schema 1/2, store, artifact, integrity and crash-recovery tests |
| §13 Context Engineering | A12, B9, B10 | context routing, nested-rule, Skill and documentation checks |
| §14 Harness Engineering | Agent Execution Discipline, M1a-0, A1, A11, A12, B2, B7, B8, B11, B12 | per-task evidence plus verify, compatibility, fault, reproducibility and release gates |
| §15 错误处理和安全 | A2, A4, A6, A10, A11, B4, B6–B8, B10 | strict errors plus path, STDIO, deadline, artifact and fail-closed tests |
| §16 测试与验收标准 | M1a-0, A2–A12, B1–B12, all hard gates | feasibility, layer-specific tests, per-task records, acceptance maps and completion bundle |
| §17 Context 与文档交付清单 | Complete File Map, A12, B9, B10 | exact documentation inventory and link/authority checks |
| §18 M1a 延后项与 M1 明确不做 | Global Constraints, M1b entry boundary, A12, B10 | scope assertions reject worker, queue, OCR, UI, remote/multi-user and extra math claims |
| §19 后续演进路线 | A12, B10 | asserted order M1 → M2 → M2.5 → M3 |
| §20 风险与缓解 | A11, B2, B4, B6–B8, B10–B12 | owning risk mitigations tied to security, compatibility, recovery, platform and evidence gates |
| §21 设计一致性与实施边界 | M1a-0 isolation, Dependency/Abstraction Budgets, phase gates, Plan Author Self-Check | version/type/YAGNI checks and no-implementation boundary |
| §22 需求覆盖索引 | Specification Coverage Matrix, this trace, A12, B11, B12 | A-01–B-10 acceptance maps and evidence JSON Pointers |
| §23 规范性外部基线 | Normative References, M1a-0, A1, A2, A10, A12, B2, B10–B12 | locks, protocol/version assertions, provenance records, config/CI evidence |

Every user-required area has at least one implementation task, one focused failing test before implementation, one regression command and one completion-evidence location. M1a-0 contains one timeboxed non-production task; formal M1a contains 12 top-level tasks in four ordered work packages; M1b contains 12 top-level tasks in four ordered work packages. All 25 tasks use the same mandatory test/diff/commit completion record.

## Plan Author Self-Check

The plan author must run these read-only checks against this document before handing it off:

```powershell
$plan = 'docs/superpowers/plans/2026-07-17-math-modeling-mcp-m1.md'
$spike = (Select-String -LiteralPath $plan -Pattern '^### Task M1a-0:').Count
$a = (Select-String -LiteralPath $plan -Pattern '^### Task A[0-9]+:').Count
$b = (Select-String -LiteralPath $plan -Pattern '^### Task B[0-9]+:').Count
$awp = (Select-String -LiteralPath $plan -Pattern '^### Work Package A-').Count
$bwp = (Select-String -LiteralPath $plan -Pattern '^### Work Package B-').Count
Write-Output "SPIKE_TASKS=$spike A_TASKS=$a B_TASKS=$b A_PACKAGES=$awp B_PACKAGES=$bwp"
if ($spike -ne 1 -or $a -ne 12 -or $b -ne 12) { throw "task budget mismatch: spike=$spike A=$a B=$b" }
if ($awp -ne 4 -or $bwp -ne 4) { throw "work-package budget mismatch: A=$awp B=$bwp" }
$commitSteps = (Select-String -LiteralPath $plan -Pattern '^\s+git commit -m ').Count
$acceptances = (Select-String -LiteralPath $plan -Pattern '^\*\*Acceptance:\*\*').Count
Write-Output "COMMIT_STEPS=$commitSteps ACCEPTANCES=$acceptances"
if ($commitSteps -ne 25 -or $acceptances -ne 25) { throw "task completion structure mismatch: commits=$commitSteps acceptances=$acceptances" }
$mapLine = (Select-String -LiteralPath $plan -Pattern '^## Complete File Map$').LineNumber
$firstTaskLine = (Select-String -LiteralPath $plan -Pattern '^### Task M1a-0:').LineNumber
if ($mapLine -ge $firstTaskLine) { throw 'file map must precede implementation tasks' }
$forbidden = Select-String -LiteralPath $plan -Pattern '(T[B]D|T[O]DO|F[I]XME|适当的测[试]|类似任[务]|其余文[件])'
if ($forbidden) { $forbidden | Format-Table LineNumber,Line; throw 'placeholder language found' }
$required = @('M1a-0','48-hour','ApplicationFacade','ProjectStore','BuiltInCapability','CapabilityValidator','ArtifactStore','FaultInjector','health_check','create_project','get_project_status','list_capabilities','run_experiment','validate_experiment','canonical-json-conformance','Test result','Git diff summary','Commit hash','M2.5','External Plugin')
foreach ($name in $required) { if (-not (Select-String -LiteralPath $plan -SimpleMatch $name -Quiet)) { throw "missing required term: $name" } }
```

Expected: command exits 0, prints `SPIKE_TASKS=1 A_TASKS=12 B_TASKS=12 A_PACKAGES=4 B_PACKAGES=4`, counts exactly 25 commit steps and 25 acceptance blocks, confirms the file map precedes M1a-0, and prints no placeholder match.

### Type and version consistency checklist

- Application Facade has exactly six strict request/result method pairs; MCP maps one tool name to each pair and contains no math implementation.
- M1a-0 exposes only one disposable fixed-equation tool outside `src/`; no formal DTO, package, test gate or wheel imports it.
- `VersionSet.m1a()` is application 0.1.0/public 0.1.0/database 1; `VersionSet.m1b()` is application 0.2.0/public 1.0.0/database 2; protocol is 2025-11-25 in both.
- M1a verifies fixed/repeatability hash smoke only; `canonical-json-conformance` and all complete RFC 8785 vectors are M1b-only.
- Artifact ID, artifact SHA-256, result hash and validation report hash have explicit byte domains; only Artifact ID equals its Artifact SHA-256.
- `run_experiment(new)` creates InputSnapshot/Experiment/Attempt; `rerun` reuses InputSnapshot/Experiment and creates an Attempt; replay creates nothing.
- validator input is a verified committed ResultSnapshot view, never an `ExecutionOutcome` or caller-provided payload.
- ProjectStore and ArtifactStore expose use-case-shaped operations only; concrete SQLite/path types remain in infrastructure and are assembled only in bootstrap.
- Built-in Capability, External Plugin, capability API version, capability contract version and implementation version are distinct terms throughout.
- M1 cooperative deadline and M2.5 process hard timeout are not conflated.

The plan is ready for implementation only after the mechanical check passes and a manual comparison against every approved design section (§§1–23) finds no uncovered requirement, unresolved risk, authority conflict or type-name conflict. This document contains no authorization to begin implementation in the current planning session.

### Authoring-time check result — 2026-07-18

| Check | Result | Evidence in this plan |
|---|---|---|
| Task and work-package budget | PASS | one non-production M1a-0 task plus A1–A12 and B1–B12; formal A-I–A-IV and B-I–B-IV budgets remain unchanged |
| TDD and review structure | PASS | all 25 tasks have contiguous steps ordered failing test → observed failure → minimum implementation → focused pass → related regression → one reviewable commit |
| Per-task completion evidence | PASS | Agent Execution Discipline requires fresh test result, staged git diff summary/check and full commit hash for M1a-0 and every A/B task |
| File-first structure | PASS | Complete File Map and Exact Public Interfaces precede M1a-0; all 255 task-owned paths map one-to-one to 255 unique rows including the plan and approved spec |
| 2026-07-18 user deltas | PASS | M1a-0 has a machine-checked 172800-second gate; complete RFC execution assets appear only in M1b; all task handoffs require test/diff/commit evidence; the uv baseline is updated from 0.11.16 to the locally verified 0.11.28 without changing architecture or scope |
| Required scope coverage | PASS | Specification Coverage Matrix covers every requested area and the approved-design trace maps §§1–23 exactly once |
| Placeholder-language scan | PASS | zero unresolved placeholder-marker matches; runtime-braced path components are defined where introduced |
| Version consistency | PASS | M1a application/public/database = 0.1.0/0.1.0/1; M1b = 0.2.0/1.0.0/2; protocol = 2025-11-25 |
| Interface consistency | PASS | six Facade methods; M1a store has no recovery mutation; B6 adds recovery; ArtifactStore/ArtifactSink both carry `schema_id`; validator consumes a verified committed snapshot |
| Phase boundary | PASS | M1a stable-hash smoke cannot claim RFC conformance; complete RFC/vector evidence is owned only by B2/M1b |
| Cost and YAGNI boundary | PASS | the disposable Spike is excluded from `src/`/wheel; every formal abstraction has a current caller/concrete implementation; M1 contains no worker, queue, dynamic plugin discovery, second store or host-specific core type |
| Planning-only boundary | PASS | this Phase 0 increment creates only this plan document and does not implement or install the planned system |

The authoring check validates plan structure and design consistency, not the future implementation. Implementation completion still requires the M1a-0 feasibility gate, every task's test/diff/commit record and the M1 Final Hard Gate.
