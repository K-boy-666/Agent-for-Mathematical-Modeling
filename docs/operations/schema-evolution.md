# Schema 与版本演进

## 权威与固定基线

公开数据形状以 wheel 内 JSON Schema 为权威，使用
[JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12)。规范化使用
[RFC 8785](https://www.rfc-editor.org/rfc/rfc8785)和锁定 `rfc8785==0.1.4`。
首个稳定基线是工具、公共 Error/Result/Capability/Validation Report 及求根契约 `1.0.0`；
发布语料和规范化基线一经提交即不可原地改写。

## 兼容规则

- request 采用逆变兼容：新实现必须继续接受最近发布基线的所有合法旧请求；新增可选字段须有稳定默认值。
- result/error 采用调用方兼容：不能删除必需字段、收窄值域、改型或改变既有状态/错误语义。
- 未知字段仍由当前严格 DTO 拒绝；“放宽 request”必须明确改 Schema，不能绕开验证。
- 新错误码、枚举值或必需字段默认视为不兼容，除非既有契约明确声明开放集合。

SemVer 分开应用于应用、MCP 工具契约、Capability API、每个能力契约、实现、Validator 策略和报告。
实现修订不自动改变数据契约；不兼容数据形状升 major，兼容新增升 minor，纯澄清或实现修复升 patch。
数据库 `PRAGMA user_version` 独立演进，M1 只接受精确 Schema `2`，doctor 不迁移旧库。

## 基线更新审查

先提交失败的旧语料/兼容测试，再更新批准规格或 ADR、Schema、Python DTO、语料、文档与打包清单。
评审必须比较规范化 Schema、旧合法/非法/边界/错误语料、完整 RFC 8785 向量、数据库迁移策略及
Windows/Ubuntu 结果。禁止自动接受 Snapshot、删除旧语料或用重试隐藏漂移。

工具语义见[MCP tools v1](../contracts/mcp-tools-v1.md)，能力语义见
[Capability API v1](../contracts/capability-api-v1.md)。
