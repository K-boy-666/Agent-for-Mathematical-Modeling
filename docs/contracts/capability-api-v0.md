# Capability API 0.1 契约路由

M1a 只加载可信、显式注册并封存的 Built-in Capability 和独立 Validator。
它们不是 External Plugin，也不包含发现、安装或权限协议。

公共能力/Validator 数据形状位于
[common Schema](../../src/modeling_core/contracts/schemas/common/0.1.0/)，
Python 契约位于 [capability.py](../../src/modeling_core/contracts/capability.py)。
能力专属 Schema 留在能力目录，本文不复制 Schema 正文。

能力与 Validator 不访问 SQLite、项目根、MCP 或 CLI。
执行由应用层提供已验证的规范输入和有限上下文；Validator 独立复核数学结果。

现有能力的输入与结果路由见 [root finding v0](root-finding-v0.md)。
