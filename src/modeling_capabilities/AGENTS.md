# modeling_capabilities 目录规则

本文件只补充根规则，作用域是 `modeling_capabilities`。

- 每个 Built-in Capability 自有描述符、Schema、实现、验证器和 context。
- 能力不得访问项目根、SQLite、MCP、CLI 或宿主状态。
- 求解器与独立验证器不得导入彼此的数值实现。
- 共享只限不可变语法、预算和契约类型。
- 新能力通过显式组合根注册，不做动态发现。
- `root_finding/context.md` 是现有求根输入的局部权威说明。
- 数学失败使用稳定错误语义；不得泄露原始异常或路径。
- 变更数值行为时同时增加契约容差内的独立验证测试。
