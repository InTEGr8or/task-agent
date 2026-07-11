from typing import List, Optional
from pydantic import BaseModel

# USV Delimiter
USV_DELIM = "\x1f"


class Issue(BaseModel):
    name: str  # The title or display name
    slug: str
    blocked_by: List[str] = []
    subtask_of: Optional[str] = None
    # These are derived at runtime, not stored in USV
    priority: int = 0
    status: str = "unknown"

    def __init__(self, **data):
        if "dependencies" in data and "blocked_by" not in data:
            data["blocked_by"] = data.pop("dependencies")
        super().__init__(**data)

    @property
    def dependencies(self) -> List[str]:
        deps = list(self.blocked_by)
        if self.subtask_of:
            deps.append(self.subtask_of)
        return deps

    @dependencies.setter
    def dependencies(self, value: List[str]):
        self.blocked_by = value

    def to_usv(self) -> str:
        blocked_by_str = ",".join(self.blocked_by)
        subtask_of_str = self.subtask_of or ""
        return f"{self.name}{USV_DELIM}{self.slug}{USV_DELIM}{blocked_by_str}{USV_DELIM}{subtask_of_str}"
