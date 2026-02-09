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
    model = genai.GenerativeModel('gemini-2.0-flash-exp')
    print("🤖 Model configured. Sending test prompt...")
            
    # Check specifically for flash versions
    print("\n🔍 Checking specific Flash models:")
    try:
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        response = model.generate_content("Ping")
        print(f"✅ gemini-2.0-flash-exp is AVAILABLE.")
    except Exception as e:
        print(f"❌ gemini-2.0-flash-exp is NOT available: {e}")

except Exception as e:
    print(f"❌ API Error: {e}")
