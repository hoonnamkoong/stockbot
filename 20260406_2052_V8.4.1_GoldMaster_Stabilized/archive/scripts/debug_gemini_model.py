import google.generativeai as genai
import os

api_key = os.environ.get('GOOGLE_API_KEY')
if not api_key:
    # Try loading from .env.local if not in env
    try:
        with open('.env.local', 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('GOOGLE_API_KEY='):
                    api_key = line.split('=')[1].strip().strip('"').strip("'")
                    break
    except:
        pass

if not api_key:
    print("Error: No API Key found.")
    exit(1)

genai.configure(api_key=api_key)

model_id = 'gemini-2.5-flash-lite'
print(f"Testing Model: {model_id}")

try:
    model = genai.GenerativeModel(model_id)
    response = model.generate_content("Hello, represent yourself.")
    print(f"Success! Response: {response.text}")
except Exception as e:
    print(f"Failed with {model_id}: {e}")
    
    print("\n--- Listing Available Models ---")
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(m.name)
    except:
        print("Could not list models.")
