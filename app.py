import os.path
import numpy as np
from fastapi import FastAPI, File, UploadFile, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import datetime
from datetime import date
import logging
from logging.handlers import TimedRotatingFileHandler
from function import entity_recog_gpt, entity_recog_gemini,custom_prompt_response,update_extracted_data,entity_recog_gpt_injuary,entity_recog_gpt_injury_Report
from summery import summarize_legal_text_gpt, summarize_legal_text_gemini
from pydantic import BaseModel
import re
import uuid
from typing import Optional, Dict
from fpdf import FPDF
from fastapi.responses import FileResponse

import openai
from dotenv import load_dotenv
import os

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MYSQL_URL = os.getenv("MYSQL_URL")

client = openai.OpenAI(api_key=OPENAI_API_KEY)
from sqlalchemy import create_engine, text

engine = create_engine(MYSQL_URL)

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
- For comparisons (e.g., year-wise, district-wise), ALWAYS generate a single SQL query using GROUP BY or WHERE ... IN (...).
- NEVER generate multiple SQL statements separated by semicolons.
- For example, for 'Compare rape cases from 2021 to 2024', generate:
  SELECT YEAR(date) as year, COUNT(*) as count FROM fir_records_CAW WHERE major_head LIKE '%rape%' AND YEAR(date) IN (2021,2022,2023,2024) GROUP BY YEAR(date);
- For counts, use SELECT COUNT(*).
- For lists, use SELECT * with appropriate WHERE clauses.
- Only return the SQL query, nothing else.

EXAMPLES:
Q: Compare rape cases from 2021 to 2024
A: SELECT YEAR(date) as year, COUNT(*) as count FROM fir_records_CAW WHERE major_head LIKE '%rape%' AND YEAR(date) IN (2021,2022,2023,2024) GROUP BY YEAR(date);

Q: Compare theft cases in 2022 and 2023
A: SELECT YEAR(date) as year, COUNT(*) as count FROM fir_records_CAW WHERE major_head LIKE '%theft%' AND YEAR(date) IN (2022,2023) GROUP BY YEAR(date);

