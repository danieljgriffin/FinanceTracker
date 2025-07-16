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
        
        # Calculate current net worth and platform allocations using live investment values
        current_net_worth = 0
        platform_allocations = {}
        
        # Calculate platform allocations using current investment values
        for platform, investments in investments_data.items():
            if platform.endswith('_cash'):
                continue  # Skip cash keys
                
            platform_total = 0
            
            # Add investment values
            for investment in investments:
                holdings = investment.get('holdings', 0)
                current_price = investment.get('current_price', 0)
                platform_total += holdings * current_price
            
            # Add cash balance
            platform_total += data_manager.get_platform_cash(platform)
            
            platform_allocations[platform] = platform_total
            current_net_worth += platform_total
        
        # Calculate percentage allocations
        total_allocation = sum(platform_allocations.values())
        platform_percentages = {}
        if total_allocation > 0:
            for platform, amount in platform_allocations.items():
                platform_percentages[platform] = (amount / total_allocation) * 100
        
        # Calculate month-on-month change (simplified for demo)
        mom_change = 5.2  # Placeholder for demo - would need historical data tracking
        
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
        contributions_data = data_manager.get_monthly_contributions_data()
        
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
        
        for platform, contributions in contributions_data.items():
            platform_total = 0
            platform_investments[platform] = {
                'investments': contributions,
                'color': PLATFORM_COLORS.get(platform, '#6b7280'),
                'total': 0
            }
            
            for contribution in contributions:
                monthly_amount = contribution.get('monthly_amount', 0)
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
        
        # Calculate totals and metrics from live data
        total_current_value = 0
        total_amount_spent = 0
        platform_totals = {}
        
        for platform, platform_investments in investments_data.items():
            if platform.endswith('_cash'):
                continue  # Skip cash keys
            
            platform_investment_total = 0
            platform_amount_spent = 0
            
            for investment in platform_investments:
                holdings = investment.get('holdings', 0)
                current_price = investment.get('current_price', 0)
                amount_spent = investment.get('amount_spent', 0)
                
                current_value = holdings * current_price
                platform_investment_total += current_value
                platform_amount_spent += amount_spent
                
                total_current_value += current_value
                total_amount_spent += amount_spent
            
            # Add cash to platform total
            cash_balance = data_manager.get_platform_cash(platform)
            platform_total_value = platform_investment_total + cash_balance
            
            # Calculate P/L metrics for this platform
            platform_pl = platform_investment_total - platform_amount_spent  # Only investment P/L, not cash
            platform_percentage_pl = (platform_pl / platform_amount_spent * 100) if platform_amount_spent > 0 else 0
            
            platform_totals[platform] = {
                'total_value': platform_total_value,
                'investment_value': platform_investment_total,
                'amount_spent': platform_amount_spent,
                'total_pl': platform_pl,
                'percentage_pl': platform_percentage_pl,
                'cash_balance': cash_balance
            }
        
        # Get unique investment names for dropdown
        unique_names = data_manager.get_unique_investment_names()
        
        return render_template('investment_manager.html',
                             investments_data=investments_data,
                             platform_colors=PLATFORM_COLORS,
                             platform_totals=platform_totals,
                             total_current_value=total_current_value,
                             total_amount_spent=total_amount_spent,
                             unique_names=unique_names,
                             data_manager=data_manager)
    except Exception as e:
        logging.error(f"Error in investment manager: {str(e)}")
        flash(f'Error loading investment manager: {str(e)}', 'error')
        return render_template('investment_manager.html',
                             investments_data={},
                             platform_colors=PLATFORM_COLORS,
                             platform_totals={},
                             total_current_value=0,
                             total_amount_spent=0,
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
            data_manager.add_investment(platform, name, holdings, amount_spent=amount_spent, symbol=symbol)
        elif input_type == 'average_buy_price':
            average_buy_price = float(request.form.get('average_buy_price', 0))
            if average_buy_price <= 0:
                flash('Average buy price must be greater than 0', 'error')
                return redirect(url_for('investment_manager'))
            data_manager.add_investment(platform, name, holdings, average_buy_price=average_buy_price, symbol=symbol)
        else:
            flash('Invalid input type', 'error')
            return redirect(url_for('investment_manager'))
        
        # Automatically fetch live price if symbol is provided
        if symbol:
            try:
                price = price_fetcher.get_price(symbol)
                if price:
                    # Update the newly added investment with the current price
                    investments_data = data_manager.get_investments_data()
                    if platform in investments_data and investments_data[platform]:
                        # Get the last added investment (most recent)
                        last_investment = investments_data[platform][-1]
                        if last_investment.get('name') == name:
                            last_investment['current_price'] = price
                            last_investment['last_updated'] = datetime.now().isoformat()
                            data_manager.save_investments_data(investments_data)
                            flash(f'Investment {name} added successfully with live price £{price:.4f}', 'success')
                        else:
                            flash(f'Investment {name} added successfully (price fetch failed)', 'success')
                    else:
                        flash(f'Investment {name} added successfully (price fetch failed)', 'success')
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
        history_data = data_manager.get_transaction_history()
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

@app.route('/update-prices')
def update_prices():
    """Update live prices for all investments"""
    try:
        investments_data = data_manager.get_investments_data()
        updated_count = 0
        
        for platform, investments in investments_data.items():
            # Skip cash platforms and ensure investments is a list
            if platform.endswith('_cash') or not isinstance(investments, list):
                continue
                
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

@app.route('/edit-investment/<platform>/<int:index>')
def edit_investment(platform, index):
    """Edit an existing investment"""
    try:
        investments_data = data_manager.get_investments_data()
        
        if platform not in investments_data or index >= len(investments_data[platform]):
            flash('Investment not found', 'error')
            return redirect(url_for('investment_manager'))
        
        investment = investments_data[platform][index]
        unique_names = data_manager.get_unique_investment_names()
        
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

@app.route('/update-investment/<platform>/<int:index>', methods=['POST'])
def update_investment(platform, index):
    """Update an existing investment"""
    try:
        name = request.form.get('name')
        holdings = float(request.form.get('holdings', 0))
        input_type = request.form.get('input_type', 'amount_spent')
        symbol = request.form.get('symbol', '')
        
        if not name or holdings <= 0:
            flash('Investment name and holdings are required', 'error')
            return redirect(url_for('edit_investment', platform=platform, index=index))
        
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
                return redirect(url_for('edit_investment', platform=platform, index=index))
            updates['amount_spent'] = amount_spent
            updates['average_buy_price'] = amount_spent / holdings
        elif input_type == 'average_buy_price':
            average_buy_price = float(request.form.get('average_buy_price', 0))
            if average_buy_price <= 0:
                flash('Average buy price must be greater than 0', 'error')
                return redirect(url_for('edit_investment', platform=platform, index=index))
            updates['average_buy_price'] = average_buy_price
            updates['amount_spent'] = average_buy_price * holdings
        
        data_manager.update_investment(platform, index, updates)
        flash(f'Investment {name} updated successfully', 'success')
        
    except Exception as e:
        logging.error(f"Error updating investment: {str(e)}")
        flash(f'Error updating investment: {str(e)}', 'error')
    
    return redirect(url_for('investment_manager'))

@app.route('/delete-investment/<platform>/<int:index>', methods=['POST'])
def delete_investment(platform, index):
    """Delete an existing investment"""
    try:
        data_manager.remove_investment(platform, index)
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
        data_manager.update_platform_cash(platform, cash_amount)
        flash(f'Cash balance updated for {platform}!', 'success')
    except ValueError:
        flash('Invalid cash amount entered!', 'error')
    except Exception as e:
        logging.error(f"Error updating cash: {str(e)}")
        flash(f'Error updating cash: {str(e)}', 'error')
    
    return redirect(url_for('investment_manager'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
