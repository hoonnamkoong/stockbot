import pdfplumber

def debug_pdf(path):
    print(f"Opening {path}...")
    try:
        with pdfplumber.open(path) as pdf:
            print(f"Pages: {len(pdf.pages)}")
            for i, page in enumerate(pdf.pages[:2]):
                text = page.extract_text()
                print(f"--- Page {i+1} ---")
                if text:
                    print(f"Length: {len(text)}")
                    print(f"First 100 chars: {text[:100]}")
                else:
                    print("No text extracted!")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug_pdf("temp.pdf")
