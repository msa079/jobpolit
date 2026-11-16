import os
from langchain.chat_models import BaseChatModel, init_chat_model
from dotenv import load_dotenv

load_dotenv()

def build_model(temperature: float = 0)->BaseChatModel:
    """创建并返回一个聊天模型实例。"""
    main_model = init_chat_model(
      model=os.getenv("MODEL_NAME"),
      model_provider="openai",
      base_url=os.getenv("MODEL_BASE_URL"),
      api_key=os.getenv("MODEL_API_KEY"),
      temperature=temperature,
      timeout=60,     
      max_retries=1,   
    )
    return main_model
