import json
import pandas as pd
import sqlite3
from constants import prompt
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

def get_db_schema(engine):
    """
    Given a SQLAlchemy Engine, return a readable schema string containing CREATE statements for each table.
    Works for both SQLite and MySQL engines.
    """
    try:
        if not isinstance(engine, Engine):
            return "❌ Invalid engine passed to get_db_schema()"

        inspector = inspect(engine)
        tables = inspector.get_table_names()

        if not tables:
            return "⚠️ No tables found in the connected database."

        schema = ""
        dialect = engine.dialect.name.lower()

        with engine.connect() as conn:
            if dialect == "mysql":
                # Use SHOW CREATE TABLE for MySQL to get full DDL
                for table in tables:
                    res = conn.execute(text(f"SHOW CREATE TABLE `{table}`;"))
                    row = res.fetchone()
                    # row structure: (table_name, create_stmt)
                    create_stmt = row[1] if row is not None else "/* could not fetch */"
                    schema += f"**{table} table:**\n```sql\n{create_stmt}\n```\n\n"
            elif dialect == "sqlite":
                # Use sqlite_master for SQLite
                for table in tables:
                    res = conn.execute(text(f"SELECT sql FROM sqlite_master WHERE name = :t;"), {"t": table})
                    row = res.fetchone()
                    create_stmt = row[0] if row and row[0] else f"/* CREATE statement not found for {table} */"
                    schema += f"**{table} table:**\n```sql\n{create_stmt}\n```\n\n"
            else:
                # Generic fallback: attempt to describe columns
                for table in tables:
                    cols = inspector.get_columns(table)
                    col_text = ", ".join([f"{c['name']} {str(c['type'])}" for c in cols])
                    create_stmt = f"CREATE TABLE {table} ({col_text});"
                    schema += f"**{table} table:**\n```sql\n{create_stmt}\n```\n\n"
        return schema

    except Exception as e:
        return f"❌ Error loading DB schema: {e}"


def get_sql_query(genai_client, prompt_text, query):
    """
    Send prompt_text + user query to the LLM.
    Accepts either a JSON response or plain SQL.
    Returns a dict with keys 'status' and 'response'.
    """
    contents = f"{prompt_text}\n\nUser Question:\n{query}"

    try:
        response = genai_client.generate_content(contents)
        ai_text = response.text.strip()

        # strip codeblock wrappers and common prefixes
        cleaned = ai_text
        # remove triple backticks with optional language tags
        cleaned = cleaned.replace("```json", "").replace("```sql", "").replace("```", "").strip()
        # remove leading 'sql ' or 'SQL ' if model prepends it
        if cleaned.lower().startswith("sql "):
            cleaned = cleaned[4:].strip()

        # Try parse JSON first
        try:
            parsed = json.loads(cleaned)
            # Ensure it has status & response
            if isinstance(parsed, dict) and ("status" in parsed and "response" in parsed):
                return parsed
            # If it's JSON but not the expected shape, treat as error message
            return {"status": "error", "response": f"Model returned JSON but missing keys: {cleaned}"}
        except json.JSONDecodeError:
            # Not JSON — see if it looks like SQL
            sql_candidate = cleaned
            if not sql_candidate:
                return {"status": "error", "response": "Model returned empty response."}

            # Heuristic: starts with SQL verbs
            sql_verbs = ("select", "show", "insert", "update", "delete", "create", "drop", "alter")
            if any(sql_candidate.lower().lstrip().startswith(v) for v in sql_verbs):
                return {"status": "success", "response": sql_candidate}
            # Otherwise return error with the raw text
            return {"status": "error", "response": f"Model returned unexpected format:\n{cleaned}"}

    except Exception as e:
        return {"status": "error", "response": f"AI communication error: {e}"}


def execute_query(query, engine):
    """
    Execute SQL query using the SQLAlchemy engine and return a DataFrame or an error string.
    """
    try:
        if not isinstance(engine, Engine):
            return f"❌ execute_query expected SQLAlchemy Engine, got {type(engine)}"

        # Use text(query) so SQLAlchemy treats it properly
        with engine.connect() as conn:
            # pd.read_sql_query accepts SQLAlchemy connectable or connection
            df = pd.read_sql_query(text(query), conn)
            return df
    except Exception as e:
        return f"❌ SQL Execution Error: {e}"


def text2sql(genai_client, user_query, engine):
    """
    Top-level: get schema, produce prompt, ask LLM, run SQL, return (sql_string_or_none, result_or_error_msg).
    engine must be a SQLAlchemy Engine.
    """
    if not user_query or len(user_query.strip()) < 3:
        return None, "⚠️ Please enter a meaningful question."

    if not isinstance(engine, Engine):
        return None, "❌ Internal error: engine is not a SQLAlchemy Engine."

    # Determine dialect and schema
    dialect = engine.dialect.name.lower()
    db_type = "MySQL" if dialect == "mysql" else "SQLite" if dialect == "sqlite" else dialect
    db_schema = get_db_schema(engine)

    # Compose detailed contextual prompt for the model (overrides constants prompt but uses it as base)
    contextual_prompt = f"""
        {prompt}

        Connected database type: {db_type}
        Here is the database schema (DDL):
        {db_schema}

        Important: produce SQL compatible with {db_type}. Output either:
        - A JSON object: {{ "status": "success", "response": "<SQL query>" }} or
        - Plain SQL (e.g. SELECT ...;). If plain SQL is returned, it will be treated as success.
        Do NOT include explanatory text alongside the SQL.
    """

    output = get_sql_query(genai_client, contextual_prompt, user_query)

    if isinstance(output, dict) and output.get("status") == "success":
        sql_query = output.get("response")
        result = execute_query(sql_query, engine)
        return sql_query, result
    else:
        # output may be dict with error message
        msg = output.get("response") if isinstance(output, dict) else str(output)
        return None, msg
