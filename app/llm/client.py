import json

from openai import OpenAI
from pydantic import BaseModel

from app.config import settings


class LLMClient:
    """Small OpenAI-compatible structured-output client."""

    def __init__(self) -> None:
        if not settings.llm_api_key:
            raise RuntimeError("LLM_API_KEY is not configured; LLM calls are disabled.")
        self._client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)

    def structured_completion(self, prompt: str, response_model: type[BaseModel]) -> BaseModel:
        try:
            response = self._client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {
                        "role": "system",
                        "content": "Return only valid JSON matching the requested schema.",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("LLM returned an empty response.")
            return response_model.model_validate(json.loads(content))
        except Exception as exc:
            raise RuntimeError(f"LLM structured completion failed: {exc}") from exc
