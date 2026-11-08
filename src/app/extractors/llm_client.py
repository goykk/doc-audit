"""Minimal DashScope OpenAI-compatible chat client (text only)."""
from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from app.config import settings


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMResponse:
    content: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    cost_cny: float


def _cost(
    prompt_tokens: int, completion_tokens: int, input_price: float, output_price: float
) -> float:
    return round(
        prompt_tokens / 1000 * input_price
        + completion_tokens / 1000 * output_price,
        6,
    )


def chat(
    messages: list[dict],
    model: str | None = None,
    json_mode: bool = True,
    max_tokens: int = 2048,
    input_price_per_1k: float | None = None,
    output_price_per_1k: float | None = None,
    response_format: dict | None = None,
) -> LLMResponse:
    if not settings.dashscope_api_key:
        raise LLMError("DASHSCOPE_API_KEY is not configured")
    model = model or settings.llm_model
    url = settings.dashscope_base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.dashscope_api_key}",
        "Content-Type": "application/json",
    }
    payload: dict = {
        "model": model,
        "messages": messages,
        "temperature": settings.llm_temperature,
        "max_tokens": max_tokens,
    }
    if response_format is not None:
        payload["response_format"] = response_format
    elif json_mode:
        payload["response_format"] = {"type": "json_object"}

    started = time.perf_counter()
    last_error = ""
    with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
        for attempt in range(settings.llm_max_retries):
            try:
                response = client.post(url, headers=headers, json=payload)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt == settings.llm_max_retries - 1:
                    break
                time.sleep(2**attempt)
                continue

            if response.status_code == 200:
                body = response.json()
                try:
                    content = body["choices"][0]["message"]["content"]
                except (KeyError, IndexError) as exc:
                    raise LLMError(f"unexpected response shape: {body}") from exc
                usage = body.get("usage") or {}
                prompt_tokens = int(usage.get("prompt_tokens") or 0)
                completion_tokens = int(usage.get("completion_tokens") or 0)
                return LLMResponse(
                    content=content or "",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_ms=round((time.perf_counter() - started) * 1000),
                    cost_cny=_cost(
                        prompt_tokens,
                        completion_tokens,
                        input_price_per_1k
                        if input_price_per_1k is not None
                        else settings.llm_input_price_per_1k,
                        output_price_per_1k
                        if output_price_per_1k is not None
                        else settings.llm_output_price_per_1k,
                    ),
                )

            body_text = response.text[:500]
            if (
                response.status_code == 400
                and "response_format" in body_text
                and json_mode
                and response_format is None
            ):
                # Some deployments reject json_object; retry once without it.
                payload.pop("response_format", None)
                json_mode = False
                continue
            if response.status_code in (400, 401, 403, 404):
                raise LLMError(f"LLM request failed ({response.status_code}): {body_text}")
            last_error = f"HTTP {response.status_code}: {body_text}"
            if attempt == settings.llm_max_retries - 1:
                break
            time.sleep(2**attempt)

    raise LLMError(f"LLM request failed after retries: {last_error}")
