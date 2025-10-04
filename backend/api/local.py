from fastapi import APIRouter, HTTPException, Body
from typing import List, Dict, Any, Optional, Tuple
import json
import re
import os
from utils.finam import FinamAPIClient
from utils.openrouter import call_llm
from pydantic import BaseModel
from dotenv import load_dotenv
from os.path import join, dirname


dotenv_path = join(dirname(__file__), '../.env')
load_dotenv(dotenv_path)

FINAM_TOKEN = os.getenv("FINAM_ACCESS_TOKEN")


router = APIRouter()
SESSIONS: Dict[str, List[Dict[str, str]]] = {}

def create_system_prompt(): 
    return """
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

def extract_api_call(text: str) -> Tuple[Optional[str], Optional[Dict]]:
    if "API_CALL:" not in text:
        return None, None
    print(text)
    call_match = re.search(r"API_CALL:\s*(\w+)", text)
    params_match = re.search(r"PARAMS:\s*(\{.*?\})", text, re.DOTALL)
    if not call_match or not params_match:
        return None, None

    method = call_match.group(1)
    params_str = params_match.group(1).strip()
    print(method, params_str)
    try:
        params = json.loads(params_str)
        return method, params
    except json.JSONDecodeError:
        return None, None


class MessageRequest(BaseModel):
    session_id: str  
    user_message: str
    account_id: Optional[str] = None 

class MessageResponse(BaseModel):
    answer: str
    session_id: str

@router.post("/message", response_model=MessageResponse)
async def message(request: MessageRequest = Body(...)):
    finam_client = FinamAPIClient(access_token=FINAM_TOKEN)

    session_id = request.session_id
    user_msg = request.user_message
    account_id = request.account_id


    if session_id not in SESSIONS:
        SESSIONS[session_id] = [{"role": "system", "content": create_system_prompt()}]

    conversation = SESSIONS[session_id]
    conversation.append({"role": "user", "content": user_msg})

    try:
        response = call_llm(conversation, temperature=0.3)
        assistant_message = response["choices"][0]["message"]["content"]

        method_name, params = extract_api_call(assistant_message)

        if method_name and params is not None:
            requires_account = method_name in {
                "get_account", "get_orders", "get_order", "create_order",
                "cancel_order", "get_trades", "get_positions"
            }

            api_response: Dict[str, Any] = {"error": "Неизвестная ошибка"}

            try:
                if requires_account:
                    if not account_id:
                        api_response = {"error": "account_id обязателен для этого метода"}
                    else:
                        if method_name == "create_order":
                            api_response = finam_client.create_order(account_id, params)
                        elif method_name == "cancel_order":
                            order_id = params.get("order_id")
                            if not order_id:
                                api_response = {"error": "order_id обязателен для cancel_order"}
                            else:
                                api_response = finam_client.cancel_order(account_id, order_id)
                        elif method_name == "get_order":
                            order_id = params.get("order_id")
                            if not order_id:
                                api_response = {"error": "order_id обязателен для get_order"}
                            else:
                                api_response = finam_client.get_order(account_id, order_id)
                        else:
                            api_response = getattr(finam_client, method_name)(account_id)
                else:
                    print(getattr(finam_client, method_name)(**params))
                    api_response = getattr(finam_client, method_name)(**params)

            except AttributeError:
                api_response = {"error": f"Метод не найден: {method_name}"}
            except Exception as e:
                api_response = {"error": str(e)}


            conversation.append({"role": "assistant", "content": assistant_message})
            conversation.append({
                "role": "user",
                "content": f"Результат API вызова: {api_response}\n\nПроанализируй это.",
            })


            response = call_llm(conversation, temperature=0.3)
            assistant_message = response["choices"][0]["message"]["content"]

        conversation.append({"role": "assistant", "content": assistant_message})
        SESSIONS[session_id] = conversation

        return MessageResponse(answer=assistant_message, session_id=session_id)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка обработки: {str(e)}")