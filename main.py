import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import openai
import re
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.enums import TA_CENTER, TA_LEFT

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
    },
    "CCTV Footage Analysis": {
        "title": "CCTV Footage Analysis",
        "fields": [
            {"name": "incident_date", "label": "Date and Time of Incident", "type": "datetime-local", "required": True},
            {"name": "camera_location", "label": "Location of CCTV Camera", "type": "text", "required": True},
            {"name": "events_captured", "label": "Description of Events Captured", "type": "textarea", "required": True},
            {"name": "perpetrators_identified", "label": "Identification of Perpetrators", "type": "textarea", "required": True},
            {"name": "chain_of_custody", "label": "Chain of Custody of Footage", "type": "textarea", "required": True},
            {"name": "analyst_name", "label": "Analyst's Name", "type": "text", "required": True},
            {"name": "analyst_signature", "label": "Analyst's Signature", "type": "text", "required": True}
        ]
    },
    "Forensic Report": {
        "title": "Forensic Report",
        "fields": [
            {"name": "case_number", "label": "Case Number", "type": "text", "required": True},
            {"name": "evidence_type", "label": "Type of Evidence", "type": "text", "required": True},
            {"name": "collection_date", "label": "Date of Collection", "type": "datetime-local", "required": True},
            {"name": "analysis_method", "label": "Method of Analysis", "type": "textarea", "required": True},
            {"name": "findings", "label": "Forensic Findings", "type": "textarea", "required": True},
            {"name": "conclusion", "label": "Conclusion", "type": "textarea", "required": True},
            {"name": "forensic_expert", "label": "Forensic Expert Name", "type": "text", "required": True}
        ]
    },
    "Digital Evidence Report": {
        "title": "Digital Evidence Report",
        "fields": [
            {"name": "device_type", "label": "Device Type", "type": "text", "required": True},
            {"name": "device_serial", "label": "Device Serial Number", "type": "text", "required": True},
            {"name": "seizure_date", "label": "Date of Seizure", "type": "datetime-local", "required": True},
            {"name": "evidence_description", "label": "Description of Digital Evidence", "type": "textarea", "required": True},
            {"name": "analysis_results", "label": "Analysis Results", "type": "textarea", "required": True},
            {"name": "expert_name", "label": "Digital Forensics Expert", "type": "text", "required": True}
        ]
    },
    "Chemical Analysis Report": {
        "title": "Chemical Analysis Report",
        "fields": [
            {"name": "sample_description", "label": "Sample Description", "type": "text", "required": True},
            {"name": "analysis_date", "label": "Date of Analysis", "type": "datetime-local", "required": True},
            {"name": "test_methods", "label": "Test Methods Used", "type": "textarea", "required": True},
            {"name": "chemical_findings", "label": "Chemical Analysis Findings", "type": "textarea", "required": True},
            {"name": "chemist_name", "label": "Chemist's Name", "type": "text", "required": True}
        ]
    },
    "Ballistic Report": {
        "title": "Ballistic Report",
        "fields": [
            {"name": "firearm_type", "label": "Firearm Type", "type": "text", "required": True},
            {"name": "cartridge_details", "label": "Cartridge Details", "type": "text", "required": True},
            {"name": "ballistic_analysis", "label": "Ballistic Analysis", "type": "textarea", "required": True},
            {"name": "expert_name", "label": "Ballistics Expert Name", "type": "text", "required": True}
        ]
    },
    "DNA Analysis Report": {
        "title": "DNA Analysis Report",
        "fields": [
            {"name": "sample_type", "label": "Sample Type", "type": "text", "required": True},
            {"name": "collection_date", "label": "Date of Collection", "type": "datetime-local", "required": True},
            {"name": "analysis_date", "label": "Date of Analysis", "type": "datetime-local", "required": True},
            {"name": "dna_findings", "label": "DNA Analysis Findings", "type": "textarea", "required": True},
            {"name": "geneticist_name", "label": "Geneticist's Name", "type": "text", "required": True}
        ]
    },
    "Fingerprint Analysis": {
        "title": "Fingerprint Analysis",
        "fields": [
            {"name": "fingerprint_type", "label": "Fingerprint Type", "type": "select", "options": ["Latent", "Patent", "Plastic"], "required": True},
            {"name": "surface_type", "label": "Surface Type", "type": "text", "required": True},
            {"name": "analysis_date", "label": "Date of Analysis", "type": "datetime-local", "required": True},
            {"name": "fingerprint_findings", "label": "Fingerprint Analysis Findings", "type": "textarea", "required": True},
            {"name": "expert_name", "label": "Fingerprint Expert Name", "type": "text", "required": True}
        ]
    },
    "Document Verification Report": {
        "title": "Document Verification Report",
        "fields": [
            {"name": "document_type", "label": "Document Type", "type": "text", "required": True},
            {"name": "verification_date", "label": "Date of Verification", "type": "datetime-local", "required": True},
            {"name": "verification_method", "label": "Method of Verification", "type": "textarea", "required": True},
            {"name": "verification_findings", "label": "Verification Findings", "type": "textarea", "required": True},
            {"name": "verifier_name", "label": "Verifier's Name", "type": "text", "required": True}
        ]
    },
    "Financial Transaction Analysis": {
        "title": "Financial Transaction Analysis",
        "fields": [
            {"name": "account_holder", "label": "Account Holder Name", "type": "text", "required": True},
            {"name": "account_number", "label": "Account Number", "type": "text", "required": True},
            {"name": "analysis_period", "label": "Analysis Period", "type": "text", "required": True},
            {"name": "suspicious_transactions", "label": "Suspicious Transactions", "type": "textarea", "required": True},
            {"name": "analysis_findings", "label": "Analysis Findings", "type": "textarea", "required": True},
            {"name": "analyst_name", "label": "Financial Analyst Name", "type": "text", "required": True}
        ]
    }
}

