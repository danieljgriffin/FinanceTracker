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
- **USD to GBP currency conversion** for US stocks
- **Custom web scraping** for 4 specific HL LISA funds (GB00BYVGKV59, LU1033663649, LU0345781172, GB00BMN91T34)
- **Multi-source fallback** (Yahoo Finance, Hargreaves Lansdown, FT Markets, cached prices)
- **Pence to pounds conversion** for UK funds
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
- HL Stocks & Shares LISA (with specialized fund price fetching)
- Cash

## Recent Changes (July 17, 2025)
- **Complete Mobile Responsiveness**: Implemented comprehensive mobile-first design for iPhone 13 Pro Max compatibility
  - **Mobile Navigation**: Hidden sidebar on mobile with hamburger menu overlay system
  - **Responsive Grid Layouts**: All grid layouts now stack properly on mobile devices
  - **Mobile-Optimized Typography**: Responsive font sizes (text-2xl sm:text-3xl lg:text-4xl)
  - **Touch-Friendly Interactions**: Minimum 44px touch targets for all buttons and interactive elements
  - **Horizontal Scrolling Tables**: Tables now scroll horizontally on mobile with proper touch support
  - **Flexible Button Layouts**: All button groups now wrap and stack appropriately on mobile
  - **Mobile-Specific CSS**: Added CSS media queries for mobile-specific styling and touch interactions
  - **Responsive Spacing**: All padding and margins now use responsive classes (px-4 sm:px-6 lg:px-8)
  - **Mobile Form Optimization**: Form inputs use 16px font size to prevent iOS zoom, proper mobile spacing
- **Fixed Sidebar Navigation**: Removed collapsible sidebar functionality per user preference
  - **Stable Layout**: Reverted to fixed 288px width sidebar for consistent navigation
  - **No Animation Complexity**: Eliminated toggle functionality for cleaner user experience
  - **Reliable Positioning**: All content areas maintain fixed margins (ml-72)
- **Income vs Investments Totals Fix**: Corrected broken totals calculation in yearly tracker
  - **JavaScript Calculation**: Replaced broken Jinja template calculation with dynamic JavaScript
  - **Real-time Updates**: Totals update automatically when editing income or investment values
  - **Proper Summation**: All years from 2017-2030 correctly included in totals calculation
  - **Page Load Calculation**: Totals display correct values immediately on page load
- **Comprehensive Rounded Corners Implementation**: Applied consistent rounded styling to all UI elements
  - **All Cards**: Every card throughout the application uses rounded-xl (16px) corners
  - **Form Elements**: All input fields, buttons, and selects use rounded-lg (12px) styling
  - **Modal and Alerts**: All popups and notifications use rounded-2xl (16px) corners
  - **Table Containers**: All table wrappers use rounded-xl (12px) corners
  - **Universal Coverage**: CSS rules with !important ensure no element has straight corners
  - **Button Styling**: All buttons (submit, cancel, action) have consistent rounded corners
  - **Input Fields**: All text inputs, number inputs, and select dropdowns have rounded corners
- **Automatic Price Refresh System**: Implemented background price updates for real-time data
  - **Background Updates**: Prices refresh automatically every 15 minutes using background threads
  - **Price Status Display**: Shows last refresh time and next update countdown on dashboard and investment manager
  - **API Endpoint**: `/api/price-status` provides real-time price update information
  - **JavaScript Integration**: Auto-refresh price status every 30 seconds without page reload
  - **Manual Override**: "Update Prices" button still works for immediate refresh
- **Income vs Investments Integration**: Moved income tracking to yearly tracker page
  - **Navigation Update**: Removed "Income vs Investments" from navigation menu
  - **Yearly Tracker Addition**: Added comprehensive income table below monthly net worth tracker
  - **Years Coverage**: Sep-Dec 2017 row plus full years 2018-2025 for complete tracking
  - **Editable Interface**: Click-to-edit income and investment amounts with save functionality
  - **Persistent Display**: Income table shows regardless of selected year in dropdown
  - **Automatic Calculations**: Live percentage calculations for % of income invested
  - **Backend Integration**: New `/update-income-data` endpoint for saving changes
- **Left Sidebar Navigation**: Modern fintech-style navigation with enhanced user experience
  - **Layout**: Fixed left sidebar navigation (288px wide) with main content adjusted accordingly
  - **Active States**: Grey background highlighting for selected navigation items with blue accent
  - **Icon Integration**: Font Awesome icons for each navigation item (dashboard, tracker, etc.)
  - **Improved Spacing**: More space per navigation item for better readability
  - **Visual Hierarchy**: Clear logo area with gradient icon and enhanced button styling
