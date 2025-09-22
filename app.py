import os
import logging
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, make_response
from flask_sqlalchemy import SQLAlchemy
from utils.price_fetcher import PriceFetcher
from utils.device_detector import get_template_path, is_mobile_device
from utils.platform_connector import platform_connector
from utils.intelligent_price_router import price_router
from datetime import datetime, timedelta
import pytz
import json
import threading
import time

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# Tasks blueprint will be imported later to avoid circular imports

# Configure logging
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET")
if not app.secret_key:
    raise ValueError("SESSION_SECRET environment variable is required for secure session management")
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_recycle': 300,
    'pool_pre_ping': True,
}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
from models import db, Goal
db.init_app(app)

# Initialize utilities with caching
price_fetcher = PriceFetcher()

# Add simple price cache for performance - DISABLED TO ENSURE FRESH DATA
price_cache = {}
CACHE_DURATION = 0  # Disabled: was 300 (5 minutes) - now always fresh data

# Global variable to track last price update
last_price_update = None

# Global variable to track last historical data collection
last_historical_collection = None

# Initialize data manager
from utils.db_data_manager import DatabaseDataManager
from datetime import timedelta

def get_data_manager():
    """Get data manager instance (lazy initialization)"""
    return DatabaseDataManager()

def get_last_update_utc():
    """Get the last price update time in UTC"""
    global last_price_update
    if last_price_update:
        return last_price_update
    return None

def ensure_recent_prices():
    """Ensure prices are recent (within 5 minutes) for better user experience"""
    MAX_AGE = timedelta(minutes=5)  # Reduced from 20 to 5 minutes for fresher data
    last_update = get_last_update_utc()
    
    if not last_update or datetime.now() - last_update > MAX_AGE:
        logging.info("Prices are stale, triggering immediate update")
        # Synchronous update to ensure fresh data on page load
        update_all_prices()
        return True
    return False

def ensure_recent_historical_data():
    """Ensure historical data has been collected recently - only at clean BST intervals"""
    MAX_AGE = timedelta(minutes=20)
    global last_historical_collection
    
    if not last_historical_collection or datetime.now() - last_historical_collection > MAX_AGE:
        # Check if we're at a clean BST 15-minute interval before collecting
        import pytz
        uk_tz = pytz.timezone('Europe/London')
        uk_now = datetime.now().astimezone(uk_tz)
        current_minute = uk_now.minute
        
        if current_minute in [0, 15, 30, 45]:
            logging.info(f"Historical data is stale, collecting at valid BST interval ({uk_now.strftime('%H:%M')})")
            collect_historical_data()
            return True
        else:
            logging.info(f"Historical data is stale but not at valid BST interval ({uk_now.strftime('%H:%M')}), waiting for next collection time")
            return False
    return False

def prepare_mobile_chart_data(data_manager):
    """Prepare chart data for mobile dashboard using real monthly data"""
    try:
        chart_data = {}
        
        # Get current live portfolio value
        current_live_value = calculate_current_net_worth()
        current_month = datetime.now().month
        current_year = datetime.now().year
        
        # Get data for all available years
        available_years = [2023, 2024, 2025]
        all_months_data = []
        
        for year in available_years:
            try:
                year_data = data_manager.get_networth_data(year)
                
                # Process each month's data - check both 1st and 31st entries
                months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                         'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
                
                for i, month in enumerate(months):
                    # Try 1st of month first, then 31st/30th if needed
                    month_keys = [f'1st {month}', f'31st {month}']
                    if month in ['Apr', 'Jun', 'Sep', 'Nov']:
                        month_keys.append(f'30th {month}')
                    if month == 'Feb':
                        month_keys.extend([f'28th {month}', f'29th {month}'])
                    
                    total = 0
                    found_data = False
                    
                    for month_key in month_keys:
                        if month_key in year_data:
                            month_data = year_data[month_key]
                            
                            # Calculate total for this month
                            for platform, value in month_data.items():
                                if platform != 'total_net_worth' and isinstance(value, (int, float)):
                                    total += value
                            
                            if total > 0:
                                found_data = True
                                break
                    
                    if found_data:
                        all_months_data.append({
                            'year': year,
                            'month': i + 1,
                            'month_name': month,
                            'value': total,
                            'date': f"{year}-{i+1:02d}-01",
                            'is_historical': True
                        })
                
                # Add current live value as endpoint for current year
                if year == current_year and current_month <= 12:
                    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
                    all_months_data.append({
                        'year': current_year,
                        'month': current_month,
                        'month_name': month_names[current_month - 1],
                        'value': current_live_value,
                        'date': f"{current_year}-{current_month:02d}-01",
                        'is_historical': False,
                        'is_current': True
                    })
            except Exception as e:
                logging.error(f"Error processing year {year}: {str(e)}")
                continue
        
        if not all_months_data:
            return {}
        
        # Sort by date
        all_months_data.sort(key=lambda x: x['date'])
        
        # Generate chart data for MAX view (all years)
        max_points = []
        max_labels = []
        
        # Use all data points for MAX view to show smooth curve with all monthly data
        max_data = all_months_data
        
        if max_data:
            min_val = min(d['value'] for d in max_data)
            max_val = max(d['value'] for d in max_data)
            value_range = max_val - min_val
            
            # Track years already added to avoid duplicates
            years_added = set()
            
            for i, data_point in enumerate(max_data):
                # Calculate position (20-340 width to leave margin, 40-200 height range)
                x = 20 + int((i / (len(max_data) - 1)) * 320) if len(max_data) > 1 else 180
                
                # Fix Y scaling to align properly with the right axis labels
                if value_range > 0:
                    y = 40 + int(((max_val - data_point['value']) / value_range) * 160)
                else:
                    y = 120
                    
                max_points.append(f"{x},{y}")
                
                # Add year labels only once per year, positioned at January of each year
                if data_point['year'] not in years_added and data_point['month'] == 1:
                    max_labels.append({'x': x, 'text': str(data_point['year'])})
                    years_added.add(data_point['year'])
        
        chart_data['MAX'] = {
            'line': ' '.join(max_points),
            'xLabels': max_labels,
            'yLabels': generate_y_labels(min_val, max_val) if max_data else [],
            'hasCurrentValue': True  # MAX view always has current value
        }
        
        # Generate data for individual years
        for year in available_years:
            year_data = [d for d in all_months_data if d['year'] == year]
            if year_data:
                year_points = []
                year_labels = []
                
                min_val = min(d['value'] for d in year_data)
                max_val = max(d['value'] for d in year_data)
                value_range = max_val - min_val
                
                # Create month positions map
                month_positions = {}
                max_month_with_data = 0
                for data_point in year_data:
                    month_positions[data_point['month']] = data_point
                    max_month_with_data = max(max_month_with_data, data_point['month'])
                
                # For current year, limit to months with actual data + current month
                if year == current_year:
                    month_range = max_month_with_data
                else:
                    month_range = 12  # Full year for historical years
                
                # Generate points and labels only for months with data
                month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                              'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
                
                for month_num in range(1, month_range + 1):
                    if month_num in month_positions:
                        # Calculate X position with margins (20-340 range)
                        x = 20 + int(((month_num - 1) / (month_range - 1)) * 320) if month_range > 1 else 180
                        
                        # Calculate Y position with proper scaling (40-200 range)
                        data_point = month_positions[month_num]
                        if value_range > 0:
                            y = 40 + int(((max_val - data_point['value']) / value_range) * 160)
                        else:
                            y = 120
                        year_points.append(f"{x},{y}")
                        
                        # Add month label
                        label_text = month_names[month_num - 1]
                        if data_point.get('is_current'):
                            label_text += '*'  # Mark current month
                        year_labels.append({'x': x, 'text': label_text})
                
                chart_data[str(year)] = {
                    'line': ' '.join(year_points),
                    'xLabels': year_labels,
                    'yLabels': generate_y_labels(min_val, max_val),
                    'hasCurrentValue': any(d.get('is_current', False) for d in year_data)
                }
        
        return chart_data
        
    except Exception as e:
        logging.error(f"Error preparing mobile chart data: {str(e)}")
        return {}

def sample_data_by_interval(data_list, hours):
    """Sample historical data to get roughly one point per interval"""
    if not data_list:
        return []
    
    from datetime import timedelta
    
    sampled_data = []
    last_sampled_time = None
    interval = timedelta(hours=hours)
    
    for data_point in data_list:
        if last_sampled_time is None or (data_point.timestamp - last_sampled_time) >= interval:
            sampled_data.append(data_point)
            last_sampled_time = data_point.timestamp
    
    # Always include the last data point
    if data_list and data_list[-1] not in sampled_data:
        sampled_data.append(data_list[-1])
    
    return sampled_data

def cleanup_old_historical_data():
    """Clean up old high-frequency data based on tiered retention policy"""
    try:
        from models import HistoricalNetWorth, db
        from datetime import datetime, timedelta
        
        now = datetime.now()
        
        # Delete data older than 24 hours that's more frequent than 6-hour intervals
        cutoff_24h = now - timedelta(days=1)
        cutoff_7d = now - timedelta(days=7)
        
        # Get data older than 24 hours but newer than 7 days
        recent_old_data = db.session.query(HistoricalNetWorth)\
            .filter(HistoricalNetWorth.timestamp < cutoff_24h)\
            .filter(HistoricalNetWorth.timestamp >= cutoff_7d)\
            .order_by(HistoricalNetWorth.timestamp.asc())\
            .all()
        
        # Keep only data that's roughly 6 hours apart
        if recent_old_data:
            to_keep = sample_data_by_interval(recent_old_data, hours=6)
            to_keep_ids = [item.id for item in to_keep]
            
            # Delete the rest
            db.session.query(HistoricalNetWorth)\
                .filter(HistoricalNetWorth.timestamp < cutoff_24h)\
                .filter(HistoricalNetWorth.timestamp >= cutoff_7d)\
                .filter(~HistoricalNetWorth.id.in_(to_keep_ids))\
                .delete(synchronize_session=False)
        
        # For data older than 7 days, keep only 12-hour intervals
        old_data = db.session.query(HistoricalNetWorth)\
            .filter(HistoricalNetWorth.timestamp < cutoff_7d)\
            .order_by(HistoricalNetWorth.timestamp.asc())\
            .all()
        
        if old_data:
            to_keep = sample_data_by_interval(old_data, hours=12)
            to_keep_ids = [item.id for item in to_keep]
            
            # Delete the rest
            db.session.query(HistoricalNetWorth)\
                .filter(HistoricalNetWorth.timestamp < cutoff_7d)\
                .filter(~HistoricalNetWorth.id.in_(to_keep_ids))\
                .delete(synchronize_session=False)
        
        db.session.commit()
        logging.info("Historical data cleanup completed")
        
    except Exception as e:
        logging.error(f"Error cleaning up historical data: {str(e)}")
        db.session.rollback()

def generate_y_labels(min_val, max_val):
    """Generate appropriate Y-axis labels for the chart with proper alignment"""
    try:
        value_range = max_val - min_val
        step = value_range / 8  # 8 intervals = 9 labels
        
        labels = []
        for i in range(9):  # 9 labels total (0 to 8)
            value = max_val - (i * step)
            # Y position should match the chart's 40-200 range
            y_pos = 40 + (i * 20)  # Aligned with chart scaling (40-200 range)
            
            if value >= 1000:
                text = f"£{value/1000:.0f}k"
            else:
                text = f"£{value:.0f}"
                
            labels.append({'y': y_pos, 'text': text})
        
        return labels
    except:
        return []

# Create database tables
with app.app_context():
    # Import models after app context is established
    from models import Investment, PlatformCash, NetworthEntry, Expense, MonthlyCommitment, IncomeData, MonthlyBreakdown
    # Import API platform models to ensure their tables are created
    from utils.api_platform_models import Platform, APIHolding, BankBalance, PriceCache, SyncLog
    db.create_all()
    
    # Initialize defaults for database
    data_manager = get_data_manager()
    get_data_manager().initialize_defaults()

# Price refresh settings
PRICE_REFRESH_INTERVAL = 900  # 15 minutes in seconds

# PWA Routes
@app.route("/manifest.webmanifest")
def manifest():
    return send_from_directory("static", "manifest.webmanifest",
                               mimetype="application/manifest+json")

@app.route("/service-worker.js")
def sw():
    return send_from_directory("static", "service-worker.js",
                               mimetype="application/javascript")

@app.route("/apple-touch-icon.png")
def apple_touch_icon():
    return send_from_directory("static", "apple-touch-icon.png",
                               mimetype="image/png")

@app.route('/static/icons/<path:filename>')
def app_icons(filename):
    return send_from_directory('static/icons', filename)

