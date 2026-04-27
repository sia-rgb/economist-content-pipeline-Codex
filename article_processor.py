#!/usr/bin/env python3
"""
文章处理工具：提取、筛选、清洗 EPUB 文章。
"""

import os
import re
import shutil

from bs4 import BeautifulSoup
from ebooklib import epub

from console_utf8 import setup_console_utf8


setup_console_utf8()


def is_article_content(text, title=""):
    """
    当前版本暂时移除所有过滤，提取所有内容
    后续可在此函数中添加智能过滤逻辑
    """
    print(f"处理内容: {title[:50]}... (长度: {len(text.strip())})")
    return True


def extract_text_from_html(html_content):
    """从HTML内容提取纯文本"""
    soup = BeautifulSoup(html_content, 'html.parser')

    # 移除脚本和样式
    for script in soup(["script", "style"]):
        script.decompose()

    # 获取文本
    text = soup.get_text()

    # 清理多余空白
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text = '\n'.join(chunk for chunk in chunks if chunk)

    return text


def extract_articles_from_epub(epub_path, output_path="articles.txt", articles_output_dir="docs"):
    """从epub文件提取文章"""
    print(f"开始处理: {epub_path}")

    try:
        # 读取epub文件
        book = epub.read_epub(epub_path)

        # 创建目录用于保存单独文章
        if not os.path.exists(articles_output_dir):
            os.makedirs(articles_output_dir, exist_ok=True)
            print(f"创建目录: {articles_output_dir}")

        all_articles = []
        article_count = 0
        filtered_count = 0

        # 遍历所有项目
        for item in book.get_items():
            if isinstance(item, epub.EpubHtml):
                # 获取HTML内容
                html_content = item.get_content()

                # 提取文本
                text = extract_text_from_html(html_content)

                # 获取标题（从文件名或内容中提取）
                title = item.get_name()

                # 判断是否为文章
                if is_article_content(text, title):
                    article_count += 1

                    # 保存单独文章文件到docs目录
                    # 生成安全的文件名：替换路径分隔符，移除扩展名
                    safe_title = title.replace('/', '_').replace('\\', '_')
                    # 移除常见的HTML扩展名
                    for ext in ['.html', '.xhtml', '.htm']:
                        if safe_title.endswith(ext):
                            safe_title = safe_title[:-len(ext)]
                            break

                    # 如果文件名仍然太长，截断
                    if len(safe_title) > 50:
                        safe_title = safe_title[:50]

                    article_filename = f"article_{article_count:03d}_{safe_title}.txt"
                    article_filepath = os.path.join(articles_output_dir, article_filename)

                    try:
                        with open(article_filepath, 'w', encoding='utf-8') as f:
                            f.write(f"来源: {title}\n\n")
                            f.write(text)
                        print(f"  保存单独文章: {article_filename}")
                    except Exception as e:
                        print(f"  警告: 无法保存单独文章文件 {article_filename}: {e}")

                    all_articles.append(f"=== 文章 {article_count} ===\n")
                    all_articles.append(f"来源: {title}\n\n")
                    all_articles.append(text)
                    all_articles.append("\n" + "="*60 + "\n\n")
                else:
                    filtered_count += 1

        print(f"处理完成: 找到 {article_count} 篇文章，过滤 {filtered_count} 个非文章内容")

        if article_count == 0:
            print("警告: 未提取到任何文章，可能需要调整过滤规则")
            return False

        # 保存到文件
        # 确保输出目录存在
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
            print(f"创建输出目录: {output_dir}")

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"经济学人文章提取结果\n")
            f.write(f"源文件: {os.path.basename(epub_path)}\n")
            f.write(f"提取文章数: {article_count}\n")
            f.write(f"过滤内容数: {filtered_count}\n")
            f.write("="*60 + "\n\n")
            f.write(''.join(all_articles))

        print(f"文章已保存到: {output_path}")
        print(f"文件大小: {os.path.getsize(output_path)} 字节")

        return True

    except Exception as e:
        print(f"处理出错: {e}")
        import traceback
        traceback.print_exc()
        return False


