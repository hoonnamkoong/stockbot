import google.generativeai as genai
import os
import sys

# Load .env.local if present
if os.path.exists('.env.local'):
    print("Loading .env.local...")
    with open('.env.local', 'r', encoding='utf-8') as f:
        for line in f:
            if 'GEMINI_KEY=' in line and not line.strip().startswith('#'):
                parts = line.strip().split('=', 1)
                if len(parts) == 2:
                    key = parts[1].strip().strip('"').strip("'")
                    os.environ['GEMINI_KEY'] = key
                    break

KEY = os.environ.get('GEMINI_KEY')

if not KEY:
    print("❌ GEMINI_KEY missing")
    sys.exit(1)

print(f"🔑 Using Key: {KEY[:5]}...")

try:
    genai.configure(api_key=KEY)
    print("🔍 Listing models:")
    models = list(genai.list_models())
    for m in models:
        if 'generateContent' in m.supported_generation_methods:
            print(f" - {m.name}")

    print("\n🔍 Test: gemini-2.0-flash-exp")
    try:
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        res = model.generate_content("Ping")
        print(f"✅ 2.0-flash-exp OK: {res.text}")
    except Exception as e:
        print(f"❌ 2.0-flash-exp FAIL: {e}")

except Exception as e:
    print(f"❌ Error: {e}")