@app.get("/report-form/{report_type}")
async def get_report_form(report_type: str):
    """Get the form structure for a specific report type"""
    # Try exact match first
    if report_type in REPORT_FORMS:
        return REPORT_FORMS[report_type]
    
    # Try partial matches for common variations
    partial_matches = {
        "vehicle": "Vehicle Inspection Report",
        "witness": "Witness Statement", 
        "cctv": "CCTV Footage Analysis",
        "medical": "Medical Injury Report",
        "injury": "Medical Injury Report",
        "postmortem": "Postmortem Report",
        "property": "Property Seizure Memo",
        "seizure": "Property Seizure Memo",
        "forensic": "Forensic Report",
        "digital": "Digital Evidence Report",
        "chemical": "Chemical Analysis Report",
        "ballistic": "Ballistic Report",
        "dna": "DNA Analysis Report",
        "fingerprint": "Fingerprint Analysis",
        "document": "Document Verification Report",
        "financial": "Financial Transaction Analysis"
    }
    
    # Check if any partial match works
    for keyword, full_report_name in partial_matches.items():
        if keyword.lower() in report_type.lower():
            if full_report_name in REPORT_FORMS:
                return REPORT_FORMS[full_report_name]
    
    # If still not found, return error
    return {"error": f"Report type '{report_type}' not found"}

