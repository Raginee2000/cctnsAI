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
You are an expert FIR (First Information Report) analyst. After analyzing the detailed FIR content, provide a conversational response that includes:

1. **Case Analysis Summary** - Briefly describe the case type and severity
2. **Suggested Reports** - List the specific reports that can be generated based on the FIR content
3. **Report Formats** - Provide the standard format for each suggested report

**Available Report Types:**
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

**Response Format:**
Start with: "After analyzing the detailed FIR content, I can see that the following reports can be generated:"

Then list each relevant report with a letter (a, b, c, etc.) and provide its standard format.

**Example Format for Reports:**

**Medical Injury Report Format:**
- Patient Details (Name, Age, Gender, Address)
- Date and Time of Examination
- Nature of Injuries (External/Internal)
- Description of Injuries (Location, Size, Type)
- Medical Opinion
- Doctor's Signature and Seal

**Postmortem Report Format:**
- Deceased Details (Name, Age, Gender, Address)
- Date and Time of Postmortem
- External Examination Findings
- Internal Examination Findings
- Cause of Death
- Medical Officer's Signature

**Property Seizure Memo Format:**
- Date and Time of Seizure
- Location of Seizure
- Description of Seized Items
- Condition of Items
- Witnesses Present
- Officer's Signature

Always include district and police station information in your analysis. Make the response conversational and professional.
"""

FIR_SUMMARY_PROMPT = """
You are an expert at summarizing FIR (First Information Report) content. Create a concise, professional summary that includes:

1. Case Type and Category
2. Key Facts and Timeline
3. Parties Involved
4. Location and Jurisdiction
5. District and Police Station - IMPORTANT: Always extract and include the district and police station information from the FIR content. Look for terms like "PS-", "Police Station", "Dist.", "District", etc.
6. Evidence Mentioned
7. Current Status
8. Recommended Actions

Make the summary clear, factual, and suitable for police records. 
CRITICAL: You MUST extract and include the district and police station information from the FIR content. Look for patterns like:
- "PS-[Station Name]"
- "Police Station [Name]"
- "Dist. [District Name]" or "District [Name]"
- "At [Location], PS-[Station], Dist. [District]"

