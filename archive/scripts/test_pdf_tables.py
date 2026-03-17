import sys
from src.pdf_analyzer import analyze_pdf

def test_pdf(url):
    print(f"Testing PDF Analysis for: {url}")
    print("-" * 50)
    
    result = analyze_pdf(url)
    
    if not result:
        print("❌ Failed to download or analyze PDF.")
        return

    print(f"Title/Opinion: {result.get('opinion')}")
    print(f"Summary Length: {len(result.get('summary', ''))} chars")
    
    tables = result.get('tables', [])
    print(f"tables count: {len(tables)}")
    
    if tables:
        print(f"\n✅ Found {len(tables)} tables!")
        for i, table in enumerate(tables):
            print(f"\n[Table {i+1}]")
            print(table[:200] + "...") # Print first 200 chars
    else:
        print("\n⚠️ No tables found. (This might be a text-only PDF or image-based)")

if __name__ == "__main__":
    # Example URL (Users can change this)
    # Using a known PDF URL or taking one from input
    url = input("Enter PDF URL to test (or press Enter for default): ").strip()
    if not url:
        print("Please provide a URL.")
    else:
        test_pdf(url)