Q: How many rape cases in 2024?
A: SELECT COUNT(*) FROM fir_records_CAW WHERE major_head LIKE '%rape%' AND YEAR(date) = 2024;
"""

app = FastAPI()
# app = FastAPI()

# Immediately after this:
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# load onnx model
#model = GLiNER.from_pretrained("model/gliner_medium", load_onnx_model=True)
logpath = datetime.datetime.now().strftime("%Y-%m-%d") + ".log"
print(logpath)
log_file = os.path.join("enrichlogs", logpath)
handler = TimedRotatingFileHandler(filename=log_file,
                                   when="midnight",
                                   interval=1,
                                   backupCount=31)
formater = logging.Formatter("%(asctime)s %(thread)s | %(levelname)s | %(message)s",
                             datefmt="%Y-%m-%d %H:%M:%S")
handler.setFormatter(formater)
handler.setLevel(logging.DEBUG)
logging.getLogger().setLevel(logging.INFO)
logging.getLogger().addHandler(handler)
logging.info("log initiated")

 
@app.get("/ping") 
async def ping():
    logging.info("API is active")
    return "Hello, I am alive"


@app.get("/logdaterange")
async def logdaterange(
        start: date = Query(default=None, example="2025-05-05"), end: date = Query(default=None, example="2024-02-22")):
    if date is None:
        return "Date parameter is required", 400
    log_lines = []
    current_date = start
    while current_date <= end:
        log_file_path = f'enrichlogs/{(current_date)}.log'
        try:
            with open(log_file_path, 'r') as file:
                log_lines.extend(file.readlines())
        except FileNotFoundError:
            print(f"File {log_file_path} not found.")
            logging.warning("No log for this day")
        current_date += datetime.timedelta(days=1)
    return log_lines


@app.post("/entity_recog")
async def entity_recog(text:str):
    return entity_recog_un(text,model, logging)

class TextInput(BaseModel):
    text: str

@app.post("/entity_recog_llm_ed")
async def entity_recog_llm_ed(input_data: TextInput):
    entities = entity_recog_gpt(input_data.text, logging)
    return {"entities": entities}

@app.post("/entity_recog_llm_ed_injuary")
async def entity_recog_llm_ed_injuary(text:str):
    return  entity_recog_gpt_injuary(text, logging)

@app.post("/entity_recog_llm_gem")
async def entity_recog_llm_gem(text:str):
    return  entity_recog_gemini(text, logging)

class SummaryInput(BaseModel):
    text: str
    
@app.post("/summarize_gpt")
async def summarize_with_gpt(input_data: SummaryInput):
    summary = summarize_legal_text_gpt(input_data.text, logging)
    if summary:
        return {"summary": summary}
    else:
        return {"summary": "Could not generate summary. Check logs for details."}


@app.post("/summarize_gemini")
async def summarize_with_gemini(text: str):
    return {"summary": summarize_legal_text_gemini(text, logging)}

class ArrestInput(BaseModel):
    text: str

@app.post("/parse_arrest_details")
async def parse_arrest_details(input: ArrestInput):
    try:
        text = input.text

        # Regex-based entity extraction
        name_match = re.search(r"(?:person is|name is)\s+(.*?)[,.]", text, re.IGNORECASE)
        date_match = re.search(r"arrested on\s+([\d/-]+)", text, re.IGNORECASE)
        location_match = re.search(r"at\s+(.*?)[,.]", text, re.IGNORECASE)
        section_match = re.search(r"under\s+Section\s+([\dA-Za-z]+)", text, re.IGNORECASE)

        response = {
            "name": name_match.group(1).strip() if name_match else "",
            "arrestDate": date_match.group(1).strip() if date_match else "",
            "location": location_match.group(1).strip() if location_match else "",
            "section": section_match.group(1).strip() if section_match else ""
        }

        return response

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}


class CustomInstructionInput(BaseModel):
    text: str
    instruction: Optional[str] = None
    existing_data: Optional[Dict[str, str]] = None

@app.post("/custom_instruction")
async def custom_instruction(input: CustomInstructionInput):
    previous_data = input.existing_data or {}

    # Step 1: Extract new values using GPT
    new_extracted = entity_recog_gpt(input.text, logging)

    # Step 2: Merge smartly – do not overwrite existing good values with blanks
    merged_data = previous_data.copy()
    for key, value in new_extracted.items():
        if value:  # update only if new value is non-empty
            merged_data[key] = value

    # Step 3: Required fields definition
    required_fields = [
        "DISTRICT", "PS", "FIR_NO", "FIR_DT", "REG_DT", "Section", "Category",
        "FIR_STATUS", "COMPLAINANT_NAME", "ACCUSED_NAME",
        "OCCURANCE_FROM_DT", "OCCURANCE_TO_DT", "OCCURANCE_PLACE"
    ]

    # Step 4: Build complete response dict (include all required fields)
    complete_data = {field: merged_data.get(field, "") for field in required_fields}

    # Step 5: Figure out which fields are still missing
    missing_fields = [field for field, val in complete_data.items() if not val]

    # Step 6: Generate GPT response message
    gpt_response = custom_prompt_response(
        original_text=input.text,
        extracted_data=complete_data,
        user_instruction=input.instruction,
        logging=logging
    )

    return {
        "extracted_entities": complete_data,  
        "gpt_response": gpt_response
    }


# class PDFWithLogo(FPDF):
#     def header(self):
#         self.image("Static/OPLogo.png", 10, 6, 30)
#         # Then adjust your title positioning if needed:
#         self.set_font("Arial", "B", 16)
#         self.cell(0, 10, "INJURY REPORT", ln=True, align="C")
#         self.ln(10)

class PDFSexualAssaultFormat(FPDF):
    def header(self):
        # Add logo on top-left
        self.image("Static/OPLogo.png", 10, 8, 25)  # Adjust width as needed
        self.set_y(30)  # Push title below logo
        self.set_font("Arial", "B", 12)
        self.cell(0, 10, "Medical examination of victim of sexual assault", ln=True, align="C")
        self.ln(5)

    def numbered_field(self, number, label, value):
        self.set_font("Arial", "", 11)

        if isinstance(number, int):
            self.cell(10, 8, f"{number}.", ln=0)
        else:
            self.cell(20, 8, f"{number}", ln=0)  # For "Any other request" or custom

        # Calculate width and wrap value if long
        self.cell(65, 8, f"{label}", ln=0)
        if len(value) > 45:
            self.ln()
            self.cell(20)
            self.multi_cell(0, 8, value)
        else:
            self.cell(0, 8, value, ln=1)

    def body(self, data):
        self.set_font("Arial", "", 11)
        self.cell(0, 8, f"Ref. No. {data.get('REF_NO', '0000/2025')}, {data.get('PS', '')}, {data.get('DISTRICT', '')}", ln=True)
        self.cell(0, 8, f"Date. {data.get('DATE', '01/01/2025')}", ln=True)
        self.ln(5)

        # CHC Address
        self.multi_cell(0, 8, f"To\n\n        The CHC, {data.get('HOSPITAL_PLACE', 'CHC Name')}, {data.get('DISTRICT', '')}\nSir/Madam,\n")
        self.multi_cell(0, 8, "Please conduct Medical examination on the following victim of sexual assault:\n")

        # Numbered Fields with improved layout
        self.numbered_field(1, "Name", data.get("NAME", ""))
        self.numbered_field(2, "Age/Sex", data.get("AGE_SEX", ""))
        self.numbered_field(3, "D/W/O", data.get("DWO", ""))
        self.numbered_field(4, "Address", data.get("ADDRESS", ""))
        self.numbered_field(5, "Police Station", data.get("PS", ""))
        self.numbered_field(6, "Name of the Investigating Officer", data.get("INVESTIGATING_OFFICER", ""))
        self.numbered_field(7, "Name of the accompanying police constable", data.get("ACCOMPANYING_CONSTABLE", ""))
        self.numbered_field(8, "Name of the relative (If accompanying)", data.get("RELATIVE_NAME", ""))
        self.numbered_field(9, "The case in brief", data.get("CASE_IN_BRIEF", ""))
        self.numbered_field(10, "Samples to be preserved", data.get("DOCUMENTS", ""))
        self.numbered_field("Any other request", "", data.get("OTHER_REQUEST", ""))

        # Query section
        self.ln(5)
        self.multi_cell(0, 8, "11. Please opine on the following queries:")
        self.multi_cell(0, 8, "a. Whether there are any injuries on her private and any other body parts suggestive of recent forceful sexual intercourse?")
        self.multi_cell(0, 8, "b. Whether the victim is pregnant?")
        self.multi_cell(0, 8, "c. Whether the victim is suffering from any venereal diseases?")
        self.multi_cell(0, 8, "d. Whether any other treatment is required?")
        self.ln(10)

        # Signature section
        self.multi_cell(0, 8, f"Name in Full: {data.get('INVESTIGATING_OFFICER', '')}")
        self.multi_cell(0, 8, f"Police Station: {data.get('PS', '')}")
        self.multi_cell(0, 8, f"Contact No.: {data.get('CONTACT_NO', 'N/A')}")


# @app.post("/generate_fir_pdf")
# async def generate_fir_pdf(data: Dict[str, str]):
#     # 🧪 Debug: verify logo presence
#     print("CWD:", os.getcwd())
#     print("OPLogo.png real path:", os.path.abspath("Static/OPLogo.png"))
#     print("exists:", os.path.exists("Static/OPLogo.png"))

#     pdf = PDFWithLogo()
#     pdf.alias_nb_pages()
#     pdf.add_page()
#     pdf.set_auto_page_break(auto=True, margin=15)

#     def add_field(label: str, key: str):
#         value = data.get(key, "N/A")
#         pdf.set_font("Arial", "B", 12)
#         pdf.cell(60, 8, f"{label}:", ln=0)
#         pdf.set_font("Arial", "", 12)
#         pdf.multi_cell(0, 8, value)

#     # Section 1: Case Details
#     pdf.set_font("Arial", "B", 14)
#     pdf.cell(0, 10, "", ln=True)
#     pdf.set_font("Arial", "", 12)
#     add_field("NAME", "NAME")
#     add_field("AGE SEX", "AGE_SEX")
#     add_field("DWO", "DWO")
#     add_field("ADDRESS", "ADDRESS")
#     add_field("INVESTIGATING OFFICER", "INVESTIGATING_OFFICER")
#     add_field("ACCOMPANYING CONSTABLE", "ACCOMPANYING_CONSTABLE")
#     pdf.ln(5)

#     # Section 2: Parties Involved
#     pdf.set_font("Arial", "B", 14)
#     pdf.cell(0, 10, "", ln=True)
#     pdf.set_font("Arial", "", 12)
#     add_field("RELATIVE NAME", "RELATIVE_NAME")
#     add_field("CASE IN BRIEF", "CASE_IN_BRIEF")
#     pdf.ln(5)

#     # Section 3: Occurrence Info
#     pdf.set_font("Arial", "B", 14)
#     pdf.cell(0, 10, "", ln=True)
#     pdf.set_font("Arial", "", 12)
#     add_field("DOCUMENTS", "DOCUMENTS")
#     add_field("OTHER_REQUEST", "OTHER_REQUEST")
#     # add_field("Place", "OCCURANCE_PLACE")
#     pdf.ln(5)

#     # Section 4: Police Info
#     pdf.set_font("Arial", "B", 14)
#     pdf.cell(0, 10, "", ln=True)
#     pdf.set_font("Arial", "", 12)
#     add_field("District", "DISTRICT")
#     add_field("Police Station", "PS")

#     # Save PDF
#     filename = f"FIR_Report_{uuid.uuid4()}.pdf"
#     os.makedirs("generated_pdfs", exist_ok=True)
#     filepath = os.path.join("generated_pdfs", filename)
#     pdf.output(filepath)

#     return FileResponse(
#         path=filepath,
#         filename="FIR_Report.pdf",
#         media_type="application/pdf"
#     )

@app.post("/generate_fir_pdf")
async def generate_structured_pdf(data: Dict[str, str]):
    pdf = PDFSexualAssaultFormat()
    pdf.add_page()
    pdf.body(data)

    filename = f"Injury_Report_{uuid.uuid4()}.pdf"
    os.makedirs("generated_pdfs", exist_ok=True)
    filepath = os.path.join("generated_pdfs", filename)
    pdf.output(filepath)

    return FileResponse(
        path=filepath,
        filename="Structured_Injury_Report.pdf",
        media_type="application/pdf"
    )


# ---------------------------------------------------------
# USED FOR INJURY REPORT
# -------------------------------------------------------------

@app.post("/custom_instruction_injury")
async def custom_instruction_injury(input: CustomInstructionInput):
    previous_data = input.existing_data or {}

    # Step 1: Extract new values using GPT
    new_extracted = entity_recog_gpt_injury_Report(input.text, logging)

    # Step 2: Merge smartly – do not overwrite existing good values with blanks
    merged_data = previous_data.copy()
    for key, value in new_extracted.items():
        if value:  # update only if new value is non-empty
            merged_data[key] = value

    # Step 3: Required fields definition
    required_fields = [
        "DISTRICT", "PS", "NAME", "AGE_SEX", "DWO", "ADDRESS", "INVESTIGATING_OFFICER",
        "ACCOMPANTING_CONSTABLE", "RELATIVE_NAME", "ACCOMPANYING_CONSTABLE",
        "CASE_IN_BRIEF", "DOCUMENTS", "OTHER_REQUEST"
    ]

    # Step 4: Build complete response dict (include all required fields)
    complete_data = {field: merged_data.get(field, "") for field in required_fields}

    # Step 5: Figure out which fields are still missing
    missing_fields = [field for field, val in complete_data.items() if not val]

    # Step 6: Generate GPT response message
    gpt_response = custom_prompt_response(
        original_text=input.text,
        extracted_data=complete_data,
        user_instruction=input.instruction,
        logging=logging
    )

    return {
        "extracted_entities": complete_data,  
        "gpt_response": gpt_response
    }

@app.post("/chat")
async def chat(request: Request):
    data = await request.json()
    user_message = data["message"]
    chat_history = data.get("history", [])

    # Check for simple acknowledgments
    simple_responses = ["okay", "ok", "thanks", "thank you", "good", "fine", "yes", "no", "nothing"]
    if user_message.lower().strip() in simple_responses:
        return {"answer": "Understood! How else can I help you with the FIR data?", "sql": "SELECT 'Acknowledged' as response"}

    sql_query = ""  # Always initialize

    # Build messages for OpenAI to generate SQL - SANITIZE ALL CONTENT
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in chat_history:
        user_content = str(turn.get("user", "")) if turn.get("user") is not None else ""
        bot_content = str(turn.get("bot", "")) if turn.get("bot") is not None else ""
        
        if user_content.strip():
            messages.append({"role": "user", "content": user_content})
        if bot_content.strip():
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

        # Reject multiple SQL statements
        if ';' in sql_query:
            return {"error": "Invalid SQL: multiple statements detected. Please rephrase your question.", "sql": sql_query}

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
                # For SELECT * queries, return the rows directly
                rows = [dict(row) for row in result.mappings()]
                return {"answer": rows, "sql": sql_query}
    except Exception as e:
        return {"error": str(e), "sql": sql_query}

if __name__ == "__main__":
    uvicorn.run(app, host='127.0.0.1', port=5000)
