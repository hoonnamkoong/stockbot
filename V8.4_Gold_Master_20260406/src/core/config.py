import os

# --- System Configuration ---
# 64-bit Python Environment
PYTHON_ENV = "64bit"

# --- API Keys ---
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
GEMINI_KEY = os.environ.get('GEMINI_KEY') # For Gemini API
# Note: GitHub Actions secrets mapping required for GEMINI_KEY

# --- Scheduler Configuration ---
# Allowlist for scraping execution (KST)
# [10, 12, 13, 15] as verified in Incident Report 2026-02-05
SCRAPING_HOURS = [10, 12, 13, 15] 

# --- Sentinel-V Algorithm Thresholds ---
SENTINEL_V = {
    # Phase 1: Entry Filters
    'SPARK_POSTS_MIN': 400,         # Minimum posts to consider a Spark (New Entrant)
    'SPARK_GROWTH_RATE': 0.5,       # 50% growth required for Existing stocks
    'PQI_MIN': 2.0,                 # Post Quality Index (Likes/Views * 100)
    'SENTIMENT_POS_MIN': 60,        # Minimum Positive Sentiment %
    
    # Phase 2: Safety Lock
    'SAFETY_LOCK_POSTS': 600,       # Trigger for 50% sell
    
    # Phase 3: Profit Run / Saturation
    'TRAILING_STOP_DROP': 4.0,      # -4% from High -> Sell All
    'SATURATION_POSTS': 800,        # Max saturation point
    'SATURATION_EXIT_COND': 'UPPER_LIMIT' # Exit if not Upper Limit
}

# --- Telegram Messages ---
MESSAGES = {
    'BUY_SIGNAL': "🚀 <b>[Sentinel-V] Strong Buy Signal</b>\n\nStock: {name} ({code})\nReason: {reason}\n🤖 AI Verification: {ai_comment}",
    'SELL_SIGNAL': "🛑 <b>[Sentinel-V] Exit Signal</b>\n\nStock: {name}\nReason: {reason} ({trigger_val})"
}
