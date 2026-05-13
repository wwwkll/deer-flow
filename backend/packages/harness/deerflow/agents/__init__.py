import warnings

# 抑制 langgraph 子流程中的高频噪声警告：
# 1. PydanticSerializationUnexpectedValue：在每次 tool/subagent 调用时都会触发
#    （field_name='context' 类型推断未命中），日志里上百条但不影响功能。
# 2. "Parameters {'extra_body'} should be specified explicitly"：每次创建
#    langchain_openai ChatOpenAI 实例时触发，已知本地模型配置故意通过 model_kwargs
#    传递 extra_body（见 config.yaml 的 repetition_penalty 等参数）。
warnings.filterwarnings(
    "ignore",
    message=r".*Pydantic serializer warnings.*",
    category=UserWarning,
    module=r"pydantic\.main",
)
warnings.filterwarnings(
    "ignore",
    message=r".*Parameters \{'extra_body'\} should be specified explicitly.*",
    category=UserWarning,
)

from .checkpointer import get_checkpointer, make_checkpointer, reset_checkpointer
from .factory import create_deerflow_agent
from .features import Next, Prev, RuntimeFeatures
from .lead_agent import make_lead_agent
from .lead_agent.prompt import prime_enabled_skills_cache
from .thread_state import SandboxState, ThreadState

# LangGraph imports deerflow.agents when registering the graph. Prime the
# enabled-skills cache here so the request path can usually read a warm cache
# without forcing synchronous filesystem work during prompt module import.
prime_enabled_skills_cache()

__all__ = [
    "create_deerflow_agent",
    "RuntimeFeatures",
    "Next",
    "Prev",
    "make_lead_agent",
    "SandboxState",
    "ThreadState",
    "get_checkpointer",
    "reset_checkpointer",
    "make_checkpointer",
]
