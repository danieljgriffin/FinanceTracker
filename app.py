import os
import logging
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from utils.price_fetcher import PriceFetcher
from utils.device_detector import get_template_path, is_mobile_device
from datetime import datetime, timedelta
import pytz
import json
import threading
import time

# Tasks blueprint will be imported later to avoid circular imports

# Configure logging
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")
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
    'Degiro': '#1e3a8a',  # Dark Blue
    'Trading212 ISA': '#0d9488',  # Teal
    'EQ (GSK shares)': '#dc2626',  # Red
    'InvestEngine ISA': '#ea580c',  # Orange
    'Crypto': '#7c3aed',  # Purple
    'HL Stocks & Shares LISA': '#0ea5e9',  # Baby Blue
    'Cash': '#059669'  # Green
}

@app.route('/')
def dashboard():
    """Main dashboard showing current net worth and allocations"""
    # Ensure data is fresh when users visit
    ensure_recent_prices()
    # Note: Historical data collection only happens at scheduled times (:00, :15, :30, :45)
    
    # Force no-cache to ensure fresh content (fix browser cache issue)
    from flask import make_response
    
    # Check if this is a mobile device and redirect to mobile version
    user_agent = request.headers.get('User-Agent', '').lower()
    if any(device in user_agent for device in ['mobile', 'android', 'iphone', 'ipad', 'tablet']):
        return mobile_dashboard()
    
    try:
        # Force database session refresh to ensure fresh data on every page load
        from app import db
        db.session.expire_all()
        
        # Get current net worth data
        data_manager = get_data_manager()
        networth_data = get_data_manager().get_networth_data()
        investments_data = get_data_manager().get_investments_data()
        
        # Get last price update time
        global last_price_update
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
        
        # Calculate monthly changes for each platform
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
            logging.error(f"Error calculating platform monthly changes: {str(e)}")
            platform_monthly_changes = {}
        
        # Calculate month-on-month change (current net worth vs current month's 1st day)
        mom_change = 0
        mom_amount_change = 0
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
            
            # Calculate changes
            if month_start_total > 0:
                mom_amount_change = current_net_worth - month_start_total
                mom_change = (mom_amount_change / month_start_total) * 100
            
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
        
        # Get next financial target - closest to current day
        next_target = None
        progress_info = None
        upcoming_targets = []
        try:
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
        
        # SINGLE SOURCE OF TRUTH - Use same calculation as investment manager
        current_net_worth = calculate_current_net_worth()  # Same as "Total Portfolio Value" on investment manager
        platform_allocations_raw = calculate_platform_totals()  # Same platform totals as investment manager
        
        # Sort platforms by total value (highest to lowest) for better display
        platform_allocations = dict(sorted(platform_allocations_raw.items(), key=lambda x: x[1], reverse=True))
        
        # Calculate platform percentages
        platform_percentages = {}
        if current_net_worth > 0:
            for platform, amount in platform_allocations.items():
                platform_percentages[platform] = (amount / current_net_worth) * 100
        
        # Calculate month-on-month and yearly changes using historical data
        mom_change = 0
        mom_amount_change = 0
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
            
            # Calculate changes
            if month_start_total > 0:
                mom_amount_change = current_net_worth - month_start_total
                mom_change = (mom_amount_change / month_start_total) * 100
            
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

        # Calculate platform monthly changes for breakdown section
        platform_monthly_changes = {}
        try:
            current_year = datetime.now().year
            current_month = datetime.now().month
            month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            current_month_name = f"1st {month_names[current_month - 1]}"
            
            current_year_data = get_data_manager().get_networth_data(current_year)
            month_start_data = current_year_data.get(current_month_name, {})
            
            for platform, current_amount in platform_allocations.items():
                previous_amount = month_start_data.get(platform, 0)
                if isinstance(previous_amount, (int, float)) and previous_amount > 0:
                    change_amount = current_amount - previous_amount
                    change_percent = (change_amount / previous_amount) * 100
                    platform_monthly_changes[platform] = {
                        'previous': previous_amount,
                        'amount': change_amount,
                        'percent': change_percent
                    }
                else:
                    platform_monthly_changes[platform] = {
                        'previous': 0,
                        'amount': 0,
                        'percent': 0
                    }
        except Exception as e:
            logging.error(f"Error calculating platform monthly changes: {str(e)}")
            platform_monthly_changes = {}

        # Create response with no-cache headers to prevent browser cache issues
        response = make_response(render_template(get_template_path('dashboard.html'), 
                             # NET WORTH DASHBOARD DATA - Same source as investment manager
                             current_net_worth=current_net_worth,  # Same as "Total Portfolio Value"
                             platform_allocations=platform_allocations,
                             platform_percentages=platform_percentages,
                             platform_monthly_changes=platform_monthly_changes,
                             mom_change=mom_change,
                             mom_amount_change=mom_amount_change,
                             yearly_increase=yearly_increase,
                             yearly_amount_change=yearly_amount_change,
                             platform_colors=PLATFORM_COLORS,
                             current_date=datetime.now().strftime('%B %d, %Y'),
                             # GOAL TRACKING DATA
                             next_target=next_target,
                             progress_info=progress_info,
                             upcoming_targets=upcoming_targets,
                             is_mobile=is_mobile_device()))
        
        # Ultra-strong cache prevention headers
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0, private'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '-1'
        response.headers['Last-Modified'] = datetime.now().strftime('%a, %d %b %Y %H:%M:%S GMT')
        response.headers['ETag'] = f'"{int(time.time())}"'
        return response
    except Exception as e:
        logging.error(f"Error in dashboard: {str(e)}")
        flash(f'Error loading dashboard: {str(e)}', 'error')
        # Clean error response with cache prevention
        response = make_response(render_template(get_template_path('dashboard.html'), 
                             current_date=datetime.now().strftime('%B %d, %Y'),
                             next_target=None,
                             progress_info=None,
                             upcoming_targets=[],
                             is_mobile=is_mobile_device()))
        
        # Apply cache prevention to error response too
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0, private'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '-1'
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
        
        return render_template('mobile/dashboard.html', 
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
                             last_updated=last_updated_bst)
    except Exception as e:
        logging.error(f"Error in mobile dashboard: {str(e)}")
        return render_template('mobile/dashboard.html', 
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
                             chart_data={})

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



