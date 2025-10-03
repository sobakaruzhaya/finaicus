import os
import httpx
import json
import re
from typing import Any, Dict, List
from dotenv import load_dotenv
from os.path import join, dirname

dotenv_path = join(dirname(__file__), '../.env')
load_dotenv(dotenv_path)


def call_llm(messages: List[Dict[str, str]], temperature: float = 0.7) -> Dict[str, Any]:
    """
    Отправляет запрос в OpenRouter API и возвращает ответ в формате OpenAI.
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY не установлен в переменных окружения")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/your-username/your-project",  # обязательно для OpenRouter
        "X-Title": "Trading Assistant",
        "Content-Type": "application/json",
    }

    json_data = {
        "model": "openai/gpt-4o-mini",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 1024,
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                url="https://openrouter.ai/api/v1/chat/completions",  
                headers=headers,
                json=json_data,
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        error_detail = e.response.json() if e.response.content else {"error": str(e)}
        raise RuntimeError(f"OpenRouter API error: {error_detail}") from e
    except Exception as e:
        raise RuntimeError(f"Network or parsing error: {e}") from e


def extract_api_call(text: str) -> tuple[str | None, dict | None]:
    """
    Извлекает API_CALL и PARAMS из ответа LLM.
    Возвращает (method_name, params_dict) или (None, None)
    """
    if "API_CALL:" not in text:
        return None, None

    call_match = re.search(r"API_CALL:\s*(\w+)", text)
    params_match = re.search(r"PARAMS:\s*(\{.*?\})", text, re.DOTALL)

    if not call_match or not params_match:
        return None, None

    method = call_match.group(1)
    params_str = params_match.group(1).strip()

    try:
        params = json.loads(params_str)
        return method, params
    except json.JSONDecodeError:
        return None, None