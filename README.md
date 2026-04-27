# Economist Content Pipeline

## 1. 项目概览 (Project Overview)

- 目标：将《经济学人》EPUB 文件转换为中文口播稿 Word 文档。
- 输入 (Input)：`.epub` 文件。
- 输出 (Output)：`.docx` 文件。
- 当前状态：MVP。

本 README 仅作为入口控制器使用，用于限定阅读顺序、执行路径和冲突裁决基准。具体业务规则、输出生成逻辑和运行参数以对应真源文件为准。


## 2. 快速开始 (Quick Start)

最短服务启动路径：

```powershell
pip install -r requirements.txt
uvicorn app:APP --host 127.0.0.1 --port 8000
```

最短命令行路径：

```powershell
python pipeline.py TE20260314.epub
```


## 3. 真源表 (Source of Truth)

冲突时按下表裁决：

| 内容 | 唯一真源 |
| :--- | :--- |
| 主流程顺序 | `pipeline.py` |
| 输出文档生成 | `docx_builder.py` |
| EPUB 提取、正文筛选与文本清洗 | `article_processor.py` |
| 翻译调用与并发参数 | `translate_articles.py` |
| 服务接口、任务状态与下载行为 | `app.py` |
| Python 依赖 | `requirements.txt` |
| 本地运行配置 | `.env` / 系统环境变量 |
| 开发约束 | `AGENTS.md` |



