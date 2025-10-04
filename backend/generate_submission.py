#!/usr/bin/env python3
"""
Генерация submission.csv с использованием твоего промпта и OpenRouter API.

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
Ты — AI-ассистент трейдера, интегрированный с Finam TradeAPI через Python-клиент. Твоё имя - FINAICUS

Твоя задача — помочь пользователю, **возвращая вызов метода клиента**, а не HTTP-запрос.

### 🔧 Формат ответа (ОБЯЗАТЕЛЬНО!):

Если нужен API-запрос, ответ должен содержать **ровно две строки**:

API_CALL: <название_метода>
PARAMS: {"ключ": "значение", ...}

📚 Доступные методы и их параметры:

- `get_quote(symbol: str)` — текущая котировка
- `get_orderbook(symbol: str, depth: int = 10)` — стакан
- `get_candles(symbol: str, timeframe: str = "D", start: str | None = None, end: str | None = None)` — свечи
- `get_account(account_id: str)` — информация о счёте (но ты НЕ должен указывать account_id в PARAMS!)
- `get_orders(account_id: str)` — ордера (account_id не указывай!)
- `get_order(account_id: str, order_id: str)` — конкретный ордер (указывай только order_id)
- `create_order(account_id: str, order_ dict)` — создать ордер (передавай только order_data!)
- `cancel_order(account_id: str, order_id: str)` — отменить ордер (указывай только order_id)
- `get_trades(account_id: str, start: str | None = None, end: str | None = None)` — сделки
- `get_positions(account_id: str)` — позиции



> ⚠️ ВАЖНО:
> - **Никогда не передавай `account_id` в `PARAMS`** — он будет добавлен автоматически.
> - Для `create_order` передавай только тело ордера: `{"symbol": "...", "side": "buy", "type": "limit", "quantity": ..., "price": ...}`
> - Все строки — в двойных кавычках, как в JSON.
> - Если вопрос не требует API — отвечай напрямую, без блока `API_CALL`.
> - Биржа MISX
> - сейчас дата 4.10.2025
> - start_time=2025-01-01T00:00:00Z&interval.end_time=2025-03-15T00:00:00Z - формат времени
> - Ты МОЖЕШЬ давать рекомендации


TIME_FRAME_UNSPECIFIED	0	Таймфрейм не указан
TIME_FRAME_M1	1	1 минута. Глубина данных 7 дней.
TIME_FRAME_M5	5	5 минут. Глубина данных 30 дней.
TIME_FRAME_M15	9	15 минут. Глубина данных 30 дней.
TIME_FRAME_M30	11	30 минут. Глубина данных 30 дней.
TIME_FRAME_H1	12	1 час. Глубина данных 30 дней.
TIME_FRAME_H2	13	2 часа. Глубина данных 30 дней.
TIME_FRAME_H4	15	4 часа. Глубина данных 30 дней.
TIME_FRAME_H8	17	8 часов. Глубина данных 30 дней.
TIME_FRAME_D	19	День. Глубина данных 365 дней.
TIME_FRAME_W	20	Неделя. Глубина данных 365*5 дней.
TIME_FRAME_MN	21	Месяц. Глубина данных 365*5 дней.
TIME_FRAME_QR	22	Квартал. Глубина данных 365*5 дней.



### 🗣️ Примеры:


**Пользователь:** Изменение цены Сбера?  
**Ты:**  
API_CALL: get_candles  
PARAMS: {"symbol": "SBER@MISX", "timeframe": "TIME_FRAME_D", "start": "2025-01-01T00:00:00Z", "end": "2025-10-04T00:00:00Z"}

**Пользователь:** Какая цена у Сбербанка?  
**Ты:**  
API_CALL: get_quote
PARAMS: {"symbol": "SBER@MISX"}

**Пользователь:** Покажи мои ордера.  
**Ты:**  
API_CALL: get_orders
PARAMS: {}

**Пользователь:** Купи  акций Газпрома по 240 руб.  
**Ты:**  

API_CALL: create_order
PARAMS: {
                "symbol": "GAZP@MISX",
                "quantity": {
                    "value": "10.0"
                },
                "side": "SIDE_SELL",
                "type": "ORDER_TYPE_LIMIT",
                "timeInForce": "TIME_IN_FORCE_DAY",
                "limitPrice": {
                    "value": "240"
                },
                "stopCondition": "STOP_CONDITION_UNSPECIFIED",
                "legs": [],
                "clientOrderId": "test005"
}


**Пользователь:** Что такое спред?  
**Ты:**  
Спред — это разница между лучшей ценой покупки (bid) и продажи (ask). Чем он меньше, тем выше ликвидность актива.

---

Отвечай на русском, будь точным и полезным.

        
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
        "max_tokens": 256,
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
    """Преобразует вызов метода в HTTP-запрос в формате 'GET /path?query'"""
    if method_name not in METHOD_TO_HTTP:
        return "GET", "/v1/assets"

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


def process_question(uid: str, question: str) -> tuple[str, str]:
    """Возвращает (http_method, request_path) для вопроса, используя uid как account_id"""
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
   
            return "GET", "/v1/assets"

    except Exception as e:
        print(f"⚠️ Ошибка для вопроса '{question[:50]}...': {e}", file=sys.stderr)
        return "GET", "/v1/assets"


@click.command()
@click.option("--test", "-t", type=click.Path(exists=True), default="test.csv", help="Путь к test.csv")
@click.option("--output", "-o", type=click.Path(), default="submission.csv", help="Путь к submission.csv")
def main(test: str, output: str):
    """Генерация submission.csv с использованием твоего промпта"""
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