# Net Worth Tracker

## Overview

This is a Flask-based web application that tracks personal net worth, investments, and financial data over time. The application replaces a detailed Google Sheets tracker with a full-featured web interface that provides dashboard views, monthly tracking, and financial analysis capabilities.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Frontend Architecture
- **Framework**: Flask with Jinja2 templating
- **Styling**: Tailwind CSS for responsive design and styling
- **Icons**: Font Awesome for UI icons
- **JavaScript**: Minimal vanilla JavaScript for interactive elements
- **Design Pattern**: Server-side rendering with traditional form submissions

### Backend Architecture
- **Framework**: Flask (Python web framework)
- **Structure**: Modular design with utilities separated into dedicated modules
- **Data Layer**: JSON file-based storage system
- **Business Logic**: Centralized in utility classes (DataManager, PriceFetcher)

### Data Storage
- **Primary Storage**: JSON files in `/data` directory
- **Files Structure**:
  - `networth_2025.json`: Monthly net worth tracking data
  - `investments.json`: Investment platform and holdings data
  - `income_tracker.json`: Yearly income and investment tracking
  - `expenses.json`: Monthly expense tracking
- **Data Persistence**: File-based JSON storage with automatic initialization

## Key Components

### Core Application (`app.py`)
- Main Flask application with route handlers
- Dashboard logic for net worth calculation and display
- Platform color scheme management for consistent UI
- Session management and error handling

### Data Management (`utils/data_manager.py`)
- Handles all data persistence operations
- JSON file management and initialization
- Data retrieval and storage methods
- Automatic directory and file creation

### Price Fetching (`utils/price_fetcher.py`)
- Live price fetching using yfinance library
- Support for stocks and cryptocurrency symbols
- Error handling for missing or invalid symbols
- Multiple price field fallback strategy

### Templates
- **Base Template**: Common navigation and layout structure
- **Dashboard**: Main overview with key metrics and allocations
- **2025 Tracker**: Monthly investment value tracking table
- **Income vs Investments**: Yearly summary analysis
- **Monthly Breakdown**: Detailed monthly income/expense breakdown
- **Investment Manager**: Add and manage investments

## Data Flow

1. **User Request**: User navigates to application routes
2. **Data Retrieval**: DataManager loads relevant JSON data
3. **Price Fetching**: PriceFetcher retrieves live market prices when needed
4. **Processing**: Application calculates metrics, percentages, and summaries
5. **Rendering**: Flask renders templates with processed data
6. **Response**: HTML page delivered to user browser

## External Dependencies

### Python Packages
- **Flask**: Web framework for routing and templating
- **yfinance**: Yahoo Finance API for live price data
- **Standard Library**: os, json, logging, datetime for core functionality

### Frontend Dependencies
- **Tailwind CSS**: CDN-delivered CSS framework
- **Font Awesome**: CDN-delivered icon library

### Investment Platforms Supported
- Degiro
- Trading212 ISA
- EQ (GSK shares)
- InvestEngine ISA
- Crypto
- HL Stocks & Shares LISA
- Cash

## Deployment Strategy

### Current Setup
- **Entry Point**: `main.py` runs Flask development server
- **Configuration**: Environment-based secret key management
- **Debug Mode**: Enabled for development with hot reload
- **Host Configuration**: Configured for `0.0.0.0:5000` for Replit compatibility

### File Structure
- Static assets in `/static` directory
- Templates in `/templates` directory
- Data files in `/data` directory (auto-created)
- Utility modules in `/utils` directory

### Development Considerations
- JSON file-based storage suitable for prototyping and small-scale usage
- Automatic data file initialization prevents startup errors
- Modular design allows for easy extension and maintenance
- Color-coded platform system for consistent UI experience

The application is designed to be a comprehensive personal finance tracker that can handle multiple investment platforms, track net worth over time, and provide detailed financial analysis through various dashboard views.