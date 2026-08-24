# 数学建模 MCP 仓库规则

本文件适用于整个仓库。
更深目录的 `AGENTS.md` 只增加该目录规则；冲突时更深规则优先。

## 使命

交付本地、可追踪、可验证的数学建模 MCP。
当前里程碑是 M1b 可信本地基线，不是多用户生产服务。
保持单发行物模块化单体，不为假想的第二实现建框架。

## 开始前阅读

1. 先读 [Context 索引](docs/context/index.md)。
2. 再读 [产品愿景](docs/product/vision.md)。
3. 涉及边界时读 [架构概览](docs/architecture/overview.md)。
4. 涉及公开数据时读对应的 [工具契约](docs/contracts/mcp-tools-v1.md)、
   [能力契约](docs/contracts/capability-api-v1.md) 或
   [求根契约](docs/contracts/root-finding-v1.md)。
5. 涉及本地状态时读 [bootstrap 与 doctor](docs/operations/bootstrap-and-doctor.md)。
6. C1 预览边界读
   [C1 接口补充](docs/superpowers/specs/2026-07-23-cumcm-2022-a-q1-contest-vertical-slice-design.md)。

## 权威顺序

用户本次明确指令最高。
已批准的后续规格补充优先于原始设计。
原始设计优先于实施计划和摘要文档。
JSON Schema 是数据形状权威。
契约文档只解释语义和路由，不复制 Schema 正文。
实现与权威来源冲突时停止扩展，先修正拥有该冲突的层。

## 依赖方向

`modeling_core` 不得导入 MCP、CLI、SQLite 或具体能力实现。
MCP 与 CLI 只通过 `ApplicationFacade` 调用用例。
当前 `ApplicationFacade` 具体实现是 `ModelingApplication`。
`ModelingApplication` 通过 `ProjectStore` 使用持久化。
当前 `ProjectStore` 具体实现是 `SQLiteProjectStore`。
Built-in Capability 不直接访问数据库、项目根或宿主。
只有组合根同时认识核心、具体能力和基础设施。
不得创建通用 Repository 基类族或服务定位器。

## MCP 与数学分离

`modeling_mcp` 只做协议、Schema 和错误映射。
MCP 层不得实现数学算法或直接读写 SQLite。
数学代码留在 `modeling_capabilities`。
求解器与独立验证器不得导入彼此的数值实现。
公开工具以 `modeling_core.contracts.tools.TOOL_NAMES` 为唯一清单；变更必须先改权威契约和失败测试。

## 能力边界

生产代码使用 Built-in Capability，不称其为插件。
能力注册表在组合时显式装配并封存。
M1 不实现 External Plugin 发现、安装、权限或 SDK。
新增能力必须自带描述符、版本化 Schema、测试和局部 context。
不要把能力专属规则移动进稳定核心。

## Schema、版本与 ADR

跨边界 DTO 使用严格验证并拒绝未知字段。
0.1 契约只属于 M1a 预览；M1b 的 1.0 是当前兼容基线。
完整 RFC 8785 符合性与项目向量由 M1b 门禁拥有。
版本语义变更必须同步 Schema、语料、文档和测试。
稳定决策记录在 `docs/adr/`；变更决策先更新或新增 ADR。

## 执行纪律

新功能或修复先写失败测试并观察预期失败。
测试真实行为；外部进程、SQLite 和文件系统使用真实边界。
时间测试使用可控时钟，不用长时间 sleep。
所有测试项目根来自 `tmp_path` 或 Harness 临时目录。
不得在仓库根创建权威 `.modeling/` 状态。
不得自动更新 Snapshot 或用重试隐藏不稳定。
必需测试不得跳过。

## 独立验证

求解成功不能代替独立验证成功。
Validator 必须能拒绝哈希自洽但数学结果伪造的输入。
数值断言使用契约容差和有限值检查。
预期数值失败与 Validation `FAILED` 不等于 Harness 崩溃。
修复跨路径缺陷时在共同入口修一次，并保留最小回归测试。

## 输入与状态安全

用户输入、项目资产和诊断源默认只读。
doctor 只诊断，不修复、不迁移、不修改权威状态。
权威状态只在项目根 `.modeling/` 下由拥有者写入。
路径必须拒绝越界、重解析和不可信绝对路径。
删除或替换前验证身份和拥有关系。
不得为简化测试移除数据丢失或安全边界。

## STDOUT、路径与秘密

MCP STDOUT 只能包含协议帧。
日志、诊断和调试文本写 STDERR。
公开结果不得泄露绝对路径、环境秘密或原始异常文本。
测试输出和 evidence 必须脱敏且有大小上限。
不要提交 `.codex/`、`.modeling/`、`build/` 或本地缓存。

## 可追踪性

持久记录保留项目、输入、能力版本、参数、Attempt、结果、Validation、警告和哈希关系。
稳定哈希只从规范化数据计算。
M1a 只声明固定向量与同环境重复执行的稳定 hash smoke。
M1b 完成声明必须覆盖完整 RFC 8785 通用与项目向量。

## 验证入口

M1b 的唯一完整验证命令是：

```powershell
uv run --locked --no-sync modeling verify --milestone m1b
```

局部开发可运行更窄测试，但完成声明必须引用新鲜完整门禁输出。
验证输出位于被忽略的 `build/verification/`，不是权威项目状态。

## Spike 边界

`spikes/m1a_0/` 只是历史可行性证据，不进入 wheel。
正式包不得导入、复制或复用 Spike 代码。
Spike 证明宿主往返，不定义生产核心抽象。

## 范围护栏

M1 保持单存储、无事件总线、无任务队列或 worker 池。
C1 只批准短生命周期受控 worker，不构成通用执行后端。
External Plugin、第二存储和通用工作流仍在范围外。
范围变化必须先修改批准规格和门禁。

## 每任务完成记录

每次提交只包含该任务授权文件。
提交前检查暂存范围与 diff。
交接必须记录以下字段：

- `Task`
- `Test result`
- `Git diff summary`
- `Commit hash`

`Test result` 给出原样命令、退出码及 passed/failed/skipped 数。
`Git diff summary` 给出暂存状态、stat 和 `git diff --cached --check`。
`Commit hash` 必须是完整提交哈希。
任一字段缺失、测试失败、必需跳过或 diff 越界时任务保持开放。
