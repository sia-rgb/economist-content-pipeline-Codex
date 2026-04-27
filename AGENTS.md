## 一、Core Principles（核心原则）

- 优先构建最小可运行版本（MVP, Minimum Viable Product）
- 优先最小改动（Minimal Change），避免不必要的重构（Refactor）
- 所有开发行为必须服务于“功能可运行”（Runnable First）
- 文档即约束（Docs as Constraints），必须严格遵守

---

## 二、Workflow（工作流程）

在开始任何新任务前，必须先说明：

### 1. 本次最小目标（Minimal Goal）

明确当前任务的最小可交付成果（MVP 输出）。

---

### 2. 流程链（Process Chain）

使用标准结构表达：

用户输入 → 系统处理 → 输出结果

或：

Input → Process → Output

必要时可使用：

A → B → C

进行流程拆解。

---

### 3. 示例（Example）

用户输入 → 文章 EPUB 文件  
系统处理 → 解析 + 清洗 + 分段翻译  
输出结果 → 中文口播稿 Word 文档  

---

⚠️ 未经用户确认，不得直接进入代码实现（DO NOT write code before confirmation）

---

## 三、Development Rules（开发规范）

- 优先实现 MVP，不提前设计复杂扩展（No Premature Optimization）
- 优先最小改动（Minimal Change）
- 提交前必须验证核心功能可运行（Runnable Check）
- 每次 commit 必须使用一句话说明改动（One-line Commit Message）

---

## 四、Forbidden Actions（禁止行为）

除非用户明确要求，否则禁止：

- 修改日志输出样式（Log Format）
- 美化 print 内容（Output Styling）
- 重命名变量（Variable Renaming）
- 修改注释风格（Comment Style）
- 调整无关格式（Formatting Changes）
- 做非必要重构（Unnecessary Refactor）

---

## 五、Execution Rule: Preflight Required（执行前检查）

在执行以下操作前，必须进行 Preflight Check：

- Benchmark（性能测试）
- Concurrency Test（并发测试）
- Performance Experiment（性能实验）

---

### Preflight Check 必须报告：

1. 代码中的实际约束（Effective Constraints）
   - 如：MAX_CONCURRENT、Semaphore 等

2. 请求参数是否真实可达（Feasibility）

3. 是否存在使实验无效的条件（Invalid Conditions）

4. 明确结论：
   - VALID（可执行）
   - INVALID（不可执行）

---

### 强制规则（Mandatory Rules）


- 若存在 INVALID 条件 → 禁止执行测试
- 禁止假设参数生效，必须验证（No Assumption）
- 执行前必须请求用户确认（Require Confirmation）

---

### Definition of Done（完成定义）

满足以下之一：

(A) Preconditions 已确认 → 成功执行测试  
(B) Preconditions 无效 → 停止并说明原因  

---

## 六、Encoding Rules（编码规范 - CRITICAL）

所有文件必须使用 UTF-8 编码（UTF-8 Only）

禁止依赖系统默认编码（No Default Encoding）

---

### Python

读取文件：
open(file, "r", encoding="utf-8")

写入文件：
open(file, "w", encoding="utf-8")

---

### PowerShell

读取文件：
Get-Content -Encoding UTF8

写入文件：
Set-Content -Encoding UTF8