@app.route('/health')
def health_check():
    """Health check endpoint for external monitoring services to prevent app sleeping"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'app': 'investment-tracker'
    })
last_price_update = None
price_update_thread = None

def calculate_platform_totals():
    """Calculate total value for each platform - SINGLE SOURCE OF TRUTH"""
    try:
        # Force fresh database session every time to eliminate stale data
        from app import db
        db.session.expire_all()
        
        data_manager = get_data_manager()
        investments_data = data_manager.get_investments_data()
        
        platform_totals = {}
        
        for platform, investments in investments_data.items():
            if platform.endswith('_cash'):
                continue  # Skip cash keys
                
            platform_total = 0
            
            # Calculate investment values (skip for Cash platform since it has no investments)
            if platform != 'Cash':
                platform_total = sum(
                    investment.get('holdings', 0) * investment.get('current_price', 0)
                    for investment in investments
                )
            
            # Add cash balance for this platform
            platform_total += data_manager.get_platform_cash(platform)
            
            
            # Only include platforms with value
            if platform_total > 0:
                platform_totals[platform] = platform_total
        
        return platform_totals
    except Exception as e:
        logging.error(f"Error calculating platform totals: {str(e)}")
        return {}

def calculate_current_net_worth():
    """Calculate current net worth by summing all platform totals"""
    platform_totals = calculate_platform_totals()
    return sum(platform_totals.values())

# Investment platform color scheme
PLATFORM_COLORS = {
    'Degiro': '#1d4ed8',  # Strong Blue
    'Trading212 ISA': '#0d9488',  # Teal Blue
    'EQ (GSK shares)': '#dc2626',  # Red
    'InvestEngine ISA': '#f97316',  # Orange
    'Crypto': '#8b5cf6',  # Purple
    'HL Stocks & Shares LISA': '#60a5fa',  # Light Blue
    'Cash': '#10b981'  # Green
}

def calculate_dashboard_analytics(data_manager, networth_data, investments_data):
    """Calculate comprehensive dashboard analytics for command center"""
    try:
        analytics = {}
        
        # Calculate 12-month net worth trend data
        analytics['twelve_month_trend'] = calculate_twelve_month_trend(data_manager)
        
        # Calculate top movers (biggest gainers/losers)
        analytics['top_movers'] = calculate_top_movers(investments_data)
        
        # Calculate total cash across all platforms
        analytics['total_cash'] = calculate_total_cash_summary(data_manager)
        
        # Calculate daily P/L (if we have yesterday's data)
        analytics['daily_pl'] = calculate_daily_pl(data_manager)
        
        # Generate alerts for dashboard
        analytics['alerts'] = generate_dashboard_alerts(data_manager, investments_data)
        
        return analytics
    except Exception as e:
        logging.error(f"Error calculating dashboard analytics: {str(e)}")
        return {
            'twelve_month_trend': [],
            'top_movers': {'gainers': [], 'losers': []},
            'total_cash': 0,
            'daily_pl': {'amount': 0, 'percent': 0},
            'alerts': []
        }

def calculate_twelve_month_trend(data_manager):
    """Calculate 12-month net worth trend for chart with robust data fetching"""
    try:
        trend_data = []
        current_date = datetime.now()
        month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        
        # Cache yearly data to avoid multiple calls
        yearly_data_cache = {}
        
        # Get data for the last 12 months
        for i in range(12, 0, -1):
            target_date = current_date - timedelta(days=30 * i)
            year = target_date.year
            month_name_base = month_names[target_date.month - 1]
            
            # Get historical data for this year (with caching)
            if year not in yearly_data_cache:
                yearly_data_cache[year] = data_manager.get_networth_data(year)
            year_data = yearly_data_cache[year]
            
            # Try multiple date formats (robust fallback like existing code)
            month_data = {}
            for day_prefix in ['1st', '31st', '30th', '29th', '28th']:
                month_key = f"{day_prefix} {month_name_base}"
                if month_key in year_data:
                    month_data = year_data[month_key]
                    break
            
            # Calculate total net worth for this month
            total_networth = 0
            for platform, value in month_data.items():
                if isinstance(value, (int, float)):
                    total_networth += value
            
            if total_networth > 0:
                trend_data.append({
                    'month': month_name_base,
                    'year': year,
                    'value': total_networth,
                    'date': target_date.strftime('%Y-%m')
                })
        
        # Add current month with live data
        current_networth = calculate_current_net_worth()
        if current_networth > 0:
            trend_data.append({
                'month': month_names[current_date.month - 1],
                'year': current_date.year,
                'value': current_networth,
                'date': current_date.strftime('%Y-%m'),
                'is_current': True
            })
        
        return trend_data
    except Exception as e:
        logging.error(f"Error calculating 12-month trend: {str(e)}")
        return []

def calculate_top_movers(investments_data):
    """Calculate biggest gainers and losers by value and percentage"""
    try:
        movers = []
        
        for platform, investments in investments_data.items():
            if platform.endswith('_cash') or platform == 'Cash':
                continue
                
            if isinstance(investments, list):
                for investment in investments:
                    holdings = investment.get('holdings', 0)
                    current_price = investment.get('current_price', 0)
                    current_value = holdings * current_price
                    
                    # Calculate daily change if we have purchase price or previous price
                    daily_change_amount = 0
                    daily_change_percent = 0
                    
                    # For now, use a simple calculation - in future we could track daily prices
                    purchase_price = investment.get('purchase_price', current_price)
                    if purchase_price > 0 and purchase_price != current_price:
                        total_change_amount = (current_price - purchase_price) * holdings
                        total_change_percent = ((current_price - purchase_price) / purchase_price) * 100
                        
                        movers.append({
                            'symbol': investment.get('symbol', investment.get('name', 'Unknown')),
                            'name': investment.get('name', investment.get('symbol', 'Unknown')),
                            'platform': platform,
                            'current_value': current_value,
                            'change_amount': total_change_amount,
                            'change_percent': total_change_percent,
                            'holdings': holdings,
                            'current_price': current_price
                        })
        
        # Sort by absolute change amount
        movers.sort(key=lambda x: abs(x['change_amount']), reverse=True)
        
        # Get top 5 gainers and losers
        gainers = [m for m in movers if m['change_amount'] > 0][:5]
        losers = [m for m in movers if m['change_amount'] < 0][:5]
        
        return {'gainers': gainers, 'losers': losers}
    except Exception as e:
        logging.error(f"Error calculating top movers: {str(e)}")
        return {'gainers': [], 'losers': []}

def calculate_total_cash_summary(data_manager):
    """Calculate total cash across all platforms"""
    try:
        total_cash = 0
        platform_cash = {}
        
        investments_data = data_manager.get_investments_data()
        for platform in investments_data.keys():
            if not platform.endswith('_cash'):
                cash_amount = data_manager.get_platform_cash(platform)
                if cash_amount > 0:
                    platform_cash[platform] = cash_amount
                    total_cash += cash_amount
        
        return {
            'total': total_cash,
            'by_platform': platform_cash
        }
    except Exception as e:
        logging.error(f"Error calculating cash summary: {str(e)}")
        return {'total': 0, 'by_platform': {}}

def calculate_daily_pl(data_manager):
    """Calculate daily profit/loss"""
    try:
        # For now, return zero - in future we could track daily snapshots
        return {'amount': 0, 'percent': 0}
    except Exception as e:
        logging.error(f"Error calculating daily P/L: {str(e)}")
        return {'amount': 0, 'percent': 0}

def generate_dashboard_alerts(data_manager, investments_data):
    """Generate alerts for stale data, issues, etc."""
    try:
        alerts = []
        
        # Check for stale price data
        global last_price_update
        if last_price_update:
            hours_since_update = (datetime.now() - last_price_update).total_seconds() / 3600
            if hours_since_update > 6:  # Alert if prices are more than 6 hours old
                alerts.append({
                    'type': 'warning',
                    'message': f'Price data is {int(hours_since_update)} hours old',
                    'action': 'refresh_prices'
                })
        
        # Check for zero-value investments (potential data issues)
        for platform, investments in investments_data.items():
            if isinstance(investments, list):
                for investment in investments:
                    if investment.get('current_price', 0) <= 0:
                        alerts.append({
                            'type': 'error',
                            'message': f'No price data for {investment.get("symbol", "investment")} on {platform}',
                            'action': 'check_investment'
                        })
        
        return alerts[:5]  # Limit to 5 most important alerts
    except Exception as e:
        logging.error(f"Error generating alerts: {str(e)}")
        return []


@app.route('/api/platform-breakdown')
def api_platform_breakdown():
    """API endpoint for platform breakdown data"""
    try:
        # Force database session refresh
        from app import db
        db.session.expire_all()
        
        # Get platform data
        platform_allocations = calculate_platform_totals()
        current_net_worth = sum(platform_allocations.values())
        
        # Calculate monthly changes for each platform (same logic as dashboard)
        platform_monthly_changes = {}
        try:
            current_year = datetime.now().year
            current_month = datetime.now().month
            
            # Get current year's data for monthly comparison
            data_manager = get_data_manager()
            networth_data = data_manager.get_networth_data(current_year)
            
            month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            current_month_name = f"1st {month_names[current_month - 1]}"
            
            month_start_data = networth_data.get(current_month_name, {})
            
            for platform, current_value in platform_allocations.items():
                try:
                    month_start_platform_value = month_start_data.get(platform, 0)
                    
                    if isinstance(month_start_platform_value, (int, float)) and month_start_platform_value > 0:
                        change_amount = current_value - month_start_platform_value
                        change_percent = (change_amount / month_start_platform_value) * 100
                        platform_monthly_changes[platform] = {
                            'amount': change_amount,
                            'percent': change_percent,
                            'previous': month_start_platform_value
                        }
                    else:
                        platform_monthly_changes[platform] = {
                            'amount': 0,
                            'percent': 0,
                            'previous': 0
                        }
                except Exception as platform_error:
                    logging.error(f"Error calculating change for {platform}: {str(platform_error)}")
                    platform_monthly_changes[platform] = {
                        'amount': 0,
                        'percent': 0,
                        'previous': 0
                    }
        except Exception as e:
            logging.error(f"Error calculating platform monthly changes: {str(e)}")
            platform_monthly_changes = {}
        
        # Sort platforms by value (highest to lowest)
        sorted_platforms = []
        cash_value = platform_allocations.pop('Cash', 0)  # Remove cash from main sorting
        
        # Sort non-cash platforms by value (descending)
        for platform, value in sorted(platform_allocations.items(), key=lambda x: x[1], reverse=True):
            change_data = platform_monthly_changes.get(platform, {'amount': 0, 'percent': 0})
            sorted_platforms.append({
                'name': platform,
                'value': value,
                'percentage': (value / current_net_worth) * 100 if current_net_worth > 0 else 0,
                'change_amount': change_data['amount'],
                'change_percent': change_data['percent']
            })
        
        # Add cash at the end if it exists
        if cash_value > 0:
            change_data = platform_monthly_changes.get('Cash', {'amount': 0, 'percent': 0})
            sorted_platforms.append({
                'name': 'Cash',
                'value': cash_value,
                'percentage': (cash_value / current_net_worth) * 100 if current_net_worth > 0 else 0,
                'change_amount': change_data['amount'],
                'change_percent': change_data['percent']
            })
        
        response = make_response(jsonify({
            'platforms': sorted_platforms,
            'total_net_worth': current_net_worth
        }))
        
        # Force fresh API data, disable all caching
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        
        return response
        
    except Exception as e:
        logging.error(f"Error in platform breakdown API: {str(e)}")
        return jsonify({'error': 'Failed to load platform breakdown data'}), 500

@app.route('/api/dashboard-chart-data')
def dashboard_chart_data():
    """API endpoint for dashboard chart data with time period filtering"""
    try:
        period = request.args.get('period', '1Y')  # Default to 1 year
        now = datetime.now()
        chart_data = []
        
        # Use collection system for shorter periods, monthly tracker for longer periods
        if period in ['24H', '1W', '1M', '3M']:
            from models import HistoricalNetWorth, db
            
            if period == '24H':
                # 15-minute intervals for last 24 hours
                cutoff = now - timedelta(days=1)
                historical_data = db.session.query(HistoricalNetWorth)\
                    .filter(HistoricalNetWorth.timestamp >= cutoff)\
                    .order_by(HistoricalNetWorth.timestamp.asc())\
                    .all()
                # Use raw data (already at 15-min intervals)
                
            elif period == '1W':
                # 6-hour intervals for last week
                cutoff = now - timedelta(days=7)
                all_data = db.session.query(HistoricalNetWorth)\
                    .filter(HistoricalNetWorth.timestamp >= cutoff)\
                    .order_by(HistoricalNetWorth.timestamp.asc())\
                    .all()
                # Sample every 6 hours
                historical_data = sample_data_by_interval(all_data, hours=6)
                
            elif period == '1M':
                # End-of-day intervals for last month
                cutoff = now - timedelta(days=30)
                all_data = db.session.query(HistoricalNetWorth)\
                    .filter(HistoricalNetWorth.timestamp >= cutoff)\
                    .order_by(HistoricalNetWorth.timestamp.asc())\
                    .all()
                # Sample every 24 hours (end of day)
                historical_data = sample_data_by_interval(all_data, hours=24)
                
            elif period == '3M':
                # End-of-day intervals for last 3 months
                cutoff = now - timedelta(days=90)
                all_data = db.session.query(HistoricalNetWorth)\
                    .filter(HistoricalNetWorth.timestamp >= cutoff)\
                    .order_by(HistoricalNetWorth.timestamp.asc())\
                    .all()
                # Sample every 24 hours (end of day)
                historical_data = sample_data_by_interval(all_data, hours=24)
            
            # Convert historical data to chart format
            for data_point in historical_data:
                chart_data.append({
                    'date': data_point.timestamp.isoformat(),
                    'value': data_point.net_worth,
                    'label': data_point.timestamp.strftime('%d %b %Y %H:%M')
                })
        
        else:
            # Use monthly tracker for longer periods (6M, 1Y, Max)
            from models import NetworthEntry
            entries = NetworthEntry.query.filter(NetworthEntry.year >= 2023).order_by(NetworthEntry.year, NetworthEntry.created_at).all()
            
            # Convert to chart format
            for entry in entries:
                # Parse month string to get approximate date
                month_parts = entry.month.split(' ')
                if len(month_parts) >= 2:
                    month_name = month_parts[1]
                    month_map = {'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                                'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12}
                    
                    if month_name in month_map:
                        # Create date (use 1st for beginning of month, 31st for end of month)
                        is_month_end = '31st' in entry.month or '30th' in entry.month or '28th' in entry.month or '29th' in entry.month
                        day = 28 if is_month_end else 1  # Use 28 to avoid month overflow issues
                        
                        try:
                            date_obj = datetime(entry.year, month_map[month_name], day)
                            chart_data.append({
                                'date': date_obj.isoformat(),
                                'value': entry.total_networth,
                                'label': f"{month_name} {entry.year}"
                            })
                        except ValueError:
                            continue
            
            # Filter by period for longer timeframes
            if period != 'Max':
                if period == '6M':
                    cutoff = now - timedelta(days=180)
                elif period == '1Y':
                    cutoff = now - timedelta(days=365)
                else:
                    cutoff = now - timedelta(days=365)  # Default to 1Y
                
                chart_data = [d for d in chart_data if datetime.fromisoformat(d['date']) >= cutoff]
        
        return jsonify(chart_data)
    
    except Exception as e:
        logging.error(f"Error getting chart data: {str(e)}")
        return jsonify([])

@app.route('/')
def home():
    """Clean black theme dashboard showing essential net worth metrics"""
    # Ensure data is fresh when users visit
    ensure_recent_prices()
    
    try:
        # Force database session refresh to ensure fresh data on every page load
        from app import db
        db.session.expire_all()
        
        # Get last price update time
        global last_price_update
        investments_data = get_data_manager().get_investments_data()
        if not last_price_update:
            # Check if we have any investment with last_updated timestamp
            for platform, investments in investments_data.items():
                if not platform.endswith('_cash') and isinstance(investments, list):
                    for investment in investments:
                        if investment.get('last_updated'):
                            try:
                                update_time = datetime.fromisoformat(investment['last_updated'])
                                if not last_price_update or update_time > last_price_update:
                                    last_price_update = update_time
                            except:
                                pass
        
        # Use the unified calculation - SINGLE SOURCE OF TRUTH
        platform_allocations = calculate_platform_totals()
        current_net_worth = sum(platform_allocations.values())
        
        # Calculate month-on-month change using networth_entries for current month's 1st day data
        mom_change = 0
        mom_amount_change = 0
        try:
            current_date = datetime.now()
            current_year = current_date.year
            current_month = current_date.month
            
            # Map month number to month name
            month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            current_month_name = f"1st {month_names[current_month - 1]}"
            
            # Get current year's data from networth_entries
            current_year_data = get_data_manager().get_networth_data(current_year)
            
            # Try to get current month's 1st day data first
            month_start_data = current_year_data.get(current_month_name, {})
            month_start_baseline = 0
            
            if month_start_data:
                # Use the stored total_networth from the NetworthEntry
                from models import NetworthEntry
                month_entry = NetworthEntry.query.filter_by(year=current_year, month=current_month_name).first()
                if month_entry and month_entry.total_networth:
                    month_start_baseline = month_entry.total_networth
                    logging.info(f"Found {current_month_name} baseline from networth_entries: £{month_start_baseline}")
                else:
                    # Fallback: calculate from platform data if total_networth not available
                    for platform, value in month_start_data.items():
                        if platform != 'total_net_worth' and isinstance(value, (int, float)):
                            month_start_baseline += value
                    logging.info(f"Calculated {current_month_name} baseline from platform data: £{month_start_baseline}")
            else:
                # If no data for current month, use most recent available month
                for i in range(current_month - 2, -1, -1):  # Start from previous month
                    fallback_month_name = f"1st {month_names[i]}"
                    fallback_data = current_year_data.get(fallback_month_name, {})
                    if fallback_data:
                        # Try to get stored total first
                        month_entry = NetworthEntry.query.filter_by(year=current_year, month=fallback_month_name).first()
                        if month_entry and month_entry.total_networth:
                            month_start_baseline = month_entry.total_networth
                        else:
                            # Calculate from platform data
                            for platform, value in fallback_data.items():
                                if platform != 'total_net_worth' and isinstance(value, (int, float)):
                                    month_start_baseline += value
                        logging.info(f"Using fallback baseline from {fallback_month_name}: £{month_start_baseline}")
                        break
            
            # Calculate changes
            if month_start_baseline > 0:
                mom_amount_change = current_net_worth - month_start_baseline
                mom_change = (mom_amount_change / month_start_baseline) * 100
                logging.info(f"Monthly calculation - Current: £{current_net_worth}, Baseline: £{month_start_baseline}, Change: £{mom_amount_change} ({mom_change:.2f}%)")
            
        except Exception as e:
            logging.error(f"Error calculating month-on-month change in dashboard_v2: {str(e)}")
            mom_change = 0
            mom_amount_change = 0
        
        # Calculate yearly net worth increase (current live portfolio vs 1st Jan current year)
        yearly_increase = 0
        yearly_amount_change = 0
        try:
            current_year = datetime.now().year
            
            # Get current year's 1st January data
            current_year_data = get_data_manager().get_networth_data(current_year)
            jan_total = 0
            
            # Get 1st Jan data
            jan_data = current_year_data.get('1st Jan', {})
            
            # Calculate January total
            for platform, value in jan_data.items():
                if platform != 'total_net_worth' and isinstance(value, (int, float)):
                    jan_total += value
            
            # Calculate changes
            if jan_total > 0:
                yearly_amount_change = current_net_worth - jan_total
                yearly_increase = (yearly_amount_change / jan_total) * 100
            
        except Exception as e:
            logging.error(f"Error calculating yearly increase: {str(e)}")
            yearly_increase = 0
            yearly_amount_change = 0

        # Sort platform allocations by value (high to low, with cash at bottom)
        sorted_platforms = []
        cash_value = platform_allocations.pop('Cash', 0)  # Remove cash from main sorting
        
        # Sort non-cash platforms by value (descending)
        for platform, value in sorted(platform_allocations.items(), key=lambda x: x[1], reverse=True):
            sorted_platforms.append((platform, value))
        
        # Always add cash at the bottom if it exists
        if cash_value > 0:
            sorted_platforms.append(('Cash', cash_value))
        
        # Rebuild platform_allocations in sorted order
        platform_allocations = dict(sorted_platforms)
        
        # Calculate percentage allocations
        total_allocation = sum(platform_allocations.values())
        platform_percentages = {}
        if total_allocation > 0:
            for platform, amount in platform_allocations.items():
                platform_percentages[platform] = (amount / total_allocation) * 100
        
        # Calculate platform-specific monthly changes (needed for mobile template)
        platform_monthly_changes = {}
        try:
            current_date = datetime.now()
            current_year = current_date.year
            current_month = current_date.month
            month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            current_month_name = f"1st {month_names[current_month - 1]}"
            
            # Get current year's data
            current_year_data = get_data_manager().get_networth_data(current_year)
            month_start_data = current_year_data.get(current_month_name, {})
            
            # If no current month data, use previous month
            if not month_start_data and current_month > 1:
                fallback_month_name = f"1st {month_names[current_month - 2]}"
                month_start_data = current_year_data.get(fallback_month_name, {})
            
            # Calculate platform-specific changes
            for platform in platform_allocations.keys():
                current_value = platform_allocations.get(platform, 0)
                baseline_value = month_start_data.get(platform, 0)
                
                amount_change = current_value - baseline_value
                percent_change = 0
                if baseline_value > 0:
                    percent_change = (amount_change / baseline_value) * 100
                
                platform_monthly_changes[platform] = {
                    'amount': amount_change,
                    'percent': percent_change
                }
        
        except Exception as e:
            logging.error(f"Error calculating platform monthly changes: {str(e)}")
            # Initialize empty platform changes
            for platform in platform_allocations.keys():
                platform_monthly_changes[platform] = {'amount': 0, 'percent': 0}

        # Get next financial target - closest to current day
        next_target = None
        progress_info = None
        upcoming_targets = []
        try:
            from models import Goal
            today = datetime.now().date()
            # Get all active goals and find the closest one to today (future or current)
            active_goals = Goal.query.filter_by(status='active').order_by(Goal.target_date.asc()).all()
            if active_goals:
                # Find the closest goal to today's date
                next_target = min(active_goals, key=lambda g: abs((g.target_date - today).days))
                
                # Get upcoming targets (next 2-3 after the current target)
                current_target_index = active_goals.index(next_target)
                upcoming_targets = active_goals[current_target_index + 1:current_target_index + 4]  # Next 3 targets
                
                # Calculate progress
                remaining_amount = next_target.target_amount - current_net_worth
                progress_percentage = min((current_net_worth / next_target.target_amount) * 100, 100)
                
                # Calculate time remaining
                today = datetime.now().date()
                target_date = next_target.target_date
                days_remaining = (target_date - today).days
                
                progress_info = {
                    'remaining_amount': max(0, remaining_amount),
                    'progress_percentage': progress_percentage,
                    'days_remaining': max(0, days_remaining),
                    'is_achieved': current_net_worth >= next_target.target_amount
                }
        except Exception as e:
            logging.error(f"Error calculating next target: {str(e)}")
        
        # Create response with no-cache headers - use device detection for template
        template_path = get_template_path('dashboard_v2.html')
        response = make_response(render_template(template_path, 
                             current_net_worth=current_net_worth,
                             platform_allocations=platform_allocations,
                             platform_percentages=platform_percentages,
                             platform_monthly_changes=platform_monthly_changes,
                             mom_change=mom_change,
                             mom_amount_change=mom_amount_change,
                             yearly_increase=yearly_increase,
                             yearly_amount_change=yearly_amount_change,
                             platform_colors=PLATFORM_COLORS,
                             current_date=datetime.now().strftime('%B %d, %Y'),
                             today=datetime.now(),
                             last_price_update=last_price_update,
                             next_target=next_target,
                             progress_info=progress_info,
                             upcoming_targets=upcoming_targets))
        
        # Force fresh content, disable all caching
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache' 
        response.headers['Expires'] = '0'
        return response
    
    except Exception as e:
        logging.error(f"Error in dashboard_v2: {str(e)}")
        # Return error fallback - use device detection for template
        template_path = get_template_path('dashboard_v2.html')
        response = make_response(render_template(template_path, 
                             current_net_worth=0,
                             platform_allocations={},
                             platform_percentages={},
                             platform_monthly_changes={},
                             mom_change=0,
                             mom_amount_change=0,
                             yearly_increase=0,
                             yearly_amount_change=0,
                             platform_colors=PLATFORM_COLORS,
                             current_date=datetime.now().strftime('%B %d, %Y'),
                             today=datetime.now(),
                             last_price_update=None,
                             next_target=None,
                             progress_info=None,
                             upcoming_targets=[]))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache' 
        response.headers['Expires'] = '0'
        return response

@app.route('/mobile')
def mobile_dashboard():
    """Mobile-only dashboard with Trading212-style interface"""
    # Ensure data is fresh when mobile users visit
    ensure_recent_prices()
    # Note: Historical data collection only happens at scheduled times (:00, :15, :30, :45)
    
    try:
        # Force database session refresh to ensure fresh data on every page load
        from app import db
        db.session.expire_all()
        
        # Get current net worth data
        data_manager = get_data_manager()
        networth_data = get_data_manager().get_networth_data()
        investments_data = get_data_manager().get_investments_data()
        
        # Use the unified calculation - SINGLE SOURCE OF TRUTH
        platform_allocations = calculate_platform_totals()
        current_net_worth = sum(platform_allocations.values())
        
        # Sort platform allocations by value (high to low, with cash at bottom)
        sorted_platforms = []
        cash_value = platform_allocations.pop('Cash', 0)  # Remove cash from main sorting
        
        # Sort non-cash platforms by value (descending)
        for platform, value in sorted(platform_allocations.items(), key=lambda x: x[1], reverse=True):
            sorted_platforms.append((platform, value))
        
        # Always add cash at the bottom if it exists
        if cash_value > 0:
            sorted_platforms.append(('Cash', cash_value))
        
        # Rebuild platform_allocations in sorted order
        platform_allocations = dict(sorted_platforms)
        
        # Calculate percentage allocations
        total_allocation = sum(platform_allocations.values())
        platform_percentages = {}
        if total_allocation > 0:
            for platform, amount in platform_allocations.items():
                platform_percentages[platform] = (amount / total_allocation) * 100
        
        # Calculate month-on-month change and platform-specific changes
        mom_change = 0
        mom_amount_change = 0
        platform_monthly_changes = {}
        
        try:
            current_year = datetime.now().year
            current_month = datetime.now().month
            
            # Map month number to month name
            month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            current_month_name = f"1st {month_names[current_month - 1]}"
            
            # Get current year's data
            current_year_data = get_data_manager().get_networth_data(current_year)
            
            # Get current month's 1st day data
            month_start_data = current_year_data.get(current_month_name, {})
            month_start_total = 0
            
            # Calculate month start total
            for platform, value in month_start_data.items():
                if platform != 'total_net_worth' and isinstance(value, (int, float)):
                    month_start_total += value
            
            # Calculate overall portfolio changes
            if month_start_total > 0:
                mom_amount_change = current_net_worth - month_start_total
                mom_change = (mom_amount_change / month_start_total) * 100
            
            # Calculate platform-specific monthly changes
            for platform in platform_allocations.keys():
                try:
                    current_platform_value = platform_allocations[platform]
                    month_start_platform_value = month_start_data.get(platform, 0)
                    
                    if month_start_platform_value > 0:
                        platform_change_amount = current_platform_value - month_start_platform_value
                        platform_change_percent = (platform_change_amount / month_start_platform_value) * 100
                        platform_monthly_changes[platform] = {
                            'amount': platform_change_amount,
                            'percent': platform_change_percent
                        }
                    else:
                        platform_monthly_changes[platform] = {
                            'amount': 0,
                            'percent': 0
                        }
                except Exception as platform_error:
                    logging.error(f"Error calculating change for {platform}: {str(platform_error)}")
                    platform_monthly_changes[platform] = {
                        'amount': 0,
                        'percent': 0
                    }
            
        except Exception as e:
            logging.error(f"Error calculating month-on-month change: {str(e)}")
            mom_change = 0
            mom_amount_change = 0
            platform_monthly_changes = {}
        
        # Calculate year-over-year change (same year comparison, Jan 1st to current)
        yoy_amount_change = 0
        yoy_percentage_change = 0
        try:
            # Get January 1st data for current year
            jan_first_data = current_year_data.get("1st Jan", {})
            jan_first_total = 0
            
            # Calculate January 1st total
            for platform, value in jan_first_data.items():
                if platform != 'total_net_worth' and isinstance(value, (int, float)):
                    jan_first_total += value
            
            # Calculate year-to-date changes
            if jan_first_total > 0:
                yoy_amount_change = current_net_worth - jan_first_total
                yoy_percentage_change = (yoy_amount_change / jan_first_total) * 100
            
        except Exception as e:
            logging.error(f"Error calculating year-over-year change: {str(e)}")
            yoy_amount_change = 0
            yoy_percentage_change = 0
        
        # Prepare chart data for different time ranges
        chart_data = prepare_mobile_chart_data(data_manager)
        
        # Get last updated time from global variable and convert to BST
        global last_price_update
        last_updated_bst = None
        if last_price_update:
            bst = pytz.timezone('Europe/London')
            last_updated_bst = last_price_update.replace(tzinfo=pytz.UTC).astimezone(bst)
        
        # Create response with no-cache headers for mobile
        response = make_response(render_template('mobile/dashboard.html', 
                             current_net_worth=current_net_worth,
                             platform_allocations=platform_allocations,
                             platform_percentages=platform_percentages,
                             platform_monthly_changes=platform_monthly_changes,
                             mom_change=mom_change,
                             mom_amount_change=mom_amount_change,
                             yoy_amount_change=yoy_amount_change,
                             yoy_percentage_change=yoy_percentage_change,
                             platform_colors=PLATFORM_COLORS,
                             current_date=datetime.now().strftime('%B %d, %Y'),
                             today=datetime.now(),
                             chart_data=chart_data,
                             last_updated=last_updated_bst))
        
        # Force fresh content, disable all caching for mobile
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache' 
        response.headers['Expires'] = '0'
        return response
    except Exception as e:
        logging.error(f"Error in mobile dashboard: {str(e)}")
        response = make_response(render_template('mobile/dashboard.html', 
                             current_net_worth=0,
                             platform_allocations={},
                             platform_percentages={},
                             platform_monthly_changes={},
                             mom_change=0,
                             mom_amount_change=0,
                             yoy_amount_change=0,
                             yoy_percentage_change=0,
                             platform_colors=PLATFORM_COLORS,
                             current_date=datetime.now().strftime('%B %d, %Y'),
                             today=datetime.now(),
                             chart_data={}))
        # Force fresh content even in error case
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache' 
        response.headers['Expires'] = '0'
        return response

@app.route('/mobile-info')
def mobile_info():
    """Information page about the mobile app"""
    return render_template('mobile_info.html')

@app.route('/mobile/investments')
def mobile_investments():
    """Mobile investments page with full functionality"""
    try:
        investments_data = get_data_manager().get_investments_data()
        
        # Calculate totals and metrics from live data - optimized
        total_current_value = 0
        total_amount_spent = 0
        platform_totals = {}
        platform_colors = PLATFORM_COLORS
        
        # Get platform totals using unified calculation
        platform_totals_dict = calculate_platform_totals()
        
        for platform, platform_investments in investments_data.items():
            if platform.endswith('_cash'):
                continue  # Skip cash keys
            
            # Get the total from our unified calculation instead of recalculating
            platform_total_value = platform_totals_dict.get(platform, 0)
            platform_investment_total = platform_total_value - get_data_manager().get_platform_cash(platform)
            platform_amount_spent = sum(
                investment.get('amount_spent', 0)
                for investment in platform_investments
            )
            
            total_current_value += platform_investment_total
            total_amount_spent += platform_amount_spent
            
            # Add cash to platform total (but don't sum for total_cash)
            cash_balance = get_data_manager().get_platform_cash(platform)
            platform_total_value = platform_investment_total + cash_balance
            
            # Calculate P/L metrics for this platform
            platform_pl = platform_investment_total - platform_amount_spent
            platform_percentage_pl = (platform_pl / platform_amount_spent * 100) if platform_amount_spent > 0 else 0
            
            platform_totals[platform] = {
                'total_value': platform_total_value,
                'investment_value': platform_investment_total,
                'amount_spent': platform_amount_spent,
                'total_pl': platform_pl,
                'percentage_pl': platform_percentage_pl,
                'cash_balance': cash_balance
            }
        
        # Get bank account cash (Cash platform only)
        bank_account_cash = get_data_manager().get_platform_cash('Cash')
        
        # Use consistent net worth calculation (same as other pages) - moved earlier to avoid scoping issue
        current_net_worth = calculate_current_net_worth()
        
        # Calculate overall portfolio metrics using consistent method (same as desktop)
        total_portfolio_pl = current_net_worth - total_amount_spent  # Total portfolio gain vs amount spent
        total_portfolio_percentage_pl = (total_portfolio_pl / total_amount_spent * 100) if total_amount_spent > 0 else 0
        
        # Calculate month-on-month platform changes
        platform_monthly_changes = {}
        try:
            current_year = datetime.now().year
            current_month = datetime.now().month
            
            month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            current_month_name = f"1st {month_names[current_month - 1]}"
            
            current_year_data = get_data_manager().get_networth_data(current_year)
            month_start_data = current_year_data.get(current_month_name, {})
            
            for platform in platform_totals.keys():
                try:
                    current_platform_value = platform_totals[platform]['total_value']
                    month_start_platform_value = month_start_data.get(platform, 0)
                    
                    if month_start_platform_value > 0:
                        platform_change_amount = current_platform_value - month_start_platform_value
                        platform_change_percent = (platform_change_amount / month_start_platform_value) * 100
                        platform_monthly_changes[platform] = {
                            'amount': platform_change_amount,
                            'percent': platform_change_percent
                        }
                    else:
                        platform_monthly_changes[platform] = {'amount': 0, 'percent': 0}
                except Exception as platform_error:
                    logging.error(f"Error calculating change for {platform}: {str(platform_error)}")
                    platform_monthly_changes[platform] = {'amount': 0, 'percent': 0}
        except Exception as e:
            logging.error(f"Error calculating monthly changes: {str(e)}")
        
        # Sort platforms by highest to lowest total value
        sorted_platforms = sorted(platform_totals.items(), key=lambda x: x[1]['total_value'], reverse=True)
        sorted_investments_data = {platform: investments_data[platform] for platform, _ in sorted_platforms if platform in investments_data}
        sorted_platform_totals = {platform: totals for platform, totals in sorted_platforms}
        
        # Get unique investment names for dropdown
        unique_names = get_data_manager().get_unique_investment_names()
        
        return render_template('mobile/investments.html',
                             investments_data=sorted_investments_data,
                             total_current_value=total_current_value or 0,
                             total_amount_spent=total_amount_spent or 0,
                             bank_account_cash=bank_account_cash or 0,
                             current_net_worth=current_net_worth or 0,
                             total_portfolio_pl=total_portfolio_pl or 0,
                             total_portfolio_percentage_pl=total_portfolio_percentage_pl or 0,
                             platform_totals=sorted_platform_totals or {},
                             platform_colors=platform_colors,
                             platform_monthly_changes=platform_monthly_changes or {},
                             unique_names=unique_names or [],
                             data_manager=get_data_manager())
    
    except Exception as e:
        logging.error(f"Error in mobile investments: {str(e)}")
        flash(f'Error loading investments: {str(e)}', 'error')
        return render_template('mobile/investments.html', 
                             investments_data={}, 
                             total_current_value=0,
                             total_amount_spent=0, 
                             bank_account_cash=0, 
                             current_net_worth=0,
                             total_portfolio_pl=0,
                             total_portfolio_percentage_pl=0,
                             platform_totals={},
                             platform_colors=PLATFORM_COLORS,
                             platform_monthly_changes={},
                             unique_names=[],
                             data_manager=get_data_manager())

@app.route('/mobile/goals')
def mobile_goals():
    """Mobile goals page"""
    return render_template('mobile/goals.html')

@app.route('/mobile/monthly')
def mobile_monthly():
    """Mobile monthly breakdown page"""
    return render_template('mobile/monthly.html')

@app.route('/mobile/tracker')
def mobile_tracker():
    """Mobile tracker page"""
    return render_template('mobile/tracker.html')

@app.route('/yearly-tracker')
@app.route('/yearly-tracker/<int:year>')
def yearly_tracker(year=None):
    """Yearly tracker page with support for multiple years"""
    try:
        # Get available years and set default - optimized
        available_years = get_data_manager().get_available_years()
        if not available_years:
            available_years = [2025]  # Start with current year only
        
        # Use current year or default to 2025
        if year is None:
            year = 2025
        
        # Ensure the requested year exists
        if year not in available_years:
            get_data_manager().create_new_year(year)
            available_years = get_data_manager().get_available_years()
        
        networth_data = get_data_manager().get_networth_data(year)
        investments_data = get_data_manager().get_investments_data()
        
        # Define months with both 1st and 31st entries for some months
        months = [
            '1st Jan', '1st Feb', '1st Mar', '1st Apr', '1st May', '1st Jun',
            '1st Jul', '1st Aug', '1st Sep', '1st Oct', '1st Nov', '1st Dec', '31st Dec'
        ]
        
        # Get all platforms (including cash)
        all_platforms = []
        for platform, investments in investments_data.items():
            if not platform.endswith('_cash'):
                all_platforms.append({
                    'name': platform,
                    'color': PLATFORM_COLORS.get(platform, '#6b7280')
                })
        
        # Calculate monthly totals and month-on-month changes
        monthly_totals = {}
        monthly_changes = {}
        previous_total = 0
        
        # Get December 1st data from previous year for first month comparison
        previous_year_december_total = 0
        if year > 2017:  # Only try to get previous year data if not the earliest year
            try:
                previous_year_data = get_data_manager().get_networth_data(year - 1)
                december_data = previous_year_data.get('1st Dec', {})
                
                for platform in all_platforms:
                    platform_value = december_data.get(platform['name'], 0)
                    if platform_value and isinstance(platform_value, (int, float)):
                        previous_year_december_total += platform_value
                        
            except Exception as e:
                logging.error(f"Error getting previous year data: {e}")
                previous_year_december_total = 0
        
        for month in months:
            month_data = networth_data.get(month, {})
            total = 0
            
            for platform in all_platforms:
                platform_value = month_data.get(platform['name'], 0)
                if platform_value and isinstance(platform_value, (int, float)):
                    total += platform_value
            
            monthly_totals[month] = total
            
            # Calculate month-on-month change
            if total > 0:
                # For first month (1st Jan), compare against previous year's 1st Dec
                if month == '1st Jan' and previous_year_december_total > 0:
                    change_percent = ((total - previous_year_december_total) / previous_year_december_total) * 100
                    monthly_changes[month] = change_percent
                # For all other months, compare against previous month
                elif previous_total > 0:
                    change_percent = ((total - previous_total) / previous_total) * 100
                    monthly_changes[month] = change_percent
                else:
                    monthly_changes[month] = None
            else:
                monthly_changes[month] = None
            
            if total > 0:
                previous_total = total
        
        # Calculate yearly net worth increase percentage
        yearly_increase_percent = 0
        current_year_int = datetime.now().year
        
        if year == current_year_int:
            # For current year, compare current net worth to 1st Jan of current year (same as dashboard)
            try:
                # Use the same shared function as dashboard for consistency
                current_net_worth = calculate_current_net_worth()
                
                # Get current year's 1st Jan value (same as dashboard calculation)
                current_year_data = get_data_manager().get_networth_data(year)
                jan_total = 0
                jan_data = current_year_data.get('1st Jan', {})
                
                for platform in all_platforms:
                    platform_value = jan_data.get(platform['name'], 0)
                    if platform_value and isinstance(platform_value, (int, float)):
                        jan_total += platform_value
                
                if jan_total > 0:
                    yearly_increase_percent = ((current_net_worth - jan_total) / jan_total) * 100
                
            except Exception as e:
                logging.error(f"Error calculating live yearly increase: {str(e)}")
                yearly_increase_percent = 0
        else:
            # For historical years, compare 31st Dec to 1st Jan of same year
            jan_total = monthly_totals.get('1st Jan', 0)
            dec_total = monthly_totals.get('31st Dec', 0)
            
            if jan_total > 0 and dec_total > 0:
                yearly_increase_percent = ((dec_total - jan_total) / jan_total) * 100
        
        # Get income data for the income vs investments table
        income_data = get_data_manager().get_income_data()
        
        return render_template('yearly_tracker.html', 
                             networth_data=networth_data,
                             platforms=all_platforms,
                             months=months,
                             monthly_totals=monthly_totals,
                             monthly_changes=monthly_changes,
                             yearly_increase_percent=yearly_increase_percent,
                             current_year=year,
                             available_years=available_years,
                             platform_colors=PLATFORM_COLORS,
                             income_data=income_data)
    except Exception as e:
        logging.error(f"Error in yearly tracker: {str(e)}")
        flash(f'Error loading yearly tracker: {str(e)}', 'error')
        return render_template('yearly_tracker.html', 
                             networth_data={},
                             platforms=[],
                             months=[],
                             monthly_totals={},
                             monthly_changes={},
                             yearly_increase_percent=0,
                             current_year=2025,
                             available_years=[2025],
                             platform_colors=PLATFORM_COLORS,
                             income_data={})

@app.route('/tracker-2025')
def tracker_2025():
    """Redirect to yearly tracker for backward compatibility"""
    return redirect(url_for('yearly_tracker', year=2025))

@app.route('/create-year', methods=['POST'])
def create_year():
    """Create a new year for tracking"""
    try:
        year = int(request.form.get('year'))
        if get_data_manager().create_new_year(year):
            flash(f'Year {year} created successfully', 'success')
        else:
            flash(f'Year {year} already exists', 'warning')
    except (ValueError, TypeError):
        flash('Invalid year format', 'error')
    
    return redirect(url_for('yearly_tracker', year=year))

@app.route('/update-monthly-value', methods=['POST'])
def update_monthly_value():
    """Update monthly networth value(s)"""
    try:
        # Check if it's a batch update
        changes_json = request.form.get('changes')
        if changes_json:
            import json
            changes = json.loads(changes_json)
            year = None
            
            for change in changes:
                change_year = int(change['year'])
                change_month = change['month']
                change_platform = change['platform']
                change_value = float(change['value'])
                
                get_data_manager().update_monthly_networth(change_year, change_month, change_platform, change_value)
                year = change_year  # Store for redirect
            
            flash(f'Updated {len(changes)} values successfully', 'success')
        else:
            # Single update (legacy support)
            year = int(request.form.get('year'))
            month = request.form.get('month')
            platform = request.form.get('platform')
            value = float(request.form.get('value', 0))
            
            get_data_manager().update_monthly_networth(year, month, platform, value)
            flash(f'Updated {platform} for {month} {year}', 'success')
    except (ValueError, TypeError) as e:
        flash(f'Error updating value: {str(e)}', 'error')
    
    return redirect(url_for('yearly_tracker', year=year))


@app.route('/update-income-data', methods=['POST'])
def update_income_data():
    """Update income vs investments data"""
    try:
        changes = json.loads(request.form.get('changes', '[]'))
        income_data = get_data_manager().get_income_data()
        
        for change in changes:
            year = change['year']
            field = change['field']
            value = float(change['value'])
            
            # Initialize year data if it doesn't exist
            if year not in income_data:
                income_data[year] = {}
            
            # Update the specific field
            income_data[year][field] = value
        
        # Save updated data
        get_data_manager().save_income_data(income_data)
        
        flash(f'Updated {len(changes)} income values successfully', 'success')
        return redirect(url_for('yearly_tracker'))
        
    except Exception as e:
        logging.error(f"Error updating income data: {str(e)}")
        flash(f'Error updating income data: {str(e)}', 'error')
        return redirect(url_for('yearly_tracker'))

@app.route('/income-investments')
def income_investments():
    """Income vs Investment tracker"""
    try:
        income_data = get_data_manager().get_income_data()
        monthly_investments = get_data_manager().get_monthly_investments()
        years = list(range(2017, 2026))  # 2017-2025
        
        return render_template('income_investments.html',
                             income_data=income_data,
                             monthly_investments=monthly_investments,
                             years=years)
    except Exception as e:
        logging.error(f"Error in income investments: {str(e)}")
        flash(f'Error loading income vs investments: {str(e)}', 'error')
        return render_template('income_investments.html',
                             income_data={},
                             monthly_investments={},
                             years=[])

@app.route('/add-monthly-investment', methods=['POST'])
def add_monthly_investment():
    """Add monthly investment data"""
    try:
        year = int(request.form.get('year'))
        month = int(request.form.get('month'))
        month_name = request.form.get('month_name')
        income_received = float(request.form.get('income_received', 0))
        amount_invested = float(request.form.get('amount_invested', 0))
        
        get_data_manager().add_monthly_investment(
            year=year,
            month=month, 
            month_name=month_name,
            income_received=income_received,
            amount_invested=amount_invested
        )
        
        flash(f'Added investment data for {month_name} {year}', 'success')
        
    except Exception as e:
        logging.error(f"Error adding monthly investment: {str(e)}")
        flash(f'Error adding monthly investment: {str(e)}', 'error')
    
    return redirect(url_for('income_investments'))

@app.route('/api/chart-data')
def chart_data():
    """API endpoint for chart data with value and invested lines"""
    try:
        chart_data = get_data_manager().get_chart_data_with_invested()
        return jsonify(chart_data)
    except Exception as e:
        logging.error(f"Error generating chart data: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/monthly-breakdown')
def monthly_breakdown():
    """Monthly breakdown page with income, expenses, and investments"""
    try:
        # Get monthly breakdown data
        breakdown_data = get_data_manager().get_monthly_breakdown_data()
        
        # Extract data
        monthly_income = breakdown_data.get('monthly_income', 0)
        monthly_expenses = breakdown_data.get('monthly_expenses', [])
        platform_investments = breakdown_data.get('platform_investments', {})
        
        # Calculate total expenses
        total_monthly_expenses = sum(expense['monthly_amount'] for expense in monthly_expenses)
        
        # Get totals from breakdown data
        total_monthly_investments = breakdown_data.get('total_monthly_investments', 0)
        
        # Calculate free cash
        free_cash_monthly = monthly_income - total_monthly_expenses - total_monthly_investments
        free_cash_annual = free_cash_monthly * 12
        
        return render_template('monthly_breakdown.html',
                             current_month=datetime.now().strftime('%B'),
                             monthly_income=monthly_income,
                             annual_income=monthly_income * 12,
                             monthly_expenses=monthly_expenses,
                             total_monthly_expenses=total_monthly_expenses,
                             total_annual_expenses=total_monthly_expenses * 12,
                             platform_investments=platform_investments,
                             total_monthly_investments=total_monthly_investments,
                             total_annual_investments=total_monthly_investments * 12,
                             free_cash_monthly=free_cash_monthly,
                             free_cash_annual=free_cash_annual,
                             platform_colors=PLATFORM_COLORS)
    except Exception as e:
        logging.error(f"Error in monthly breakdown: {str(e)}")
        flash(f'Error loading monthly breakdown: {str(e)}', 'error')
        return render_template('monthly_breakdown.html',
                             current_month=datetime.now().strftime('%B'),
                             monthly_income=0,
                             annual_income=0,
                             monthly_expenses=[],
                             total_monthly_expenses=0,
                             total_annual_expenses=0,
                             platform_investments={},
                             total_monthly_investments=0,
                             total_annual_investments=0,
                             free_cash_monthly=0,
                             free_cash_annual=0,
                             platform_colors=PLATFORM_COLORS)

@app.route('/investment-manager')
def investment_manager():
    """Investment manager for CRUD operations"""
    try:
        investments_data = get_data_manager().get_investments_data()
        
        # Calculate totals and metrics from live data - optimized
        total_current_value = 0
        total_amount_spent = 0
        total_cash = 0
        platform_totals = {}
        
        # Get platform totals using unified calculation
        platform_totals_dict = calculate_platform_totals()
        
        for platform, platform_investments in investments_data.items():
            if platform.endswith('_cash'):
                continue  # Skip cash keys
            
            # Get the total from our unified calculation instead of recalculating
            platform_total_value = platform_totals_dict.get(platform, 0)
            platform_investment_total = platform_total_value - get_data_manager().get_platform_cash(platform)
            platform_amount_spent = sum(
                investment.get('amount_spent', 0)
                for investment in platform_investments
            )
            
            total_current_value += platform_investment_total
            total_amount_spent += platform_amount_spent
            
            # Add cash to platform total
            cash_balance = get_data_manager().get_platform_cash(platform)
            platform_total_value = platform_investment_total + cash_balance
            total_cash += cash_balance
            
            # Calculate P/L metrics for this platform
            platform_pl = platform_investment_total - platform_amount_spent
            platform_percentage_pl = (platform_pl / platform_amount_spent * 100) if platform_amount_spent > 0 else 0
            
            platform_totals[platform] = {
                'total_value': platform_total_value,
                'investment_value': platform_investment_total,
                'amount_spent': platform_amount_spent,
                'total_pl': platform_pl,
                'percentage_pl': platform_percentage_pl,
                'cash_balance': cash_balance
            }
        
        # Calculate overall portfolio metrics (investments + cash)
        total_portfolio_value = total_current_value + total_cash
        total_portfolio_pl = total_portfolio_value - total_amount_spent  # Total portfolio gain vs amount spent
        total_portfolio_percentage_pl = (total_portfolio_pl / total_amount_spent * 100) if total_amount_spent > 0 else 0
        
        # Get unique investment names for dropdown
        unique_names = get_data_manager().get_unique_investment_names()
        
        # Get investment names by platform for dropdown
        platform_investment_names = data_manager.get_all_investment_names()
        
        return render_template('investment_manager.html',
                             investments_data=investments_data,
                             platform_colors=PLATFORM_COLORS,
                             platform_totals=platform_totals,
                             total_current_value=total_current_value,
                             total_amount_spent=total_amount_spent,
                             total_cash=total_cash,
                             total_portfolio_value=total_portfolio_value,
                             total_portfolio_pl=total_portfolio_pl,
                             total_portfolio_percentage_pl=total_portfolio_percentage_pl,
                             unique_names=unique_names,
                             platform_investment_names=platform_investment_names,
                             data_manager=data_manager,
                             last_price_update=last_price_update)
    except Exception as e:
        logging.error(f"Error in investment manager: {str(e)}")
        flash(f'Error loading investment manager: {str(e)}', 'error')
        return render_template('investment_manager.html',
                             investments_data={},
                             platform_colors=PLATFORM_COLORS,
                             platform_totals={},
                             total_current_value=0,
                             total_amount_spent=0,
                             total_cash=0,
                             total_portfolio_value=0,
                             total_portfolio_pl=0,
                             total_portfolio_percentage_pl=0,
                             unique_names=[],
                             platform_investment_names={},
                             data_manager=data_manager,
                             last_price_update=None)

@app.route('/add-investment', methods=['POST'])
def add_investment():
    """Add new investment"""
    try:
        platform = request.form.get('platform')
        name = request.form.get('name')
        holdings = float(request.form.get('holdings', 0))
        input_type = request.form.get('input_type', 'amount_spent')
        symbol = request.form.get('symbol', '')
        
        if not platform or not name or holdings <= 0:
            flash('Platform, investment name, and holdings are required', 'error')
            return redirect(url_for('investment_manager'))
        
        # Handle different input types
        if input_type == 'amount_spent':
            amount_spent = float(request.form.get('amount_spent', 0))
            if amount_spent <= 0:
                flash('Amount spent must be greater than 0', 'error')
                return redirect(url_for('investment_manager'))
            investment_data = {
                'name': name,
                'holdings': holdings,
                'amount_spent': amount_spent,
                'average_buy_price': amount_spent / holdings if holdings > 0 else 0,
                'symbol': symbol,
                'current_price': 0.0
            }
            get_data_manager().add_investment(platform, investment_data)
        elif input_type == 'average_buy_price':
            average_buy_price = float(request.form.get('average_buy_price', 0))
            if average_buy_price <= 0:
                flash('Average buy price must be greater than 0', 'error')
                return redirect(url_for('investment_manager'))
            investment_data = {
                'name': name,
                'holdings': holdings,
                'amount_spent': average_buy_price * holdings,
                'average_buy_price': average_buy_price,
                'symbol': symbol,
                'current_price': 0.0
            }
            get_data_manager().add_investment(platform, investment_data)
        else:
            flash('Invalid input type', 'error')
            return redirect(url_for('investment_manager'))
        
        # Automatically fetch live price if symbol is provided
        if symbol:
            try:
                # Platform-specific symbol handling
                original_symbol = symbol
                
                # For UK/European platforms, try adding .L suffix if not present
                if platform in ['Degiro', 'InvestEngine ISA', 'Trading212 ISA', 'HL Stocks & Shares LISA']:
                    if not symbol.endswith('.L'):
                        symbol = symbol + '.L'
                
                price = price_fetcher.get_price(symbol)
                
                # If .L suffix didn't work, try original symbol
                if not price and symbol != original_symbol:
                    price = price_fetcher.get_price(original_symbol)
                    symbol = original_symbol
                
                # If legacy price fetcher failed, try intelligent price router
                if not price:
                    try:
                        result = price_router.get_price(symbol)
                        if 'price' in result:
                            price = result['price']
                            logging.info(f"Intelligent router found price for {symbol}: £{price}")
                        else:
                            logging.warning(f"Intelligent router failed for {symbol}: {result.get('error', 'Unknown error')}")
                    except Exception as e:
                        logging.error(f"Error with intelligent router for {symbol}: {str(e)}")
                
                if price:
                    # Update the newly added investment with the current price
                    try:
                        # Find the most recently added investment for this platform and name
                        from models import Investment
                        latest_investment = Investment.query.filter_by(platform=platform, name=name).order_by(Investment.id.desc()).first()
                        
                        if latest_investment:
                            # Update the investment price directly in the database
                            get_data_manager().update_investment_price(latest_investment.id, price)
                            # Also update the symbol if it worked
                            get_data_manager().update_investment(latest_investment.id, {'symbol': symbol})
                            flash(f'Investment {name} added successfully with live price £{price:.4f}', 'success')
                        else:
                            flash(f'Investment {name} added successfully (price update failed)', 'success')
                    except Exception as update_error:
                        logging.error(f"Error updating investment price after adding: {str(update_error)}")
                        flash(f'Investment {name} added successfully (price update failed)', 'success')
                else:
                    flash(f'Investment {name} added successfully (no live price available for {symbol})', 'success')
            except Exception as e:
                logging.error(f"Error fetching price for {symbol}: {str(e)}")
                flash(f'Investment {name} added successfully (price fetch failed)', 'success')
        else:
            flash(f'Investment {name} added successfully', 'success')
        
    except Exception as e:
        logging.error(f"Error adding investment: {str(e)}")
        flash(f'Error adding investment: {str(e)}', 'error')
    
    return redirect(url_for('investment_manager'))

def check_and_complete_goals():
    """Check if any active goals have been achieved and automatically mark them as completed"""
    try:
        from models import Goal, db
        from datetime import datetime
        
        # Get current net worth
        current_net_worth = calculate_current_net_worth()
        
        # Find all active goals that have been achieved
        active_goals = Goal.query.filter_by(status='active').all()
        completed_goals = []
        
        for goal in active_goals:
            if current_net_worth >= goal.target_amount:
                # Goal achieved! Mark as completed
                goal.status = 'completed'
                goal.completed_at = datetime.utcnow()
                completed_goals.append(goal)
                logging.info(f"🎉 Goal automatically completed: '{goal.title}' (£{goal.target_amount:,.0f}) achieved with net worth £{current_net_worth:,.0f}")
        
        if completed_goals:
            db.session.commit()
            logging.info(f"✅ {len(completed_goals)} goal(s) automatically completed")
            
    except Exception as e:
        logging.error(f"Error in automatic goal completion: {str(e)}")
        # Don't re-raise since this shouldn't break the price update process

def update_all_prices():
    """Update live prices for all investments using optimized batch fetching"""
    global last_price_update
    try:
        data_manager = get_data_manager()
        investments_data = data_manager.get_investments_data()
        
        # Collect all symbols to update
        symbols_to_update = []
        symbol_to_investments = {}  # Changed to handle multiple investments per symbol
        
        for platform, investments in investments_data.items():
            # Skip cash platforms and ensure investments is a list
            if platform.endswith('_cash') or not isinstance(investments, list):
                continue
                
            for investment in investments:
                symbol = investment.get('symbol')
                if symbol and investment.get('id'):
                    if symbol not in symbols_to_update:
                        symbols_to_update.append(symbol)
                    
                    # Store all investments for this symbol
                    if symbol not in symbol_to_investments:
                        symbol_to_investments[symbol] = []
                    symbol_to_investments[symbol].append(investment)
        
        if not symbols_to_update:
            logging.info("No symbols to update")
            return 0
        
        # Batch fetch prices for efficiency
        logging.info(f"Batch updating prices for {len(symbols_to_update)} investments")
        updated_prices = price_fetcher.get_multiple_prices(symbols_to_update)
        
        # Use intelligent price router for failed symbols
        failed_symbols = []
        for symbol in symbols_to_update:
            if symbol not in updated_prices:
                failed_symbols.append(symbol)
        
        if failed_symbols:
            logging.info(f"Using intelligent price router for {len(failed_symbols)} failed symbols")
            for symbol in failed_symbols:
                try:
                    result = price_router.get_price(symbol)
                    if 'price' in result:
                        updated_prices[symbol] = result['price']
                        logging.info(f"Intelligent router found price for {symbol}: £{result['price']}")
                    else:
                        logging.warning(f"Intelligent router failed for {symbol}: {result.get('error', 'Unknown error')}")
                except Exception as e:
                    logging.error(f"Error with intelligent router for {symbol}: {str(e)}")
        
        # Update database with fetched prices
        updated_count = 0
        for symbol, price in updated_prices.items():
            if symbol in symbol_to_investments:
                # Update ALL investments with this symbol (across all platforms)
                investments = symbol_to_investments[symbol]
                for investment in investments:
                    try:
                        data_manager.update_investment_price(investment['id'], price)
                        updated_count += 1
                        logging.info(f"Updated {symbol} (ID {investment['id']}, {investment.get('platform', 'unknown')}): £{price}")
                    except Exception as e:
                        logging.error(f"Error updating database for {symbol} ID {investment['id']}: {str(e)}")
        
        global last_price_update
        last_price_update = datetime.now()
        logging.info(f'Background price update completed: {updated_count}/{len(symbols_to_update)} prices updated')
        
        # Check for automatic goal completion after price updates
        try:
            check_and_complete_goals()
        except Exception as e:
            logging.error(f"Error checking goal completion: {str(e)}")
        
        return updated_count
        
    except Exception as e:
        logging.error(f"Error updating prices: {str(e)}")
        return 0

def collect_historical_data():
    """Collect current net worth data for historical tracking every 15 minutes"""
    global last_historical_collection
    try:
        from models import HistoricalNetWorth, db
        import pytz
        
        # Calculate current net worth and platform breakdown
        current_net_worth = calculate_current_net_worth()
        
        # Get platform allocations
        data_manager = get_data_manager()
        investments_data = data_manager.get_investments_data()
        
        platform_breakdown = {}
        for platform, investments in investments_data.items():
            if platform.endswith('_cash'):
                continue
                
            platform_total = 0
            if platform != 'Cash':
                platform_total = sum(
                    investment.get('holdings', 0) * investment.get('current_price', 0)
                    for investment in investments
                )
            
            platform_total += data_manager.get_platform_cash(platform)
            
            if platform_total > 0:
                platform_breakdown[platform] = platform_total
        
        # Use current time for real-time collection every 15 minutes
        now = datetime.now()
        uk_tz = pytz.timezone('Europe/London')
        uk_now = now.astimezone(uk_tz)
        
        # Store historical data point with current timestamp
        historical_entry = HistoricalNetWorth(
            timestamp=uk_now,
            net_worth=current_net_worth,
            platform_breakdown=platform_breakdown
        )
        
        db.session.add(historical_entry)
        db.session.commit()
        
        last_historical_collection = datetime.now()
        logging.info(f"Historical data collected: £{current_net_worth:,.2f} at {uk_now.strftime('%H:%M')}")
        
    except Exception as e:
        logging.error(f"Error collecting historical data: {str(e)}")

def collect_weekly_historical_data():
    """Collect current net worth data for weekly tracking every 6 hours at midnight, 6am, noon, 6pm"""
    try:
        from models import WeeklyHistoricalNetWorth, db
        import pytz
        
        # Calculate current net worth and platform breakdown
        current_net_worth = calculate_current_net_worth()
        
        # Get platform allocations
        data_manager = get_data_manager()
        investments_data = data_manager.get_investments_data()
        
        platform_breakdown = {}
        for platform, investments in investments_data.items():
            if platform.endswith('_cash'):
                continue
                
            platform_total = 0
            if platform != 'Cash':
                platform_total = sum(
                    investment.get('holdings', 0) * investment.get('current_price', 0)
                    for investment in investments
                )
            
            platform_total += data_manager.get_platform_cash(platform)
            
            if platform_total > 0:
                platform_breakdown[platform] = platform_total
        
        # Use current time for weekly collection
        now = datetime.now()
        uk_tz = pytz.timezone('Europe/London')
        uk_now = now.astimezone(uk_tz)
        
        # Store weekly historical data point with current timestamp
        weekly_entry = WeeklyHistoricalNetWorth(
            timestamp=uk_now,
            net_worth=current_net_worth,
            platform_breakdown=platform_breakdown
        )
        
        db.session.add(weekly_entry)
        db.session.commit()
        
        logging.info(f"Weekly historical data collected: £{current_net_worth:,.2f} at {uk_now.strftime('%H:%M')}")
        
    except Exception as e:
        logging.error(f"Error collecting weekly historical data: {str(e)}")

def collect_monthly_historical_data():
    """Collect current net worth data for monthly tracking every 12 hours at midnight and noon"""
    try:
        from models import MonthlyHistoricalNetWorth, db
        import pytz
        
        # Calculate current net worth and platform breakdown
        current_net_worth = calculate_current_net_worth()
        
        # Get platform allocations
        data_manager = get_data_manager()
        investments_data = data_manager.get_investments_data()
        
        platform_breakdown = {}
        for platform, investments in investments_data.items():
            if platform.endswith('_cash'):
                continue
                
            platform_total = 0
            if platform != 'Cash':
                platform_total = sum(
                    investment.get('holdings', 0) * investment.get('current_price', 0)
                    for investment in investments
                )
            
            platform_total += data_manager.get_platform_cash(platform)
            
            if platform_total > 0:
                platform_breakdown[platform] = platform_total
        
        # Use current time for monthly collection
        now = datetime.now()
        uk_tz = pytz.timezone('Europe/London')
        uk_now = now.astimezone(uk_tz)
        
        # Store monthly historical data point with current timestamp
        monthly_entry = MonthlyHistoricalNetWorth(
            timestamp=uk_now,
            net_worth=current_net_worth,
            platform_breakdown=platform_breakdown
        )
        
        db.session.add(monthly_entry)
        db.session.commit()
        
        logging.info(f"Monthly historical data collected: £{current_net_worth:,.2f} at {uk_now.strftime('%H:%M')}")
        
    except Exception as e:
        logging.error(f"Error collecting monthly historical data: {str(e)}")

def collect_daily_historical_data():
    """Collect current net worth data for daily tracking at end of day (midnight)"""
    try:
        from models import DailyHistoricalNetWorth, db
        import pytz
        
        # Calculate current net worth and platform breakdown
        current_net_worth = calculate_current_net_worth()
        
        # Get platform allocations
        data_manager = get_data_manager()
        investments_data = data_manager.get_investments_data()
        
        platform_breakdown = {}
        for platform, investments in investments_data.items():
            if platform.endswith('_cash'):
                continue
                
            platform_total = 0
            if platform != 'Cash':
                platform_total = sum(
                    investment.get('holdings', 0) * investment.get('current_price', 0)
                    for investment in investments
                )
            
            platform_total += data_manager.get_platform_cash(platform)
            
            if platform_total > 0:
                platform_breakdown[platform] = platform_total
        
        # Use current time for daily collection
        now = datetime.now()
        uk_tz = pytz.timezone('Europe/London')
        uk_now = now.astimezone(uk_tz)
        
        # Store daily historical data point with current timestamp
        daily_entry = DailyHistoricalNetWorth(
            timestamp=uk_now,
            net_worth=current_net_worth,
            platform_breakdown=platform_breakdown
        )
        
        db.session.add(daily_entry)
        db.session.commit()
        
        logging.info(f"Daily historical data collected: £{current_net_worth:,.2f} at {uk_now.strftime('%H:%M')}")
        
    except Exception as e:
        logging.error(f"Error collecting daily historical data: {str(e)}")

def auto_populate_monthly_tracker():
    """Automatically populate tracker with current month's data on 1st of month"""
    try:
        import pytz
        
        # Get current date in BST
        uk_tz = pytz.timezone('Europe/London')
        uk_now = datetime.now().astimezone(uk_tz)
        
        year = uk_now.year
        current_month_abbr = uk_now.strftime('%b')
        current_month = f"1st {current_month_abbr}"
        
        # Get current investment data  
        data_manager = get_data_manager()
        investments_data = data_manager.get_investments_data()
        
        # Calculate platform totals (investments + cash)
        platform_totals = {}
        for platform, investments in investments_data.items():
            total_value = 0
            
            if isinstance(investments, list):
                # Calculate investment values
                for investment in investments:
                    if isinstance(investment, dict) and 'holdings' in investment:
                        try:
                            holdings = float(investment.get('holdings', 0))
                            price = float(investment.get('current_price', 0))
                            total_value += holdings * price
                        except (ValueError, TypeError):
                            continue
            
            # Add cash balance
            cash_balance = data_manager.get_platform_cash(platform)
            total_value += cash_balance
            
            if total_value > 0:
                platform_totals[platform] = total_value
        
        # Update monthly values for all platforms
        for platform, value in platform_totals.items():
            data_manager.update_monthly_networth(year, current_month, platform, value)
        
        logging.info(f"Auto-populated tracker: {current_month} {year} with {len(platform_totals)} platforms")
        
    except Exception as e:
        logging.error(f"Error auto-populating monthly tracker: {str(e)}")