def filter_articles_by_length(input_dir, output_dir, min_length=2000):
    """
    基于内容长度筛选文章

    Args:
        input_dir: 输入目录路径
        output_dir: 输出目录路径
        min_length: 最小字符长度阈值，默认1000字符
    """
    print(f"开始筛选文章...")
    print(f"输入目录: {input_dir}")
    print(f"输出目录: {output_dir}")
    print(f"最小长度: {min_length}字符")
    print("=" * 60)

    # 确保输出目录存在
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"创建输出目录: {output_dir}")

    # 统计信息
    total_files = 0
    kept_files = 0
    filtered_files = 0

    # 遍历输入目录
    for filename in os.listdir(input_dir):
        # 只处理.txt文件，排除汇总文件
        if not filename.endswith('.txt'):
            continue

        if filename == 'TE20260314_articles.txt':
            print(f"跳过汇总文件: {filename}")
            continue

        filepath = os.path.join(input_dir, filename)
        total_files += 1

        try:
            # 读取文件内容
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            # 计算内容长度（不包括首行的"来源:"行）
            # 跳过第一行（来源信息），计算剩余内容的长度
            lines = content.split('\n')
            if len(lines) > 1 and lines[0].startswith('来源:'):
                # 跳过第一行"来源:"行
                actual_content = '\n'.join(lines[1:])
            else:
                actual_content = content

            content_length = len(actual_content.strip())

            # 判断是否保留
            if content_length >= min_length:
                # 复制文件到输出目录
                output_path = os.path.join(output_dir, filename)
                shutil.copy2(filepath, output_path)
                kept_files += 1
                print(f"[+] 保留: {filename} ({content_length}字符)")
            else:
                filtered_files += 1
                print(f"[-] 过滤: {filename} ({content_length}字符)")

        except Exception as e:
            print(f"[!] 处理失败: {filename} - {e}")
            filtered_files += 1

    print("=" * 60)
    print(f"筛选完成!")
    print(f"总文件数: {total_files}")
    print(f"保留文章: {kept_files}")
    print(f"过滤文件: {filtered_files}")

    # 显示保留的文件列表
    if kept_files > 0:
        print(f"\n保留的文件已保存到: {output_dir}")
        print("前10个保留文件:")
        kept_files_list = os.listdir(output_dir)[:10]
        for i, f in enumerate(kept_files_list, 1):
            print(f"  {i}. {f}")
        if len(kept_files_list) > 10:
            print(f"  ... 还有 {kept_files - 10} 个文件")

    return kept_files > 0