@app.get("/available-reports")
async def get_available_reports():
    """Get list of all available report types"""
    return {"reports": list(REPORT_FORMS.keys())}

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
                # Analyze only - Use a simpler approach
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
                
                # Simple keyword-based report suggestion
                suggested_reports = []
                fir_content_lower = fir_content.lower()
                
                # Check for specific keywords and suggest appropriate reports
                if any(word in fir_content_lower for word in ["vehicle", "bike", "motorcycle", "car", "registration"]):
                    suggested_reports.append("Vehicle Inspection Report")
                
                if any(word in fir_content_lower for word in ["witness", "saw", "seen", "observed"]):
                    suggested_reports.append("Witness Statement")
                
                if any(word in fir_content_lower for word in ["cctv", "camera", "footage", "video"]):
                    suggested_reports.append("CCTV Footage Analysis")
                
                if any(word in fir_content_lower for word in ["injury", "hurt", "wound", "medical", "hospital", "doctor"]):
                    suggested_reports.append("Medical Injury Report")
                
                if any(word in fir_content_lower for word in ["death", "deceased", "murder", "killed"]):
                    suggested_reports.append("Postmortem Report")
                
                if any(word in fir_content_lower for word in ["seized", "recovered", "stolen", "property", "items"]):
                    suggested_reports.append("Property Seizure Memo")
                
                if any(word in fir_content_lower for word in ["evidence", "forensic", "scientific"]):
                    suggested_reports.append("Forensic Report")
                
                if any(word in fir_content_lower for word in ["phone", "mobile", "digital", "computer", "device"]):
                    suggested_reports.append("Digital Evidence Report")
                
                if any(word in fir_content_lower for word in ["chemical", "substance", "drug"]):
                    suggested_reports.append("Chemical Analysis Report")
                
                if any(word in fir_content_lower for word in ["gun", "firearm", "bullet", "ballistic"]):
                    suggested_reports.append("Ballistic Report")
                
                if any(word in fir_content_lower for word in ["dna", "blood", "biological"]):
                    suggested_reports.append("DNA Analysis Report")
                
                if any(word in fir_content_lower for word in ["fingerprint", "print"]):
                    suggested_reports.append("Fingerprint Analysis")
                
                if any(word in fir_content_lower for word in ["document", "paper", "certificate"]):
                    suggested_reports.append("Document Verification Report")
                
                if any(word in fir_content_lower for word in ["bank", "financial", "transaction", "money", "account"]):
                    suggested_reports.append("Financial Transaction Analysis")
                
                # If no specific reports found, add default ones
                if not suggested_reports:
                    suggested_reports = ["Witness Statement", "Property Seizure Memo"]
                
                # Limit to 5 reports maximum
                suggested_reports = suggested_reports[:5]
                
                print(f"DEBUG: Suggested reports: {suggested_reports}")
                
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

@app.get("/test-report")
async def test_report():
    """Test endpoint that always returns a working report form"""
    return {
        "title": "Test Report",
        "fields": [
            {"name": "test_field", "label": "Test Field", "type": "text", "required": True}
        ]
    }

