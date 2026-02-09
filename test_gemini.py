import google.generativeai as genai
import os
import sys

# Load .env.local if present
if os.path.exists('.env.local'):
    print("Loading .env.local...")
    with open('.env.local', 'r', encoding='utf-8') as f:
        for line in f:
            if 'GEMINI_KEY=' in line and not line.strip().startswith('#'):
                key = line.strip().split('=', 1)[1].strip('"').strip("'")
                os.environ['GEMINI_KEY'] = key

KEY = os.environ.get('GEMINI_KEY')

if not KEY:
    print("❌ GEMINI_KEY not found in environment or .env.local")
    sys.exit(1)

print(f"🔑 Found Key: {KEY[:5]}...{KEY[-3:]}")

try:
    genai.configure(api_key=KEY)
    model = genai.GenerativeModel('gemini-1.5-pro')
    print("🤖 Model configured. Sending test prompt...")
    
    response = model.generate_content("Hello, are you working? Reply with 'Yes, I am active.'")
    print(f"✅ Response received: {response.text}")

except Exception as e:
    print(f"❌ API Error: {e}")
