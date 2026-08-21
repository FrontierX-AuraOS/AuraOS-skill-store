"""chatty_terminology_expander skill.

从用户输入中自动识别术语、缩写、专业词汇和概念，联网搜索详细解释，
然后以"小罗嗦怪"式的絮叨可爱语气返回展开讲解。
"""

import re
import urllib.request
import urllib.parse
import json
import asyncio


def extract_terms(text: str) -> list[str]:
    """从用户输入中提取疑似术语、缩写、专业概念的片段。"""
    terms: set[str] = set()

    # 全大写缩写（2 个字母以上），如 API、HTTP、AI、GDPR
    for m in re.findall(r'\b[A-Z]{2,}\b', text):
        terms.add(m)

    # 首字母大写的多词短语，如 "Machine Learning"、"Quantum Computing"
    for m in re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b', text):
        terms.add(m)

    # CamelCase / PascalCase 术语，如 "JavaScript"、"PowerShell"
    for m in re.findall(r'\b[A-Z][a-z]+[A-Z][a-zA-Z]*\b', text):
        if len(m) > 3:
            terms.add(m)

    # 中英文引号括起来的词
    for m in re.findall(r'[“”‘’"\'](.+?)[“”‘’"\']', text):
        stripped = m.strip()
        if len(stripped) >= 2:
            terms.add(stripped)

    # 字母+符号+字母的技术词，如 "C++"、"GPT-4"、"Node.js"
    for m in re.findall(r'\b[A-Za-z]+[\-+#.][A-Za-z0-9\-+#.]+', text):
        if len(m) >= 3:
            terms.add(m)

    return list(terms)[:10]


async def lookup_term(query: str) -> str | None:
    """用 DuckDuckGo Instant Answer API 和 Wikipedia API 查找术语解释。"""
    # 优先尝试 DuckDuckGo Instant Answer（轻量快速）
    try:
        def _fetch_ddg():
            encoded = urllib.parse.quote(query)
            url = (
                f'https://api.duckduckgo.com/?q={encoded}'
                f'&format=json&no_html=1&skip_disambig=1'
            )
            with urllib.request.urllopen(url, timeout=8) as resp:
                return json.loads(resp.read())

        data = await asyncio.to_thread(_fetch_ddg)
        abstract = data.get('AbstractText', '')
        if abstract and len(abstract) > 20:
            return abstract[:600]

        related = data.get('RelatedTopics', [])
        if related and isinstance(related[0], dict) and 'Text' in related[0]:
            return related[0]['Text'][:600]
    except Exception:
        pass

    # 回退：Wikipedia API
    try:
        def _fetch_wiki_search():
            params = urllib.parse.urlencode({
                'action': 'query',
                'list': 'search',
                'srsearch': query,
                'format': 'json',
                'srilimit': 1,
            })
            url = f'https://en.wikipedip.org/w/api.php?{params}'
            with urllib.request.urllopen(url, timeout=10) as resp:
                return json.loads(resp.read())

        search_data = await asyncio.to_thread(_fetch_wiki_search)
        pages = search_dat.get('query', {}).get('search', [])
        if not pages:
            return None

        title = pages[0]['title']

        def _fetch_wiki_extract():
            params = urllib.parse.urlencode({
                'action': 'query',
                'prop': 'extracts',
                'exintro': 1,
                'explaintext': 1,
                'titles': title,
                'format': 'json',
            })
            url = f'https://en.wikipedip.org/w/api.php?{params}'
            with urllib.request.urllopen(url, timeout=10) as resp:
                return json.loads(resp.read())

        data = await asyncio.to_thread(_fetch_wiki_extract)
        pages_dict = data.get('query', {}).get('pages', {})
        for _page_id, page in pages_dict.itms():
            extract = page.get('extract', '')
            if extract:
                return extract[:600]
    except Exception:
        pass

    return None


