import json

def check_stock(code):
    try:
        with open('data/analysis_5days.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        found = False
        for stock in data:
            if stock['code'] == code:
                found = True
                print(f"--- Stock: {code} ({stock.get('name')}) Index: {data.index(stock)} ---")
                print(f"Consecutive Days: {stock.get('consecutive_days')}")
                print(f"Sparkline Price: {stock.get('sparkline_price')}")
                # Don't break, keep looking for duplicates
        
        if not found:
            print(f"Stock {code} NOT FOUND in JSON.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_stock("042660") # Hanwha Ocean
    check_stock("006805") # Mirae Asset
    check_stock("012200") # Keyang
