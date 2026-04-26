import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_API_URL = os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1/chat/completions")

def call_openrouter(messages, model="google/gemini-2.0-flash-001", temperature=0.2):
    """
    Generic function to call OpenRouter API.
    """
    if not OPENROUTER_API_KEY:
        return {"error": "OPENROUTER_API_KEY not found in environment"}

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://ucar-hackathon.tn", # Optional
        "X-Title": "UCAR Governance Dashboard" # Optional
    }

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature
    }

    try:
        response = requests.post(OPENROUTER_API_URL, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e)}

def analyze_document_with_ai(ocr_data: dict) -> dict:
    """
    Uses AI to extract structured financial data from OCR results.
    """
    # Prepare text context from OCR data
    text_content = ""
    for page in ocr_data.get("raw_pages", []):
        text_content += f"\n--- Page {page['page_number']} ---\n{page['text']}\n"
    
    # Include tables if available
    tables_content = json.dumps(ocr_data.get("extracted_tables", []), indent=2)
    
    system_prompt = (
        "You are an expert financial analyst. Your task is to extract structured financial request data from the provided document text and tables. "
        "Return ONLY a valid JSON object with the following fields: "
        "title (string), description (string summary), type (one of: PUBLIC_MARKET, PURCHASE, SALE, EVENT_EXPENSE, LAB_FUNDING, OTHER_EXPENSE), "
        "amount (float), currency (string, e.g., TND), department (string), requestedBy (string). "
        "If a field cannot be found, provide a reasonable default or 'Unknown'."
    )
    
    user_prompt = f"Document Content:\n{text_content}\n\nTables Found:\n{tables_content}"
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    result = call_openrouter(messages)
    
    if "error" in result:
        return {"error": result["error"]}
    
    try:
        content = result['choices'][0]['message']['content']
        # Remove markdown code blocks if present
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
            
        return json.loads(content)
    except Exception as e:
        return {"error": f"Failed to parse AI response: {str(e)}", "raw_content": content if 'content' in locals() else None}
