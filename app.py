import streamlit as st
import google.generativeai as genai
from sqlalchemy import create_engine
from utilities import text2sql, get_db_schema
from constants import DB_PATH

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

# ---------------------- SIDEBAR ----------------------
st.sidebar.header("⚙️ Configuration")

# Database Mode
db_option = st.sidebar.radio(
    "Choose Database Mode",
    ["Use default SQLite Database", "Connect to MySQL Database"]
)

# ---------------------- SESSION INITIALIZATION ----------------------
if "engine" not in st.session_state:
    st.session_state.engine = None
if "question_history" not in st.session_state:
    st.session_state.question_history = []
if "show_schema" not in st.session_state:
    st.session_state.show_schema = False
if "show_history" not in st.session_state:
    st.session_state.show_history = False

# ---------------------- DATABASE CONNECTION (Fixed Switching) ----------------------
def get_database(db_type, db_path=None, mysql_host=None, mysql_user=None, mysql_password=None, mysql_db=None, mysql_port=3306):
    """Create a database engine for SQLite or MySQL."""
    try:
        if db_type == "sqlite":
            if not db_path:
                raise ValueError("SQLite DB path not provided.")
            return create_engine(f"sqlite:///{db_path}")

        elif db_type == "mysql":
            if not all([mysql_host, mysql_user, mysql_password, mysql_db]):
                raise ValueError("Missing MySQL connection details.")
            engine_url = f"mysql+mysqlconnector://{mysql_user}:{mysql_password}@{mysql_host}:{mysql_port}/{mysql_db}"
            return create_engine(engine_url)
    except Exception as e:
        st.error(f"❌ Database connection failed: {e}")
        return None


# --- Handle database selection ---
if "db_mode" not in st.session_state:
    st.session_state.db_mode = db_option  # Track which mode is active

# If user changes the DB mode, reset the engine
if db_option != st.session_state.db_mode:
    st.session_state.engine = None
    st.session_state.db_mode = db_option
    st.info(f"🔄 Switched to {db_option}. Please reconnect if needed.")

# Connect to SQLite (default)
if db_option == "Use default SQLite Database":
    if st.session_state.engine is None:
        engine = get_database("sqlite", db_path=DB_PATH)
        if engine:
            st.session_state.engine = engine
            st.success("✅ Connected to default SQLite database!")

# Connect to MySQL (manual connection)
elif db_option == "Connect to MySQL Database":
    mysql_host = st.sidebar.text_input("MySQL Host", value="localhost")
    mysql_port = st.sidebar.text_input("MySQL Port", value="3306")
    mysql_user = st.sidebar.text_input("MySQL Username", value="root")
    mysql_password = st.sidebar.text_input("MySQL Password", type="password")
    mysql_db = st.sidebar.text_input("MySQL Database Name")

    if st.sidebar.button("Connect to MySQL"):
        try:
            port_val = int(mysql_port)
            engine = get_database(
                "mysql",
                mysql_host=mysql_host,
                mysql_user=mysql_user,
                mysql_password=mysql_password,
                mysql_db=mysql_db,
                mysql_port=port_val
            )
            if engine:
                st.session_state.engine = engine
                st.success(f"✅ Connected to MySQL Database: {mysql_db}")
            else:
                st.error("❌ Could not establish a connection to MySQL.")
        except ValueError:
            st.error("MySQL port must be a number (e.g. 3306).")

# Stop app until valid connection is available
if not st.session_state.engine:
    st.info("ℹ️ Waiting for a valid database connection...")
    st.stop()

# ---------------------- GEMINI API SETUP ----------------------
api_key = st.sidebar.text_input("Enter your Google Gemini API Key:", type="password")
if not api_key:
    st.warning("🔑 Provide your Google API key to continue")
    st.stop()

try:
    genai.configure(api_key=api_key)
    genai_client = genai.GenerativeModel(model_name="gemini-2.5-flash")
except Exception as e:
    st.error(f"❌ API configuration failed: {e}")
    st.stop()

# ---------------------- QUERY EXECUTION (Persistent Display) ----------------------
if "last_sql_query" not in st.session_state:
    st.session_state.last_sql_query = None
if "last_result" not in st.session_state:
    st.session_state.last_result = None

query = st.text_input("Ask your question about the database:")

if st.button("Execute"):
    if not query.strip():
        st.warning("⚠️ Please enter a valid question.")
        st.stop()

    # Add question to history (no duplicates)
    if not st.session_state.question_history or query != st.session_state.question_history[-1]:
        st.session_state.question_history.append(query)

    # Execute query
    sql_query, result = text2sql(genai_client, query, st.session_state.engine)

    # Save latest output in session (persist on sidebar interactions)
    st.session_state.last_sql_query = sql_query
    st.session_state.last_result = result

# ---------------------- DISPLAY PERSISTENT RESULTS ----------------------
if st.session_state.last_sql_query or st.session_state.last_result:
    with st.expander("🧠 Generated SQL Query", expanded=True):
        if st.session_state.last_sql_query:
            st.code(st.session_state.last_sql_query, language="sql")
        else:
            st.info("No SQL query generated yet.")

    with st.expander("📊 Query Result", expanded=True):
        if st.session_state.last_result is not None:
            st.write(st.session_state.last_result)
        else:
            st.info("No results to display.")
else:
    st.write("💬 Enter a question to get started.")


# ---------------------- VIEW / HIDE SCHEMA ----------------------
def toggle_schema():
    st.session_state.show_schema = not st.session_state.show_schema

toggle_label = "📘 View Database Schema" if not st.session_state.show_schema else "🙈 Hide Database Schema"
st.sidebar.button(toggle_label, on_click=toggle_schema)

if st.session_state.show_schema:
    with st.expander("📘 Database Schema", expanded=True):
        with st.spinner("Fetching database schema..."):
            schema_text = get_db_schema(st.session_state.engine)
            st.markdown(schema_text)
            st.download_button(
                "⬇️ Download Schema",
                schema_text,
                file_name="database_schema.md",
                mime="text/markdown"
            )

# ---------------------- SHOW / HIDE QUESTION HISTORY ----------------------
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
