from pydantic import BaseModel, Field
from typing import Dict, Optional

class ModelConfig(BaseModel):
    provider: str
    model: str
    api_key_env: Optional[str] = None
    api_key_secret_name: Optional[str] = None

class AgentConfig(BaseModel):
    default_model: str
    models: Dict[str, ModelConfig]

