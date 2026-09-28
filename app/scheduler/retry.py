from pydantic import BaseModel, Field


class RetryPolicy(BaseModel):
    max_retries: int = Field(default=0, ge=0)
    retry_delay: float = Field(default=0.0, ge=0.0)
