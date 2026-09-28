import re

from pydantic import BaseModel, Field, model_validator

from .capability import CapabilityName


class AgentRole(BaseModel):
    name: str
    capabilities: list[CapabilityName]
    goal: str
    backstory: str = ""


class AgentSpec(BaseModel):
    id: str | None = None
    role: AgentRole
    tools: list[str] = Field(default_factory=list)
    max_iterations: int = Field(default=3, ge=1)

    @model_validator(mode="after")
    def assign_default_id(self) -> "AgentSpec":
        if self.id is None:
            self.id = re.sub(r"[^a-z0-9]+", "_", self.role.name.lower()).strip("_")
        return self
