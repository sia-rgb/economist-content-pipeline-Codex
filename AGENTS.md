# AGENTS.md

## 核心原则（Core Principles）

1. 最小可运行优先（MVP First）
   - 优先构建最小可运行版本（MVP）
   - 所有开发行为必须服务于“功能可运行”

2. 最小改动（Minimal Change）
   - 优先最小改动，避免不必要的重构

3. 可运行优先（Runnable First）
   - 提交前必须保证核心功能可运行

4. 文档即约束（Docs as Constraints - CRITICAL）
   - 所有文档均视为运行时约束，必须严格执行

   强制规则（Mandatory Rules）：
   - 不允许将文档视为参考或建议
   - 不允许偏离文档定义的结构或逻辑
   - 文档冲突必须通过优先级（Precedence）规则解决
   - 不允许基于经验或常识替代文档规则

---

## 以下三类约束的区别

| 类型 | 控制什么 | 本质 |
|------|----------|------|
| **流程约束（Process）** | 怎么思考 | 思维路径 |
| **行为约束（Behavior）** | 能做什么 / 不能做什么 | 行为边界 | 
| **执行约束（Execution）** | 什么时候可以做 | 执行时机 | 


## 流程约束（Process Constraints）

### 工作流程（Workflow）

在开始任何任务前，必须输出：

#### 1. 最小目标（Minimal Goal）
明确本次任务的最小可交付成果（MVP）

#### 2. 流程链（Process Chain）

必须使用标准结构表达：

- 用户输入 → 系统处理 → 输出结果  
- 或：Input → Process → Output  
- 必要时使用：A → B → C

未经用户确认，不得进入代码实现

---

## 行为约束（Behavior Constraints）

### 1.开发规范（Development Rules）

- 禁止过早优化
- 优先最小改动
- 提交前必须通过 Runnable Check
- commit 必须一句话说明

---

### 2.禁止行为（Forbidden Actions）

除非用户明确要求，否则禁止：

- 修改日志输出样式
- 美化 print 内容
- 重命名变量
- 修改注释风格
- 调整无关格式
- 非必要重构

---

### 3.编码规范（Encoding Rules - CRITICAL）

- 所有文件必须使用 UTF-8
- 禁止依赖系统默认编码

---

## 执行约束（Execution Constraints）

### 执行前检查（Preflight Required）

适用场景：

- Benchmark
- Concurrency Test
- Performance Experiment

#### 必须检查：

1. 实际约束（Effective Constraints）
2. 可行性（Feasibility）
3. 无效条件（Invalid Conditions）

#### 输出结论：

- VALID
- INVALID

#### 强制规则（Mandatory Rules）：

- 若 INVALID → 禁止执行
- 禁止假设参数生效
- 必须请求用户确认

#### 完成定义（Definition of Done）：

- Preconditions valid → 执行  
- Preconditions invalid → 停止
