import os
import re
import json
import time
import logging
from typing import Optional

import requests

logger = logging.getLogger("ulp.llm")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


GEN_MODEL = os.getenv("ULP_GEN_MODEL", "openrouter/free")
JUDGE_MODEL = os.getenv("ULP_JUDGE_MODEL", "openrouter/free")


SELF_VERIFY = os.getenv("ULP_SELF_VERIFY", "1") != "0"


class LLMError(Exception):
    pass


def _api_key() -> str:
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise LLMError("OPENROUTER_API_KEY не задан. Добавьте его в backend/.env")
    return key


def chat(
    messages: list[dict],
    model: str = GEN_MODEL,
    temperature: float = 0.5,
    max_tokens: int = 700,
    response_json: bool = False,
    retries: int = 4,
    timeout: int = 120,
) -> str:
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",

        "HTTP-Referer": "https://localhost",
        "X-Title": "Ultimate Learning Platform",
    }

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }


    if response_json and "free" not in model.lower():
        payload["response_format"] = {"type": "json_object"}

    last_err: Optional[str] = None

    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                OPENROUTER_URL, headers=headers, json=payload, timeout=timeout
            )
        except requests.RequestException as exc:
            last_err = f"Сеть: {exc}"
            logger.warning("LLM сетевая ошибка (попытка %s): %s", attempt, exc)
            time.sleep(1.5 * attempt)
            continue

        if resp.status_code == 200:
            try:
                data = resp.json()
            except ValueError as exc:
                last_err = f"OpenRouter вернул не-JSON: {exc}"
                logger.warning("%s (попытка %s)", last_err, attempt)
                time.sleep(1.5 * attempt)
                continue

            choices = data.get("choices")
            if choices:
                try:
                    msg = choices[0].get("message", {}) or {}


                    content = (
                        msg.get("content")
                        or msg.get("reasoning")
                        or msg.get("reasoning_content")
                        or ""
                    )
                    content = content.strip() if isinstance(content, str) else ""
                    if content:
                        return content


                    last_err = "Модель вернула пустой ответ"
                    logger.warning("%s (попытка %s)", last_err, attempt)
                    time.sleep(1.5 * attempt)
                    continue
                except (KeyError, IndexError, TypeError) as exc:
                    last_err = f"Неожиданная структура choices: {exc}"
                    logger.warning("%s (попытка %s)", last_err, attempt)
                    time.sleep(1.5 * attempt)
                    continue


            err = data.get("error")
            if isinstance(err, dict):
                msg = err.get("message", str(err))
            else:
                msg = str(err) if err else "ответ без choices"
            last_err = f"OpenRouter (200) без choices: {msg}"
            logger.warning("%s (попытка %s)", last_err, attempt)
            time.sleep(2.0 * attempt)
            continue


        if resp.status_code in (429, 500, 502, 503, 504):
            last_err = f"OpenRouter вернул {resp.status_code}"
            logger.warning("%s (попытка %s)", last_err, attempt)
            time.sleep(2.0 * attempt)
            continue


        last_err = f"OpenRouter вернул {resp.status_code}: {resp.text[:300]}"
        logger.error(last_err)
        break

    raise LLMError(last_err or "Не удалось получить ответ от модели")


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"```(?:json)?", re.IGNORECASE)


def extract_json(text: str) -> dict:
    if not text:
        raise LLMError("Пустой ответ модели")

    cleaned = _THINK_RE.sub("", text)
    cleaned = _FENCE_RE.sub("", cleaned).strip()


    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass


    start = cleaned.find("{")
    if start == -1:
        raise LLMError("В ответе модели нет JSON")

    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = cleaned[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError as exc:
                    raise LLMError(f"Не удалось разобрать JSON: {exc}") from exc

    raise LLMError("Не найден завершённый JSON-объект в ответе модели")
