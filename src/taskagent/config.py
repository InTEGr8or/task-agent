from pydantic import BaseModel
from typing import Dict, Optional
import keyring
from abc import ABC, abstractmethod


class ModelConfig(BaseModel):
    provider: str
    model: str
    api_key_env: Optional[str] = None
    api_key_secret_name: Optional[str] = None


class AgentConfig(BaseModel):
    default_model: str
    models: Dict[str, ModelConfig]


class SecretManager(ABC):
    @abstractmethod
    def get_secret(self, name: str) -> Optional[str]:
        pass


class KeyringSecretManager(SecretManager):
    def __init__(self, service_name: str = "task-agent"):
        self.service_name = service_name

    def get_secret(self, name: str) -> Optional[str]:
        return keyring.get_password(self.service_name, name)
