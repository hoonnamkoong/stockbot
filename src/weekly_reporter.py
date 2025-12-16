
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import pandas as pd
from datetime import datetime, timedelta
import glob

def send_weekly_report():
    print("[Weekly Report] Checking if today is the reporting day...")
    
    # KST 기준 금요일 전송 (Friday = 4 in 0-6 index)
    # GitHub Runner is UTC, so add 9 hours.
    now_utc = datetime.utcnow()
    now_kst = now_utc + timedelta(hours=9)
    
    # if now_kst.weekday() != 4:
    #     print(f"[Weekly Report] Today is {now_kst.strftime('%A')}, not Friday. Skipping.")
    #     return

    # User Request: "매주 장이 끝나는 날" -> Friday (or Manually Triggered)
    # For now, we will allow it to run if triggered, but logically checks dates.
    
    print(f"[Weekly Report] Starting Report Generation for {now_kst.strftime('%Y-%m-%d')}...")

    # 1. Find CSV files for this week (Mon-Fri)
    # Calculate start of week (Monday)
    start_of_week = now_kst - timedelta(days=now_kst.weekday())
    start_str = start_of_week.strftime("%Y%m%d")
    
    # Pattern: trending_integrated_YYYYMMDD_HHMMSS.csv
    # We will gather ALL files and filter by date.
    all_files = glob.glob("trending_integrated_*.csv")
    weekly_files = []
    
    for f in all_files:
        # Extract date part
        try:
            # f = trending_integrated_20251212_042058.csv
            date_part = f.split('_')[2] # 20251212
            if date_part >= start_str:
                weekly_files.append(f)
        except:
            continue
            
    if not weekly_files:
        print("[Weekly Report] No files found for this week.")
        return

    print(f"[Weekly Report] Found {len(weekly_files)} files: {weekly_files}")

    # 2. Merge Data
    merged_data = []
    for f in weekly_files:
        try:
            df = pd.read_csv(f)
            # Add 'Source File' or 'Date' column if needed
            df['Reports_Date'] = f.split('_')[2] + "_" + f.split('_')[3].replace('.csv','')
            merged_data.append(df)
        except Exception as e:
            print(f"Error reading {f}: {e}")
            
    if not merged_data:
        print("[Weekly Report] Failed to merge data.")
        return

    final_df = pd.concat(merged_data, ignore_index=True)
    
    # Save as Excel
    output_filename = f"Weekly_Stock_Report_{now_kst.strftime('%Y%m%d')}.xlsx"
    final_df.to_excel(output_filename, index=False)
    print(f"[Weekly Report] Created Excel: {output_filename}")

    # 3. Send Email
    email_user = os.environ.get('EMAIL_USER')
    email_pass = os.environ.get('EMAIL_PASS')
    recipient = "hoon.namkoong@gmail.com"
    
    if not email_user or not email_pass:
        print("[Weekly Report] EMAIL_USER or EMAIL_PASS missing. Cannot send email.")
        print(f"PLEASE ADD SECRETS: EMAIL_USER (gmail address), EMAIL_PASS (App Password)")
        return

    msg = MIMEMultipart()
    msg['From'] = email_user
    msg['To'] = recipient
    msg['Subject'] = f"📅 [Weekly StockBot] Weekly Report ({now_kst.strftime('%Y-%m-%d')})"

    body = f"""
    StockBot Weekly Report
    
    Date: {now_kst.strftime('%Y-%m-%d')}
    Files Merged: {len(weekly_files)}
    
    See attachment.
    """
    msg.attach(MIMEText(body, 'plain'))

    with open(output_filename, "rb") as f:
        part = MIMEApplication(f.read(), Name=output_filename)
        part['Content-Disposition'] = f'attachment; filename="{output_filename}"'
        msg.attach(part)

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(email_user, email_pass)
        server.send_message(msg)
        server.quit()
        print(f"[Weekly Report] Email sent successfully to {recipient}")
    except Exception as e:
        print(f"[Weekly Report] Failed to send email: {e}")

if __name__ == "__main__":
    send_weekly_report()
