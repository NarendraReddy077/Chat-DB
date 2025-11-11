import streamlit as st
import google.generativeai as genai
from sqlalchemy import create_engine, text
from utilities import text2sql, get_db_schema
from constants import DB_PATH
import os

# ---------------------- PAGE CONFIG ----------------------
st.set_page_config(page_title="ChatDB - Chat with SQL", page_icon="🤖", layout="wide")

st.markdown(
    """
    <style>
        .main-header {
            font-size: 2rem;
            font-weight: bold;
            text-align: center;
            margin-bottom: 0.5rem;
        }
        .sub-header {
            text-align: center;
            color: gray;
            margin-bottom: 2rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)
st.markdown("<div class='main-header'>🦜 ChatDB</div>", unsafe_allow_html=True)
st.markdown("<div class='sub-header'>Chat naturally with your SQL database and get instant insights</div>", unsafe_allow_html=True)

# ---------------------- SESSION INITIALIZATION ----------------------
if "engine" not in st.session_state:
    st.session_state.engine = None
if "connected_db" not in st.session_state:
    st.session_state.connected_db = "Default SQLite"
if "question_history" not in st.session_state:
    st.session_state.question_history = []
if "show_schema" not in st.session_state:
    st.session_state.show_schema = False
if "show_history" not in st.session_state:
    st.session_state.show_history = False
if "last_sql_query" not in st.session_state:
    st.session_state.last_sql_query = None
if "last_result" not in st.session_state:
    st.session_state.last_result = None

# ---------------------- DB HELPER ----------------------
def get_database(db_type, db_path=None, mysql_host=None, mysql_user=None, mysql_password=None, mysql_db=None, mysql_port=3306):
    """Return SQLAlchemy engine for SQLite or MySQL."""
    try:
        if db_type == "sqlite":
            if not db_path:
                raise ValueError("SQLite path missing.")
            return create_engine(f"sqlite:///{db_path}")

        elif db_type == "mysql":
            if not all([mysql_host, mysql_user, mysql_password, mysql_db]):
                raise ValueError("Missing MySQL details.")
            url = f"mysql+mysqlconnector://{mysql_user}:{mysql_password}@{mysql_host}:{mysql_port}/{mysql_db}"
            return create_engine(url)
    except Exception as e:
        st.error(f"❌ Database connection failed: {e}")
        return None

# ---------------------- CONNECT DATABASE ----------------------
st.sidebar.subheader("🗄️ Database Connection")

mode = st.sidebar.radio(
    "Select Connection Type:",
    ["Use Default Demo Database (SQLite)", "Connect MySQL Database"],
)

fallback_used = False

if mode == "Connect MySQL Database":
    mysql_host = st.sidebar.text_input("MySQL Host", value="localhost")
    mysql_port = st.sidebar.text_input("Port", value="3306")
    mysql_user = st.sidebar.text_input("Username", value="root")
    mysql_password = st.sidebar.text_input("Password", type="password")
    mysql_db = st.sidebar.text_input("Database Name")

    if st.sidebar.button("🔗 Connect"):
        try:
            engine = get_database(
                "mysql",
                mysql_host=mysql_host,
                mysql_user=mysql_user,
                mysql_password=mysql_password,
                mysql_db=mysql_db,
                mysql_port=int(mysql_port),
            )
            # ✅ FIX: wrap SQL in text()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            st.session_state.engine = engine
            st.session_state.connected_db = f"MySQL ({mysql_db})"
            st.sidebar.success(f"✅ Connected to MySQL Database: {mysql_db}")
        except Exception as e:
            st.sidebar.error(f"❌ MySQL connection failed: {e}")
            st.sidebar.info("🔄 Falling back to demo SQLite database...")
            engine = get_database("sqlite", db_path=DB_PATH)
            if engine:
                st.session_state.engine = engine
                st.session_state.connected_db = "Default SQLite (Fallback)"
                fallback_used = True

else:
    if st.session_state.engine is None or st.session_state.connected_db != "Default SQLite":
        engine = get_database("sqlite", db_path=DB_PATH)
        if engine:
            st.session_state.engine = engine
            st.session_state.connected_db = "Default SQLite"
            st.sidebar.success("✅ Using default demo SQLite database.")

# Stop if nothing connected
if not st.session_state.engine:
    st.error("⚠️ No database connection found. Please connect to continue.")
    st.stop()

# ---------------------- GEMINI API SETUP ----------------------
api_key = st.sidebar.text_input("Enter your Google Gemini API Key:", type="password")
if not api_key:
    st.warning("🔑 Please provide your Google API key to continue.")
    st.stop()

try:
    genai.configure(api_key=api_key)
    genai_client = genai.GenerativeModel(model_name="gemini-2.5-flash")
except Exception as e:
    st.error(f"❌ API configuration failed: {e}")
    st.stop()

# ---------------------- MAIN CHAT ----------------------
st.write(f"### 📊 Connected Database: `{st.session_state.connected_db}`")
if fallback_used:
    st.info("⚙️ You’re now using the demo database because your MySQL connection failed.")

query = st.text_input("💬 Ask your question about the database:")

if st.button("Execute"):
    if not query.strip():
        st.warning("⚠️ Please enter a valid question.")
        st.stop()

    if not st.session_state.question_history or query != st.session_state.question_history[-1]:
        st.session_state.question_history.append(query)

    sql_query, result = text2sql(genai_client, query, st.session_state.engine)
    st.session_state.last_sql_query = sql_query
    st.session_state.last_result = result

# ---------------------- DISPLAY ----------------------
if st.session_state.last_sql_query or st.session_state.last_result:
    with st.expander("🧠 Generated SQL Query", expanded=True):
        st.code(st.session_state.last_sql_query or "No SQL generated", language="sql")
    with st.expander("📊 Query Result", expanded=True):
        if st.session_state.last_result is not None:
            st.write(st.session_state.last_result)
        else:
            st.info("No results to display.")
else:
    st.info("💡 Type a question and click Execute to get started.")

# ---------------------- SCHEMA ----------------------
def toggle_schema():
    st.session_state.show_schema = not st.session_state.show_schema

toggle_label = "📘 View Database Schema" if not st.session_state.show_schema else "🙈 Hide Database Schema"
st.sidebar.button(toggle_label, on_click=toggle_schema)

if st.session_state.show_schema:
    with st.expander("📘 Database Schema", expanded=True):
        with st.spinner("Fetching schema..."):
            schema_text = get_db_schema(st.session_state.engine)
            st.markdown(schema_text)
            st.download_button(
                "⬇️ Download Schema",
                schema_text,
                file_name="database_schema.md",
                mime="text/markdown",
            )

# ---------------------- HISTORY + RESET ----------------------
def toggle_history():
    st.session_state.show_history = not st.session_state.show_history

def reset_conversation():
    st.session_state.question_history = []
    st.session_state.last_sql_query = None
    st.session_state.last_result = None
    st.sidebar.success("✅ Cleared history and last output!")

st.sidebar.markdown("---")
history_label = "📜 Show History" if not st.session_state.show_history else "🙈 Hide History"
st.sidebar.button(history_label, on_click=toggle_history)

if st.session_state.show_history:
    st.sidebar.markdown("### 💬 Questions Asked (This Session)")
    if st.session_state.question_history:
        for i, question in enumerate(reversed(st.session_state.question_history), 1):
            st.sidebar.markdown(f"**{i}.** {question}")
    else:
        st.sidebar.info("No questions asked yet.")
    st.sidebar.markdown("---")
    st.sidebar.button("♻️ Reset Conversation", on_click=reset_conversation)
