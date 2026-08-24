# Capability API 1.0 稳定契约

Capability API 版本是 `modeling-capability/1.0.0`。公共数据形状由
[Capability Schema](../../src/modeling_core/contracts/schemas/common/1.0.0/modeling-capability.schema.json)、
[Validator Schema](../../src/modeling_core/contracts/schemas/common/1.0.0/modeling-validator.schema.json)、
[Result Schema](../../src/modeling_core/contracts/schemas/common/1.0.0/modeling-result.schema.json)和
[Validation Report Schema](../../src/modeling_core/contracts/schemas/common/1.0.0/modeling-validation-report.schema.json)
定义；Python 端口在 [capability.py](../../src/modeling_core/contracts/capability.py)。

## 术语与版本轴

- API 版本：宿主应用与所有能力共享的描述符、执行和 Validator 形状。
- 契约版本：某个 capability 输入/结果语义，例如 `numerical.root_finding/1.0.0`。
- 实现版本：具体 Built-in Capability 或 Validator 代码版本；不替代契约版本。
- 策略版本：独立 Validator 采用的判定参数 Schema 与语义。
- 报告版本：Validation 报告信封与指标形状。

Built-in Capability 是随发行物交付、在唯一组合根显式注册并在启动后封存的可信数学实现；
它不是 External Plugin。External Plugin 指未来可发现、安装并受权限控制的第三方单元，M1 不提供其
发现、安装、权限或 SDK。两者不得共用“插件”含义。

## 执行边界

能力接收已通过自身 input Schema 的 payload、规范化版本和有限执行上下文；它不访问 SQLite、
项目根、MCP、CLI 或宿主。描述符声明稳定 ID、契约/实现版本、Schema 哈希、默认/最大限制、制品角色
和 Validator。注册表按 `(capability_id, contract_version)` 排序并封存，未知或不支持版本失败关闭。

Validator 读取已提交且重新校验哈希的结果，通过独立数值实现产生 `PASSED`、`FAILED` 或
`INCONCLUSIVE`；求解器和 Validator 不导入彼此的 evaluator。合法描述符必须引用存在且有效的
版本化 Schema；缺少 Schema、重复 ID/版本或交叉版本字段是无效注册。

当前目录见[能力目录](../capabilities/index.md)，求根语义见[root finding v1](root-finding-v1.md)。