- **Rounded Corner Design**: Complete UI modernization with rounded corners throughout
  - **Cards**: All cards now use 16px border radius (rounded-xl) for modern appearance
  - **Buttons**: All buttons use 12px radius (rounded-xl) with gradient backgrounds
  - **Form Elements**: Input fields, selects, and textareas use 12px radius
  - **Progress Bars**: Full rounded progress bars with smooth transitions
  - **Tables**: Rounded table containers with proper overflow handling
  - **Modals**: 16px radius for modal dialogs with enhanced backdrop blur
- **Dark Mode Liquid Glass UI**: Complete visual overhaul with dark theme and liquid glass effects
  - **Background**: Multi-layered dark gradient background (slate-900 to slate-800)
  - **Card Styling**: Transparent liquid glass cards with subtle borders and backdrop blur
  - **Navigation**: Left sidebar with glass morphism effect and smooth transitions
  - **Text Colors**: Updated all text to white/gray for dark mode compatibility
  - **Progress Bars**: Dark-themed progress bars with improved contrast
- **Performance Optimizations**: Significant speed improvements across the application
  - **Dashboard**: Optimized platform allocation calculations using list comprehensions
  - **Investment Manager**: Streamlined data processing and reduced redundant calculations
  - **Yearly Tracker**: Reduced initial year creation overhead
  - **Font Awesome**: Updated to version 6.4.0 for better icon loading
- **Month-on-Month Calculation Fix**: Corrected dashboard month-on-month calculation
  - **Proper Logic**: Now compares current live net worth against current month's 1st day value
  - **Dynamic Month Detection**: Automatically detects current month (July 2025)
  - **Accurate Percentage**: Shows true month-to-date performance change
- **Dynamic Arrow Icons**: Fixed yearly net worth icons to match month-on-month styling
  - **Positive**: Green background with up arrow (fa-arrow-up)
  - **Negative**: Red background with down arrow (fa-arrow-down)
  - **Neutral**: Gray background with minus icon (fa-minus)
  - **Consistent Design**: Both metrics now use identical visual patterns

## Recent Changes (July 16, 2025) - Previous
- **Yearly Tracker System**: Completely redesigned 2025 tracker into a comprehensive yearly tracking system
  - **Multi-Year Support**: Can now track 2023, 2024, 2025 and create new years (e.g., 2026)
  - **Enhanced Data Structure**: Monthly tracking with both 1st of month and 31st December entries
  - **Platform-Based Tracking**: Track total platform values (investments + cash) instead of individual investments
  - **Month-on-Month Calculations**: Automatic percentage change calculations between months
  - **Year Management**: Easy year selection, creation, and navigation interface
  - **Editable Interface**: Click-to-edit monthly values with automatic save functionality
- **Dashboard Improvement**: Replaced "Active Platforms" metric with "Yearly Net Worth Increase"
  - **Intelligent Calculation**: Compares current year vs previous year end values
  - **Fallback Logic**: Uses latest available month data if December 31st not available
  - **Visual Indicators**: Color-coded display (green for gains, red for losses) with trending icons
- **Data Manager Enhancements**: Added multi-year support with automatic file management
  - **Flexible Data Storage**: Separate JSON files for each year (networth_2023.json, networth_2024.json, etc.)
  - **Automatic Initialization**: Creates missing year files when needed
  - **Historical Data Support**: Ready for importing 2023 and 2024 historical data
- **Navigation Updates**: Updated navigation to point to new "Yearly Tracker" instead of "2025 Tracker"
- **Backward Compatibility**: Old /tracker-2025 route redirects to new yearly tracker system
- **Fixed Edit/Delete Functionality**: Investment edit and delete buttons now fully functional
- **Enhanced Price Fetching**: Added USD to GBP currency conversion for all US stocks
- **HL LISA Fund Support**: Custom web scraping for 4 specific funds that don't work with yfinance
- **Live Price Updates**: Successfully fetching real-time prices for all 4 HL LISA funds
- **Transaction History**: Complete audit trail of all investment changes with timestamps
- **Flexible Input Options**: Support for both "Amount Spent" and "Average Buy Price" input methods
- **Currency Conversion Fix**: Corrected USD to GBP conversion logic (META: $702.75 → £524.62)
- **UBS Fund Price Fix**: Fixed UBS S&P 500 to use web scraping (correct price: £2.1106 vs incorrect £0.81)
- **All HL LISA Funds Updated**: Added symbols and live prices for all 4 funds:
  - Baillie Gifford: GB00BYVGKV59 (£3.5510)
  - Fidelity Global Technology: LU1033663649 (£9.3340)
  - Ninety One Natural Resources: LU0345781172 (£48.2400)
  - UBS S&P 500: GB00BMN91T34 (£2.1106)
