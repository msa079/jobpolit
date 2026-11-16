from typing import TypeVar

from pydantic import BaseModel
from langchain_core.messages import HumanMessage, SystemMessage

from .config import build_model
from .schemas import JobRequirement, UserProfile, MatchReport
from .prompts import JD_PARSER_PROMPT, PROFILE_EXTRACT_PROMPT, MATCH_SCORE_PROMPT

T = TypeVar("T", bound=BaseModel)


def _structured(prompt: str, schema: type[T], text: str, model=None) -> T:
    """按指定提示词和输出结构解析文本；可传入模型复用。"""
    model = model or build_model(temperature=0)
    structured_model = model.with_structured_output(schema)
    messages = [
        SystemMessage(prompt),
        HumanMessage(text),
    ]
    
    return structured_model.invoke(messages)  # pyright: ignore[reportReturnType]


def parse_jd(jd_text: str, model=None) -> JobRequirement:
    """把一段 JD 原文抽成结构化的 JobRequirement 对象。"""
    return _structured(JD_PARSER_PROMPT, JobRequirement, jd_text, model)


def extract_profile(text: str, model=None) -> UserProfile:
    """从简历面板提交的文本提取画像；保存与完整替换由网页后端负责。"""
    return _structured(PROFILE_EXTRACT_PROMPT, UserProfile, text, model)


def score_match(jd: JobRequirement, profile: UserProfile, model=None) -> MatchReport:
    """根据用户简历和岗位需求，计算匹配分数和匹配程度。"""
    text = f"岗位要求：\n{jd.model_dump_json()}\n\n候选人画像：\n{profile.model_dump_json()}"
    report = _structured(MATCH_SCORE_PROMPT, MatchReport, text, model)

    if not report.education_ok:
        return report.model_copy(update={"score": 0, "level": "low", "result": "不建议投递"})
    return report
