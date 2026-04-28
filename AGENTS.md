# AGENTS.md

## 1. 核心原则 (Core Principles)

- **最小可运行优先 (MVP First)**：优先构建最小可运行版本，所有行为必须服务于“功能可运行”。
- **最小改动 (Minimal Change)**：优先选择改动最小的方案，严禁非必要的重构。
- **可运行检查 (Runnable First)**：提交前必须保证核心功能在当前环境下可运行。
- **文档即约束 (Docs as Constraints - [CRITICAL])**：
  - 文档是运行时硬约束，严禁将其视为建议或参考。
  - 严禁偏离文档定义的结构或逻辑，严禁以经验/常识替代规则。
  - 冲突必须通过本文件定义的“优先级 (Precedence)”规则解决。

---

## 2. 约束分类 (Constraint Categories)

| 类型 | 控制对象 | 本质 |
| :--- | :--- | :--- |
| **流程约束 (Process)** | 思考过程 | 思维路径 |
| **行为约束 (Behavior)** | 动作边界 | 能做什么 / 不能做什么 |
| **执行约束 (Execution)** | 触发时机 | 什么时候可以做 |

---

## 3. 流程约束 (Process Constraints)

### 3.1 工作流程 (Workflow)
在开始任何任务前，必须输出以下内容并获得用户确认：

1. **最小目标 (Minimal Goal)**：明确本次任务的最小可交付成果 (MVP)。
2. **流程链 (Process Chain)**：使用标准结构表达，如 `Input → Process → Output` 或 `A → B → C`。
3. **确认机制**：未经用户明确确认，不得进入代码实现阶段。

---

## 4. 行为约束 (Behavior Constraints)

### 4.1 开发规范 (Development Rules)
- **禁止过早优化**：严禁在 MVP 阶段设计复杂的扩展性。
- **最小化改动**：在实现目标前提下，严禁触碰无关代码。
- **单行提交**：每次 Commit 必须使用一句话清晰说明改动核心。

### 4.2 禁止行为 (Forbidden Actions)
除非用户明确要求，否则**禁止**：
- 修改日志输出样式或美化 print 内容。
- 重命名变量、修改注释风格。
- 调整无关格式或进行非必要重构。

### 4.3 编码规范 (Encoding Rules - [CRITICAL])
- 所有文件读写必须显式指定 `UTF-8` 编码。
- 严禁依赖系统默认编码。

### 4.4 输出风格 (Output Style)
- 保持客观、中立、冷静的语气。
- 优先使用短句，避免冗余、重复及情绪化表达。

---

## 5. 执行约束 (Execution Constraints)

### 5.1 执行前检查 (Preflight Required)
**适用场景**：Benchmark、并发测试、性能实验。

- **检查项**：必须核实实际约束 (Effective Constraints)、可行性 (Feasibility) 及无效条件 (Invalid Conditions)。
- **结论判定**：仅输出 `VALID` 或 `INVALID`。
- **强制规则**：
  - 若判定为 `INVALID`，禁止执行。
  - 严禁假设参数生效，必须经过验证。
  - 执行前必须请求用户显式确认。

---

## 6. 文档优先级 (Precedence)

### 6.1 优先级矩阵 (Priority Matrix)
当指令或文档冲突时，按以下层级**降序**执行：

1. **Level 0: 最高准则 (The Law) - `AGENTS.md`**
   - 任何行为不得违反本文件定义的禁止行为与强制规则。
2. **Level 1: 直接指令 (Direct Order) - 当前用户 Prompt**
   - 在不违反 L0 的前提下，以用户最新指令为准。
3. **Level 2: 全局上下文 (Global Context) - `README.md`**
   - 确保改动符合项目既定架构与业务链路。
4. **Level 3: 既有逻辑 (Legacy Logic) - 现有代码**
   - 作为现状参考，但必须服从 L0-L2 的修改指令。

### 6.2 脚本冲突裁决 (Inter-script Arbitration)
当不同脚本逻辑冲突时，遵循以下逻辑：
- **调用者优先 (Caller > Callee)**：主控脚本的需求高于模块内部实现。
- **下游优先 (Downstream > Upstream)**：以数据流末端的格式需求反向要求上游适配。
- **通用优先 (Global Utils > Local Logic)**：严禁为单一业务破坏通用工具类的稳定性。
- **风险最小化 (Minimal Disruption)**：优先选择改动成本最低、受影响范围最小的方案。

### 6.3 冲突处理协议 (Conflict Protocol)
若无法自动裁决，Agent 必须执行：
- **识别 (Identify)**：清晰指出具体的冲突点及涉及的文件。
- **挂起 (Suspend)**：立即停止任何写操作（进入 Read-only 模式）。
- **报告 (Report)**：向用户提交冲突详情并给出建议方案。
- **待命 (Wait)**：在获得用户显式授权前，严禁继续。