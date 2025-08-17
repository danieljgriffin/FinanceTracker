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

# Configure logging
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")

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

# Add simple price cache for performance
price_cache = {}
CACHE_DURATION = 300  # 5 minutes cache for API calls

# Initialize data manager
from utils.db_data_manager import DatabaseDataManager

def get_data_manager():
    """Get data manager instance (lazy initialization)"""
    return DatabaseDataManager()

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
@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/service-worker.js')
def service_worker():
    return send_from_directory('static', 'service-worker.js')

@app.route('/static/icons/<path:filename>')
def app_icons(filename):
    return send_from_directory('static/icons', filename)
last_price_update = None
price_update_thread = None

def calculate_current_net_worth():
    """Calculate current net worth using stored investment prices (consistent across dashboard and tracker)"""
    data_manager = get_data_manager()
    investments_data = get_data_manager().get_investments_data()
    current_net_worth = 0
    
    # Calculate platform allocations using current investment values
    for platform, investments in investments_data.items():
        if platform.endswith('_cash'):
            continue  # Skip cash keys only
            
        platform_total = 0
        
        # Calculate investment values (skip for Cash platform since it has no investments)
        if platform != 'Cash':
            platform_total = sum(
                investment.get('holdings', 0) * investment.get('current_price', 0)
                for investment in investments
            )
        
        # Add cash balance (for all platforms including Cash)
        platform_total += get_data_manager().get_platform_cash(platform)
        
        if platform_total > 0:  # Only include platforms with value
            current_net_worth += platform_total
    
    return current_net_worth

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
    try:
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
        
        # Calculate current net worth using shared function
        current_net_worth = calculate_current_net_worth()
        
        # Calculate platform allocations using current investment values - optimized
        platform_allocations = {}
        for platform, investments in investments_data.items():
            if platform.endswith('_cash'):
                continue  # Skip cash keys only
                
            platform_total = 0
            
            # Calculate investment values (skip for Cash platform since it has no investments)
            if platform != 'Cash':
                platform_total = sum(
                    investment.get('holdings', 0) * investment.get('current_price', 0)
                    for investment in investments
                )
            
            # Add cash balance (for all platforms including Cash)
            platform_total += get_data_manager().get_platform_cash(platform)
            
            if platform_total > 0:  # Only include platforms with value
                platform_allocations[platform] = platform_total
        
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
            current_month_num = datetime.now().month
            
            # Get the previous month's data
            if current_month_num == 1:
                # January - compare to December of previous year
                prev_year = current_year - 1
                prev_month_name = '1st Dec'
            else:
                # Other months - use current year
                prev_year = current_year
                month_names = ['', '1st Jan', '1st Feb', '1st Mar', '1st Apr', '1st May', '1st Jun',
                              '1st Jul', '1st Aug', '1st Sep', '1st Oct', '1st Nov', '1st Dec']
                prev_month_name = month_names[current_month_num - 1]
            
            # Get previous month's data
            prev_year_data = get_data_manager().get_networth_data(prev_year)
            prev_month_data = prev_year_data.get(prev_month_name, {})
            
            # Calculate changes for each platform
            for platform, current_value in platform_allocations.items():
                prev_value = prev_month_data.get(platform, 0)
                if isinstance(prev_value, (int, float)) and prev_value > 0:
                    change_amount = current_value - prev_value
                    change_percent = (change_amount / prev_value) * 100
                    platform_monthly_changes[platform] = {
                        'amount': change_amount,
                        'percent': change_percent,
                        'previous': prev_value
                    }
                else:
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
        
        return render_template(get_template_path('dashboard.html'), 
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
                             upcoming_targets=upcoming_targets,
                             is_mobile=is_mobile_device())
    except Exception as e:
        logging.error(f"Error in dashboard: {str(e)}")
        flash(f'Error loading dashboard: {str(e)}', 'error')
        return render_template(get_template_path('dashboard.html'), 
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
                             upcoming_targets=[],
                             is_mobile=is_mobile_device())

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

@app.route('/auto-populate-month', methods=['POST'])
def auto_populate_month():
    """Auto-populate current month with investment data"""
    try:
        year = int(request.form.get('year'))
        # Get current month in the format expected by yearly tracker (e.g., "1st Jul")
        current_day = datetime.now().day
        current_month_abbr = datetime.now().strftime('%b')
        current_month = f"1st {current_month_abbr}"
        
        # Get current investment data
        investments_data = get_data_manager().get_investments_data()
        
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
            cash_balance = get_data_manager().get_platform_cash(platform)
            total_value += cash_balance
            
            if total_value > 0:
                platform_totals[platform] = total_value
        
        # Update monthly values for all platforms
        for platform, value in platform_totals.items():
            get_data_manager().update_monthly_networth(year, current_month, platform, value)
        
        flash(f'Auto-populated {current_month} {year} with current investment data', 'success')
        return redirect(url_for('yearly_tracker', year=year))
    except Exception as e:
        logging.error(f"Error auto-populating month: {str(e)}")
        flash(f'Error auto-populating month: {str(e)}', 'error')
        return redirect(url_for('yearly_tracker'))

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
        
        for platform, platform_investments in investments_data.items():
            if platform.endswith('_cash'):
                continue  # Skip cash keys
            
            # Use list comprehensions for better performance
            platform_investment_total = sum(
                investment.get('holdings', 0) * investment.get('current_price', 0)
                for investment in platform_investments
            )
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
                             data_manager=data_manager)

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

@app.route('/transaction-history')
def transaction_history():
    """View transaction history"""
    try:
        history_data = get_data_manager().get_transaction_history()
        # Sort by timestamp descending (most recent first)
        history_data.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return render_template('transaction_history.html',
                             history_data=history_data,
                             platform_colors=PLATFORM_COLORS)
    except Exception as e:
        logging.error(f"Error in transaction history: {str(e)}")
        flash(f'Error loading transaction history: {str(e)}', 'error')
        return render_template('transaction_history.html',
                             history_data=[],
                             platform_colors=PLATFORM_COLORS)

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
        
        last_price_update = datetime.now()
        logging.info(f'Background price update completed: {updated_count}/{len(symbols_to_update)} prices updated')
        
        return updated_count
        
    except Exception as e:
        logging.error(f"Error updating prices: {str(e)}")
        return 0

def background_price_updater():
    """Background thread function to update prices every 15 minutes"""
    while True:
        try:
            time.sleep(PRICE_REFRESH_INTERVAL)
            # Create Flask application context for database access
            with app.app_context():
                update_all_prices()
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
        # Convert UTC to BST
        last_updated_bst = last_price_update.replace(tzinfo=pytz.UTC).astimezone(bst)
        last_updated_str = last_updated_bst.strftime('%H:%M:%S')
        
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
    """API endpoint to get net worth chart data for different years"""
    try:
        year_param = request.args.get('year', '2025')
        chart_type = request.args.get('type', 'line')  # line or bar
        data_manager = get_data_manager()
        
        labels = []
        values = []
        platform_data = {}  # For stacked bar chart
        
        if year_param == 'all':
            # Get data from all years (2023, 2024, 2025)
            years_to_include = [2023, 2024, 2025]
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

# Start background updater when app starts
start_background_updater()

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