def auto_populate_dec31_tracker():
    """Automatically populate tracker with Dec 31st data for year-end"""
    try:
        import pytz
        
        # Get current date in BST
        uk_tz = pytz.timezone('Europe/London')
        uk_now = datetime.now().astimezone(uk_tz)
        
        year = uk_now.year
        dec31_month = "31st Dec"
        
        # Get current investment data
        data_manager = get_data_manager()
        investments_data = data_manager.get_investments_data()
        
        # Calculate platform totals (investments + cash)
        platform_totals = {}
        for platform, investments in investments_data.items():
            total_value = 0
            
            if isinstance(investments, list):
                # Calculate investment values
                for investment in investments:
                    if isinstance(investment, dict) and 'holdings' in investment:
                        try:
                            holdings = float(investment.get('holdings', 0))
                            price = float(investment.get('current_price', 0))
                            total_value += holdings * price
                        except (ValueError, TypeError):
                            continue
            
            # Add cash balance
            cash_balance = data_manager.get_platform_cash(platform)
            total_value += cash_balance
            
            if total_value > 0:
                platform_totals[platform] = total_value
        
        # Update Dec 31st values for all platforms
        for platform, value in platform_totals.items():
            data_manager.update_monthly_networth(year, dec31_month, platform, value)
        
        logging.info(f"Auto-populated tracker: {dec31_month} {year} with {len(platform_totals)} platforms")
        
    except Exception as e:
        logging.error(f"Error auto-populating Dec 31st tracker: {str(e)}")

