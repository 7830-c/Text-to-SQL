GENERATOR_PROMPT = """You are an expert SQLite developer.
Write one SQLite query that answers the question, using ONLY the tables and columns in the schema.

Rules:
- Return only the SQL query. No explanation, no markdown.
- Use SQLite syntax.
- Use only columns that exist in the schema.

Schema:
{schema}{context}

Question: {question}

SQL:"""


CORRECTOR_PROMPT = """You are an expert SQLite developer. A query you wrote failed, so fix it.

Rules:
- Return only the corrected SQL query. No explanation, no markdown.
- Use SQLite syntax and only tables/columns that exist in the schema.
- Read the database error carefully; it tells you what is wrong.

Schema:
{schema}{context}

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



DICT_BATCH_PROMPT = """You document a database for people who have never seen it.
Below are some of its tables with their columns (name:type). Tables marked [empty] have no rows.

Return ONE JSON object with exactly two keys:
- "tables": an object mapping each table name to ONE plain sentence (max 20 words) saying what the table stores.
- "notes": a list of up to 4 short strings about how columns or tables relate or are named, for example which
  columns together hold a person's full name, or which ID columns point to which table. Only include notes you
  are fairly sure of. Use [] if there are none.

Do not invent business details the names do not support.
Return only the JSON.

Tables:
{catalog}"""


DICT_OVERVIEW_PROMPT = """Write a short overview of a database for someone who is about to ask questions about it.
Below are its tables with one-line descriptions.

Return ONE JSON object with exactly these keys:
- "overview": 2 to 4 plain sentences on what the database seems to be for.
- "areas": a list of up to 8 short strings, each naming a main area and its key tables,
  for example "Users and logins: accounts_user, accounts_passwordresetotp".

Return only the JSON.

Tables:
{lines}"""