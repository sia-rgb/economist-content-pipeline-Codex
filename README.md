# Ecno-assist

经济学人文章翻译工具。当前目标是把《经济学人》英文文章从 `epub` 自动转换为中文口播逐字稿，并支持通过最小 FastAPI 服务完成网页上传、异步处理、状态查询和下载 `docx` 的闭环。

## 当前能力

- EPUB 提取文章内容
- 筛选非正文内容
- 清洗为标准化“标题 + 正文”格式
- 调用 DeepSeek API 生成中文口播稿
- 合并翻译结果为 Word 文档
- 提供最简网页前端入口
- 提供最小 FastAPI 服务接口：
  - 上传 `epub`
  - 查询任务状态
  - 下载 `docx`
  - 访问口令校验
  - `20MB` 上传大小限制

## 当前处理流程

用户输入 `epub` → 系统提取文章 → 筛选正文 → 清洗格式 → 翻译为中文口播稿 → 合并为 `docx` → 输出结果

服务模式下的流程是：

用户上传 `epub` → 服务创建 `task_id` 和任务目录 → 后台调用现有 `run_pipeline()` → 写入 `output.docx` 和 `status.json` → 用户查询状态或下载结果

## 核心文件

- `pipeline.py`：统一入口，串联 MVP1 到 MVP5
- `article_processor.py`：文章提取、筛选和格式清洗（MVP1 到 MVP3）
- `translate_articles.py`：调用 DeepSeek API 翻译
- `docx_builder.py`：合并生成 Word（MVP5）
- `app.py`：最小 FastAPI 服务入口

## 最小启动说明

### 1. 安装依赖

```powershell
pip install -r requirements.txt
```

### 2. 配置环境变量

如果要走真实翻译，需要可用的 DeepSeek 配置：

```powershell
$env:DEEPSEEK_API_KEY="你的key"
$env:DEEPSEEK_API_BASE="https://api.deepseek.com"
$env:DEEPSEEK_MODEL="deepseek-chat"
```

可选并发配置：

```powershell
$env:MAX_CONCURRENT="3"
```

可选任务保留期配置：

```powershell
$env:TASK_RETENTION_HOURS="24"
```

可选访问口令配置：

```powershell
$env:ACCESS_PASSWORD="猪猪侠"
```

### 3. 启动服务

```powershell
uvicorn app:APP --host 127.0.0.1 --port 8000
```

启动后可访问：

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/healthz`

### 4. 上传 EPUB

```powershell
curl.exe -X POST "http://127.0.0.1:8000/tasks" `
  -F "access_password=猪猪侠" `
  -F "file=@TE20260314.epub;type=application/epub+zip"
```

返回示例：

```json
{
  "task_id": "你的task_id",
  "status": "pending",
  "created_at": "...",
  "updated_at": "..."
}
```

### 5. 查询任务状态

```powershell
curl.exe "http://127.0.0.1:8000/tasks/你的task_id?access_password=猪猪侠"
```

当前状态只支持：

- `pending`
- `running`
- `succeeded`
- `failed`

### 6. 下载结果

```powershell
curl.exe -L "http://127.0.0.1:8000/tasks/你的task_id/download?access_password=猪猪侠" --output output.docx
```

## 接口说明

### `GET /`

返回最简网页前端入口，供普通用户输入口令、上传 `epub` 并在完成后下载 `docx`。

### `GET /api-info`

返回服务基础信息，供开发调试使用。

### `GET /healthz`

返回最小健康检查结果，适合部署后做连通性探活。调用时会顺带执行一次过期任务清理。

### `POST /tasks`

上传一个 `epub` 文件，创建任务并异步执行流水线。

约束：

- 需要 `access_password`
- 文件大小不得超过 `20MB`

### `GET /tasks/{task_id}`

读取任务状态。失败时可返回 `error.txt` 的错误摘要。

### `GET /tasks/{task_id}/download`

当任务状态为 `succeeded` 时下载 `output.docx`。

## 任务目录结构

```text
tasks/
  <task_id>/
    input.epub
    output.docx
    status.json
    error.txt
    runs/
      mvp1/
      mvp2/
      mvp3/
      mvp4/
      mvp5/
```

说明：

- `input.epub`：上传原始文件
- `output.docx`：最终输出文件
- `status.json`：任务状态
- `error.txt`：失败时的错误堆栈
- `runs/mvp1/`：EPUB 提取后的原始文章文本
- `runs/mvp2/`：按长度筛选后的文章文本
- `runs/mvp3/`：清洗后的“标题 + 正文”文章文本
- `runs/mvp4/`：翻译后的中文口播稿文本
- `runs/mvp5/`：合并生成的 Word 文档

## 直接命令行运行

如果不走服务，也可以直接调用统一入口：

```powershell
python pipeline.py TE20260314.epub
```

流程为：

`epub` → `mvp1` → `mvp2` → `mvp3` → `mvp4` → `mvp5` → `docx`

默认输出目录：

```text
runs/<epub名>/
```

命令行模式会调用真实翻译流程，需要先配置可用的 DeepSeek 环境变量。

## 技术栈

- Python
- FastAPI
- Uvicorn
- ebooklib
- BeautifulSoup4
- python-docx
- openai 兼容接口调用 DeepSeek API

## 当前限制

- 当前是最小闭环验证版本，不是完整生产系统
- 不做下载后立即清理，只做简单过期清理
- 暂未接入数据库
- 暂未实现微信提醒
- 当前更适合单用户使用场景
- 默认 FastAPI 文档入口已关闭

## 最小过期清理方案

- 仅清理状态为 `succeeded` 或 `failed` 的任务
- 不清理 `pending` 或 `running`
- 默认保留期为 24 小时，可通过 `TASK_RETENTION_HOURS` 调整
- 清理触发点：
  - 调用 `POST /tasks` 创建新任务前
  - 调用 `GET /healthz` 时
- 清理方式：
  - 读取 `status.json` 的 `updated_at`
  - 超过保留期后删除整个 `tasks/<task_id>/`

## 最小部署清单

### 运行前提

- 一台持续在线的 Linux 或 Windows 机器
- Python 运行环境
- 可写的项目目录，用于保存 `tasks/`
- 可用的 DeepSeek 环境变量
- 如需调整保留期，可设置 `TASK_RETENTION_HOURS`

### 部署命令

```powershell
pip install -r requirements.txt
uvicorn app:APP --host 0.0.0.0 --port 8000
```

### 部署后先检查

- `GET /healthz` 是否返回 `{"status":"ok", ...}`
- `tasks/` 是否能正常写入
- 上传一个 `epub` 后 `status.json` 是否生成
- 失败时 `error.txt` 是否可读取
- 过期的 `succeeded/failed` 任务是否能被清理
- 首页 `/` 是否能正常打开网页前端

### 生产前仍未做的事

- 进程保活
- 反向代理和 HTTPS
- 自动清理过期任务
- 访问控制
- 多用户并发治理

## 开发原则

- 优先最小可运行版本
- 优先最小改动，不提前做复杂扩展
- 最大化复用现有 `pipeline.py` / `run_pipeline()`
- 不重写核心流水线
