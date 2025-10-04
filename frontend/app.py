import streamlit as st
import sqlite3
import os
import json
import re
from datetime import datetime
import requests


DB_PATH = "ai_chat.db"
API_URL = "http://0.0.0.0:8000/api/local/message"

st.markdown("""
<style>
    /* Общий фон */
    .main, .block-container {
        background-color: #0e1117;
        color: #fafafa;
        padding-top: 20px;
    }

    /* Сайдбар */
    [data-testid="stSidebar"] {
        background-color: #161a25;
        color: #e0e0e0;
        padding: 1.2rem 1rem;
    }
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2 {
        color: #ffffff;
        font-size: 1.4rem;
        margin-bottom: 0.8rem;
    }

    /* Убираем лишние отступы */
    .stChatMessage {
        margin-bottom: 6px !important;
        padding: 8px 12px !important;
    }
    .stButton > button {
        margin: 2px 0 !important;
        padding: 6px 12px !important;
        border-radius: 6px;
    }
    h1, h2, h3 {
        margin-top: 0.5rem !important;
        margin-bottom: 0.3rem !important;
    }
    hr {
        margin: 8px 0 !important;
    }

    /* Стили для карточки цены */
    .price-card {
        background: #1e1e28;
        border-radius: 8px;
        padding: 10px 14px;
        display: flex;
        gap: 14px;
        margin-top: 8px;
        width: fit-content;
        box-shadow: 0 1px 3px rgba(0,0,0,0.15);
    }
    .price-value {
        font-size: 17px;
        font-weight: bold;
        color: #ffffff;
    }
    .price-change {
        font-size: 16px;
        font-weight: 600;
    }
    .change-positive { color: #28a745; }
    .change-negative { color: #dc3545; }
</style>
""", unsafe_allow_html=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (chat_id) REFERENCES chats (id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def create_new_chat(title: str = "Новый чат") -> int:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO chats (title) VALUES (?)", (title,))
        return cursor.lastrowid

def update_chat_title(chat_id: int, new_title: str):
    with get_db_connection() as conn:
        conn.execute("UPDATE chats SET title = ? WHERE id = ?", (new_title, chat_id))

def get_all_chats():
    with get_db_connection() as conn:
        rows = conn.execute("SELECT id, title FROM chats ORDER BY created_at DESC").fetchall()
        return [{"id": r["id"], "title": r["title"]} for r in rows]

def save_message(chat_id: int, role: str, content: str):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
            (chat_id, role, content)
        )

def get_chat_messages(chat_id: int):
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY created_at ASC",
            (chat_id,)
        ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]


def extract_price_and_change(text: str) -> tuple[float | None, float | None]:
    text = text.strip()
    pattern = r'([\d\s.,]+)\s*₽?\s*(?:\(|\s*)([+-]?\d*\.?\d+)%'
    match = re.search(pattern, text)
    if not match:
        return None, None
    price_str = match.group(1).replace(' ', '').replace(',', '.')
    change_str = match.group(2)
    try:
        price = float(price_str)
        change = float(change_str)
        return price, change
    except ValueError:
        return None, None


def send_message_to_api(session_id: str, user_message: str, account_id: str | None = None) -> str:
    headers = {"accept": "application/json", "Content-Type": "application/json"}
    payload = {
        "session_id": str(session_id),
        "user_message": user_message,
        "account_id": account_id or None
    }
    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("answer", "Извините, ИИ не дал понятного ответа.")
    except Exception as e:
        return f"❌ Ошибка API: {str(e)}"


if not os.path.exists(DB_PATH):
    init_db()

if "current_chat_id" not in st.session_state:
    chats = get_all_chats()
    if chats:
        st.session_state.current_chat_id = chats[0]["id"]
    else:
        st.session_state.current_chat_id = create_new_chat("Добро пожаловать!")

if "account_id" not in st.session_state:
    st.session_state.account_id = ""

with st.sidebar:
    st.title("🧠 FINAICUS")
    st.divider()

    account_id_input = st.text_input(
        "Finam Account ID",
        value=st.session_state.account_id,
        help="Укажите ID счёта Finam",
        key="account_id_input"
    )
    if account_id_input != st.session_state.account_id:
        st.session_state.account_id = account_id_input

    st.divider()

    if st.button("➕ Новый чат", use_container_width=True, type="primary"):
        st.session_state.show_new_chat_input = True

    if st.session_state.get("show_new_chat_input", False):
        with st.form("new_chat_form", clear_on_submit=True):
            title = st.text_input("Название чата", value="Новый чат")
            submitted = st.form_submit_button("Создать")
            if submitted:
                chat_id = create_new_chat(title.strip() or "Новый чат")
                st.session_state.current_chat_id = chat_id
                st.session_state.show_new_chat_input = False
                st.rerun()
        if st.button("Отмена", use_container_width=True):
            st.session_state.show_new_chat_input = False
            st.rerun()

    st.divider()
    st.subheader("История чатов")
    chats = get_all_chats()
    for chat in chats:
        col1, col2 = st.columns([5, 1])
        with col1:
            if st.button(chat["title"], key=f"chat_{chat['id']}", use_container_width=True):
                st.session_state.current_chat_id = chat["id"]
                st.rerun()
        with col2:
            if st.button("🗑️", key=f"del_{chat['id']}", help="Удалить"):
                with get_db_connection() as conn:
                    conn.execute("DELETE FROM chats WHERE id = ?", (chat["id"],))
                st.rerun()


current_chat_id = st.session_state.current_chat_id

with get_db_connection() as conn:
    chat_row = conn.execute("SELECT title FROM chats WHERE id = ?", (current_chat_id,)).fetchone()
if not chat_row:
    st.error("Чат не найден")
    st.stop()

current_title = chat_row["title"]
st.title("💬 " + current_title)


messages = get_chat_messages(current_chat_id)
for msg in messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if msg["role"] == "assistant":
            price, change = extract_price_and_change(msg["content"])
            if price is not None and change is not None:
                change_class = "change-positive" if change >= 0 else "change-negative"
                change_sign = "+" if change >= 0 else ""
                formatted_price = f"{price:,.0f} ₽".replace(",", " ")
                formatted_change = f"{change_sign}{change:.2f}%"
                st.markdown(
                    f"""
                    <div class="price-card">
                        <div class="price-value">{formatted_price}</div>
                        <div class="price-change {change_class}">{formatted_change}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

if prompt := st.chat_input("Введите ваш запрос..."):
    save_message(current_chat_id, "user", prompt)
    with st.spinner("Анализирую запрос..."):
        ai_response = send_message_to_api(
            session_id=current_chat_id,
            user_message=prompt,
            account_id=st.session_state.account_id or None
        )
    save_message(current_chat_id, "assistant", ai_response)
    st.rerun()