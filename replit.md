# Net Worth Tracker

## Overview

This Flask-based web application provides a comprehensive personal finance tracking solution. It replaces traditional spreadsheet methods with a full-featured web interface to track net worth, investments, income, and expenses over time. The project aims to offer detailed dashboard views, monthly tracking, and robust financial analysis capabilities for better personal financial management.

## User Preferences

Preferred communication style: Simple, everyday language.
Data integrity: Only use real collected data, never backfill or create synthetic historical data for charts.

## System Architecture

### Frontend
- **Framework**: Flask with Jinja2 templating for server-side rendering.
- **Styling**: Tailwind CSS for responsive design and Font Awesome for icons.
- **Interactivity**: Minimal vanilla JavaScript.
- **UI/UX Decisions**: Liquid glass modal system, consistent rounded corners across all UI elements (cards, forms, buttons), dark mode with multi-layered gradient background, and a fixed left sidebar navigation with active state highlighting. Custom iPhone home screen icon.
- **Progressive Web App (PWA)**: Separate mobile templates with bottom tab navigation, installable app experience, offline functionality, and mobile-optimized layouts. Device detection automatically serves appropriate templates.

### Backend
- **Framework**: Flask (Python).
- **Structure**: Modular design with utility classes for data management and price fetching.
- **Data Layer**: PostgreSQL database for persistent storage of all financial data (investments, cash, expenses, net worth tracking).
- **Business Logic**: Centralized in `DataManager` (or `DatabaseDataManager`) and `PriceFetcher` for handling data operations, live market price retrieval, and financial calculations.

### Key Features and Design Patterns
- **Multi-Year Tracking**: Supports tracking financial data across multiple years with month-on-month calculations.
- **Platform-Based Tracking**: Tracks total values for various investment platforms, including cash balances.
- **Real-time Price Fetching**: Utilizes `yfinance` for stocks and a custom CoinGecko integration for cryptocurrencies. Includes specialized web scraping for specific HL LISA funds and automatic USD to GBP conversion for US stocks, and pence to pounds conversion for UK stocks. Features automatic background price updates every 15 minutes with status display and manual override.
- **Editable Interface**: Allows in-app editing of financial data (income, monthly values, investments) with immediate persistence.
- **Goals Tracking**: Comprehensive goal tracking system with progress visualization, compound interest calculator, and quarterly milestone tracking similar to the user's Google Sheets approach.
- **PWA Mobile Experience**: Separate mobile templates with bottom tab navigation, touch-optimized interactions, installable app functionality, and privacy mode. Device detection serves appropriate templates automatically.
- **Privacy Mode**: Toggle functionality to blur sensitive financial data while preserving growth metrics, works across both desktop and mobile versions.

## External Dependencies

### Python Packages
- **Flask**: Web framework.
- **yfinance**: For fetching stock price data.
- **psycopg2** (implied from PostgreSQL migration): For PostgreSQL database interaction.
- **requests**, **BeautifulSoup** (implied from web scraping): For custom web scraping.
- **Standard Library**: `os`, `json`, `logging`, `datetime`.

### Frontend Dependencies
- **Tailwind CSS**: For styling (CDN).
- **Font Awesome**: For icons (CDN).

### Investment Platforms Supported
- Degiro
- Trading212 ISA
- EQ (GSK shares)
- InvestEngine ISA
- Crypto
- HL Stocks & Shares LISA
- Cash