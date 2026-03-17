import pandas as pd
try:
    df = pd.read_excel('data/monthly_report_2026-02.xlsx')
    print("Columns:", df.columns.tolist())
except Exception as e:
    print("Error:", e)