def update_all_prices():
    """Update live prices for all investments using optimized batch fetching"""
    global last_price_update
    try:
        data_manager = get_data_manager()
        investments_data = data_manager.get_investments_data()
        
        # Collect all symbols to update
        symbols_to_update = []
        symbol_to_investment = {}
        
        for platform, investments in investments_data.items():
            # Skip cash platforms and ensure investments is a list
            if platform.endswith('_cash') or not isinstance(investments, list):
                continue
                
            for investment in investments:
                symbol = investment.get('symbol')
                if symbol and investment.get('id'):
                    symbols_to_update.append(symbol)
                    symbol_to_investment[symbol] = investment
        
        if not symbols_to_update:
            logging.info("No symbols to update")
            return 0
        
        # Batch fetch prices for efficiency
        logging.info(f"Batch updating prices for {len(symbols_to_update)} investments")
        updated_prices = price_fetcher.get_multiple_prices(symbols_to_update)
        
        # Update database with fetched prices
        updated_count = 0
        for symbol, price in updated_prices.items():
            if symbol in symbol_to_investment:
                investment = symbol_to_investment[symbol]
                try:
                    data_manager.update_investment_price(investment['id'], price)
                    updated_count += 1
                    logging.info(f"Updated {symbol}: £{price}")
                except Exception as e:
                    logging.error(f"Error updating database for {symbol}: {str(e)}")
        
        global last_price_update
        last_price_update = datetime.now()
        logging.info(f'Background price update completed: {updated_count}/{len(symbols_to_update)} prices updated')
        
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
        return redirect(url_for('dashboard'))

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
    """API endpoint for live value updates"""
    # Check for fresh data before serving live values
    ensure_recent_prices()
    
    try:
        # Force database session refresh to ensure API always returns fresh data
        from app import db
        db.session.expire_all()
        
        # Use the unified calculation - SINGLE SOURCE OF TRUTH
        platform_allocations = calculate_platform_totals()
        current_net_worth = sum(platform_allocations.values())
        
        # Get last updated time
        global last_price_update
        last_updated_str = None
        if last_price_update:
            bst = pytz.timezone('Europe/London')
            last_updated_bst = last_price_update.replace(tzinfo=pytz.UTC).astimezone(bst)
            last_updated_str = last_updated_bst.strftime('%d/%m/%Y %H:%M')
        
        return {
            'current_net_worth': current_net_worth,
            'platform_allocations': platform_allocations,
            'last_updated': last_updated_str
        }
    except Exception as e:
        logging.error(f"Error in live values API: {str(e)}")
        return {'error': str(e)}, 500

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
            # Get weekly data from the last 7 days
            cutoff_time = datetime.now() - timedelta(days=7)
            data_points = WeeklyHistoricalNetWorth.query.filter(
                WeeklyHistoricalNetWorth.timestamp >= cutoff_time
            ).order_by(WeeklyHistoricalNetWorth.timestamp.asc()).all()
            
        elif time_filter == 'month':
            # Get monthly data from the last 30 days
            cutoff_time = datetime.now() - timedelta(days=30)
            data_points = MonthlyHistoricalNetWorth.query.filter(
                MonthlyHistoricalNetWorth.timestamp >= cutoff_time
            ).order_by(MonthlyHistoricalNetWorth.timestamp.asc()).all()
            
        elif time_filter == '1m':
            # Get daily data from the last 30 days - using end of day captures
            cutoff_time = datetime.now() - timedelta(days=30)
            data_points = DailyHistoricalNetWorth.query.filter(
                DailyHistoricalNetWorth.timestamp >= cutoff_time
            ).order_by(DailyHistoricalNetWorth.timestamp.asc()).all()
            
        elif time_filter == '3months':
            # Get daily data from the last 90 days
            cutoff_time = datetime.now() - timedelta(days=90)
            data_points = DailyHistoricalNetWorth.query.filter(
                DailyHistoricalNetWorth.timestamp >= cutoff_time
            ).order_by(DailyHistoricalNetWorth.timestamp.asc()).all()
            
        elif time_filter in ['year', '1y']:
            # Get daily data from the last 365 days
            cutoff_time = datetime.now() - timedelta(days=365)
            data_points = DailyHistoricalNetWorth.query.filter(
                DailyHistoricalNetWorth.timestamp >= cutoff_time
            ).order_by(DailyHistoricalNetWorth.timestamp.asc()).all()
            
        elif time_filter in ['2023', '2024', '2025']:
            # Get data from NetworthEntry for specific year
            from models import NetworthEntry
            try:
                year = int(time_filter)
                monthly_data = NetworthEntry.query.filter_by(year=year).all()
                
                # Convert monthly tracker data to chart format  
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
                
                # Sort by parsed month order
                monthly_data.sort(key=lambda x: parse_month_string(x.month))
                
                for month_data in monthly_data:
                    # Create a fake data point object that matches our chart interface
                    class FakeDataPoint:
                        def __init__(self, timestamp, net_worth):
                            self.timestamp = timestamp
                            self.net_worth = net_worth
                    
                    # Create timestamp for the end of each month
                    month_num = parse_month_string(month_data.month)
                    month_end = datetime(year, month_num, 1)
                    if month_num == 12:
                        month_end = datetime(year + 1, 1, 1) - timedelta(days=1)
                    else:
                        month_end = datetime(year, month_num + 1, 1) - timedelta(days=1)
                    
                    data_points.append(FakeDataPoint(month_end, month_data.total_networth))
                
            except Exception as e:
                logging.error(f"Error getting yearly data for {time_filter}: {str(e)}")
                data_points = []
                
        elif time_filter == 'all-years':
            # Get data from NetworthEntry for all years
            from models import NetworthEntry
            try:
                monthly_data = NetworthEntry.query.order_by(NetworthEntry.year.asc()).all()
                
                # Convert monthly tracker data to chart format
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
                
                # Sort by year then month
                monthly_data.sort(key=lambda x: (x.year, parse_month_string(x.month)))
                
                for month_data in monthly_data:
                    # Create a fake data point object that matches our chart interface
                    class FakeDataPoint:
                        def __init__(self, timestamp, net_worth):
                            self.timestamp = timestamp
                            self.net_worth = net_worth
                    
                    # Create timestamp for the end of each month
                    year = month_data.year
                    month_num = parse_month_string(month_data.month)
                    month_end = datetime(year, month_num, 1)
                    if month_num == 12:
                        month_end = datetime(year + 1, 1, 1) - timedelta(days=1)
                    else:
                        month_end = datetime(year, month_num + 1, 1) - timedelta(days=1)
                    
                    data_points.append(FakeDataPoint(month_end, month_data.total_networth))
                
            except Exception as e:
                logging.error(f"Error getting all years data: {str(e)}")
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
                
                if time_filter == 'week':
                    # For weekly data, show day and time (e.g., "Mon 12:00")
                    time_label = bst_time.strftime('%a %H:%M')
                elif time_filter == '1m':
                    # For 1 month data, show date (e.g., "22/08")
                    time_label = bst_time.strftime('%d/%m')
                elif time_filter == 'month':
                    # For monthly data, show date and time (e.g., "22/08 12:00")
                    time_label = bst_time.strftime('%d/%m %H:%M')
                elif time_filter in ['3months', 'year']:
                    # For 3 months/year data, show date (e.g., "22/08")
                    time_label = bst_time.strftime('%d/%m')
                elif time_filter in ['2023', '2024', '2025', 'all-years']:
                    # For yearly data from monthly tracker, show month/year (e.g., "Jan 23")
                    time_label = bst_time.strftime('%b %y')
                
                labels.append(time_label)
                values.append(float(point.net_worth))
        
        return jsonify({
            'labels': labels,
            'values': values,
            'count': len(data_points),
            'filter': time_filter
        })
        
    except Exception as e:
        logging.error(f"Error getting real-time chart data: {str(e)}")
        return jsonify({'error': str(e)}), 500

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
        return redirect(url_for('dashboard'))

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