def generate_medical_examination_pdf(form_data: dict, report_type: str) -> bytes:
    """
    Generate a professional medical examination PDF with logo and proper format
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    story = []
    
    # Get styles
    styles = getSampleStyleSheet()
    
    # Custom styles
    header_style = ParagraphStyle(
        'CustomHeader',
        parent=styles['Heading1'],
        fontSize=16,
        spaceAfter=20,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading2'],
        fontSize=14,
        spaceAfter=15,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=10,
        spaceAfter=6,
        alignment=TA_LEFT,
        fontName='Helvetica'
    )
    
    bold_style = ParagraphStyle(
        'CustomBold',
        parent=styles['Normal'],
        fontSize=10,
        spaceAfter=6,
        alignment=TA_LEFT,
        fontName='Helvetica-Bold'
    )
    
    # Add logo (if available) - try multiple possible paths
    logo_paths = [
        "assest/OPLogo.png",
        "assets/OPLogo.png", 
        "static/OPLogo.png",
        "OPLogo.png",
        "logo.png"
    ]
    
    logo_added = False
    for logo_path in logo_paths:
        if os.path.exists(logo_path):
            try:
                img = Image(logo_path, width=2*inch, height=1*inch)
                img.hAlign = 'LEFT'
                story.append(img)
                story.append(Spacer(1, 10))
                logo_added = True
                break
            except Exception as e:
                print(f"Logo error for {logo_path}: {e}")
                continue
    
    if not logo_added:
        # Add a placeholder text for logo
        story.append(Paragraph("LOGO PLACEHOLDER", bold_style))
        story.append(Spacer(1, 10))
    
    # Add report title
    story.append(Paragraph("Medical examination of victim of Sexual Assault", header_style))
    story.append(Spacer(1, 20))
    
    # Add reference and date
    ref_no = form_data.get('ref_no', '0000/2025')
    district = form_data.get('district', 'Kendrapada')
    police_station = form_data.get('police_station', '')
    date = form_data.get('date', '01/01/2025')
    
    ref_text = f"Ref. No. {ref_no}, District: {district}, Police Station: {police_station}<br/>Date: {date}"
    story.append(Paragraph(ref_text, normal_style))
    story.append(Spacer(1, 15))
    
    # Add recipient
    chc_name = form_data.get('chc_name', 'CHC Name')
    recipient_text = f"To<br/>The CHC, {chc_name}, {district}"
    story.append(Paragraph(recipient_text, normal_style))
    story.append(Spacer(1, 10))
    
    # Add salutation
    story.append(Paragraph("Sir/Madam,", normal_style))
    story.append(Spacer(1, 10))
    
    # Add request
    request_text = "Please conduct Medical examination on the following victim of sexual assault:"
    story.append(Paragraph(request_text, normal_style))
    story.append(Spacer(1, 15))
    
    # Create table for victim details with proper formatting
    table_data = [
        ['1.', 'Name', form_data.get('patient_name', 'Not provided')],
        ['2.', 'Age', form_data.get('age', 'Not provided')],
        ['3.', 'Sex', form_data.get('gender', 'Not provided')],
        ['4.', 'D/W/O', form_data.get('son_daughter_of', 'Not provided')],
        ['5.', 'Address', form_data.get('address', 'Not provided')],
        ['6.', 'District', form_data.get('district', 'Not provided')],
        ['7.', 'Police Station', form_data.get('police_station', 'Not provided')],
        ['8.', 'Name of the Investigating Officer', form_data.get('investigating_officer', 'Not provided')],
        ['9.', 'Name of the accompanying police constable', form_data.get('accompanying_constable', 'Not provided')],
        ['10.', 'Name of the relative (If accompanying)', form_data.get('relative_name', 'Not provided')],
        ['11.', 'The case in brief', form_data.get('case_in_brief', 'Not provided')],
        ['12.', 'Samples to be preserved', form_data.get('samples', 'Not provided')],
        ['13.', 'Any other request', form_data.get('other_request', 'Not provided')],
    ]
    
    # Create table with better styling
    table = Table(table_data, colWidths=[0.5*inch, 2.5*inch, 3*inch])
    table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('BACKGROUND', (1, 0), (1, -1), colors.lightgrey),
        ('FONTNAME', (0, 0), (1, -1), 'Helvetica-Bold'),
    ]))
    
    story.append(table)
    story.append(Spacer(1, 15))
    
    # Add medical queries
    queries_text = """Please opine on the following queries:
a. Whether there are any injuries on her private and any other body parts suggestive of recent forceful sexual intercourse?
b. Whether the victim is pregnant?
c. Whether the victim is suffering from any venereal diseases?
d. Whether any other treatment is required?"""
    
    story.append(Paragraph(queries_text, normal_style))
    story.append(Spacer(1, 20))
    
    # Add signature section
    signature_data = [
        ['Name in Full:', form_data.get('officer_name', 'Not provided')],
        ['Police Station:', form_data.get('police_station', '')],
        ['District:', form_data.get('district', 'Kendrapada')],
        ['Contact No.:', form_data.get('contact_no', 'N/A')],
    ]
    
    signature_table = Table(signature_data, colWidths=[1.5*inch, 4*inch])
    signature_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
    ]))
    
    story.append(signature_table)
    
    # Build PDF
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()