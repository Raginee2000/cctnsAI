import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import openai
import re

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MYSQL_URL = os.getenv("MYSQL_URL")

client = openai.OpenAI(api_key=OPENAI_API_KEY)
engine = create_engine(MYSQL_URL)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TABLE_SCHEMA = """
Table name: fir_records_CAW
Columns:
fir_no VARCHAR(20),
ipc_sections VARCHAR(255),
district VARCHAR(100),
date DATE,
description TEXT,
police_station VARCHAR(100),
case_status VARCHAR(50),
major_head VARCHAR(100)
"""

SYSTEM_PROMPT = f"""
You are a helpful assistant for police data analysis. You answer questions about the FIR database with the following schema:
{TABLE_SCHEMA}

IMPORTANT:
- For each user question, generate the most appropriate single SQL query (MySQL dialect).
- For counts, use SELECT COUNT(*).
- For details, use SELECT * with relevant WHERE clauses.
- For comparisons (e.g., year-wise, district-wise), use GROUP BY and return aggregated results.
- For follow-up questions like "show me all", "show me in tabular form", "show details", or "list them", use the chat history to infer the last filter or context, and generate a SELECT * query with the same filter as the previous count or summary.
- If the previous answer was a table, you may repeat the table.
- NEVER generate multiple SQL statements separated by semicolons.
- Only return the SQL query, nothing else.

EXAMPLES:
Q: How many FIRs were filed in the last 6 months?
A: SELECT COUNT(*) FROM fir_records_CAW WHERE date >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH);

Q: show me all
A: SELECT * FROM fir_records_CAW WHERE date >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH);

Q: show me in tabular form
A: SELECT * FROM fir_records_CAW WHERE date >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH);

Q: Compare rape cases in 2022, 2023, and 2024
A: SELECT YEAR(date) as year, COUNT(*) as count FROM fir_records_CAW WHERE major_head LIKE '%rape%' AND YEAR(date) IN (2022,2023,2024) GROUP BY YEAR(date);

Q: List all rape cases in the year 2024
A: SELECT * FROM fir_records_CAW WHERE major_head LIKE '%rape%' AND YEAR(date) = 2024;

Q: How many theft cases in 2023?
A: SELECT COUNT(*) FROM fir_records_CAW WHERE major_head LIKE '%theft%' AND YEAR(date) = 2023;

Q: Show details for FIR number FIR00136.
A: SELECT * FROM fir_records_CAW WHERE fir_no = 'FIR00136';

Q: show me all women and child related cases only
A: SELECT * FROM fir_records_CAW WHERE major_head LIKE '%woman%' OR major_head LIKE '%child%' OR description LIKE '%woman%' OR description LIKE '%child%';
"""

# FIR Analysis and Summarization Prompts
FIR_ANALYSIS_PROMPT = """
You are an expert FIR (First Information Report) analyst. Analyze the provided FIR content and determine:

1. The type of case (e.g., theft, assault, fraud, domestic violence, etc.)
2. Severity level (low, medium, high, critical)
3. Key details like location, time, parties involved, injuries, property damage
4. Relevant IPC sections that might apply
5. Suggested document types that would be needed for this case

Based on the analysis, suggest relevant document types such as:
- Medical Injury Report
- Postmortem Report
- Property Seizure Memo
- Witness Statement
- Forensic Report
- Vehicle Inspection Report
- Bank Statement Analysis
- CCTV Footage Analysis
- Digital Evidence Report
- Chemical Analysis Report
- Ballistic Report
- DNA Analysis Report
- Fingerprint Analysis
- Document Verification Report
- Financial Transaction Analysis

Provide your analysis in a structured format.
"""

FIR_SUMMARY_PROMPT = """
You are an expert at summarizing FIR (First Information Report) content. Create a concise, professional summary that includes:

1. Case Type and Category
2. Key Facts and Timeline
3. Parties Involved
4. Location and Jurisdiction
5. Evidence Mentioned
6. Current Status
7. Recommended Actions

Make the summary clear, factual, and suitable for police records.
"""

