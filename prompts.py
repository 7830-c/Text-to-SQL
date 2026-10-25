GENERATOR_PROMPT = """You are an expert SQLite developer.
Write one SQLite query that answers the question, using ONLY the tables and columns in the schema.

Rules:
- Return only the SQL query. No explanation, no markdown.
- Use SQLite syntax.
- Use only columns that exist in the schema.

Schema:
{schema}

Question: {question}

SQL:"""


CORRECTOR_PROMPT = """You are an expert SQLite developer. A query you wrote failed, so fix it.

Rules:
- Return only the corrected SQL query. No explanation, no markdown.
- Use SQLite syntax and only tables/columns that exist in the schema.
- Read the database error carefully; it tells you what is wrong.

Schema:
{schema}

Question: {question}

Failed query:
{sql}

Database error:
{error}

Corrected SQL:"""