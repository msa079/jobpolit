import json
import os
from typing import Annotated

from langchain.tools import tool
from langchain_tavily import TavilySearch
from langgraph.prebuilt import InjectedState
from pydantic import Field

from .core import parse_jd, score_match
from .config import build_model
from .schemas import UserProfile

tavily_search = TavilySearch(
    tavily_api_key=os.getenv("TAVILY_API_KEY"),
    max_results=5,
    search_depth="advanced",
    include_raw_content=True,
)

def _profile_from_state(state: dict) -> UserProfile:
    """只读取简历面板提交的画像，不从聊天中提取。"""
    profile = state.get("profile") if isinstance(state, dict) else None
    if isinstance(profile, UserProfile):
        return profile
    return UserProfile.model_validate(profile or {})


@tool
def search_jobs(
    state: Annotated[dict, InjectedState],
    company: Annotated[
        str | None,
        Field(description="目标公司全称，例如：字节跳动。用户只说“字节”时补成全称"),
    ] = None,
    position_keywords: Annotated[
        str | None,
        Field(description="岗位方向关键词，例如：Agent开发、后端开发。只传方向本身，不要传整句话，也不要带公司名"),
    ] = None,
) -> str:
    """搜索实习招聘信息，只返回岗位名称和链接，不含岗位要求。

    适用：用户想找某家公司、或某个岗位方向的在招实习岗位。
    不适用：用户问“这个岗位我匹配吗”时用 match_job；贴了 JD 只想知道要求时用 analyze_jd。

    company 和 position_keywords 至少给一个：只给了公司就只传公司，只给了方向就只传方向。
    结果会按用户在简历投递面板提交的学历和届别筛选，尽量只给能投的岗位。
    拿到的只有岗位名和链接，没有岗位要求——要判断匹配，让用户点开链接把 JD 原文贴过来。
    """

    if not company and not position_keywords:
        return "还没法搜索：请先问清用户想找哪家公司、或哪个岗位方向，至少给一个再调用。"

    profile = _profile_from_state(state)
    edu_hint = " ".join(x for x in (profile.education, profile.graduation_year) if x)

    query = " ".join(x for x in (company, position_keywords, edu_hint) if x) + " 招聘实习"
    
    desc = " ".join(x for x in (company, position_keywords) if x)

    result = tavily_search.invoke(query)
    if isinstance(result, dict) and result.get("error"):
        return (
            f"搜索服务出错：{result['error']} "
            "请如实告知用户本次搜索失败、可以稍后重试，不要编造岗位信息。"
        )
    results = []
    if isinstance(result, dict):
        results = [r for r in (result.get("results") or []) if isinstance(r, dict)]
    if not results:
        return (
            f"未找到相关岗位：未搜索到「{desc}」的实习招聘信息，"
            "请告知用户本次搜索无结果。"
        )

    slim = [
        {
            "title": r.get("title"),
            "url": r.get("url"),
        }
        for r in results
    ]
    return json.dumps(slim, ensure_ascii=False)


@tool
def analyze_jd(
    jd_text: Annotated[
        str,
        Field(description="招聘 JD 的原文完整文本，不要摘录、改写或总结"),
    ],
) -> str:
    """解析招聘 JD，列出岗位、硬性要求和加分项，不做匹配度打分。

    适用：用户贴了 JD，只想知道“这个岗位要求什么”；或想比较两个岗位的要求差异。
    不适用：用户问“我匹配吗 / 适合投吗”时用 match_job——它会自己解析 JD，
            不要先调本工具再调 match_job，否则同一份 JD 会被解析两次。

    如果 JD 里只有岗位职责、没有“要求 / 熟悉 / 掌握”这类句子，must_have 会返回空列表。
    """
   
    model = build_model(temperature=0)
    jd = parse_jd(jd_text, model)
    
    return jd.model_dump_json()


@tool
def match_job(
    jd_text: Annotated[
        str,
        Field(description="招聘 JD 的原文完整文本，不要摘录、改写或总结"),
    ],
    state: Annotated[dict, InjectedState],
) -> str:
    """评估用户和一段招聘 JD 的匹配度，给出分数、命中/缺少的技能和投递建议。

    适用：用户贴了 JD 原文，并问“这个岗位我匹配吗 / 我适合投吗”。
    不适用：用户只是想找岗位时用 search_jobs；只想知道岗位要求时用 analyze_jd。

    本工具会自己解析 JD，所以不需要先调 analyze_jd。
    用户的情况不用传：会读取服务端注入的简历画像，不从聊天历史提取。
    没有简历画像时会返回提示，此时应请用户点击“简历投递”，不要编造技能。
    """
 
    model = build_model(temperature=0)
    profile = _profile_from_state(state)

    if not (profile.skills or profile.projects or profile.target_role):
        return (
            "还没法打分：还没有提交可用于匹配的个人简历。"
            "请先点击页面右上角“简历投递”提交简历，再进行匹配；不要替用户编造技能。"
        )

    jd = parse_jd(jd_text, model)

    if not jd.must_have:
        return (
            "这段内容里没有明确的岗位要求（没看到“要求 / 熟悉 / 掌握”这类句子），没法对照打分。"
            "请让用户把招聘页里“岗位职责”和“任职要求”两段完整贴过来。"
        )

    report = score_match(jd, profile, model)

    return json.dumps(
        {"report": report.model_dump(), "profile": profile.model_dump()},
        ensure_ascii=False,
    )
