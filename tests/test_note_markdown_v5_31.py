# -*- coding: utf-8 -*-
"""v5.31 学习笔记 Markdown 显示契约：卡片摘要不得漏出源码噪声。

`_md_excerpt` 取代原先的 `re.sub(r'[#*`>\\-]', '', ...)`:旧口径既把正文里的连字符
一并删掉，又管不住 `![图](/uploads/x.png)` 这类图片/链接语法直接露到卡片上。
"""
from api.learning_routes import _md_excerpt


def test_heading_and_emphasis_stripped():
    assert _md_excerpt('# 标题\n\n**重点** 与 *斜体*') == '标题 重点 与 斜体'


def test_image_syntax_does_not_leak():
    s = _md_excerpt('看图 ![图1](/uploads/a.png) 完')
    assert '/uploads' not in s
    assert '![' not in s
    assert s == '看图 图1 完'


def test_link_keeps_text_only():
    assert _md_excerpt('参考 [官方文档](https://x.cn/y) 说明') == '参考 官方文档 说明'


def test_code_fence_and_list_markers():
    assert _md_excerpt('- 一\n- 二\n\n```py\nprint(1)\n```\n') == '一 二'


def test_hyphen_inside_word_survives():
    # 旧口径会把它压成 stateoftheart
    assert _md_excerpt('state-of-the-art 模型') == 'state-of-the-art 模型'


def test_underscore_identifiers_survive():
    assert _md_excerpt('用 user_id 字段') == '用 user_id 字段'


def test_length_capped():
    assert len(_md_excerpt('x' * 500, 100)) == 100


def test_display_math_collapses_to_marker():
    s = _md_excerpt('## 公式\n$$\\lim_{x \\to 0} \\frac{\\sin x}{x} = 1$$\n完')
    assert s == '公式 [公式] 完'
    assert '\\frac' not in s and '$$' not in s


def test_inline_math_collapses_to_marker():
    assert _md_excerpt('可导必连续，连续 $|x|$ 未必可导') == '可导必连续，连续 [公式] 未必可导'


def test_dollar_amount_not_swallowed():
    # 单个 $ 不构成公式，不得被折叠
    assert _md_excerpt('成本约 $10 与 $20 之间') == '成本约 $10 与 $20 之间'


def test_empty_and_none_safe():
    assert _md_excerpt('') == ''
    assert _md_excerpt(None) == ''
