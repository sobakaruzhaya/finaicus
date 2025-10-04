#!/usr/bin/env python3
"""
Генерация submission.csv с использованием OpenRouter API и кастомного промпта.

Использование:
    python scripts/generate_submission.py --test test.csv --output submission.csv
"""

import csv
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

import click
import httpx
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """
Ты — AI-ассистент трейдера, интегрированный с Finam TradeAPI через Python-клиент. 
Твоя задача — возвращать вызов метода клиента строго в формате:

API_CALL: <название_метода>
PARAMS: {"ключ": "значение", ...}


---

## 📚 Важные факты из документации (REST API Finam)

### Подключение и авторизация  
- Все запросы идут к базовому пути REST API Finam. ([tradeapi.finam.ru](https://tradeapi.finam.ru/docs/guides/rest/))  
- Токен / авторизация управляется на стороне клиента / HTTP-заголовков (вне твоей ответственности).  

### Счета (Accounts)  
- `/accounts` — информация по счетам.  
- `/accounts/{account_id}` — данные по конкретному счету.  

### Инструменты (Instruments)  
- `/instruments` — список инструментов / фильтрация.  
- `/instruments/{symbol}/quotes/latest` — котировка по инструменту.  
- `/instruments/{symbol}/orderbook` — стакан заявок.  
- `/instruments/{symbol}/bars` — исторические данные (свечи) / бары.  

### Заявки и ордера (Orders / Trades)  
- `/accounts/{account_id}/orders` — все заявки по счёту.  
- `/accounts/{account_id}/orders/{order_id}` — конкретная заявка.  
- `/accounts/{account_id}/trades` — сделки по счёту (с возможностью фильтрации по времени)  
- Отмена заявки: `DELETE /accounts/{account_id}/orders/{order_id}`  
- Создать заявку: `POST /accounts/{account_id}/orders`  

---

📌 Доступные методы:
- get_quote(symbol: str)
- get_orderbook(symbol: str, depth: int = 10)
- get_candles(symbol: str, timeframe: str = "D", start: str | None = None, end: str | None = None)
- get_account(account_id: str) → account_id НЕ передавать
- get_orders(account_id: str)
- get_order(account_id: str, order_id: str) → только order_id
- create_order(account_id: str, order_data)
- cancel_order(account_id: str, order_id: str)
- get_trades(account_id: str, start: str | None = None, end: str | None = None)
- get_positions(account_id: str)

⚠️ Правила:
- Никогда не передавай account_id в PARAMS — он добавляется автоматически.
- Если метод неочевиден, выбери ближайший по смыслу (например: цена → get_quote, история → get_candles, заявки → get_orders, позиции → get_positions).
- Никогда не придумывай неизвестных методов и не используй пустые вызовы.
- Все строки — только в JSON-формате с двойными кавычками.
- Биржа: MISX
- Сегодня: 2025-10-04
- Формат времени: 2025-01-01T00:00:00Z

Примеры:

Пользователь: Какая цена у Сбербанка?
AI:
API_CALL: get_quote
PARAMS: {"symbol": "SBER@MISX"}

Пользователь: Изменение цены Сбера с января?
AI:
API_CALL: get_candles
PARAMS: {"symbol": "SBER@MISX", "timeframe": "TIME_FRAME_D", "start": "2025-01-01T00:00:00Z", "end": "2025-10-04T00:00:00Z"}
"""

METHOD_TO_HTTP = {
    "get_quote": ("GET", "/v1/instruments/{symbol}/quotes/latest"),
    "get_orderbook": ("GET", "/v1/instruments/{symbol}/orderbook"),
    "get_candles": ("GET", "/v1/instruments/{symbol}/bars"),
    "get_account": ("GET", "/v1/accounts/{account_id}"),
    "get_orders": ("GET", "/v1/accounts/{account_id}/orders"),
    "get_order": ("GET", "/v1/accounts/{account_id}/orders/{order_id}"),
    "get_trades": ("GET", "/v1/accounts/{account_id}/trades"),
    "get_positions": ("GET", "/v1/accounts/{account_id}"),
    "create_order": ("POST", "/v1/accounts/{account_id}/orders"),
    "cancel_order": ("DELETE", "/v1/accounts/{account_id}/orders/{order_id}"),
}


