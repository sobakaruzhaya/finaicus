import streamlit as st
import sqlite3
import os
import json
from datetime import datetime
import requests


DB_PATH = "ai_chat.db"
API_URL = "http://0.0.0.0:8000/api/local/message"  



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


def send_message_to_api(session_id: str, user_message: str, account_id: str | None = None) -> str:
    headers = {
        "accept": "application/json",
        "Content-Type": "application/json"
    }
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
    except requests.exceptions.RequestException as e:
        return f"❌ Ошибка при обращении к API: {str(e)}"
    except json.JSONDecodeError:
        return "❌ Некорректный ответ от сервера: не удалось распарсить JSON."


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
    st.title("🧠 Мои чаты")
    st.divider()


    account_id_input = st.text_input(
        "Finam Account ID",
        value=st.session_state.account_id,
        help="Укажите ID счёта Finam (опционально)",
        key="account_id_input"
    )
    if account_id_input != st.session_state.account_id:
        st.session_state.account_id = account_id_input

    st.divider()


    if st.button("➕ Новый чат", use_container_width=True):
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
    st.subheader("Список чатов")


    chats = get_all_chats()
    for chat in chats:
        col1, col2 = st.columns([5, 1])
        with col1:
            if st.button(chat["title"], key=f"chat_{chat['id']}", use_container_width=True):
                st.session_state.current_chat_id = chat["id"]
                st.rerun()
        with col2:
            if st.button("🗑️", key=f"del_{chat['id']}", help="Удалить чат"):
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

st.title("💬 AI-ассистент трейдера")

col_title, col_edit = st.columns([10, 1])
with col_title:
    new_title = st.text_input(
        "Название чата",
        value=current_title,
        label_visibility="collapsed",
        key=f"title_input_{current_chat_id}"
    )
with col_edit:
    st.write("✏️")

if new_title != current_title:
    update_chat_title(current_chat_id, new_title)
    st.rerun()


messages = get_chat_messages(current_chat_id)
for msg in messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

if prompt := st.chat_input("Напишите ваш вопрос..."):
    save_message(current_chat_id, "user", prompt)
    with st.spinner("ИИ анализирует запрос..."):
        ai_response = send_message_to_api(
            session_id=current_chat_id,
            user_message=prompt,
            account_id=st.session_state.account_id or None
        )
    save_message(current_chat_id, "assistant", ai_response)
    st.rerun()