# modeling_core 目录规则

本文件只补充根规则，作用域是 `modeling_core`。

- 核心不得导入 CLI、MCP、SQLite、组合根或具体能力。
- `ApplicationFacade` 保持宿主无关；`ModelingApplication` 编排用例。
- `ProjectStore` 只暴露当前用例所需操作，不建通用 CRUD 基类。
- `Clock` 与 `IdGenerator` 保持小而显式，测试实现留在 tests。
- 公共 DTO 严格、拒绝未知字段，并使用版本化 Schema。
- 领域状态转换集中维护；外围层不得绕过不变量。
- 能力专属 Schema、解析和数值逻辑不得移入核心。
- 修改公开契约时同步 Schema、语料、调用方和回归测试。