def call_openrouter(messages: List[Dict[str, str]], model: str = "openai/gpt-4o-mini") -> Dict[str, Any]:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY не установлен")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/your-project",
        "X-Title": "Finam API Assistant",
        "Content-Type": "application/json",
    }

    json_data = {
        "model": model,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 128, 
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=json_data,
        )
        response.raise_for_status()
        return response.json()


def extract_api_call(text: str):
    import re
    import json

    if "API_CALL:" not in text:
        return None, None

    call_match = re.search(r"API_CALL:\s*(\w+)", text)
    params_match = re.search(r"PARAMS:\s*(\{.*?\})", text, re.DOTALL)

    if not call_match or not params_match:
        return None, None

    method = call_match.group(1)
    try:
        params = json.loads(params_match.group(1))
        return method, params
    except Exception:
        return None, None


def convert_to_http_request(method_name: str, params: dict, account_id: str) -> tuple[str, str]:
    if method_name not in METHOD_TO_HTTP:
        return "GET", "/v1/instruments"

    http_method, path_template = METHOD_TO_HTTP[method_name]
    path = path_template

    if "{symbol}" in path and "symbol" in params:
        path = path.replace("{symbol}", params["symbol"])

    if "{order_id}" in path and "order_id" in params:
        path = path.replace("{order_id}", params["order_id"])

    if "{account_id}" in path:
        path = path.replace("{account_id}", account_id)

    query_params = []
    if method_name == "get_candles":
        if "timeframe" in params:
            query_params.append(f"tf={params['timeframe']}")
        if "start" in params:
            query_params.append(f"interval.start_time={params['start']}")
        if "end" in params:
            query_params.append(f"interval.end_time={params['end']}")
    elif method_name == "get_trades":
        if "start" in params:
            query_params.append(f"interval.start_time={params['start']}")
        if "end" in params:
            query_params.append(f"interval.end_time={params['end']}")

    if query_params:
        path += "?" + "&".join(query_params)

    return http_method, path


def smart_fallback(question: str) -> tuple[str, str]:
    q = question.lower()
    if any(w in q for w in ["цена", "котировка", "quote"]):
        return "GET", "/v1/instruments/SBER@MISX/quotes/latest"
    if any(w in q for w in ["свеч", "динамика", "истор", "график"]):
        return "GET", "/v1/instruments/SBER@MISX/bars?tf=TIME_FRAME_D"
    if any(w in q for w in ["ордер", "заявк"]):
        return "GET", "/v1/accounts/{account_id}/orders"
    if any(w in q for w in ["позици", "portfolio"]):
        return "GET", "/v1/accounts/{account_id}"
    return "GET", "/v1/instruments"


def process_question(uid: str, question: str) -> tuple[str, str]:
    """Возвращает (http_method, request_path) для вопроса"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    try:
        response = call_openrouter(messages)
        llm_text = response["choices"][0]["message"]["content"]

        method_name, params = extract_api_call(llm_text)

        if method_name and params is not None:
            http_method, request_path = convert_to_http_request(method_name, params, account_id=uid)
            return http_method, request_path
        else:
            return smart_fallback(question)

    except Exception as e:
        print(f"⚠️ Ошибка для вопроса '{question[:50]}...': {e}", file=sys.stderr)
        return smart_fallback(question)


@click.command()
@click.option("--test", "-t", type=click.Path(exists=True), default="test.csv", help="Путь к test.csv")
@click.option("--output", "-o", type=click.Path(), default="submission.csv", help="Путь к submission.csv")
def main(test: str, output: str):
    """Генерация submission.csv"""
    test_path = Path(test)
    output_path = Path(output)

    questions = []
    with open(test_path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            questions.append({"uid": row["uid"], "question": row["question"]})

    print(f"Загружено {len(questions)} вопросов из {test_path}")

    results = []
    for item in questions:
        uid = item["uid"]
        question = item["question"]
        http_method, request_path = process_question(uid, question)
        results.append({"uid": uid, "type": http_method, "request": request_path})
        print(f"✅ {uid}: {http_method} {request_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["uid", "type", "request"], delimiter=";")
        writer.writeheader()
        writer.writerows(results)

    print(f"\n🎉 Готово! Результат сохранён в {output_path}")


if __name__ == "__main__":
    main()
