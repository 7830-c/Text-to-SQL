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


PICKER_PROMPT = """You choose which database tables are needed to answer a question.
Below is every table in the database with its columns. Tables marked [empty] have no rows.

Rules:
- Return only table names, separated by commas. No explanation.
- Choose at most {n} tables: the ones that hold the data the question asks for, plus any tables needed to join them.
- Prefer tables whose columns directly match what the question asks for.

Question: {question}

Tables:
{catalog}

Table names:"""