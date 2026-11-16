from langchain.agents import AgentState, create_agent

from .db import new_checkpointer
from .prompts import SYSTEM_PROMPT,RESUME_PROMPT
from .tools import analyze_jd, match_job, search_jobs
from .config import build_model

class ResumeState(AgentState):
    profile: dict


def config_for(thread_id: str) -> dict:
    """把 thread_id 包成 LangGraph 需要的 config 结构。"""
    return {"configurable": {"thread_id": thread_id}}


def build_agent(model=None, temperature: float = 0.2):
    """构建 agent。传入 model 则直接用，否则按 temperature 新建一个。"""
    model = model or build_model(temperature)
    checkpointer = new_checkpointer()
    return create_agent(
        model,
        tools=[search_jobs, analyze_jd, match_job],
        system_prompt=SYSTEM_PROMPT + RESUME_PROMPT,
        state_schema=ResumeState,
        checkpointer=checkpointer,
    )