- **Investment Manager Display Fix**: Resolved template iteration errors and display issues
- **Platform Total Calculation Fix**: Fixed platform totals to properly include both investment values and cash balances
- **Cash Balance Integration**: Successfully integrated cash tracking with investment totals (e.g., HL LISA: £27,903.88 total)
- **Template Optimization**: Moved complex calculations from Jinja2 templates to backend route for better reliability
- **Backend Platform Totals**: Implemented server-side calculation of platform totals for accurate display:
  - HL LISA: £27,903.88 (£27,546.88 investments + £357.00 cash)
  - Degiro: £2,098.11 (META investment value)
  - All other platforms showing appropriate totals or £0.00 when empty
- **Total P/L Display Fix**: Removed £ symbol from Total P/L column to fix alignment issues
  - Values now display as "+1,024.95" instead of "£+1,024.95"
  - Improved readability and consistent alignment for all profit/loss values
- **GSK and Haleon Share Price Fix**: Added pence-to-pounds conversion for UK stocks
  - GSK.L: Correctly displays £14.2150 (converted from 1421.5 pence)
  - HLN.L: Correctly displays £3.6000 (converted from 360.0 pence)
  - Added automatic detection of Yahoo Finance "GBp" currency code for UK stocks
  - EQ platform now shows correct total: £6,139.50 (GSK £5,970.30 + Haleon £169.20)
- **Platform Totals Implementation**: Added comprehensive platform summary rows at bottom of each platform
  - Shows total investment value (excluding cash), total amount spent, percentage P/L, and total P/L
  - Backend calculation ensures accurate totals (e.g., EQ: £6,139.50 total, £1,796.81 spent, +241.69% P/L)
  - Visually distinguished with gray background and bold formatting for easy identification
- **Automatic Price Fetching**: Implemented live price fetching when investments are added
  - Automatically fetches current price when symbol is provided during investment creation
  - Fixed price update error handling to skip invalid data structures
  - European ETFs require correct suffixes (e.g., VUSA.L for London Stock Exchange)
  - Success messages include live price information when available
- **Enhanced Decimal Precision**: Increased holdings precision to support 7 decimal places
  - Input fields now accept step="0.0000001" for precise share quantities
  - Display format updated to show 7 decimal places (e.g., 15.5521236 shares)
  - Both add and edit investment forms support high-precision holdings input
- **Improved Currency Conversion Logic**: Enhanced price fetching with robust currency detection
  - USD stocks automatically convert to GBP using live exchange rates
  - UK stocks (*.L) correctly convert from pence (GBp) to pounds (÷100)
  - Fixed Rolls-Royce (RR.L) pricing: correct symbol now shows £9.88 vs incorrect £1.38
  - Enhanced currency detection supports GBp, GBX, pence variations for UK stocks
  - Stocks already in GBP remain unchanged to prevent double conversion
- **Platform-Specific Symbol Handling**: Automatic symbol correction for UK/European platforms
  - InvestEngine ISA, Degiro, Trading212 ISA, HL LISA automatically add .L suffix
  - Fixed InvestEngine ISA live prices: VUAG.L (£88.25), CNX1.L (£967.00), IITU.L (£27.51)
  - System tries .L suffix first, falls back to original symbol if needed
  - Automatic price fetching works for all platforms when adding new investments
- **Unlimited Decimal Precision**: Fixed decimal input limitations in holdings fields
  - Changed from step="0.0000001" to step="any" for unlimited precision
  - Both add investment and edit investment forms now support any decimal precision
  - Successfully tested with 0.15146765 holdings value
  - Resolves browser validation issues that prevented precise decimal input
- **CoinGecko Integration**: Implemented proper cryptocurrency price fetching
  - Added comprehensive CoinGecko API integration with 40+ cryptocurrency mappings
  - Crypto prices now fetched directly in GBP from CoinGecko API
  - Includes rate limiting protection with retry mechanisms and exponential backoff
  - Fallback to Yahoo Finance if CoinGecko fails
  - Fixed crypto pricing: BTC (£89,071), ETH (£2,491.80), SOL (£129.02), FET (£0.58), TRX (£0.23)
  - Total crypto portfolio value accurately calculated at £22,615.41

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