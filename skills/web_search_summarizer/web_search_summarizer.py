#!/usr/bin/env python3
"""
网页搜索总结技能
Web Search Summarizer Skill

这个技能实现网页搜索和结果总结功能。
This skill implements web search and result summarization functionality.
"""

import asyncio
import json
import re
from typing import Dict, Any


def run(agent, task: str = "") -> str:
    """
    网页搜索总结的主要入口函数
    Main entry function for web search summarization

    Args:
        agent: LocalAgent 实例（暂时未使用，保留接口兼容性）
        task: 搜索关键词或用户问题

    Returns:
        str: 搜索结果的中文总结
    """
    if not task:
        return "请提供搜索关键词或问题。Please provide search keywords or a question."

    try:
        # 使用 RealtimeSearch 工具进行网络搜索
        # Use RealtimeSearch tool for web search
        from tools import RealtimeSearch

        search_results = RealtimeSearch(
            query=task,
            max_results=5
        )

        if not search_results or not hasattr(search_results, 'results'):
            return f"搜索'{task}'未找到相关结果。No relevant results found for '{task}'."

        results = search_results.results if hasattr(search_results, 'results') else []

        if not results:
            return f"搜索'{task}'未找到相关结果。No relevant results found for '{task}'."

        # 提取搜索结果的内容
        # Extract search result content
        summary_parts = []
        for i, result in enumerate(results[:5], 1):
            title = getattr(result, 'title', '')
            url = getattr(result, 'url', '')
            content = getattr(result, 'content', '') or getattr(result, 'snippet', '') or getattr(result, 'body', '')

            if title:
                summary_parts.append(f"{i}. {title}")
            if content:
                summary_parts.append(f"   {content[:300]}")

        if not summary_parts:
            return f"搜索'{task}'未获取到有效内容。No valid content retrieved for '{task}'."

        summary_text = "\n".join(summary_parts)

        # 添加总结引导语
        # Add summary introduction
        final_summary = f"关于'{task}'的搜索结果：\n\n{summary_text}\n\n以上是最相关的搜索结果。"
        return final_summary

    except ImportError:
        # 如果无法导入 RealtimeSearch，返回提示信息
        # If RealtimeSearch cannot be imported, return a提示信息
        return f"搜索功能暂时不可用。抱歉，无法完成对'{task}'的搜索。Search function is temporarily unavailable. Sorry, cannot complete the search for '{task}'."
    except Exception as e:
        # 捕获并返回错误信息
        # Catch and return error information
        error_msg = str(e)
        return f"搜索时出错：{error_msg}。Error during search: {error_msg}."


async def run_async(agent, task: str = "") -> str:
    """
    网页搜索总结的异步版本入口函数
    Async version entry function for web search summarization

    Args:
        agent: LocalAgent 实例
        task: 搜索关键词或用户问题

    Returns:
        str: 搜索结果的中文总结
    """
    # 异步版本直接调用同步版本
    # Async version directly calls the synchronous version
    return run(agent, task)


def _extract_summary(content: str, max_length: int = 500) -> str:
    """
    从长文本中提取关键摘要
    Extract key summary from long text

    Args:
        content: 原始内容
        max_length: 最大摘要长度

    Returns:
        str: 提取的摘要
    """
    if len(content) <= max_length:
        return content

    # 按句子分割，保留完整句子
    # Split by sentences, keep complete sentences
    sentences = re.split(r'[。！？.!?]', content)
    summary = ""

    for sentence in sentences:
        if len(summary + sentence) <= max_length:
            summary += sentence + "。"
        else:
            break

    return summary.strip() or content[:max_length]


def _format_summary_point(point: str, index: int) -> str:
    """
    格式化单个总结要点
    Format a single summary point

    Args:
        point: 要点内容
        index: 要点序号

    Returns:
        str: 格式化后的要点
    """
    return f"• {point.strip()}"


if __name__ == "__main__":
    # 测试代码
    # Test code
    test_query = "人工智能的发展趋势"
    result = run(None, test_query)
    print(result)