If district or police station information is not explicitly mentioned, indicate "Not specified" but always include this field.
"""

# Report form templates
REPORT_FORMS = {
    "Medical Injury Report": {
        "title": "Medical Injury Report",
        "fields": [
            {"name": "patient_name", "label": "Patient Name", "type": "text", "required": True},
            {"name": "patient_age", "label": "Age", "type": "number", "required": True},
            {"name": "patient_gender", "label": "Gender", "type": "select", "options": ["Male", "Female", "Other"], "required": True},
            {"name": "patient_address", "label": "Address", "type": "textarea", "required": True},
            {"name": "examination_date", "label": "Date of Examination", "type": "datetime-local", "required": True},
            {"name": "injury_nature", "label": "Nature of Injuries", "type": "select", "options": ["External", "Internal", "Both"], "required": True},
            {"name": "injury_description", "label": "Description of Injuries", "type": "textarea", "required": True},
            {"name": "medical_opinion", "label": "Medical Opinion", "type": "textarea", "required": True},
            {"name": "doctor_name", "label": "Doctor's Name", "type": "text", "required": True},
            {"name": "hospital", "label": "Hospital/Clinic", "type": "text", "required": True}
        ]
    },
    "Postmortem Report": {
        "title": "Postmortem Report",
        "fields": [
            {"name": "deceased_name", "label": "Deceased Name", "type": "text", "required": True},
            {"name": "deceased_age", "label": "Age", "type": "number", "required": True},
            {"name": "deceased_gender", "label": "Gender", "type": "select", "options": ["Male", "Female", "Other"], "required": True},
            {"name": "deceased_address", "label": "Address", "type": "textarea", "required": True},
            {"name": "postmortem_date", "label": "Date of Postmortem", "type": "datetime-local", "required": True},
            {"name": "external_findings", "label": "External Examination Findings", "type": "textarea", "required": True},
            {"name": "internal_findings", "label": "Internal Examination Findings", "type": "textarea", "required": True},
            {"name": "cause_of_death", "label": "Cause of Death", "type": "textarea", "required": True},
            {"name": "medical_officer", "label": "Medical Officer's Name", "type": "text", "required": True}
        ]
    },
    "Property Seizure Memo": {
        "title": "Property Seizure Memo",
        "fields": [
            {"name": "seizure_date", "label": "Date and Time of Seizure", "type": "datetime-local", "required": True},
            {"name": "seizure_location", "label": "Location of Seizure", "type": "text", "required": True},
            {"name": "seized_items", "label": "Description of Seized Items", "type": "textarea", "required": True},
            {"name": "item_condition", "label": "Condition of Items", "type": "textarea", "required": True},
            {"name": "witnesses", "label": "Witnesses Present", "type": "textarea", "required": True},
            {"name": "officer_name", "label": "Officer's Name", "type": "text", "required": True},
            {"name": "officer_rank", "label": "Officer's Rank", "type": "text", "required": True}
        ]
    },
    "Witness Statement": {
        "title": "Witness Statement",
        "fields": [
            {"name": "witness_name", "label": "Witness Name", "type": "text", "required": True},
            {"name": "witness_age", "label": "Age", "type": "number", "required": True},
            {"name": "witness_address", "label": "Address", "type": "textarea", "required": True},
            {"name": "statement_date", "label": "Date of Statement", "type": "datetime-local", "required": True},
            {"name": "event_description", "label": "Description of Events", "type": "textarea", "required": True},
            {"name": "witness_signature", "label": "Witness Signature", "type": "text", "required": True}
        ]
    },
    "Vehicle Inspection Report": {
        "title": "Vehicle Inspection Report",
        "fields": [
            {"name": "vehicle_number", "label": "Vehicle Registration Number", "type": "text", "required": True},
            {"name": "vehicle_type", "label": "Vehicle Type", "type": "text", "required": True},
            {"name": "inspection_date", "label": "Date of Inspection", "type": "datetime-local", "required": True},
            {"name": "inspection_location", "label": "Location of Inspection", "type": "text", "required": True},
            {"name": "inspection_findings", "label": "Inspection Findings", "type": "textarea", "required": True},
            {"name": "inspector_name", "label": "Inspector's Name", "type": "text", "required": True},
            {"name": "inspector_rank", "label": "Inspector's Rank", "type": "text", "required": True}
        ]
    }
}

@app.get("/report-form/{report_type}")
async def get_report_form(report_type: str):
    """Get the form structure for a specific report type"""
    if report_type in REPORT_FORMS:
        return REPORT_FORMS[report_type]
    else:
        return {"error": "Report type not found"}

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
    if user_message.lower().strip() in ['1', '2', '3'] and chat_history:
        # Look for FIR content in the recent history
        fir_content = None
        for turn in reversed(chat_history):
            if turn.get('fir_content'):
                fir_content = turn['fir_content']
                break
        
        if fir_content:
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
                print(f"DEBUG: Summary response: {summary}")  # Debug print
                return {"answer": f"**FIR Summary:**\n\n{summary}", "sql": None}
            
            elif choice == '2':
                # Analyze and suggest documents
                analysis_response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": FIR_ANALYSIS_PROMPT},
                        {"role": "user", "content": f"Please analyze this FIR content and suggest relevant document types:\n\n{fir_content}"}
                    ],
                    max_tokens=800,
                    temperature=0.3,
                )
                analysis = analysis_response.choices[0].message.content.strip()
                
                # Extract suggested reports from the analysis using multiple patterns
                import re
                suggested_reports = []
                lines = analysis.split('\n')
                
                for line in lines:
                    line = line.strip()
                    # Pattern 1: "a) **Medical Injury Report**"
                    match = re.search(r'[a-j]\)\s*\*\*(.+?)\*\*', line)
                    if match:
                        suggested_reports.append(match.group(1).strip())
                        continue
                    
                    # Pattern 2: "a) Medical Injury Report"
                    match = re.search(r'[a-j]\)\s*(.+?)(?:\s*\(|$)', line)
                    if match:
                        report_name = match.group(1).strip()
                        # Clean up common prefixes/suffixes
                        report_name = re.sub(r'^\*\*|\*\*$', '', report_name)
                        if report_name and len(report_name) > 3:
                            suggested_reports.append(report_name)
                        continue
                    
                    # Pattern 3: Look for report types in bullet points
                    if line.startswith('-') or line.startswith('•'):
                        # Extract report types from lines like "- Medical Injury Report"
                        report_match = re.search(r'[-•]\s*(.+?)(?:\s*\(|$)', line)
                        if report_match:
                            report_name = report_match.group(1).strip()
                            # Clean up common prefixes/suffixes
                            report_name = re.sub(r'^\*\*|\*\*$', '', report_name)
                            if report_name and len(report_name) > 3:
                                suggested_reports.append(report_name)
                
                # Pattern 4: Look for "a. Vehicle Inspection Report Format:" pattern
                if not suggested_reports:
                    format_pattern = re.findall(r'[a-j]\.\s*([^*]+?)\s+Report\s+Format', analysis)
                    for match in format_pattern:
                        if match.strip() and len(match.strip()) > 3:
                            suggested_reports.append(f"{match.strip()} Report")
                
                # Pattern 5: Look for "**a. Vehicle Inspection Report Format:**" pattern
                if not suggested_reports:
                    format_pattern = re.findall(r'\*\*[a-j]\.\s*([^*]+?)\s+Report\s+Format\*\*', analysis)
                    for match in format_pattern:
                        if match.strip() and len(match.strip()) > 3:
                            suggested_reports.append(f"{match.strip()} Report")
                
                # If no reports found, try to extract from the text
                if not suggested_reports:
                    # Look for common report types in the entire text
                    common_reports = [
                        "Medical Injury Report", "Postmortem Report", "Property Seizure Memo",
                        "Witness Statement", "Forensic Report", "Vehicle Inspection Report",
                        "CCTV Footage Analysis", "Digital Evidence Report", "Chemical Analysis Report",
                        "Ballistic Report", "DNA Analysis Report", "Fingerprint Analysis",
                        "Document Verification Report", "Financial Transaction Analysis"
                    ]
                    
                    for report in common_reports:
                        if report.lower() in analysis.lower():
                            suggested_reports.append(report)
                
                # Remove duplicates and clean up
                suggested_reports = list(dict.fromkeys([report.strip() for report in suggested_reports if report.strip() and len(report.strip()) > 3]))
                
                print(f"DEBUG: Extracted reports: {suggested_reports}")
                
                return {
                    "answer": f"**Suggested Reports for this FIR:**\n\n{analysis}", 
                    "suggested_reports": suggested_reports,
                    "fir_content": fir_content,
                    "sql": None
                }
            
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