import json
import os

try:
    import FinanceDataReader as fdr
except ImportError:
    print("FinanceDataReader is not installed. Run `pip install finance-datareader`")
    exit(1)

def main():
    print("Fetching KRX Stock Listing...")
    df = fdr.StockListing('KRX')
    stocks = []
    
    # We only need active stocks (usually ones without nan names, etc.)
    for idx, row in df.iterrows():
        name = str(row.get('Name', ''))
        code = str(row.get('Code', ''))
        if name and code and name != 'nan':
            stocks.append({"code": code, "name": name})
            
    print(f"Total {len(stocks)} stocks fetched.")
    
    # Save to public/stock_master.json
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public')
    os.makedirs(output_dir, exist_ok=True)
    
    output_path = os.path.join(output_dir, 'stock_master.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(stocks, f, ensure_ascii=False, indent=2)
        
    print(f"Saved successfully to {output_path}")

if __name__ == "__main__":
    main()
