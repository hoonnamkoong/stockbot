import os
import glob
import pandas as pd
from datetime import datetime, timedelta
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders

def send_monthly_report():
    # 1. Determine "Last Month"
    today = datetime.now()
    first = today.replace(day=1)
    last_month = first - timedelta(days=1)
    target_ym = last_month.strftime("%Y%m") # e.g. 202511
    
    print(f"📊 Generating Monthly Report for: {last_month.strftime('%B %Y')}")
    
    # 2. Find CSVs matching this YM
    # Filename format: trending_integrated_YYYYMMDD_HHMMSS.csv
    csv_pattern = f"data/trending_integrated_{target_ym}*.csv"
    files = glob.glob(csv_pattern)
    
    if not files:
        print(f"❌ No data files found for {target_ym}")
        return

    print(f"Found {len(files)} data files.")

    # 3. Combine Data
    combined_df = pd.DataFrame()
    for f in files:
        try:
            df = pd.read_csv(f)
            # Extract timestamp from filename for 'Collected At' column
            # filename example: data/trending_integrated_20251210_195101.csv
            basename = os.path.basename(f)
            time_part = basename.split('_')[2] + "_" + basename.split('_')[3].replace('.csv','')
            # Format: YYYYMMDD_HHMMSS
            dt = datetime.strptime(time_part, "%Y%m%d_%H%M%S")
            df['Collected_At'] = dt
            
            combined_df = pd.concat([combined_df, df])
        except Exception as e:
            print(f"Skipping {f}: {e}")

    if combined_df.empty:
        print("❌ Combined DataFrame is empty.")
        return

    # 4. Save to Excel
    output_filename = f"StockBot_Report_{target_ym}.xlsx"
    combined_df.to_excel(output_filename, index=False)
    print(f"✅ Excel saved: {output_filename}")

    # 5. Email Config
    GMAIL_USER = os.environ.get("GMAIL_USER")
    GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
    TO_EMAIL = "hoon.namkoong@gmail.com"
    
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("❌ Missing GMAIL_USER or GMAIL_APP_PASSWORD env vars.")
        return

    # 6. Send Email
    try:
        msg = MIMEMultipart()
        msg['From'] = GMAIL_USER
        msg['To'] = TO_EMAIL
        msg['Subject'] = f"📊 StockBot Monthly Report: {last_month.strftime('%B %Y')}"

        body = f"""
        StockBot Monthly Data Report
        
        Period: {last_month.strftime('%Y-%m')}
        Total Records: {len(combined_df)}
        Files Processed: {len(files)}
        
        Attached is the consolidated Excel file.
        """
        msg.attach(MIMEText(body, 'plain'))

        # Attachment
        with open(output_filename, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
        
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f"attachment; filename= {output_filename}",
        )
        msg.attach(part)

        # SMTP Send
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        text = msg.as_string()
        server.sendmail(GMAIL_USER, TO_EMAIL, text)
        server.quit()
        
        print(f"✅ Email sent successfully to {TO_EMAIL}")

    except Exception as e:
        print(f"❌ Failed to send email: {e}")

if __name__ == "__main__":
    send_monthly_report()
