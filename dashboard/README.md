
# Stock Scraper Dashboard

This is a Next.js application that provides a dashboard for the Naver Finance Stock Scraper. It allows you to run the scraper manually, view generated reports, and download them.

## Prerequisites

- Node.js (v18 or higher)
- Python 3.x (with `requests`, `beautifulsoup4`, `pandas` installed)

## Getting Started

1. **Install Dependencies**:
   ```bash
   cd dashboard
   npm install
   ```

2. **Run the Development Server**:
   ```bash
   npm run dev
   ```
   Open [http://localhost:3000](http://localhost:3000) with your browser.

3. **Run the Scheduler**:
   To enable automatic scraping at 10:00, 13:00, and 15:00, run:
   ```bash
   node scheduler.js
   ```
   Keep this terminal window open.

## Features

- **Run Scraper**: Trigger the Python script immediately.
- **File List**: View and download historical CSV reports.
- **Automation**: Scheduled execution via `scheduler.js`.

## Tech Stack

- **Framework**: Next.js 14 (App Router)
- **UI Library**: Mantine UI (v7) + Tailwind CSS
- **Backend API**: Next.js Route Handlers (executing Python subprocess)