def background_price_updater():
    """Background thread function to update prices every 15 minutes and collect historical data with smart intervals"""
    global last_historical_collection
    
    # Set initial collection time to trigger first collection
    last_historical_collection = datetime.now() - timedelta(minutes=31)  # Trigger first collection soon
    last_cleanup = datetime.now() - timedelta(days=1)  # Trigger first cleanup
    last_price_update = datetime.now() - timedelta(minutes=16)  # Trigger first price update soon
    
    while True:
        try:
            time.sleep(60)  # Check every minute to catch clean 15-minute intervals
            # Create Flask application context for database access
            with app.app_context():
                now = datetime.now()
                
                # Update prices every 15 minutes
                time_since_price_update = (now - last_price_update).total_seconds() / 60
                if time_since_price_update >= 15:
                    update_all_prices()
                    last_price_update = now
                    logging.info("✅ Price update completed")
                
                
                # Collect historical data at aligned 15-minute intervals (00, 15, 30, 45)
                import pytz
                uk_tz = pytz.timezone('Europe/London')
                uk_now = now.astimezone(uk_tz)
                current_minute = uk_now.minute
                
                # Check if we're on a clean 15-minute boundary for 24-hour data
                is_15min_collection_time = current_minute in [0, 15, 30, 45]
                time_since_last = (now - last_historical_collection).total_seconds() / 60
                
                # Collect only at clean 15-minute intervals and avoid duplicates
                if is_15min_collection_time and time_since_last >= 10:  # 10 min gap to avoid duplicates
                    collect_historical_data()
                    last_historical_collection = now  # Update the last collection time
                    logging.info(f"✅ Historical collection completed at aligned time: {uk_now.strftime('%H:%M:%S')} BST")
                elif is_15min_collection_time:
                    logging.info(f"⏰ Collection time {uk_now.strftime('%H:%M')} BST but too soon since last (wait {10 - time_since_last:.1f} min)")
                else:
                    logging.debug(f"⏳ Not collection time - current minute: {current_minute}, next at: {[x for x in [0,15,30,45] if x > current_minute] or [0]}")
                
                # Check if we're on a 6-hour boundary for weekly data (00:00, 6am, noon, 6pm)
                # Midnight collection at 00:00 for proper end-of-day snapshots
                current_hour = uk_now.hour
                is_6hour_collection_time = (current_hour in [0, 6, 12, 18] and current_minute == 0)
                
                if is_6hour_collection_time:
                    collect_weekly_historical_data()
                    logging.info(f"✅ Weekly historical collection completed at: {uk_now.strftime('%H:%M')} BST")
                
                # Check if we're on a 12-hour boundary for monthly data (00:00, noon)
                # Midnight collection at 00:00 for proper end-of-day snapshots
                is_12hour_collection_time = (current_hour in [0, 12] and current_minute == 0)
                
                if is_12hour_collection_time:
                    collect_monthly_historical_data()
                    logging.info(f"✅ Monthly historical collection completed at: {uk_now.strftime('%H:%M')} BST")
                
                # Check if we're at end of day for daily data (00:00)
                # Midnight collection for proper end-of-day snapshots
                is_daily_collection_time = current_hour == 0 and current_minute == 0
                
                if is_daily_collection_time:
                    collect_daily_historical_data()
                    logging.info(f"✅ Daily historical collection completed at: {uk_now.strftime('%H:%M')} BST")
                
                # Check for monthly tracker auto-population (1st of month at 00:05)
                is_monthly_tracker_time = (uk_now.day == 1 and current_hour == 0 and current_minute == 5)
                
                if is_monthly_tracker_time:
                    auto_populate_monthly_tracker()
                    logging.info(f"✅ Monthly tracker auto-populated at: {uk_now.strftime('%H:%M')} BST")
                
                # Check for December 31st tracker collection (Dec 31st at 23:55)
                is_dec31_tracker_time = (uk_now.month == 12 and uk_now.day == 31 and current_hour == 23 and current_minute == 55)
                
                if is_dec31_tracker_time:
                    auto_populate_dec31_tracker()
                    logging.info(f"✅ Dec 31st tracker auto-populated at: {uk_now.strftime('%H:%M')} BST")
                
                # Clean up old data daily to maintain tiered storage
                if (now - last_cleanup).total_seconds() >= 86400:  # 24 hours
                    cleanup_old_historical_data()
                    last_cleanup = now
                    
        except Exception as e:
            logging.error(f"Error in background price updater: {str(e)}")
            time.sleep(60)  # Wait 1 minute before retrying

