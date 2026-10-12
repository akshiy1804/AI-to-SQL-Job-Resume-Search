

import os
import re
import time

import pandas as pd
import psycopg2
import sqlglot
import streamlit as st
from dotenv import load_dotenv
from groq import Groq
from sqlglot import exp

load_dotenv()

# ---------------- PAGE CONFIGURATION ----------------

st.set_page_config(
    page_title="AI-to-SQL Job & Resume Search",
    layout="wide",
)

st.title("AI-to-SQL Job & Resume Search")
st.write(
    "Search job and candidate data using natural language."
)

# ---------------- CONFIGURATION ----------------

GROQ_MODEL = "openai/gpt-oss-120b"

ALLOWED_VIEWS = {
    "v_job_catalogue",
    "v_job_required_skills",
    "v_candidate_profiles",
    "v_candidate_skills",
    "v_company_job_counts",
}

SCHEMA_INFO = """
Convert the user's natural-language question into PostgreSQL SQL.

Use only these approved views and columns:

1. v_job_catalogue:
job_id, job_title, company_name, city_state, country,
job_level, job_type, posted_on, job_link, job_summary

2. v_job_required_skills:
job_id, job_title, company_name, skill_id, skill_name

3. v_candidate_profiles:
candidate_id, full_name, city, total_experience_years

4. v_candidate_skills:
candidate_id, full_name, city, skill_name,
proficiency, years_used

5. v_company_job_counts:
company_id, company_name, job_count

Rules:
- Generate exactly one PostgreSQL SELECT query.
- Use only the approved views and columns.
- Never generate modifying SQL.
- Use ILIKE for case-insensitive text matching.
- Add LIMIT 50 unless the user requests a smaller limit.
- Return SQL only, without Markdown fences or explanations.
- Never invent columns.
"""

# ---------------- DATABASE CONNECTION ----------------

def get_connection():
    required = [
        "DB_HOST",
        "DB_PORT",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
    ]

    missing = [
        name for name in required
        if not os.getenv(name)
    ]

    if missing:
        raise ValueError(
            "Missing database settings in .env: "
            + ", ".join(missing)
        )

    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        connect_timeout=5,
    )


# ---------------- AI SQL GENERATION ----------------

def generate_sql(question):
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        raise ValueError(
            "GROQ_API_KEY is missing from your .env file."
        )

    client = Groq(api_key=api_key)

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {
                "role": "system",
                "content": SCHEMA_INFO,
            },
            {
                "role": "user",
                "content": question,
            },
        ],
        temperature=0,
    )

    content = response.choices[0].message.content

    if not content:
        raise ValueError("The AI returned an empty response.")

    return content.strip()


# ---------------- SQL VALIDATION ----------------

def validate_sql(sql):
    sql = re.sub(
        r"```(?:sql)?",
        "",
        sql,
        flags=re.IGNORECASE,
    ).replace("```", "").strip()

    sql = sql.rstrip(";").strip()

    if not sql:
        raise ValueError("The generated SQL is empty.")

    try:
        statements = sqlglot.parse(sql, read="postgres")
    except Exception as exc:
        raise ValueError(
            "The generated SQL could not be parsed."
        ) from exc

    if len(statements) != 1 or statements[0] is None:
        raise ValueError("Only one SQL statement is allowed.")

    tree = statements[0]

    if not isinstance(tree, exp.Select):
        raise ValueError("Only SELECT queries are permitted.")

    forbidden_nodes = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Drop,
        exp.Create,
        exp.Alter,
        exp.Command,
    )

    for node in tree.walk():
        if isinstance(node, forbidden_nodes):
            raise ValueError(
                "A modifying SQL operation was detected."
            )

    tables = list(tree.find_all(exp.Table))

    if not tables:
        raise ValueError(
            "The query must read from an approved view."
        )

    for table in tables:
        if table.db or table.catalog:
            raise ValueError(
                "Schema-qualified references are not allowed."
            )

        if table.name.lower() not in ALLOWED_VIEWS:
            raise ValueError(
                f"View not permitted: {table.name}"
            )

    if not tree.args.get("limit"):
        tree.set(
            "limit",
            exp.Limit(
                expression=exp.Literal.number(50)
            ),
        )

    return tree.sql(dialect="postgres")


# ---------------- AUDIT LOGGING ----------------

def log_query(
    question,
    sql,
    status,
    reason=None,
    elapsed_ms=None,
):
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO nl_query_log
                    (
                        request_text,
                        generated_sql,
                        validation_status,
                        rejection_reason,
                        execution_time_ms
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        question,
                        sql or None,
                        status,
                        reason,
                        elapsed_ms,
                    ),
                )
    except Exception:
        # Keep logging failures from interrupting the interface.
        pass


# ---------------- SEARCH INTERFACE ----------------

question = st.text_area(
    "Ask a question about jobs or candidates",
    placeholder=(
        "Find Python developer jobs in Bengaluru"
    ),
    height=100,
)

if st.button("Search", type="primary"):
    if not question.strip():
        st.warning("Please enter a search question.")

    else:
        sql = ""
        start_time = time.perf_counter()

        try:
            with st.spinner("Generating SQL..."):
                generated_sql = generate_sql(question)

            with st.spinner("Validating SQL..."):
                sql = validate_sql(generated_sql)

            st.subheader("Generated SQL")
            st.code(sql, language="sql")

            with st.spinner("Searching the database..."):
                with get_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            "SET TRANSACTION READ ONLY"
                        )
                        cursor.execute(
                            "SET LOCAL statement_timeout = '10s'"
                        )
                        cursor.execute(sql)

                        rows = cursor.fetchall()
                        columns = [
                            description[0]
                            for description in cursor.description
                        ]

                results = pd.DataFrame(
                    rows,
                    columns=columns,
                )

            elapsed_ms = int(
                (time.perf_counter() - start_time) * 1000
            )

            log_query(
                question,
                sql,
                "ACCEPTED",
                elapsed_ms=elapsed_ms,
            )

            st.success(
                f"Search completed! {len(results)} result(s) found."
            )

            st.dataframe(
                results,
                use_container_width=True,
                hide_index=True,
            )

            if not results.empty:
                st.download_button(
                    "Download results as CSV",
                    data=results.to_csv(
                        index=False
                    ).encode("utf-8"),
                    file_name="job_search_results.csv",
                    mime="text/csv",
                )

        except Exception as exc:
            elapsed_ms = int(
                (time.perf_counter() - start_time) * 1000
            )

            if isinstance(exc, ValueError):
                message = str(exc)
                status = "REJECTED"
            else:
                message = f"{type(exc).__name__}: {exc}"
                status = "ERROR"

            log_query(
                question,
                sql,
                status,
                reason=message[:1000],
                elapsed_ms=elapsed_ms,
            )

            st.error(f"Search failed: {message}")