@app.post("/chat")
async def chat(request: Request):
    data = await request.json()
    user_message = data["message"]
    chat_history = data.get("history", [])

    # Handle simple acknowledgments (e.g., "okay", "thanks")
    greetings = {
        "hi": "Hello! How can I assist you with FIR data today?",
        "hello": "Hello! How can I assist you with FIR data today?",
        "how are you": "I'm just a bot, but I'm here to help you!",
        "what is the weather today": "I'm focused on FIR data, but I hope the weather is nice!",
        "bye": "Goodbye! If you need more information, just ask anytime.",
        "goodbye": "Goodbye! If you need more information, just ask anytime.",
        "thank you": "You're welcome! Let me know if you have more questions.",
        "thanks": "You're welcome! Let me know if you have more questions.",
        "good morning": "Good morning! How can I help you today?",
        "good evening": "Good evening! How can I assist you?",
    }
    user_message_clean_for_greetings = user_message.lower().strip()
    if user_message_clean_for_greetings in greetings:
        return {"answer": greetings[user_message_clean_for_greetings], "sql": None}

    simple_responses = ["okay", "ok", "nothing"] # "thanks", "thank you", "good", "fine", "yes", "no" are handled by greetings
    if user_message_clean_for_greetings in simple_responses:
        return {"answer": "Understood! How else can I help you with the FIR data?", "sql": "SELECT 'Acknowledged' as response"}

    # Check if this looks like FIR content (not a database query)
    # Look for FIR content indicators
    fir_indicators = [
        'police station', 'ps-', 'dist.', 'district', 'fir', 'case', 'complaint',
        'alleging', 'reported', 'incident', 'accused', 'victim', 'suspect',
        'seized', 'recovered', 'arrested', 'detained', 'investigation',
        'witness', 'evidence', 'confession', 'remand', 'magistrate'
    ]
    
    # Check if the message contains FIR-related keywords and is long enough
    has_fir_keywords = any(indicator in user_message.lower() for indicator in fir_indicators)
    is_long_text = len(user_message) > 150
    is_not_query = not any(keyword in user_message.lower() for keyword in ['show', 'how many', 'count', 'list', 'compare', 'find', 'search', 'filter', 'where', 'select', 'sql'])
    
    if has_fir_keywords and is_long_text and is_not_query:
        # This looks like FIR content - offer analysis options
        return {
            "answer": f"I see you've provided FIR content. What would you like me to do with this data?\n\n1. **Summarize the FIR** - Create a concise summary\n2. **Analyze and suggest documents** - Determine case type and suggest relevant reports\n3. **Both** - Summarize and analyze\n\nPlease respond with 1, 2, or 3.",
            "fir_content": user_message,
            "needs_analysis": True
        }

    # Handle analysis requests
    if user_message.lower().strip() in ['1', '2', '3'] and chat_history and chat_history[-1].get('fir_content'):
        fir_content = chat_history[-1]['fir_content']
        choice = user_message.lower().strip()
        
        if choice == '1':
            # Summarize only
            summary_response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": FIR_SUMMARY_PROMPT},
                    {"role": "user", "content": f"Please summarize this FIR content:\n\n{fir_content}"}
                ],
                max_tokens=500,
                temperature=0.3,
            )
            summary = summary_response.choices[0].message.content.strip()
            return {"answer": f"**FIR Summary:**\n\n{summary}", "sql": None}
        
        elif choice == '2':
            # Analyze and suggest documents
            analysis_response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": FIR_ANALYSIS_PROMPT},
                    {"role": "user", "content": f"Please analyze this FIR content and suggest relevant document types:\n\n{fir_content}"}
                ],
                max_tokens=600,
                temperature=0.3,
            )
            analysis = analysis_response.choices[0].message.content.strip()
            return {"answer": f"**FIR Analysis and Document Suggestions:**\n\n{analysis}", "sql": None}
        
        elif choice == '3':
            # Both summarize and analyze
            summary_response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": FIR_SUMMARY_PROMPT},
                    {"role": "user", "content": f"Please summarize this FIR content:\n\n{fir_content}"}
                ],
                max_tokens=500,
                temperature=0.3,
            )
            summary = summary_response.choices[0].message.content.strip()
            
            analysis_response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": FIR_ANALYSIS_PROMPT},
                    {"role": "user", "content": f"Please analyze this FIR content and suggest relevant document types:\n\n{fir_content}"}
                ],
                max_tokens=600,
                temperature=0.3,
            )
            analysis = analysis_response.choices[0].message.content.strip()
            
            return {"answer": f"**FIR Summary:**\n\n{summary}\n\n**Analysis and Document Suggestions:**\n\n{analysis}", "sql": None}

    sql_query = ""  # Always initialize

    # Build messages for OpenAI to generate SQL - SANITIZE ALL CONTENT
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in chat_history:
        user_content = str(turn.get("user", "")) if turn.get("user") is not None else ""
        bot_content = str(turn.get("bot", "")) if turn.get("bot") is not None else ""
        if user_content.strip():
            messages.append({"role": "user", "content": user_content})
        if bot_content.strip() and len(bot_content) < 500: # Limit bot history length
            messages.append({"role": "assistant", "content": bot_content})
    messages.append({"role": "user", "content": str(user_message)})

    try:
        # Step 1: Use OpenAI to convert question to SQL
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=300,
            temperature=0,
        )
        sql_query = response.choices[0].message.content.strip().strip("```sql").strip("```").strip()

        # Remove a single trailing semicolon (if present)
        sql_query_clean = sql_query.strip()
        if sql_query_clean.endswith(';'):
            sql_query_clean = sql_query_clean[:-1].strip()

        # If there is still a semicolon, it's a problem (multiple statements)
        if ';' in sql_query_clean:
            return {"error": "Invalid SQL: multiple statements detected. Please rephrase your question.", "sql": sql_query}

        # Use the cleaned query for execution
        sql_query = sql_query_clean

        # After generating sql_query, check if it looks like SQL
        if not sql_query.strip().upper().startswith(('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'SHOW', 'DESCRIBE')):
            return {"answer": "I understand. How else can I help you with the FIR data?", "sql": "SELECT 'Acknowledged' as response"}

        # Step 2: Run SQL query
        with engine.connect() as conn:
            result = conn.execute(text(sql_query))
            lower_sql = sql_query.lower()

            # Check if it's a simple acknowledgment query
            if "acknowledged" in lower_sql or "welcome" in lower_sql:
                row = result.fetchone()
                response_text = row[0] if row is not None else "Understood!"
                return {"answer": response_text, "sql": sql_query}
            elif "count" in lower_sql and "group by" not in lower_sql:
                row = result.fetchone()
                count = row[0] if row is not None else 0
                # Step 3: Generate a conversational response using OpenAI
                conv_prompt = [
                    {"role": "system", "content": "You are a helpful assistant for police data analysis. Given a user's question and the answer from the database, reply in a natural, conversational way."},
                    {"role": "user", "content": f"User question: {user_message}\nDatabase answer: {count}"}
                ]
                conv_response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=conv_prompt,
                    max_tokens=100,
                    temperature=0,
                )
                natural_reply = conv_response.choices[0].message.content.strip()
                return {"answer": natural_reply, "count": count, "sql": sql_query}
            else:
                # For SELECT * or GROUP BY queries, return the rows directly
                rows = [dict(row) for row in result.mappings()]
                return {"answer": rows, "sql": sql_query}
    except Exception as e:
        return {"error": str(e), "sql": sql_query}