@app.route('/update-prices')
def update_prices():
    """Update live prices for all investments - manual trigger"""
    try:
        updated_count = update_all_prices()
        flash(f'Updated prices for {updated_count} investments', 'success')
        
    except Exception as e:
        logging.error(f"Error updating prices: {str(e)}")
        flash(f'Error updating prices: {str(e)}', 'error')
    
    # Debug log the referrer
    referrer = request.referrer
    logging.info(f"Update prices called from: {referrer}")
    
    # Redirect back to the referring page or dashboard if no referer
    if referrer and '/update-prices' not in referrer:
        return redirect(referrer)
    else:
        return redirect(url_for('home'))

@app.route('/manual-collect-data')
def manual_collect_data():
    """Manually trigger historical data collection"""
    try:
        collect_historical_data()
        return jsonify({'status': 'success', 'message': 'Historical data collected successfully'})
    except Exception as e:
        logging.error(f"Error in manual data collection: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/test-weekly-collection', methods=['POST'])
def test_weekly_collection():
    """Manually trigger weekly historical data collection for testing"""
    try:
        collect_weekly_historical_data()
        return jsonify({'status': 'success', 'message': 'Weekly historical data collected successfully'})
    except Exception as e:
        logging.error(f"Error in weekly data collection: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/test-monthly-collection', methods=['POST'])
def test_monthly_collection():
    """Manually trigger monthly historical data collection for testing"""
    try:
        collect_monthly_historical_data()
        return jsonify({'status': 'success', 'message': 'Monthly historical data collected successfully'})
    except Exception as e:
        logging.error(f"Error in monthly data collection: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/test-daily-collection', methods=['POST'])
def test_daily_collection():
    """Manually trigger daily historical data collection for testing"""
    try:
        collect_daily_historical_data()
        return jsonify({'status': 'success', 'message': 'Daily historical data collected successfully'})
    except Exception as e:
        logging.error(f"Error in daily data collection: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/live-values')
def live_values():
    """API endpoint for live value updates with comprehensive dashboard data"""
    # Check for fresh data before serving live values
    ensure_recent_prices()
    
    try:
        # Force database session refresh to ensure API always returns fresh data
        from app import db
        db.session.expire_all()
        
        # Use the unified calculation - SINGLE SOURCE OF TRUTH
        platform_allocations = calculate_platform_totals()
        current_net_worth = sum(platform_allocations.values())
        
        # Calculate month-on-month change (current net worth vs current month's 1st day)
        mom_change = 0
        mom_amount_change = 0
        platform_monthly_changes = {}
        try:
            current_year = datetime.now().year
            current_month = datetime.now().month
            
            # Map month number to month name
            month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            current_month_name = f"1st {month_names[current_month - 1]}"
            
            # Get current year's data
            current_year_data = get_data_manager().get_networth_data(current_year)
            
            # Get current month's 1st day data
            month_start_data = current_year_data.get(current_month_name, {})
            month_start_total = 0
            
            # Calculate month start total
            for platform, value in month_start_data.items():
                if platform != 'total_net_worth' and isinstance(value, (int, float)):
                    month_start_total += value
            
            # Calculate overall changes
            if month_start_total > 0:
                mom_amount_change = current_net_worth - month_start_total
                mom_change = (mom_amount_change / month_start_total) * 100
            
            # Calculate platform-specific monthly changes
            for platform, current_value in platform_allocations.items():
                try:
                    month_start_platform_value = month_start_data.get(platform, 0)
                    
                    if isinstance(month_start_platform_value, (int, float)) and month_start_platform_value > 0:
                        change_amount = current_value - month_start_platform_value
                        change_percent = (change_amount / month_start_platform_value) * 100
                        platform_monthly_changes[platform] = {
                            'amount': change_amount,
                            'percent': change_percent,
                            'previous': month_start_platform_value
                        }
                    else:
                        platform_monthly_changes[platform] = {
                            'amount': 0,
                            'percent': 0,
                            'previous': 0
                        }
                except Exception as platform_error:
                    logging.error(f"Error calculating change for {platform}: {str(platform_error)}")
                    platform_monthly_changes[platform] = {
                        'amount': 0,
                        'percent': 0,
                        'previous': 0
                    }
                    
        except Exception as e:
            logging.error(f"Error calculating month-on-month change: {str(e)}")
            mom_change = 0
            mom_amount_change = 0

        # Calculate yearly net worth increase (current live portfolio vs 1st Jan current year)
        yearly_increase = 0
        yearly_amount_change = 0
        try:
            current_year = datetime.now().year
            
            # Get current year's 1st January data
            current_year_data = get_data_manager().get_networth_data(current_year)
            jan_total = 0
            
            # Get 1st Jan data
            jan_data = current_year_data.get('1st Jan', {})
            
            # Calculate January total
            for platform, value in jan_data.items():
                if platform != 'total_net_worth' and isinstance(value, (int, float)):
                    jan_total += value
            
            # Calculate changes
            if jan_total > 0:
                yearly_amount_change = current_net_worth - jan_total
                yearly_increase = (yearly_amount_change / jan_total) * 100
                
        except Exception as e:
            logging.error(f"Error calculating yearly increase: {str(e)}")
            yearly_increase = 0
            yearly_amount_change = 0
        
        # Calculate platform percentages
        platform_percentages = {}
        if current_net_worth > 0:
            for platform, value in platform_allocations.items():
                platform_percentages[platform] = (value / current_net_worth) * 100

        # Get next financial target - closest to current day
        next_target = None
        progress_info = None
        try:
            today = datetime.now().date()
            # Get all active goals and find the closest one to today (future or current)
            active_goals = Goal.query.filter_by(status='active').order_by(Goal.target_date.asc()).all()
            if active_goals:
                # Find the closest goal to today's date
                next_target = min(active_goals, key=lambda g: abs((g.target_date - today).days))
                
                # Calculate progress
                remaining_amount = next_target.target_amount - current_net_worth
                progress_percentage = min((current_net_worth / next_target.target_amount) * 100, 100)
                
                # Calculate time remaining
                today = datetime.now().date()
                target_date = next_target.target_date
                days_remaining = (target_date - today).days
                
                progress_info = {
                    'remaining_amount': max(0, remaining_amount),
                    'progress_percentage': progress_percentage,
                    'days_remaining': max(0, days_remaining),
                    'is_achieved': current_net_worth >= next_target.target_amount,
                    'target_amount': next_target.target_amount,
                    'title': next_target.title
                }
        except Exception as e:
            logging.error(f"Error calculating next target: {str(e)}")
        
        # Get last updated time
        global last_price_update
        last_updated_str = None
        if last_price_update:
            bst = pytz.timezone('Europe/London')
            last_updated_bst = last_price_update.replace(tzinfo=pytz.UTC).astimezone(bst)
            last_updated_str = last_updated_bst.strftime('%d/%m/%Y %H:%M')
        
        # Create response with cache-busting headers for live API data
        response = make_response(jsonify({
            'current_net_worth': current_net_worth,
            'platform_allocations': platform_allocations,
            'platform_percentages': platform_percentages,
            'platform_monthly_changes': platform_monthly_changes,
            'mom_change': mom_change,
            'mom_amount_change': mom_amount_change,
            'yearly_increase': yearly_increase,
            'yearly_amount_change': yearly_amount_change,
            'progress_info': progress_info,
            'last_updated': last_updated_str
        }))
        
        # Force fresh API data, disable all caching
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache' 
        response.headers['Expires'] = '0'
        response.headers['Vary'] = 'Accept'
        return response
    except Exception as e:
        logging.error(f"Error in live values API: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/available-years')
def get_available_years():
    """API endpoint to get all available years from year-month tracker"""
    try:
        from models import NetworthEntry
        years = db.session.query(NetworthEntry.year).distinct().order_by(NetworthEntry.year.asc()).all()
        available_years = [year[0] for year in years]
        return jsonify({'years': available_years})
    except Exception as e:
        logging.error(f"Error getting available years: {str(e)}")
        return jsonify({'years': [2023, 2024, 2025]}), 500

@app.route('/api/collect-historical-data', methods=['POST'])
def manual_collect_historical_data():
    """Manual endpoint to trigger historical data collection"""
    try:
        with app.app_context():
            collect_historical_data()
        return jsonify({'success': True, 'message': 'Historical data collected successfully'})
    except Exception as e:
        logging.error(f"Error in manual historical data collection: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/realtime-chart-data')
def realtime_chart_data():
    """API endpoint for real-time historical chart data - supports multiple time ranges"""
    # Ensure historical data is fresh for real-time charts
    ensure_recent_historical_data()
    
    try:
        from models import HistoricalNetWorth, WeeklyHistoricalNetWorth, MonthlyHistoricalNetWorth, DailyHistoricalNetWorth
        import pytz
        
        # Get filter parameter (default to '24h')
        time_filter = request.args.get('filter', '24h')
        
        if time_filter == 'week':
            # Show ONLY genuine 6-hourly data from recent valid collections
            # Filter to avoid showing fake historical data - only recent authentic collections
            recent_cutoff = datetime.now() - timedelta(days=3)  # Only last 3 days of genuine data
            data_points = HistoricalNetWorth.query.filter(
                HistoricalNetWorth.timestamp >= recent_cutoff
            ).order_by(HistoricalNetWorth.timestamp.asc()).all()
            
        elif time_filter == 'month':
            # ONLY show authentic daily data - filter out fake £200 increment patterns
            # Look for only the authentic value from Aug 22: £114,869.96
            data_points = DailyHistoricalNetWorth.query.filter(
                DailyHistoricalNetWorth.net_worth > 114000  # Only authentic values, not fake incremental ones
            ).order_by(DailyHistoricalNetWorth.timestamp.asc()).all()
            
        elif time_filter == '1m':
            # Same as month - ONLY authentic data (values with decimals, not fake round increments)
            data_points = DailyHistoricalNetWorth.query.filter(
                DailyHistoricalNetWorth.net_worth > 114000  # Filter out fake incremental data
            ).order_by(DailyHistoricalNetWorth.timestamp.asc()).all()
            
        elif time_filter == '3months':
            # ONLY authentic data - no fake incremental patterns
            data_points = DailyHistoricalNetWorth.query.filter(
                DailyHistoricalNetWorth.net_worth > 114000  # Only genuine values
            ).order_by(DailyHistoricalNetWorth.timestamp.asc()).all()
            
        elif time_filter in ['year', '1y']:
            # ONLY authentic data - no fake yearly historical extrapolation
            data_points = DailyHistoricalNetWorth.query.filter(
                DailyHistoricalNetWorth.net_worth > 114000  # Only genuine values
            ).order_by(DailyHistoricalNetWorth.timestamp.asc()).all()
            
        elif time_filter.isdigit() and int(time_filter) >= 2023:
            # Get data from NetworthEntry for specific year - using authentic year-month tracker data
            from models import NetworthEntry
            try:
                year = int(time_filter)
                monthly_data = NetworthEntry.query.filter_by(year=year).all()
                
                # Convert monthly tracker data to chart format using real data
                data_points = []
                
                # Helper function to parse the unusual month format (e.g., "1st May")
                def parse_month_string(month_str):
                    """Parse month strings like '1st May' to month number"""
                    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
                    for i, month_name in enumerate(month_names):
                        if month_name in month_str:
                            return i + 1
                    return 1  # Default to January if can't parse
                
                # Sort by parsed month order to ensure proper timeline
                monthly_data.sort(key=lambda x: parse_month_string(x.month))
                
                for month_data in monthly_data:
                    # Create data point object that matches our chart interface with REAL VALUES
                    class AuthenticDataPoint:
                        def __init__(self, timestamp, net_worth):
                            self.timestamp = timestamp
                            self.net_worth = net_worth
                    
                    # Create timestamp for the end of each month
                    month_num = parse_month_string(month_data.month)
                    # Use last day of month for more accurate representation
                    if month_num == 12:
                        month_end = datetime(year + 1, 1, 1) - timedelta(days=1)
                    else:
                        month_end = datetime(year, month_num + 1, 1) - timedelta(days=1)
                    
                    # Use the AUTHENTIC total_networth value from database
                    data_points.append(AuthenticDataPoint(month_end, month_data.total_networth))
                
            except Exception as e:
                logging.error(f"Error getting yearly data for {time_filter}: {str(e)}")
                data_points = []
                
        elif time_filter in ['max', 'all', 'all-years']:
            # Get ALL data from NetworthEntry for maximum view - AUTHENTIC year-month tracker data  
            from models import NetworthEntry
            try:
                monthly_data = NetworthEntry.query.order_by(NetworthEntry.year.asc()).all()
                
                # Convert monthly tracker data to chart format using REAL DATA
                data_points = []
                
                # Helper function to parse the unusual month format (e.g., "1st May")
                def parse_month_string(month_str):
                    """Parse month strings like '1st May' to month number"""
                    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
                    for i, month_name in enumerate(month_names):
                        if month_name in month_str:
                            return i + 1
                    return 1  # Default to January if can't parse
                
                # Sort by year then month to ensure proper timeline
                monthly_data.sort(key=lambda x: (x.year, parse_month_string(x.month)))
                
                for month_data in monthly_data:
                    # Create authentic data point object with REAL VALUES
                    class AuthenticDataPoint:
                        def __init__(self, timestamp, net_worth):
                            self.timestamp = timestamp
                            self.net_worth = net_worth
                    
                    # Create timestamp for the end of each month
                    year = month_data.year
                    month_num = parse_month_string(month_data.month)
                    if month_num == 12:
                        month_end = datetime(year + 1, 1, 1) - timedelta(days=1)
                    else:
                        month_end = datetime(year, month_num + 1, 1) - timedelta(days=1)
                    
                    # Use AUTHENTIC total_networth value from year-month tracker
                    data_points.append(AuthenticDataPoint(month_end, month_data.total_networth))
                
            except Exception as e:
                logging.error(f"Error getting max/all data: {str(e)}")
                data_points = []
            
        else:  # Default to 24h
            # Get data from last 24 hours
            cutoff_time = datetime.now() - timedelta(hours=24)
            data_points = HistoricalNetWorth.query.filter(
                HistoricalNetWorth.timestamp >= cutoff_time
            ).order_by(HistoricalNetWorth.timestamp.asc()).all()
        
        labels = []
        values = []
        
        uk_tz = pytz.timezone('Europe/London')
        
        # For 24h data, deduplicate by time label to avoid duplicate entries
        if time_filter == '24h':
            time_data_map = {}  # {time_label: (timestamp, net_worth)}
            
            for point in data_points:
                # Convert to BST for display
                bst_time = point.timestamp.astimezone(uk_tz)
                time_label = bst_time.strftime('%H:%M')
                
                # Keep only the most recent entry for each time label
                if time_label not in time_data_map or point.timestamp > time_data_map[time_label][0]:
                    time_data_map[time_label] = (point.timestamp, float(point.net_worth))
            
            # Sort by timestamp and build final arrays
            sorted_items = sorted(time_data_map.items(), key=lambda x: x[1][0])
            for time_label, (timestamp, net_worth) in sorted_items:
                labels.append(time_label)
                values.append(net_worth)
        else:
            # For other time filters, process normally
            for point in data_points:
                # Convert to BST for display
                bst_time = point.timestamp.astimezone(uk_tz)
                
                if time_filter in ['all-years', 'max', 'all', '2023', '2024', '2025'] or time_filter.isdigit():
                    # For yearly data from monthly tracker, show month/year (e.g., "Jan 23")
                    time_label = bst_time.strftime('%b %y')
                elif time_filter == 'week':
                    # For weekly data, show day and time (e.g., "Mon 12:00")
                    time_label = bst_time.strftime('%a %H:%M')
                elif time_filter == '1m':
                    # For 1 month data, show date (e.g., "22/08")
                    time_label = bst_time.strftime('%d/%m')
                elif time_filter == 'month':
                    # For desktop monthly data (now using daily data), show date (e.g., "22/08")
                    time_label = bst_time.strftime('%d/%m')
                elif time_filter in ['3months', 'year']:
                    # For 3 months/year data, show date (e.g., "22/08")
                    time_label = bst_time.strftime('%d/%m')
                else:
                    # Default fallback for any unhandled time_filter values
                    time_label = bst_time.strftime('%d/%m %H:%M')
                
                labels.append(time_label)
                values.append(float(point.net_worth))
        
        # Create response with cache-busting headers
        response = make_response(jsonify({
            'labels': labels,
            'values': values,
            'count': len(data_points),
            'filter': time_filter
        }))
        
        # Force fresh chart data, disable all caching
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache' 
        response.headers['Expires'] = '0'
        response.headers['Vary'] = 'Accept'
        return response
        
    except Exception as e:
        logging.error(f"Error getting real-time chart data: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/manual-collection')
def manual_collection():
    """Manually trigger historical data collection"""
    try:
        collect_historical_data()
        return jsonify({'success': True, 'message': 'Data collection completed'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/price-status')
def price_status():
    """API endpoint to check when prices were last updated"""
    global last_price_update
    
    # Convert to BST timezone for display
    bst = pytz.timezone('Europe/London')
    
    # Get current date in BST
    current_bst = datetime.now(bst)
    current_date_str = current_bst.strftime('%B %d, %Y')
    
    if last_price_update:
        # Convert UTC to BST and format like mobile version
        last_updated_bst = last_price_update.replace(tzinfo=pytz.UTC).astimezone(bst)
        last_updated_str = last_updated_bst.strftime('%d/%m/%Y %H:%M')
        
        # Calculate next update time
        next_update_in = PRICE_REFRESH_INTERVAL - int((datetime.now() - last_price_update).total_seconds())
        next_update_in = max(0, next_update_in)  # Ensure non-negative
        
        # Calculate minutes until next update
        minutes_until_next = max(0, int(next_update_in / 60))
    else:
        last_updated_str = None
        next_update_in = PRICE_REFRESH_INTERVAL
        minutes_until_next = int(PRICE_REFRESH_INTERVAL / 60)
    
    return jsonify({
        'last_updated': last_updated_str,
        'next_update_in': next_update_in,
        'current_date': current_date_str,
        'minutes_until_next': minutes_until_next
    })

@app.route('/api/networth-chart-data')
def networth_chart_data():
    """API endpoint to get net worth chart data for different years and historical time ranges"""
    # Ensure historical data is fresh for chart display
    ensure_recent_historical_data()
    
    try:
        year_param = request.args.get('year', '2025')
        chart_type = request.args.get('type', 'line')  # line or bar
        data_manager = get_data_manager()
        
        # Check if this is a new historical time range
        if year_param in ['1d', '1w', '3m', '6m']:
            return jsonify(get_historical_chart_data(year_param, chart_type))
        
        labels = []
        values = []
        platform_data = {}  # For stacked bar chart
        
        if year_param == 'all' or year_param == 'all-years':
            # Get data from all years (2023, 2024, 2025) - enhanced with historical data
            return jsonify(get_enhanced_all_years_chart_data(chart_type))
        elif year_param == '2024-2025':
            # Get data from 2024 and 2025
            years_to_include = [2024, 2025]
        else:
            # Get data from specific year
            years_to_include = [int(year_param)]
        
        for year in years_to_include:
            try:
                year_data = data_manager.get_networth_data(year)
                
                # Process each month in chronological order - including both December entries
                month_order = ['1st Jan', '1st Feb', '1st Mar', '1st Apr', '1st May', '1st Jun',
                              '1st Jul', '1st Aug', '1st Sep', '1st Oct', '1st Nov', '1st Dec', '31st Dec']
                
                for month in month_order:
                    if month in year_data:
                        month_data = year_data[month]
                        
                        # Calculate total for this month
                        month_total = 0
                        month_platforms = {}
                        
                        for platform, value in month_data.items():
                            if platform != 'total_net_worth' and isinstance(value, (int, float)):
                                month_total += value
                                # Store platform data for stacked bar chart
                                if chart_type == 'bar':
                                    month_platforms[platform] = value
                        
                        # Only add if there's actual data
                        if month_total > 0:
                            # Format label
                            if len(years_to_include) > 1:
                                # Multi-year view - include year
                                if month == '1st Dec':
                                    label = f"1st Dec {year}"
                                elif month == '31st Dec':
                                    label = f"31st Dec {year}"
                                else:
                                    month_short = month.replace('1st ', '').replace('31st ', '')
                                    label = f"{month_short} {year}"
                            else:
                                # Single year view - distinguish the two December entries
                                if month == '1st Dec':
                                    label = "1st Dec"
                                elif month == '31st Dec':
                                    label = "31st Dec"
                                else:
                                    label = month.replace('1st ', '').replace('31st ', '')
                            
                            labels.append(label)
                            values.append(round(month_total, 2))
                            
                            # For stacked bar chart, store platform breakdown
                            if chart_type == 'bar':
                                for platform, value in month_platforms.items():
                                    if platform not in platform_data:
                                        platform_data[platform] = [0] * (len(labels) - 1)  # Fill previous months with zeros
                                    platform_data[platform].append(value)
                                
                                # Ensure all existing platforms have data for this month
                                for platform in list(platform_data.keys()):
                                    if platform not in month_platforms:
                                        platform_data[platform].append(0)
                            
            except Exception as e:
                logging.error(f"Error getting data for year {year}: {str(e)}")
                continue
        
        if chart_type == 'bar':
            # Ensure all datasets have the same length as labels
            datasets = []
            for platform, data in platform_data.items():
                # Ensure data array matches labels length
                while len(data) < len(labels):
                    data.append(0)  # Fill missing months with 0
                
                # Trim if too long
                data = data[:len(labels)]
                
                dataset = {
                    'label': platform,
                    'data': data,
                    'backgroundColor': get_platform_color(platform),
                    'borderColor': get_platform_color(platform),
                    'borderWidth': 1
                }
                datasets.append(dataset)
            
            # Return stacked bar chart data
            return jsonify({
                'labels': labels,
                'datasets': datasets
            })
        else:
            # Return line chart data
            return jsonify({
                'labels': labels,
                'values': values
            })
            
    except Exception as e:
        logging.error(f"Error in networth_chart_data: {str(e)}")
        return jsonify({'labels': [], 'values': []}), 500

def get_historical_chart_data(time_range, chart_type):
    """Get chart data using tiered historical data with smart sampling"""
    try:
        from models import HistoricalNetWorth, db
        from datetime import datetime, timedelta
        
        now = datetime.now()
        
        # Smart data selection based on time range
        if time_range == '1d':
            # Use 30-minute data for last 24 hours
            cutoff = now - timedelta(days=1)
            # Filter for data that's roughly every 30 minutes
            historical_data = db.session.query(HistoricalNetWorth)\
                .filter(HistoricalNetWorth.timestamp >= cutoff)\
                .order_by(HistoricalNetWorth.timestamp.asc())\
                .all()
        elif time_range == '1w':
            # Use 6-hour sampling for last week
            cutoff = now - timedelta(days=7)
            all_data = db.session.query(HistoricalNetWorth)\
                .filter(HistoricalNetWorth.timestamp >= cutoff)\
                .order_by(HistoricalNetWorth.timestamp.asc())\
                .all()
            # Sample every 6 hours worth of data
            historical_data = sample_data_by_interval(all_data, hours=6)
        elif time_range in ['3m', '6m']:
            # Use 12-hour sampling for 3-6 months
            days = 90 if time_range == '3m' else 180
            cutoff = now - timedelta(days=days)
            all_data = db.session.query(HistoricalNetWorth)\
                .filter(HistoricalNetWorth.timestamp >= cutoff)\
                .order_by(HistoricalNetWorth.timestamp.asc())\
                .all()
            # Sample every 12 hours worth of data
            historical_data = sample_data_by_interval(all_data, hours=12)
        elif time_range == '1y':
            # Use 24-hour sampling for 1 year
            cutoff = now - timedelta(days=365)
            all_data = db.session.query(HistoricalNetWorth)\
                .filter(HistoricalNetWorth.timestamp >= cutoff)\
                .order_by(HistoricalNetWorth.timestamp.asc())\
                .all()
            # Sample every 24 hours worth of data
            historical_data = sample_data_by_interval(all_data, hours=24)
        else:
            cutoff = now - timedelta(days=30)
            historical_data = db.session.query(HistoricalNetWorth)\
                .filter(HistoricalNetWorth.timestamp >= cutoff)\
                .order_by(HistoricalNetWorth.timestamp.asc())\
                .all()
        
        # The historical_data is already set above by the smart sampling logic
        
        # Convert UTC timestamps to BST for user-friendly display
        import pytz
        bst_tz = pytz.timezone('Europe/London')
        
        labels = []
        values = []
        
        for entry in historical_data:
            # Convert UTC timestamp to BST for display
            utc_time = entry.timestamp.replace(tzinfo=pytz.UTC)
            bst_time = utc_time.astimezone(bst_tz)
            
            # Format time based on range
            if time_range == '1d':
                # For 1-day view, show BST time as HH:MM (e.g., "20:00", "20:30")
                time_label = bst_time.strftime('%H:%M')
            elif time_range == '1w':
                # For 1-week view, show day and time
                time_label = bst_time.strftime('%a %H:%M')
            else:
                # For longer ranges, show date
                time_label = bst_time.strftime('%d/%m')
            
            labels.append(time_label)
            values.append(round(entry.net_worth, 2))
        
        if not historical_data:
            # Return current data point if no historical data available
            current_net_worth = calculate_current_net_worth()
            current_bst = datetime.now(bst_tz)
            
            if chart_type == 'line':
                time_format = '%H:%M' if time_range == '1d' else ('%a %H:%M' if time_range == '1w' else '%d/%m')
                return {
                    'labels': [current_bst.strftime(time_format)],
                    'values': [current_net_worth]
                }
            else:
                # For bar charts, convert to platform datasets
                colors = {
                    'Degiro': '#1e3a8a',
                    'Trading212 ISA': '#0d9488',
                    'EQ (GSK shares)': '#dc2626',
                    'InvestEngine ISA': '#ea580c',
                    'Crypto': '#7c3aed',
                    'HL Stocks & Shares LISA': '#0ea5e9',
                    'Cash': '#22c55e'
                }
                
                datasets = []
                for platform, value in platform_breakdown.items():
                    color = colors.get(platform, '#6b7280')
                    datasets.append({
                        'label': platform,
                        'data': [value],
                        'backgroundColor': color,
                        'borderColor': color,
                        'borderWidth': 1
                    })
                
                return {
                    'labels': ['Now'],
                    'datasets': datasets
                }
        
        # Return the formatted data
        if chart_type == 'line':
            return {
                'labels': labels,
                'values': values
            }
        
        else:
            # Bar chart: platform breakdown over time
            colors = {
                'Degiro': '#1e3a8a',
                'Trading212 ISA': '#0d9488',
                'EQ (GSK shares)': '#dc2626',
                'InvestEngine ISA': '#ea580c',
                'Crypto': '#7c3aed',
                'HL Stocks & Shares LISA': '#0ea5e9',
                'Cash': '#22c55e'
            }
            
            # Get all unique platforms
            all_platforms = set()
            for entry in historical_data:
                all_platforms.update(entry.platform_breakdown.keys())
            
            # Create datasets for each platform
            datasets = []
            labels = []
            
            # Create BST labels for bar charts
            labels = []
            for entry in historical_data:
                utc_time = entry.timestamp.replace(tzinfo=pytz.UTC)
                bst_time = utc_time.astimezone(bst_tz)
                
                if time_range == '1d':
                    labels.append(bst_time.strftime('%H:%M'))
                elif time_range == '1w':
                    labels.append(bst_time.strftime('%a %H:%M'))
                else:
                    labels.append(bst_time.strftime('%d/%m'))
            
            # Create dataset for each platform
            for platform in sorted(all_platforms):
                color = colors.get(platform, '#6b7280')
                platform_data = []
                
                for entry in historical_data:
                    value = entry.platform_breakdown.get(platform, 0)
                    platform_data.append(value)
                
                datasets.append({
                    'label': platform,
                    'data': platform_data,
                    'backgroundColor': color,
                    'borderColor': color,
                    'borderWidth': 1
                })
            
            return {
                'labels': labels,
                'datasets': datasets
            }
    
    except Exception as e:
        logging.error(f"Error getting historical chart data: {str(e)}")
        # Fallback to empty data
        return {
            'labels': [],
            'values': [] if chart_type == 'line' else {'datasets': []}
        }

def get_enhanced_all_years_chart_data(chart_type):
    """Get all years chart data enhanced with historical data for recent periods"""
    try:
        data_manager = get_data_manager()
        
        # Use existing logic but enhanced with historical data
        labels = []
        values = []
        platform_data = {}
        years_to_include = [2023, 2024, 2025]
        
        for year in years_to_include:
            try:
                year_data = data_manager.get_networth_data(year)
                
                # Process each month in chronological order - including both December entries
                month_order = ['1st Jan', '1st Feb', '1st Mar', '1st Apr', '1st May', '1st Jun',
                              '1st Jul', '1st Aug', '1st Sep', '1st Oct', '1st Nov', '1st Dec', '31st Dec']
                
                for month in month_order:
                    if month in year_data:
                        month_data = year_data[month]
                        
                        # Calculate total for this month
                        month_total = 0
                        month_platforms = {}
                        
                        for platform, value in month_data.items():
                            if platform != 'total_net_worth' and isinstance(value, (int, float)):
                                month_total += value
                                # Store platform data for stacked bar chart
                                if chart_type == 'bar':
                                    month_platforms[platform] = value
                        
                        # Only add if there's actual data
                        if month_total > 0:
                            # Format label
                            if month == '1st Dec':
                                label = f"1st Dec {year}"
                            elif month == '31st Dec':
                                label = f"31st Dec {year}"
                            else:
                                month_short = month.replace('1st ', '').replace('st', '').replace('nd', '').replace('rd', '').replace('th', '')
                                label = f"{month_short} {year}"
                            
                            labels.append(label)
                            values.append(month_total)
                            
                            # Store platform data for stacked bar chart
                            if chart_type == 'bar':
                                # First, ensure all existing platforms have placeholder for this month
                                for existing_platform in platform_data:
                                    if existing_platform not in month_platforms:
                                        platform_data[existing_platform].append(0)
                                
                                # Then add the actual data for platforms that have values
                                for platform, value in month_platforms.items():
                                    if platform not in platform_data:
                                        # New platform - backfill with zeros for all previous months
                                        platform_data[platform] = [0] * (len(labels) - 1)
                                    platform_data[platform].append(value)
                                
                                # Finally, ensure all platforms now have the same number of data points
                                expected_length = len(labels)
                                for platform in platform_data:
                                    while len(platform_data[platform]) < expected_length:
                                        platform_data[platform].append(0)
                
            except Exception as e:
                logging.error(f"Error processing year {year}: {str(e)}")
                continue
        
        # Add recent historical data points but with smart filtering to avoid daily spam
        try:
            from models import HistoricalNetWorth, db
            from datetime import datetime, timedelta
            
            # Only add today's data point if we're looking at current month/year
            # This prevents the chart from being cluttered with daily dates
            now = datetime.now()
            current_month = now.strftime('%b %Y')  # e.g., "Aug 2025"
            
            # Check if current month data exists in monthly tracker
            current_month_in_monthly = any(current_month in label for label in labels)
            
            # Only add historical data if:
            # 1. We don't have current month in monthly tracker yet, OR
            # 2. We want to show current value as the latest point
            cutoff = datetime.now() - timedelta(days=1)  # Only today's data
            recent_historical = db.session.query(HistoricalNetWorth)\
                .filter(HistoricalNetWorth.timestamp >= cutoff)\
                .order_by(HistoricalNetWorth.timestamp.desc())\
                .limit(1)\
                .all()
            
            if recent_historical and not current_month_in_monthly:
                entry = recent_historical[0]
                # Use month format instead of daily format for consistency
                label = entry.timestamp.strftime('%b %Y')  # e.g., "Aug 2025"
                
                # Only add if not already present
                if label not in labels:
                    labels.append(label)
                    values.append(entry.net_worth)
                    
                    # Add platform data for bar charts
                    if chart_type == 'bar':
                        # Add any new platforms that weren't in previous entries first
                        for platform, value in entry.platform_breakdown.items():
                            if platform not in platform_data:
                                platform_data[platform] = [0] * (len(labels) - 1)  # Fill previous entries with 0
                        
                        # Now ensure all platforms have the correct data for this new entry
                        for platform in platform_data:
                            if platform in entry.platform_breakdown:
                                platform_data[platform].append(entry.platform_breakdown[platform])
                            else:
                                platform_data[platform].append(0)
        
        except Exception as e:
            logging.error(f"Error adding historical data to all years view: {str(e)}")
        
        if chart_type == 'bar':
            # Convert platform_data to datasets format
            colors = {
                'Degiro': '#1e3a8a',
                'Trading212 ISA': '#0d9488',
                'EQ (GSK shares)': '#dc2626',
                'InvestEngine ISA': '#ea580c',
                'Crypto': '#7c3aed',
                'HL Stocks & Shares LISA': '#0ea5e9',
                'Cash': '#22c55e'
            }
            
            datasets = []
            for platform, data in platform_data.items():
                color = colors.get(platform, '#6b7280')
                datasets.append({
                    'label': platform,
                    'data': data,
                    'backgroundColor': color,
                    'borderColor': color,
                    'borderWidth': 1
                })
            
            return {
                'labels': labels,
                'datasets': datasets
            }
        else:
            # Return line chart data
            return {
                'labels': labels,
                'values': values
            }
            
    except Exception as e:
        logging.error(f"Error getting enhanced all years chart data: {str(e)}")
        return {
            'labels': [],
            'values': [] if chart_type == 'line' else {'datasets': []}
        }

def get_platform_color(platform):
    """Get consistent color for each platform - uses same colors as PLATFORM_COLORS"""
    return PLATFORM_COLORS.get(platform, '#6b7280')

# Initialize background price updater thread
def start_background_updater():
    """Start the background price updater thread"""
    global price_update_thread
    if price_update_thread is None or not price_update_thread.is_alive():
        price_update_thread = threading.Thread(target=background_price_updater, daemon=True)
        price_update_thread.start()
        logging.info("Background price updater started")

# --- scheduled tasks endpoint ---
import os, threading
from flask import request, abort, jsonify
from datetime import datetime

CRON_TOKEN = os.getenv("CRON_TOKEN", "")

def run_15m_job():
    with app.app_context():
        try:
            # Run price updates and historical data collection
            app.logger.info("🚀 External 15m job starting at %s", datetime.utcnow())
            update_all_prices()
            
            # Only collect historical data if we're on a clean BST 15-minute boundary
            import pytz
            uk_tz = pytz.timezone('Europe/London')
            uk_now = datetime.now().astimezone(uk_tz)
            current_minute = uk_now.minute
            
            if current_minute in [0, 15, 30, 45]:
                app.logger.info("✅ External call at valid BST interval (%s), collecting data", uk_now.strftime('%H:%M'))
                collect_historical_data()
            else:
                app.logger.info("⏭️ External call at invalid BST interval (%s), skipping historical collection", uk_now.strftime('%H:%M'))
                
            app.logger.info("✅ External 15m job completed at %s", datetime.utcnow())
        except Exception as e:
            app.logger.error("❌ External 15m job failed: %s", str(e))

def run_6h_job():
    with app.app_context():
        try:
            app.logger.info("🚀 External 6h job starting at %s", datetime.utcnow())
            collect_weekly_historical_data()
            app.logger.info("✅ External 6h job completed at %s", datetime.utcnow())
        except Exception as e:
            app.logger.error("❌ External 6h job failed: %s", str(e))

def run_daily_job():
    with app.app_context():
        try:
            app.logger.info("🚀 External daily job starting at %s", datetime.utcnow())
            
            # Run daily cleanup and monthly tracker checks
            collect_daily_historical_data()
            cleanup_old_historical_data()
            
            # Check if it's the 1st of the month for monthly tracker
            import pytz
            uk_tz = pytz.timezone('Europe/London')
            uk_now = datetime.now().astimezone(uk_tz)
            if uk_now.day == 1 and uk_now.hour == 0:  # 1st of month at midnight
                auto_populate_monthly_tracker()
            
            # Check if it's December 31st for year-end tracker
            if uk_now.month == 12 and uk_now.day == 31 and uk_now.hour == 23:  # Dec 31st at 11 PM
                auto_populate_dec31_tracker()
                
            app.logger.info("✅ External daily job completed at %s", datetime.utcnow())
        except Exception as e:
            app.logger.error("❌ External daily job failed: %s", str(e))

# temporarily allow GET for testing; keep POST for real use
@app.route("/tasks/run", methods=["POST", "GET"])
def tasks_run():
    if request.method == "GET":
        return jsonify(ok=True, hint="use POST with Authorization header", cron_token_set=bool(CRON_TOKEN)), 200

    if not CRON_TOKEN:
        abort(500, "CRON_TOKEN missing on server")

    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {CRON_TOKEN}":
        abort(401)

    job = request.args.get("t")
    mapping = {"15m": run_15m_job, "6h": run_6h_job, "daily": run_daily_job}
    fn = mapping.get(job)
    if not fn:
        abort(400, "unknown task")

    app.logger.info("🎯 Received external task request: %s at %s", job, datetime.utcnow())
    threading.Thread(target=fn, daemon=True).start()
    return jsonify(ok=True, started=job), 202
# --- end scheduled tasks endpoint ---

# Start background updater when app starts (only if not using external scheduling)
USE_EXTERNAL_SCHEDULING = os.environ.get("USE_EXTERNAL_SCHEDULING", "false").lower() == "true"

if not USE_EXTERNAL_SCHEDULING:
    start_background_updater()
else:
    logging.info("External scheduling enabled - starting lightweight background thread for live price updates only")
    # Start a lightweight background thread for live price updates only
    def external_mode_price_updater():
        """Lightweight price updater for external scheduling mode - only updates prices, no historical data"""
        global last_price_update
        last_price_update = datetime.now() - timedelta(minutes=16)  # Trigger first update soon
        
        while True:
            try:
                time.sleep(30)  # 30-second intervals for live price updates
                with app.app_context():
                    now = datetime.now()
                    
                    # Update prices every 30 seconds for live dashboard
                    time_since_price_update = (now - last_price_update).total_seconds()
                    if time_since_price_update >= 30:
                        update_all_prices()
                        last_price_update = now
                        logging.debug("Live price update completed (external mode)")
                        
            except Exception as e:
                logging.error(f"Error in external mode price updater: {str(e)}")
                time.sleep(30)
    
    # Start the lightweight updater for live prices
    price_thread = threading.Thread(target=external_mode_price_updater, daemon=True)
    price_thread.start()
    logging.info("Lightweight price updater started for external scheduling mode")

@app.route('/edit-investment/<platform>/<int:index>')
def edit_investment(platform, index):
    """Edit an existing investment"""
    try:
        investments_data = get_data_manager().get_investments_data()
        
        if platform not in investments_data or index >= len(investments_data[platform]):
            flash('Investment not found', 'error')
            return redirect(url_for('investment_manager'))
        
        investment = investments_data[platform][index]
        unique_names = get_data_manager().get_unique_investment_names()
        
        return render_template('edit_investment.html',
                             investment=investment,
                             platform=platform,
                             index=index,
                             unique_names=unique_names,
                             platform_colors=PLATFORM_COLORS)
    except Exception as e:
        logging.error(f"Error editing investment: {str(e)}")
        flash(f'Error editing investment: {str(e)}', 'error')
        return redirect(url_for('investment_manager'))

@app.route('/update-investment/<platform>/<int:investment_id>', methods=['POST'])
def update_investment(platform, investment_id):
    """Update an existing investment"""
    try:
        name = request.form.get('name')
        holdings = float(request.form.get('holdings', 0))
        input_type = request.form.get('input_type', 'amount_spent')
        symbol = request.form.get('symbol', '')
        
        if not name or holdings <= 0:
            flash('Investment name and holdings are required', 'error')
            return redirect(url_for('investment_manager'))
        
        # Prepare update data
        updates = {
            'name': name,
            'holdings': holdings,
            'symbol': symbol
        }
        
        # Handle different input types
        if input_type == 'amount_spent':
            amount_spent = float(request.form.get('amount_spent', 0))
            if amount_spent <= 0:
                flash('Amount spent must be greater than 0', 'error')
                return redirect(url_for('investment_manager'))
            updates['amount_spent'] = amount_spent
            updates['average_buy_price'] = amount_spent / holdings
        elif input_type == 'average_buy_price':
            average_buy_price = float(request.form.get('average_buy_price', 0))
            if average_buy_price <= 0:
                flash('Average buy price must be greater than 0', 'error')
                return redirect(url_for('investment_manager'))
            updates['average_buy_price'] = average_buy_price
            updates['amount_spent'] = average_buy_price * holdings
        
        # Update the investment directly by ID
        get_data_manager().update_investment(investment_id, updates)
        flash(f'Investment {name} updated successfully', 'success')
        
    except Exception as e:
        logging.error(f"Error updating investment: {str(e)}")
        flash(f'Error updating investment: {str(e)}', 'error')
    
    return redirect(url_for('investment_manager'))

@app.route('/delete-investment/<platform>/<int:investment_id>', methods=['POST'])
def delete_investment(platform, investment_id):
    """Delete an existing investment"""
    try:
        get_data_manager().remove_investment_by_id(investment_id)
        flash('Investment deleted successfully', 'success')
        
    except Exception as e:
        logging.error(f"Error deleting investment: {str(e)}")
        flash(f'Error deleting investment: {str(e)}', 'error')
    
    return redirect(url_for('investment_manager'))

@app.route('/update_cash/<platform>', methods=['POST'])
def update_cash(platform):
    """Update cash balance for a platform"""
    try:
        cash_amount = float(request.form.get('cash_amount', 0))
        get_data_manager().update_platform_cash(platform, cash_amount)
        flash(f'Cash balance updated for {platform}!', 'success')
    except ValueError:
        flash('Invalid cash amount entered!', 'error')
    except Exception as e:
        logging.error(f"Error updating cash: {str(e)}")
        flash(f'Error updating cash: {str(e)}', 'error')
    
    return redirect(url_for('investment_manager'))

@app.route('/add_investment_mobile', methods=['POST'])
def add_investment_mobile():
    """Add new investment from mobile"""
    try:
        platform = request.form.get('platform')
        name = request.form.get('name')
        holdings = float(request.form.get('holdings', 0))
        input_type = request.form.get('input_type', 'amount_spent')
        symbol = request.form.get('symbol', '')
        
        if not platform or not name or holdings <= 0:
            flash('Platform, investment name, and holdings are required', 'error')
            return redirect(url_for('mobile_investments'))
        
        # Handle different input types
        if input_type == 'amount_spent':
            amount_spent = float(request.form.get('amount_spent', 0))
            if amount_spent <= 0:
                flash('Amount spent must be greater than 0', 'error')
                return redirect(url_for('mobile_investments'))
            investment_data = {
                'name': name,
                'holdings': holdings,
                'amount_spent': amount_spent,
                'average_buy_price': amount_spent / holdings if holdings > 0 else 0,
                'symbol': symbol,
                'current_price': 0.0
            }
            get_data_manager().add_investment(platform, investment_data)
        elif input_type == 'average_buy_price':
            average_buy_price = float(request.form.get('average_buy_price', 0))
            if average_buy_price <= 0:
                flash('Average buy price must be greater than 0', 'error')
                return redirect(url_for('mobile_investments'))
            investment_data = {
                'name': name,
                'holdings': holdings,
                'amount_spent': average_buy_price * holdings,
                'average_buy_price': average_buy_price,
                'symbol': symbol,
                'current_price': 0.0
            }
            get_data_manager().add_investment(platform, investment_data)
        else:
            flash('Invalid input type', 'error')
            return redirect(url_for('mobile_investments'))
        
        flash(f'Investment {name} added successfully to {platform}', 'success')
        
    except Exception as e:
        logging.error(f"Error adding investment on mobile: {str(e)}")
        flash(f'Error adding investment: {str(e)}', 'error')
    
    return redirect(url_for('mobile_investments'))

@app.route('/update_investment_mobile', methods=['POST'])
def update_investment_mobile():
    """Update existing investment from mobile"""
    try:
        investment_id = int(request.form.get('investment_id'))
        name = request.form.get('name')
        holdings = float(request.form.get('holdings', 0))
        input_type = request.form.get('input_type', 'amount_spent')
        symbol = request.form.get('symbol', '')
        
        if not name or holdings <= 0:
            flash('Investment name and holdings are required', 'error')
            return redirect(url_for('mobile_investments'))
        
        # Prepare update data
        updates = {
            'name': name,
            'holdings': holdings,
            'symbol': symbol
        }
        
        # Handle different input types
        if input_type == 'amount_spent':
            amount_spent = float(request.form.get('amount_spent', 0))
            if amount_spent <= 0:
                flash('Amount spent must be greater than 0', 'error')
                return redirect(url_for('mobile_investments'))
            updates['amount_spent'] = amount_spent
            updates['average_buy_price'] = amount_spent / holdings
        elif input_type == 'average_buy_price':
            average_buy_price = float(request.form.get('average_buy_price', 0))
            if average_buy_price <= 0:
                flash('Average buy price must be greater than 0', 'error')
                return redirect(url_for('mobile_investments'))
            updates['average_buy_price'] = average_buy_price
            updates['amount_spent'] = average_buy_price * holdings
        
        # Update the investment directly by ID
        get_data_manager().update_investment(investment_id, updates)
        flash(f'Investment {name} updated successfully', 'success')
        
    except Exception as e:
        logging.error(f"Error updating investment on mobile: {str(e)}")
        flash(f'Error updating investment: {str(e)}', 'error')
    
    return redirect(url_for('mobile_investments'))

@app.route('/update_cash_mobile', methods=['POST'])
def update_cash_mobile():
    """Update cash balance for a platform from mobile"""
    try:
        platform = request.form.get('platform')
        cash_amount = float(request.form.get('cash_amount', 0))
        get_data_manager().update_platform_cash(platform, cash_amount)
        flash(f'Cash balance updated for {platform}!', 'success')
    except ValueError:
        flash('Invalid cash amount entered!', 'error')
    except Exception as e:
        logging.error(f"Error updating cash on mobile: {str(e)}")
        flash(f'Error updating cash: {str(e)}', 'error')
    
    return redirect(url_for('mobile_investments'))

@app.route('/update_total_cash_mobile', methods=['POST'])
def update_total_cash_mobile():
    """Update total cash amount from mobile"""
    try:
        new_total = float(request.form.get('amount', 0))
        
        # Set cash to main platform (typically 'Cash' platform)
        get_data_manager().update_platform_cash('Cash', new_total)
        
        # Clear cash from all other platforms to avoid double counting
        platforms = ['Degiro', 'InvestEngine ISA', 'Trading212 ISA', 'HL Stocks & Shares LISA', 'EQ (GSK shares)', 'Crypto']
        for platform in platforms:
            current_cash = get_data_manager().get_platform_cash(platform)
            if current_cash > 0:
                get_data_manager().update_platform_cash(platform, 0)
        
        flash(f'Total cash updated to £{new_total:,.2f}!', 'success')
    except ValueError:
        flash('Invalid cash amount entered!', 'error')
    except Exception as e:
        logging.error(f"Error updating total cash on mobile: {str(e)}")
        flash(f'Error updating total cash: {str(e)}', 'error')
    
    return redirect(url_for('mobile_investments'))

@app.route('/update-monthly-income', methods=['POST'])
def update_monthly_income():
    """Update monthly income via API"""
    try:
        data = request.get_json()
        monthly_income = float(data.get('monthly_income', 0))
        
        if monthly_income < 0:
            return jsonify({'success': False, 'message': 'Monthly income cannot be negative'})
        
        get_data_manager().update_monthly_income(monthly_income)
        return jsonify({'success': True, 'message': 'Monthly income updated successfully'})
        
    except Exception as e:
        logging.error(f"Error updating monthly income: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/add-expense', methods=['POST'])
def add_expense():
    """Add expense via API"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        monthly_amount = float(data.get('monthly_amount', 0))
        
        if not name:
            return jsonify({'success': False, 'message': 'Expense name is required'})
        
        if monthly_amount < 0:
            return jsonify({'success': False, 'message': 'Monthly amount cannot be negative'})
        
        get_data_manager().add_expense(name, monthly_amount)
        return jsonify({'success': True, 'message': 'Expense added successfully'})
        
    except Exception as e:
        logging.error(f"Error adding expense: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/delete-expense', methods=['POST'])
def delete_expense():
    """Delete expense via API"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        
        if not name:
            return jsonify({'success': False, 'message': 'Expense name is required'})
        
        get_data_manager().delete_expense_by_name(name)
        return jsonify({'success': True, 'message': 'Expense deleted successfully'})
        
    except Exception as e:
        logging.error(f"Error deleting expense: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/add-investment-commitment', methods=['POST'])
def add_investment_commitment():
    """Add investment commitment via API"""
    try:
        data = request.get_json()
        platform = data.get('platform', '').strip()
        name = data.get('name', '').strip()
        monthly_amount = float(data.get('monthly_amount', 0))
        
        if not platform or not name:
            return jsonify({'success': False, 'message': 'Platform and investment name are required'})
        
        if monthly_amount < 0:
            return jsonify({'success': False, 'message': 'Monthly amount cannot be negative'})
        
        get_data_manager().add_investment_commitment(platform, name, monthly_amount)
        return jsonify({'success': True, 'message': 'Investment commitment added successfully'})
        
    except Exception as e:
        logging.error(f"Error adding investment commitment: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/delete-investment-commitment', methods=['POST'])
def delete_investment_commitment():
    """Delete investment commitment via API"""
    try:
        data = request.get_json()
        platform = data.get('platform', '').strip()
        name = data.get('name', '').strip()
        
        if not platform or not name:
            return jsonify({'success': False, 'message': 'Platform and investment name are required'})
        
        get_data_manager().delete_commitment_by_platform_and_name(platform, name)
        return jsonify({'success': True, 'message': 'Investment commitment deleted successfully'})
        
    except Exception as e:
        logging.error(f"Error deleting investment commitment: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/tracker-data')
def api_tracker_data():
    """API endpoint for tracker page data"""
    try:
        data_manager = get_data_manager()
        
        # Get available years from networth data
        available_years = []
        networth_entries = NetworthEntry.query.with_entities(NetworthEntry.year).distinct().all()
        available_years = sorted([entry[0] for entry in networth_entries], reverse=True)
        
        if not available_years:
            available_years = [datetime.now().year]
        
        # Get platform progress data
        platform_data = {}
        for year in available_years:
            year_entries = NetworthEntry.query.filter_by(year=year).order_by(NetworthEntry.id).all()
            year_data = {}
            
            for entry in year_entries:
                # Get platform data from JSON field
                platform_data_dict = entry.get_platform_data()
                
                for platform_name, platform_value in platform_data_dict.items():
                    if platform_name not in year_data:
                        year_data[platform_name] = {'months': {}}
                    
                    if platform_value and platform_value > 0:
                        year_data[platform_name]['months'][entry.month] = {
                            'value': float(platform_value),
                            'change': 0  # We'll calculate this later
                        }
            
            platform_data[year] = year_data
        
        # Get income vs investments data
        income_vs_investments = {}
        income_entries = IncomeData.query.all()
        
        for entry in income_entries:
            income_vs_investments[entry.year] = {
                'take_home': entry.income or 0,
                'invested': entry.investment or 0
            }
        
        return jsonify({
            'available_years': available_years,
            'platform_data': platform_data,
            'income_vs_investments': income_vs_investments
        })
        
    except Exception as e:
        logging.error(f"Error getting tracker data: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/add-year', methods=['POST'])
def api_add_year():
    """API endpoint to add a new year"""
    try:
        data = request.get_json()
        year = data.get('year')
        
        if not year:
            return jsonify({'success': False, 'message': 'Year is required'})
        
        # Check if year already exists
        existing = IncomeData.query.filter_by(year=year).first()
        if existing:
            return jsonify({'success': False, 'message': 'Year already exists'})
        
        # Create new income data entry for the year
        income_entry = IncomeData(year=year, income=0, investment=0)
        db.session.add(income_entry)
        db.session.commit()
        
        return jsonify({'success': True, 'message': f'Year {year} added successfully'})
        
    except Exception as e:
        logging.error(f"Error adding year: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/update-expense', methods=['POST'])
def update_expense():
    """Update expense via API"""
    try:
        data = request.get_json()
        old_name = data.get('old_name', '').strip()
        new_name = data.get('name', '').strip()
        monthly_amount = float(data.get('monthly_amount', 0))
        
        if not old_name or not new_name:
            return jsonify({'success': False, 'message': 'Expense names are required'})
        
        if monthly_amount < 0:
            return jsonify({'success': False, 'message': 'Monthly amount cannot be negative'})
        
        get_data_manager().update_expense_by_name(old_name, new_name, monthly_amount)
        return jsonify({'success': True, 'message': 'Expense updated successfully'})
        
    except Exception as e:
        logging.error(f"Error updating expense: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/update-investment-commitment', methods=['POST'])
def update_investment_commitment():
    """Update investment commitment via API"""
    try:
        data = request.get_json()
        old_platform = data.get('old_platform', '').strip()
        old_name = data.get('old_name', '').strip()
        new_platform = data.get('platform', '').strip()
        new_name = data.get('name', '').strip()
        monthly_amount = float(data.get('monthly_amount', 0))
        
        if not old_platform or not old_name or not new_platform or not new_name:
            return jsonify({'success': False, 'message': 'All fields are required'})
        
        if monthly_amount < 0:
            return jsonify({'success': False, 'message': 'Monthly amount cannot be negative'})
        
        # For now, we'll delete the old commitment and create a new one if platform changes
        # If same platform, just update the commitment
        if old_platform == new_platform:
            get_data_manager().update_commitment_by_platform_and_name(old_platform, old_name, new_name, monthly_amount)
        else:
            # Delete old commitment and create new one
            get_data_manager().delete_commitment_by_platform_and_name(old_platform, old_name)
            get_data_manager().add_investment_commitment(new_platform, new_name, monthly_amount)
        return jsonify({'success': True, 'message': 'Investment commitment updated successfully'})
        
    except Exception as e:
        logging.error(f"Error updating investment commitment: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/asset-allocation')
def api_asset_allocation():
    """API endpoint for asset class allocation data"""
    try:
        data_manager = get_data_manager()
        allocation_data = data_manager.get_asset_class_allocation()
        return jsonify(allocation_data)
    except Exception as e:
        logging.error(f"Error getting asset allocation data: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/geographic-allocation')
def api_geographic_allocation():
    """API endpoint for geographic/sector allocation data"""
    try:
        data_manager = get_data_manager()
        allocation_data = data_manager.get_geographic_sector_allocation()
        return jsonify(allocation_data)
    except Exception as e:
        logging.error(f"Error getting geographic allocation data: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/investment-details')
def api_investment_details():
    """API endpoint for investment details with P&L calculations"""
    try:
        data_manager = get_data_manager()
        investments_data = data_manager.get_investments_data()
        
        result = {
            'platforms': {}
        }
        
        # Process each platform
        for platform, investments in investments_data.items():
            if platform.endswith('_cash'):
                continue  # Skip cash keys
                
            platform_info = {
                'investments': [],
                'cash': data_manager.get_platform_cash(platform)
            }
            
            # Process investments
            for investment in investments:
                investment_details = {
                    'name': investment.get('name', ''),
                    'holdings': investment.get('holdings', 0),
                    'current_price': investment.get('current_price', 0),
                    'current_value': investment.get('holdings', 0) * investment.get('current_price', 0),
                    'amount_spent': investment.get('amount_spent', 0),
                    'average_buy_price': investment.get('average_buy_price', 0),
                    'profit_loss': 0,
                    'profit_loss_percent': 0
                }
                
                # Calculate P&L
                if investment_details['amount_spent'] > 0:
                    investment_details['profit_loss'] = investment_details['current_value'] - investment_details['amount_spent']
                    investment_details['profit_loss_percent'] = (investment_details['profit_loss'] / investment_details['amount_spent']) * 100
                
                platform_info['investments'].append(investment_details)
            
            result['platforms'][platform] = platform_info
        
        return jsonify(result)
        
    except Exception as e:
        logging.error(f"Error getting investment details: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/update-cash-balance', methods=['POST'])
def api_update_cash_balance():
    """API endpoint to update cash balance for a platform"""
    try:
        data = request.get_json()
        platform = data.get('platform')
        amount = data.get('amount')
        
        if not platform or amount is None:
            return jsonify({'success': False, 'message': 'Platform and amount are required'})
        
        get_data_manager().set_platform_cash(platform, float(amount))
        return jsonify({'success': True, 'message': 'Cash balance updated successfully'})
        
    except Exception as e:
        logging.error(f"Error updating cash balance: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/monthly-breakdown')
def api_monthly_breakdown():
    """API endpoint for monthly breakdown data"""
    try:
        data_manager = get_data_manager()
        
        # Use the existing monthly breakdown method
        breakdown_data = data_manager.get_monthly_breakdown_data()
        
        # Extract data
        monthly_income = breakdown_data.get('monthly_income', 0)
        monthly_expenses = breakdown_data.get('monthly_expenses', [])
        platform_investments = breakdown_data.get('platform_investments', {})
        
        # Format expenses for API
        expenses = []
        total_expenses = 0
        for expense in monthly_expenses:
            expenses.append({
                'category': expense.get('name', ''),
                'amount': expense.get('monthly_amount', 0)
            })
            total_expenses += expense.get('monthly_amount', 0)
        
        # Use the same total calculation as desktop version
        total_investment_commitments = breakdown_data.get('total_monthly_investments', 0)
        
        # Format investment commitments for API
        investment_commitments = []
        
        for platform, platform_data in platform_investments.items():
            if platform_data and isinstance(platform_data, dict):
                investments_list = platform_data.get('investments', [])
                if investments_list and isinstance(investments_list, list):
                    for investment in investments_list:
                        if isinstance(investment, dict) and investment.get('monthly_amount', 0) > 0:
                            investment_commitments.append({
                                'platform': platform,
                                'name': investment.get('name', ''),
                                'amount': investment.get('monthly_amount', 0)
                            })
        
        return jsonify({
            'monthly_income': monthly_income,
            'expenses': expenses,
            'total_expenses': total_expenses,
            'investment_commitments': investment_commitments,
            'total_investment_commitments': total_investment_commitments
        })
        
    except Exception as e:
        logging.error(f"Error getting monthly breakdown: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/update-monthly-data', methods=['POST'])
def api_update_monthly_data():
    """API endpoint to update monthly data"""
    try:
        data = request.get_json()
        field = data.get('field')
        value = data.get('value')
        
        if field == 'income':
            get_data_manager().update_income(float(value))
            return jsonify({'success': True, 'message': 'Income updated successfully'})
        else:
            return jsonify({'success': False, 'message': 'Invalid field'})
        
    except Exception as e:
        logging.error(f"Error updating monthly data: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/goals')
def api_goals():
    """API endpoint for goals data"""
    try:
        goals_list = Goal.query.order_by(Goal.target_date.asc()).all()
        
        # Convert goals to JSON format
        goals_json = []
        for goal in goals_list:
            goals_json.append({
                'id': goal.id,
                'title': goal.title,
                'description': goal.description,
                'target_amount': goal.target_amount,
                'target_date': goal.target_date.isoformat(),
                'created_at': goal.created_at.isoformat() if goal.created_at else None
            })
        
        return jsonify(goals_json)
        
    except Exception as e:
        logging.error(f"Error getting goals: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/goals')
def goals():
    """Goals tracking page"""
    try:
        goals_list = Goal.query.order_by(Goal.target_date.asc()).all()
        
        # Get current net worth and monthly investment for calculator
        data_manager = get_data_manager()
        current_net_worth = calculate_current_net_worth()
        breakdown_data = data_manager.get_monthly_breakdown_data()
        monthly_investment = breakdown_data.get('total_monthly_investments', 0)
        
        return render_template('goals.html',
                             goals=goals_list,
                             current_net_worth=current_net_worth,
                             monthly_investment=monthly_investment,
                             today=datetime.now().date())
    except Exception as e:
        logging.error(f"Error loading goals page: {e}")
        flash(f'Error loading goals: {str(e)}', 'error')
        return redirect(url_for('home'))

@app.route('/api/goals', methods=['POST'])
def create_goal():
    """Create a new goal"""
    try:
        data = request.get_json()
        
        goal = Goal(
            title=data.get('title'),
            description=data.get('description', ''),
            target_amount=float(data.get('target_amount')),
            target_date=datetime.strptime(data.get('target_date') + '-01', '%Y-%m-%d').date()
        )
        
        db.session.add(goal)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Goal created successfully'})
    except Exception as e:
        logging.error(f"Error creating goal: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/goals/<int:goal_id>', methods=['GET'])
def get_goal(goal_id):
    """Get a specific goal"""
    try:
        goal = Goal.query.get_or_404(goal_id)
        return jsonify(goal.to_dict())
    except Exception as e:
        logging.error(f"Error getting goal: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/goals/<int:goal_id>', methods=['PUT'])
def update_goal(goal_id):
    """Update a goal"""
    try:
        goal = Goal.query.get_or_404(goal_id)
        data = request.get_json()
        
        goal.title = data.get('title', goal.title)
        goal.description = data.get('description', goal.description)
        goal.target_amount = float(data.get('target_amount', goal.target_amount))
        goal.target_date = datetime.strptime(data.get('target_date') + '-01', '%Y-%m-%d').date()
        goal.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Goal updated successfully'})
    except Exception as e:
        logging.error(f"Error updating goal: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/goals/<int:goal_id>', methods=['DELETE'])
def delete_goal(goal_id):
    """Delete a goal"""
    try:
        goal = Goal.query.get_or_404(goal_id)
        
        db.session.delete(goal)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Goal deleted successfully'})
    except Exception as e:
        logging.error(f"Error deleting goal: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/goals/<int:goal_id>/toggle-completion', methods=['POST'])
def toggle_goal_completion(goal_id):
    """Toggle goal completion status"""
    try:
        goal = Goal.query.get_or_404(goal_id)
        
        # Toggle the status
        if goal.status == 'completed':
            goal.status = 'active'
        else:
            goal.status = 'completed'
            
        goal.updated_at = datetime.now()
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'Goal marked as {goal.status}',
            'status': goal.status
        })
    except Exception as e:
        logging.error(f"Error toggling goal completion: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/complete-goal/<int:goal_id>', methods=['POST'])
def complete_goal(goal_id):
    """Mark a goal as completed"""
    try:
        goal = Goal.query.get_or_404(goal_id)
        
        # Mark as completed
        goal.status = 'completed'
        goal.updated_at = datetime.now()
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': 'Goal marked as completed'
        })
    except Exception as e:
        logging.error(f"Error completing goal: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# Platform Connection API Routes
@app.route('/api/test_connection', methods=['POST'])
def test_connection():
    """Test API connection to platform"""
    try:
        data = request.get_json()
        platform_type = data.get('platform_type')
        credentials = data.get('credentials', {})
        
        if not platform_type:
            return jsonify({'success': False, 'error': 'Platform type required'}), 400
        
        # Test the connection using platform connector
        result = platform_connector.test_connection(platform_type, credentials)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
            
    except Exception as e:
        logging.error(f"Error testing platform connection: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/save_platform_connection', methods=['POST'])
def save_platform_connection():
    """Save platform connection and sync initial data"""
    try:
        from utils.api_platform_models import Platform, db
        
        data = request.get_json()
        platform_type = data.get('platform_type')
        credentials = data.get('credentials', {})
        
        if not platform_type:
            return jsonify({'success': False, 'error': 'Platform type required'}), 400
        
        # Test connection first
        test_result = platform_connector.test_connection(platform_type, credentials)
        if not test_result['success']:
            return jsonify({'success': False, 'error': 'Connection test failed'}), 400
        
        # Check if platform already exists
        existing_platform = Platform.query.filter_by(
            name=platform_type.title().replace('_', ' '),
            platform_type=platform_type
        ).first()
        
        if existing_platform:
            # Update existing platform
            platform = existing_platform
            platform.set_credentials(credentials)
            platform.sync_status = 'active'
            platform.error_message = None
        else:
            # Create new platform
            platform = Platform(
                name=platform_type.title().replace('_', ' '),
                platform_type=platform_type,
                api_type='rest_api',
                sync_status='active'
            )
            platform.set_credentials(credentials)
            db.session.add(platform)
        
        platform.last_sync = datetime.utcnow()
        db.session.commit()
        
        # Start initial data sync in background with improved rate limiting
        from threading import Thread
        import time
        def sync_platform_data():
            try:
                # Add longer delay for Trading 212 beta API rate limiting
                if platform_type == 'trading212':
                    time.sleep(10)  # Extended delay for Trading 212's aggressive beta rate limiting
                    logging.info(f"Starting Trading 212 sync after rate limit delay")
                
                sync_result = platform_connector.sync_platform_data(platform_type, credentials)
                if sync_result['success']:
                    # Update platform with successful sync
                    platform.sync_status = 'active'
                    platform.error_message = None
                else:
                    platform.sync_status = 'error'
                    platform.error_message = sync_result.get('error', 'Unknown sync error')
                db.session.commit()
            except Exception as e:
                platform.sync_status = 'error'
                platform.error_message = str(e)
                db.session.commit()
                logging.error(f"Background sync failed: {e}")
        
        Thread(target=sync_platform_data, daemon=True).start()
        
        return jsonify({
            'success': True, 
            'message': f'{platform_type.title()} connected successfully',
            'platform_id': platform.id
        })
        
    except Exception as e:
        logging.error(f"Error saving platform connection: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/add_manual_platform', methods=['POST'])
def add_manual_platform():
    """Add manual platform for tracking"""
    try:
        from utils.api_platform_models import Platform, db
        
        data = request.get_json()
        platform_name = data.get('platform_name')
        platform_type = data.get('platform_type', 'manual')
        
        if not platform_name:
            return jsonify({'success': False, 'error': 'Platform name required'}), 400
        
        # Check if platform already exists
        existing_platform = Platform.query.filter_by(
            name=platform_name,
            platform_type='manual'
        ).first()
        
        if existing_platform:
            return jsonify({'success': False, 'error': 'Platform already exists'}), 400
        
        # Create new manual platform
        platform = Platform(
            name=platform_name,
            platform_type='manual',
            api_type='manual',
            sync_status='manual'
        )
        
        db.session.add(platform)
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'{platform_name} added successfully',
            'platform_id': platform.id
        })
        
    except Exception as e:
        logging.error(f"Error adding manual platform: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/platforms', methods=['GET'])
def get_platforms():
    """Get list of connected platforms"""
    try:
        from utils.api_platform_models import Platform
        
        platforms = Platform.query.all()
        return jsonify({
            'success': True,
            'platforms': [platform.to_dict() for platform in platforms]
        })
        
    except Exception as e:
        logging.error(f"Error fetching platforms: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/sync_platform/<int:platform_id>', methods=['POST'])
def sync_platform(platform_id):
    """Manually trigger platform sync"""
    try:
        from utils.api_platform_models import Platform
        
        platform = Platform.query.get_or_404(platform_id)
        
        if platform.api_type == 'manual':
            return jsonify({'success': False, 'error': 'Manual platforms cannot be synced'}), 400
        
        credentials = platform.get_credentials()
        if not credentials:
            return jsonify({'success': False, 'error': 'No credentials found'}), 400
        
        # Sync data
        sync_result = platform_connector.sync_platform_data(platform.platform_type, credentials)
        
        if sync_result['success']:
            platform.last_sync = datetime.utcnow()
            platform.sync_status = 'active'
            platform.error_message = None
            db.session.commit()
        else:
            platform.sync_status = 'error'
            platform.error_message = sync_result.get('error', 'Sync failed')
            db.session.commit()
        
        return jsonify(sync_result)
        
    except Exception as e:
        logging.error(f"Error syncing platform: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
