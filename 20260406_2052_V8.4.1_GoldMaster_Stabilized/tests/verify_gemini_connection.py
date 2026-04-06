
import os
import google.generativeai as genai
import google.generativeai as genai
# from dotenv import load_dotenv # Optional: Install python-dotenv if needed locally

def test_gemini_connection():
    # 1. Load API Key
    # load_dotenv() 
    api_key = os.environ.get('GOOGLE_API_KEY')
    
    if not api_key:
        # Try fallback names people often use
        api_key = os.environ.get('GEMINI_KEY') or os.environ.get('GEMINI_API_KEY')

    if not api_key:
        print("❌ Error: GOOGLE_API_KEY not found in environment or .env file.")
        print("Please check your .env file.")
        return

    print(f"✅ API Key found: {api_key[:5]}...{api_key[-5:]}")

    # 2. Configure Gemini
    try:
        genai.configure(api_key=api_key)
        
        # 3. Test Model: gemini-2.5-flash-lite
        model_name = 'gemini-2.5-flash-lite'
        print(f"🔄 Connecting to model: {model_name}...")
        
        model = genai.GenerativeModel(model_name)
        
        # 4. Generate Sample Content
        prompt = "Hello, are you functional? Reply with 'Yes, I am working'."
        response = model.generate_content(prompt)
        
        if response.text:
            print(f"✅ Success! Response: {response.text.strip()}")
        else:
            print("⚠️ Response received but empty text.")

    except Exception as e:
        print(f"❌ Connection Failed: {e}")
        print("\nPossible causes:")
        print("1. Invalid API Key")
        print("2. Model name 'gemini-2.5-flash-lite' not available to your key/region.")
        print("3. Quota exceeded.")

if __name__ == "__main__":
    test_gemini_connection()
