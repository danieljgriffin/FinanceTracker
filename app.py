import os
import logging
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from utils.price_fetcher import PriceFetcher
from utils.data_manager import DataManager
from datetime import datetime
import json

# Configure logging
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")

# Initialize utilities
price_fetcher = PriceFetcher()
data_manager = DataManager()

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
        networth_data = data_manager.get_networth_data()
        investments_data = data_manager.get_investments_data()
        
        # Calculate current net worth
        current_month = datetime.now().strftime('%B')
        current_net_worth = 0
        platform_allocations = {}
        
        if networth_data and current_month in networth_data:
            current_net_worth = networth_data[current_month].get('total_net_worth', 0)
            
            # Calculate platform allocations
            for platform, investments in investments_data.items():
                platform_total = 0
                for investment in investments:
                    if current_month in networth_data and investment['name'] in networth_data[current_month]:
                        platform_total += networth_data[current_month][investment['name']]
                platform_allocations[platform] = platform_total
        
        # Calculate percentage allocations
        total_allocation = sum(platform_allocations.values())
        platform_percentages = {}
        if total_allocation > 0:
            for platform, amount in platform_allocations.items():
                platform_percentages[platform] = (amount / total_allocation) * 100
        
        # Calculate month-on-month change
        previous_month = 'November'  # Simplified for demo
        mom_change = 0
        if networth_data and previous_month in networth_data:
            prev_net_worth = networth_data[previous_month].get('total_net_worth', 0)
            if prev_net_worth > 0:
                mom_change = ((current_net_worth - prev_net_worth) / prev_net_worth) * 100
        
        return render_template('dashboard.html', 
                             current_net_worth=current_net_worth,
                             platform_allocations=platform_allocations,
                             platform_percentages=platform_percentages,
                             mom_change=mom_change,
                             platform_colors=PLATFORM_COLORS,
                             current_date=datetime.now().strftime('%B %d, %Y'))
    except Exception as e:
        logging.error(f"Error in dashboard: {str(e)}")
        flash(f'Error loading dashboard: {str(e)}', 'error')
        return render_template('dashboard.html', 
                             current_net_worth=0,
                             platform_allocations={},
                             platform_percentages={},
                             mom_change=0,
                             platform_colors=PLATFORM_COLORS,
                             current_date=datetime.now().strftime('%B %d, %Y'))

@app.route('/tracker-2025')
def tracker_2025():
    """2025 monthly tracker page"""
    try:
        networth_data = data_manager.get_networth_data()
        investments_data = data_manager.get_investments_data()
        
        months = ['January', 'February', 'March', 'April', 'May', 'June',
                 'July', 'August', 'September', 'October', 'November', 'December']
        
        # Get all unique investments
        all_investments = []
        for platform, investments in investments_data.items():
            for investment in investments:
                all_investments.append({
                    'name': investment['name'],
                    'platform': platform,
                    'color': PLATFORM_COLORS.get(platform, '#6b7280')
                })
        
        return render_template('tracker_2025.html', 
                             networth_data=networth_data,
                             investments=all_investments,
                             months=months,
                             platform_colors=PLATFORM_COLORS)
    except Exception as e:
        logging.error(f"Error in tracker 2025: {str(e)}")
        flash(f'Error loading 2025 tracker: {str(e)}', 'error')
        return render_template('tracker_2025.html', 
                             networth_data={},
                             investments=[],
                             months=[],
                             platform_colors=PLATFORM_COLORS)

@app.route('/income-investments')
def income_investments():
    """Income vs Investment tracker"""
    try:
        income_data = data_manager.get_income_data()
        years = list(range(2017, 2026))  # 2017-2025
        
        return render_template('income_investments.html',
                             income_data=income_data,
                             years=years)
    except Exception as e:
        logging.error(f"Error in income investments: {str(e)}")
        flash(f'Error loading income vs investments: {str(e)}', 'error')
        return render_template('income_investments.html',
                             income_data={},
                             years=[])

@app.route('/monthly-breakdown')
def monthly_breakdown():
    """Monthly breakdown page with income, expenses, and investments"""
    try:
        current_month = request.args.get('month', datetime.now().strftime('%B'))
        
        # Get data for current month
        income_data = data_manager.get_income_data()
        expenses_data = data_manager.get_expenses_data()
        investments_data = data_manager.get_investments_data()
        
        # Calculate monthly income
        monthly_income = 0
        if current_month in income_data:
            monthly_income = income_data[current_month].get('take_home_income', 0)
        
        # Calculate total expenses
        total_monthly_expenses = 0
        monthly_expenses = []
        if current_month in expenses_data:
            for expense in expenses_data[current_month]:
                monthly_expenses.append(expense)
                total_monthly_expenses += expense.get('monthly_amount', 0)
        
        # Calculate investment totals by platform
        platform_investments = {}
        total_monthly_investments = 0
        
        for platform, investments in investments_data.items():
            platform_total = 0
            platform_investments[platform] = {
                'investments': investments,
                'color': PLATFORM_COLORS.get(platform, '#6b7280'),
                'total': 0
            }
            
            for investment in investments:
                monthly_amount = investment.get('monthly_amount', 0)
                platform_total += monthly_amount
                total_monthly_investments += monthly_amount
            
            platform_investments[platform]['total'] = platform_total
        
        # Calculate free cash
        free_cash_monthly = monthly_income - total_monthly_expenses - total_monthly_investments
        free_cash_annual = free_cash_monthly * 12
        
        return render_template('monthly_breakdown.html',
                             current_month=current_month,
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
                             current_month='January',
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
        investments_data = data_manager.get_investments_data()
        return render_template('investment_manager.html',
                             investments_data=investments_data,
                             platform_colors=PLATFORM_COLORS)
    except Exception as e:
        logging.error(f"Error in investment manager: {str(e)}")
        flash(f'Error loading investment manager: {str(e)}', 'error')
        return render_template('investment_manager.html',
                             investments_data={},
                             platform_colors=PLATFORM_COLORS)

@app.route('/add-investment', methods=['POST'])
def add_investment():
    """Add new investment"""
    try:
        platform = request.form.get('platform')
        name = request.form.get('name')
        monthly_amount = float(request.form.get('monthly_amount', 0))
        symbol = request.form.get('symbol', '')
        
        if not platform or not name:
            flash('Platform and investment name are required', 'error')
            return redirect(url_for('investment_manager'))
        
        # Add investment to data
        data_manager.add_investment(platform, name, monthly_amount, symbol)
        flash(f'Investment {name} added successfully', 'success')
        
    except Exception as e:
        logging.error(f"Error adding investment: {str(e)}")
        flash(f'Error adding investment: {str(e)}', 'error')
    
    return redirect(url_for('investment_manager'))

@app.route('/update-prices')
def update_prices():
    """Update live prices for all investments"""
    try:
        investments_data = data_manager.get_investments_data()
        updated_count = 0
        
        for platform, investments in investments_data.items():
            for investment in investments:
                if investment.get('symbol'):
                    try:
                        price = price_fetcher.get_price(investment['symbol'])
                        if price:
                            investment['current_price'] = price
                            investment['last_updated'] = datetime.now().isoformat()
                            updated_count += 1
                    except Exception as e:
                        logging.error(f"Error updating price for {investment['name']}: {str(e)}")
        
        # Save updated data
        data_manager.save_investments_data(investments_data)
        flash(f'Updated prices for {updated_count} investments', 'success')
        
    except Exception as e:
        logging.error(f"Error updating prices: {str(e)}")
        flash(f'Error updating prices: {str(e)}', 'error')
    
    return redirect(url_for('investment_manager'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
