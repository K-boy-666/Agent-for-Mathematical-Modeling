---
name: add-capability
description: Use when adding or registering a Built-in Capability, its descriptor, versioned Schemas, validator, local context, or focused verification route.
---

# Add a Built-in Capability

## Overview

能力只有在契约、数学实现、独立验证和显式装配一起可验证时才算加入；目录可见性本身不是完成条件。

## Procedure

1. 从 [Context 索引](../../../docs/context/index.md) 加载根规则、`modeling_capabilities` 规则、能力契约和该能力的局部 context；不要加载无关数学。
2. 使用下面的完整命令生成最小目录；`capability_id` 必须是规范化裸 ID，不含 `/1.0.0`。

   ```powershell
   uv run --locked --no-sync modeling capability scaffold <capability_id> --destination src/modeling_capabilities --tests-destination tests
   ```
3. 先写失败测试，覆盖描述符、版本化 input/canonical/success/failure Schema、求解行为和独立 Validator 拒绝伪造结果。
4. 完成描述符、Schema、实现、Validator 和局部 `context.md`；Schema 保持数据形状权威，Skill 不复制字段表。
5. 在 [唯一组合根](../../../src/modeling_bootstrap/composition.py) 的 `seal()` 前显式构造并注册能力与 Validator；注册表封存后不再追加。
6. 在 [能力目录](../../../docs/capabilities/index.md) 增加一行摘要和权威链接。

## Verification

运行能力专属测试，然后执行聚焦反馈：

```powershell
uv run --locked --no-sync modeling verify --capability numerical.root_finding
```

聚焦反馈通过后仍需运行当前里程碑完整门；聚焦模式不生成发布证据。
从 [Context 索引](../../../docs/context/index.md) 读取当前里程碑：B9–B12 分支使用
`uv run --locked --no-sync modeling verify --milestone m1b`，不要从旧的 M1a 摘要猜测。

## References

- [Built-in Capability 语义](../../../docs/contracts/capability-api-v0.md)
- [能力目录](../../../docs/capabilities/index.md)
- [组合根规则](../../../src/modeling_bootstrap/AGENTS.md)
- [能力目录规则](../../../src/modeling_capabilities/AGENTS.md)

## Common mistakes

| mistake | correction |
|---|---|
| 只让能力出现在列表中 | 同步交付描述符、Schema、实现、Validator、context 和测试 |
| 把版本拼进 `capability_id` | 传裸 ID；版本由描述符字段表达 |
| 扫描目录或解封注册表 | 在唯一组合根、`seal()` 前显式注册 |
| 只跑全仓测试 | 先跑能力聚焦反馈，再跑里程碑门 |
