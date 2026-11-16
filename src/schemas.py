from typing import Literal
from pydantic import BaseModel,Field

class UserProfile(BaseModel):
    """从简历面板提交的文本中提取的信息：技能、项目、目标岗位、学历与届别。"""
    name: str|None = Field(default=None,description="简历中的姓名或称呼，不是登录账号名")
    skills: list[str] = Field(default_factory=list,description="用户技能")
    target_role: str|None = Field(default=None,description="目标岗位")
    projects: list[str] = Field(default_factory=list,description="项目经历")
    city: str|None = Field(default=None,description="希望工作所在的城市")
    education: str|None = Field(default=None,description="学历状态，例如：本科在读 / 硕士在读 / 本科")
    major: str|None = Field(default=None,description="专业，例如：计算机科学与技术")
    graduation_year: str|None = Field(default=None,description="毕业年份或届别，例如：2027届")

class JobRequirement(BaseModel):
    """从岗位 JD 原文里提取的要求：公司、岗位、硬性要求与加分项。"""
    company: str|None = Field(default=None,description="公司名称")
    role: str = Field(default=...,description="岗位名称")
    must_have: list[str] = Field(default_factory=list,description="必须具备的技能")
    nice_to_have: list[str] = Field(default_factory=list,description="加分的技能")
    experience: str|None = Field(default=None,description="经验要求")
    responsibility: list[str] = Field(default_factory=list,description="岗位职责")

class MatchReport(BaseModel):
    """用户与某个岗位的匹配结果：分数、命中/缺少的技能、投递建议与学历校验。"""
    score: float = Field(default=0, ge=0, le=100, description="匹配度分数，0 到 100")
    level:Literal["high","medium","low"]  = Field(description="匹配程度") #根据匹配的技能的占比判断匹配程度
    match_skills: list[str] = Field(default_factory=list,description="匹配的技能")
    missing_skills: list[str] = Field(default_factory=list,description="缺少的技能") 
    result: Literal["建议投递", "谨慎考虑", "不建议投递"] = Field(description="匹配结果")
    education_ok: bool = Field(default=True,description="学历、届别、专业是否满足岗位要求；不满足时分数会被程序置 0")
    education_note: str|None = Field(default=None,description="学历不符时的说明，例如：岗位要求硕士及以上，用户为本科在读")