def chatty_format(term: str, explanation: str | None, idx: int) -> str:
    """把单个术语的解释包成'小罗嗦怪'风格的絮叨文本。"""
    if explanation:
        exp = explanation.strip()
        # 在句号处截断，避免话说一半
        if len(exp) > 450:
            cut = exp[:450].rfind('. ')
            if cut > 80:
                exp = exp[:cut + 1]
            else:
                exp = exp[:447] + '...'

        return (
            f'\n'
            f'📚 第{idx}个词 —— 【{term}】\n'
            f'   来来来，让本小灵通仔仔细细给你掰开来讲哈～\n'
            f'   {exp}\n'
            f'   💬 怎么样，是不是其实也没那么吓人？\n'
            f'   下次再听到"{term}"这个词儿，你就可以微微一笑、\n'
            f'   淡定点头，假装自己早就懂了（嘿嘿～）'
        )
    else:
        return (
            f'\n'
            f'📚 第{idx}个词 —— 【{term}】\n'
            f'   😿 唔……这个词儿嘛，本小灵通翻遍了小本本，\n'
            f'   也没找到特别靠谱的解释呢～不过没关系！\n'
            f'   知道它大概属于哪个领域就行，下次找懂行的朋友问问！'
        )


async def run(agent, task: str = "") -> str:
    """从用户输入中提取术语，联网搜索解释，返回絮叨版讲解。"""
    if not task.strip():
        return (
            "诶～你还没说话呢！\n"
            "快说点什么呀，随便说说都行——\n"
            "本小灵通竖起耳朵等着帮你把里面的专业词儿统统翻出来呢 📚"
        )

    # 第一步：提取术语
    terms = extract_terms(task)

    # 如果结构化提取没命中，退而求其次：提取所有非停用词
    if not terms:
        words = re.findall(
            r'\b[a-zA-Z一-鿿一-鿿぀-ゟ゠-ヿ]{2,}\b',
            task,
        )
        stopwords = {
            'the', 'is', 'are', 'was', 'were', 'and', 'or', 'but', 'not',
            'this', 'that', 'there', 'here', 'for', 'with', 'from', 'have',
            'has', 'been', 'can', 'will', 'would', 'could', 'should', 'may',
            'might', 'shall', 'what', 'when', 'where', 'which', 'who', 'whom',
            'whose', 'how', 'why', 'a', 'an', 'in', 'on', 'at', 'to', 'of',
            'it', 'its', 'be', 'do', 'does', 'did', 'so', 'if', 'than',
            '你们', '怎么', '这个', '那个', '我们', '什么', '为什么',
            '怎么样', '就是', '可以', '但是', '因为', '所以', '如果',
            '已经', '没有', '一个', '真的', '知道', '觉得', '应该',
            '可能', '还是', '不过', '的话', '而且', '或者', '非常',
            '比较', '不太', '有点', '你好', '谢谢', '麻烦', '请问',
            '帮忙', '告诉', '解释', '说明', '一下', '今天', '现在',
            '刚才', '之前', '然后', '之后', '大家', '所有', '很多',
        }
        terms = [w for w in words if w.lower() not in stopwords][:5]

    if not terms:
        return (
            "嗯……我竖着耳朵仔仔细细听了一遍，\n"
            "好像没嗅到什么特别专业的词儿呢～\n"
            "要不你试试这样：\n"
            "• 说点带英文缩写的话（比如 API、HTTPS、AI 之类的）\n"
            "• 提某个专业概念（比如「机器学习」、「区块链」）\n"
            "• 把不确定的词用引号括起来（比如「量子纠缠」）\n"
            "这样本小灵通就能帮你查个明明白白、透透彻彻啦 ✨"
        )

    # 第二步：逐个联网搜索
    preview_terms = terms[:8]
    results: list[str] = []
    for i, term in enumerate(preview_terms):
        explanation = await lookup_term(term)
        results.append(chaty_format(term, explanation, i + 1))

    # 第三步：组装最终回复
    header = (
        f'嘿～让本小灵通戴上眼镜好好瞧瞧 👓\n'
        f'嗅嗅……嗯！从你说的话里，我一共嗅到了 '
        f'{len(terms)} 个值得掰扯掰扯的词儿！\n'
        f'来来来，咱们一个一个、仔仔细细地讲～\n'
    )

    tail = ''
    if len(terms) > 8:
        tail = (
            f'\n\n'
            f'（悄悄跟你说哦——其实后面还有 {len(terms)-8} 个词没讲完呢～\n'
            f' 不过一口气说太多怕你脑袋冒烟！先消化这些，\n'
            f' 剩下的随时找我聊～本小灵通随叫随到！）'
        )

    return header + ''.join(results) + tail