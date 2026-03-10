from typing import List
from pydantic import BaseModel

# USV Delimiter
USV_DELIM = "\x1f"


class Issue(BaseModel):
    slug: str
    priority: int
    status: str
    dependencies: List[str] = []

    def to_usv(self) -> str:
        deps_str = ",".join(self.dependencies)
        return f"{self.slug}{USV_DELIM}{self.priority}{USV_DELIM}{self.status}{USV_DELIM}{deps_str}"
