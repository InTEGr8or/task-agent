from pydantic import BaseModel

# USV Delimiter
USV_DELIM = '\x1f'

class Issue(BaseModel):
    slug: str
    priority: int
    status: str

    def to_usv(self) -> str:
        return f"{self.slug}{USV_DELIM}{self.priority}{USV_DELIM}{self.status}"