def extract_title_and_content(text):
    """
    从原始文本中提取标题和正文

    Args:
        text: 原始文章文本

    Returns:
        tuple: (title, content) 或 (None, None) 如果提取失败
    """
    lines = text.split('\n')

    # 模式1：查找包含日期格式的行
    # 匹配如 "Mar 12, 2026 07:17 AM" 或 "Mar 12, 2026 08:10 AM | location"
    date_pattern = r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+(AM|PM)'

    # 查找内容开始的行（跳过"来源:"和导航行）
    content_start_idx = -1
    for i, line in enumerate(lines):
        # 跳过空行和导航行
        if not line.strip():
            continue
        if line.strip() in ['文章', '节', '下一项', '上一项']:
            continue
        if line.startswith('来源:'):
            continue

        # 检查是否包含日期格式
        if re.search(date_pattern, line):
            content_start_idx = i
            break

    if content_start_idx == -1:
        # 如果没有找到日期格式，尝试其他方法
        # 查找第一个非空、非导航、非来源的行
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            if line.strip() in ['文章', '节', '下一项', '上一项']:
                continue
            if line.startswith('来源:'):
                continue
            content_start_idx = i
            break

    if content_start_idx == -1:
        # 无法找到内容起始行
        return None, None

    # 提取标题行（包含日期的那一行）
    title_line = lines[content_start_idx]

    # 从标题行中分离标题和日期
    # 查找日期位置
    date_match = re.search(date_pattern, title_line)
    if date_match:
        date_start = date_match.start()
        # 标题是日期前的部分
        title = title_line[:date_start].strip()
        # 剩余部分是日期和可能的其他信息
        date_part = title_line[date_start:].strip()
    else:
        # 没有找到日期，整行作为标题
        title = title_line.strip()
        date_part = ""

    # 提取正文（从下一行开始到文件末尾）
    content_lines = []
    for i in range(content_start_idx + 1, len(lines)):
        line = lines[i].strip()
        # 跳过结尾的导航元素和下载信息
        if line in ['文章', '节', '下一项', '上一项']:
            continue
        if line.startswith('This article was downloaded by calibre from'):
            continue
        if not line:
            # 保留空行，但过滤连续多个空行
            if not content_lines or content_lines[-1].strip():
                content_lines.append('')
            continue
        content_lines.append(line)

    # 清理正文：去除开头和结尾的多余空行
    while content_lines and not content_lines[0].strip():
        content_lines.pop(0)
    while content_lines and not content_lines[-1].strip():
        content_lines.pop(-1)

    content = '\n'.join(content_lines)

    return title, content


def clean_article_file(input_path, output_path):
    """
    清理单个文章文件

    Args:
        input_path: 输入文件路径
        output_path: 输出文件路径

    Returns:
        bool: 是否成功
    """
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            text = f.read()

        title, content = extract_title_and_content(text)

        if title is None or content is None:
            print(f"[!] 提取失败: {os.path.basename(input_path)}")
            return False

        # 写入清理后的文件
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"{title}\n\n")
            f.write(content)

        return True

    except Exception as e:
        print(f"[!] 处理错误: {os.path.basename(input_path)} - {e}")
        return False


def clean_articles(input_dir, output_dir):
    """
    清理目录中的所有文章文件

    Args:
        input_dir: 输入目录路径
        output_dir: 输出目录路径
    """
    print(f"开始清理文章格式...")
    print(f"输入目录: {input_dir}")
    print(f"输出目录: {output_dir}")
    print("=" * 60)

    # 确保输出目录存在
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"创建输出目录: {output_dir}")

    # 统计信息
    total_files = 0
    success_files = 0
    failed_files = 0

    # 遍历输入目录
    for filename in os.listdir(input_dir):
        # 只处理.txt文件
        if not filename.endswith('.txt'):
            continue

        input_path = os.path.join(input_dir, filename)
        output_path = os.path.join(output_dir, filename)
        total_files += 1

        # 清理文章
        success = clean_article_file(input_path, output_path)

        if success:
            success_files += 1
            print(f"[+] 清理成功: {filename}")
        else:
            failed_files += 1

    print("=" * 60)
    print(f"清理完成!")
    print(f"总文件数: {total_files}")
    print(f"成功清理: {success_files}")
    print(f"处理失败: {failed_files}")

    # 显示示例
    if success_files > 0:
        print(f"\n清理后的文件已保存到: {output_dir}")
        print("前5个清理文件示例:")
        success_files_list = os.listdir(output_dir)[:5]
        for i, f in enumerate(success_files_list, 1):
            filepath = os.path.join(output_dir, f)
            try:
                with open(filepath, 'r', encoding='utf-8') as file:
                    content = file.read()
                lines = content.split('\n')
                title = lines[0] if lines else "无标题"
                print(f"  {i}. {f}")
                print(f"     标题: {title[:50]}..." if len(title) > 50 else f"     标题: {title}")
            except:
                print(f"  {i}. {f} (读取失败)")

    return success_files > 0
