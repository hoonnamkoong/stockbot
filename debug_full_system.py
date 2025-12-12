import sys
import os
import requests
import time

print("--- [Step 1] Dependency Check ---")
try:
    import pdfplumber
    print("✅ pdfplumber imported successfully.")
except ImportError:
    print("❌ pdfplumber NOT FOUND. Please run: pip install pdfplumber")

try:
    from pypdf import PdfReader
    print("✅ pypdf imported successfully.")
except ImportError:
    print("❌ pypdf NOT FOUND.")

print("\n--- [Step 2] Telegram Credential Check ---")
token = os.environ.get("TELEGRAM_BOT_TOKEN")
chat_id = os.environ.get("TELEGRAM_CHAT_ID")

if not token:
    print("⚠️  TELEGRAM_BOT_TOKEN env var is missing.")
    token = input("Enter Bot Token manually: ").strip()
else:
    print(f"✅ Token found in env: {token[:4]}...")

if not chat_id:
    print("⚠️  TELEGRAM_CHAT_ID env var is missing.")
    chat_id = input("Enter Chat ID manually: ").strip()
else:
    print(f"✅ Chat ID found in env: {chat_id}")

print("\n--- [Step 3] Network & PDF Analysis Test ---")
pdf_url = "https://stock.pstatic.net/stock-research/invest/63/20251212_invest_276330000.pdf" 
# (This is one of the URLs from the user's json)

print(f"Target URL: {pdf_url}")
try:
    response = requests.get(pdf_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
    print(f"Download Status: {response.status_code}")
    print(f"Content Size: {len(response.content)} bytes")
    
    if response.status_code == 200:
        print("✅ PDF Download Successful.")
        
        # Test Analysis Logic with imported modules
        from src.pdf_analyzer import analyze_pdf
        print("Running analyze_pdf()...")
        result = analyze_pdf(pdf_url)
        
        print(f"\n[Analysis Result]")
        print(f"Opinion: {result.get('opinion')}")
        print(f"Summary: {result.get('summary')[:50]}...")
        
        tables = result.get('tables', [])
        if tables:
            print(f"✅ TABLES DETECTED: {len(tables)} found.")
            print("First table preview:")
            print(tables[0][:100] + "...")
        else:
            print("❌ NO TABLES found in this PDF.")
            
    else:
        print("❌ PDF Download Failed.")

except Exception as e:
    print(f"❌ Network/Analysis Error: {e}")

print("\n--- [Step 4] Sending Test Telegram ---")
try:
    msg = f"🔍 Debug Test: Analysis Complete. Tables Found: {len(tables) if 'tables' in locals() else 0}"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": msg}
    res = requests.post(url, json=payload, timeout=5)
    print(f"Telegram Status: {res.status_code}")
    if res.status_code == 200:
        print("✅ Telegram Message Sent Successfully.")
    else:
        print(f"❌ Telegram Failed: {res.text}")
except Exception as e:
    print(f"❌ Telegram Error: {e}")
