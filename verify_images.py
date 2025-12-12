from pdf_analyzer import analyze_pdf
import json
import os

if __name__ == "__main__":
    if os.path.exists("temp.pdf"):
        # Use full path to avoid ambiguity in open() inside analyze_pdf if using relative
        full_path = os.path.abspath("temp.pdf")
        print(f"Analyzing {full_path}...")
        result = analyze_pdf(full_path)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("temp.pdf not found.")
