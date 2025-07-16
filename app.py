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
        
        # Calculate yearly net worth increase (current live portfolio vs previous year end)
        yearly_increase = 0
        try:
            current_year = datetime.now().year
            previous_year = current_year - 1
            
            # Get previous year's December 31st data
            previous_year_data = data_manager.get_networth_data(previous_year)
            previous_year_total = 0
            
            # Try 31st Dec, then 1st Dec as fallback
            dec_data = previous_year_data.get('31st Dec', {})
            if not dec_data:
                dec_data = previous_year_data.get('1st Dec', {})
            
            # Calculate previous year total
            for platform, value in dec_data.items():
                if platform != 'total_net_worth' and isinstance(value, (int, float)):
                    previous_year_total += value
            
            # Calculate percentage increase
            if previous_year_total > 0:
                yearly_increase = ((current_net_worth - previous_year_total) / previous_year_total) * 100
            
        except Exception as e:
            logging.error(f"Error calculating yearly increase: {str(e)}")
            yearly_increase = 0
        
        return render_template('dashboard.html', 
                             current_net_worth=current_net_worth,
                             platform_allocations=platform_allocations,
                             platform_percentages=platform_percentages,
                             mom_change=mom_change,
                             yearly_increase=yearly_increase,
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
                             yearly_increase=0,
                             platform_colors=PLATFORM_COLORS,
                             current_date=datetime.now().strftime('%B %d, %Y'))

@app.route('/yearly-tracker')
@app.route('/yearly-tracker/<int:year>')
def yearly_tracker(year=None):
    """Yearly tracker page with support for multiple years"""
    try:
        # Get available years and set default
        available_years = data_manager.get_available_years()
        if not available_years:
            # Create initial years if none exist
            for initial_year in [2023, 2024, 2025]:
                data_manager.create_new_year(initial_year)
            available_years = [2023, 2024, 2025]
        
        # Use current year or default to 2025
        if year is None:
            year = 2025
        
        # Ensure the requested year exists
        if year not in available_years:
            data_manager.create_new_year(year)
            available_years = data_manager.get_available_years()
        
        networth_data = data_manager.get_networth_data(year)
        investments_data = data_manager.get_investments_data()
        
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
        
        for month in months:
            month_data = networth_data.get(month, {})
            total = 0
            
            for platform in all_platforms:
                platform_value = month_data.get(platform['name'], 0)
                if platform_value and isinstance(platform_value, (int, float)):
                    total += platform_value
            
            monthly_totals[month] = total
            
            # Calculate month-on-month change
            if total > 0 and previous_total > 0:
                change_percent = ((total - previous_total) / previous_total) * 100
                monthly_changes[month] = change_percent
            else:
                monthly_changes[month] = None
            
            if total > 0:
                previous_total = total
        
        # Calculate yearly net worth increase percentage
        yearly_increase_percent = 0
        current_year_int = datetime.now().year
        
        if year == current_year_int:
            # For current year, compare current live portfolio value to previous year's end
            try:
                from utils.price_fetcher import PriceFetcher
                price_fetcher = PriceFetcher()
                
                # Get live portfolio value (from dashboard calculation)
                current_net_worth = 0
                for platform, investments in investments_data.items():
                    if not platform.endswith('_cash'):
                        platform_total = 0
                        for investment in investments:
                            if investment.get('symbol'):
                                live_price = price_fetcher.get_price(investment['symbol'])
                                if live_price:
                                    platform_total += investment['holdings'] * live_price
                        
                        # Add cash balance
                        cash_balance = data_manager.get_platform_cash(platform)
                        platform_total += cash_balance
                        current_net_worth += platform_total
                
                # Get previous year's end value
                previous_year_data = data_manager.get_networth_data(year - 1)
                previous_year_total = 0
                dec_data = previous_year_data.get('31st Dec', {})
                if not dec_data:
                    dec_data = previous_year_data.get('1st Dec', {})
                
                for platform in all_platforms:
                    platform_value = dec_data.get(platform['name'], 0)
                    if platform_value and isinstance(platform_value, (int, float)):
                        previous_year_total += platform_value
                
                if previous_year_total > 0:
                    yearly_increase_percent = ((current_net_worth - previous_year_total) / previous_year_total) * 100
                
            except Exception as e:
                logging.error(f"Error calculating live yearly increase: {str(e)}")
                yearly_increase_percent = 0
        else:
            # For historical years, compare 31st Dec to 1st Jan of same year
            jan_total = monthly_totals.get('1st Jan', 0)
            dec_total = monthly_totals.get('31st Dec', 0)
            
            if jan_total > 0 and dec_total > 0:
                yearly_increase_percent = ((dec_total - jan_total) / jan_total) * 100
        
        return render_template('yearly_tracker.html', 
                             networth_data=networth_data,
                             platforms=all_platforms,
                             months=months,
                             monthly_totals=monthly_totals,
                             monthly_changes=monthly_changes,
                             yearly_increase_percent=yearly_increase_percent,
                             current_year=year,
                             available_years=available_years,
                             platform_colors=PLATFORM_COLORS)
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
                             platform_colors=PLATFORM_COLORS)

@app.route('/tracker-2025')
def tracker_2025():
    """Redirect to yearly tracker for backward compatibility"""
    return redirect(url_for('yearly_tracker', year=2025))

@app.route('/create-year', methods=['POST'])
def create_year():
    """Create a new year for tracking"""
    try:
        year = int(request.form.get('year'))
        if data_manager.create_new_year(year):
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
                
                data_manager.update_monthly_networth(change_year, change_month, change_platform, change_value)
                year = change_year  # Store for redirect
            
            flash(f'Updated {len(changes)} values successfully', 'success')
        else:
            # Single update (legacy support)
            year = int(request.form.get('year'))
            month = request.form.get('month')
            platform = request.form.get('platform')
            value = float(request.form.get('value', 0))
            
            data_manager.update_monthly_networth(year, month, platform, value)
            flash(f'Updated {platform} for {month} {year}', 'success')
    except (ValueError, TypeError) as e:
        flash(f'Error updating value: {str(e)}', 'error')
    
    return redirect(url_for('yearly_tracker', year=year))

@app.route('/auto-populate-month', methods=['POST'])
def auto_populate_month():
    """Auto-populate current month with investment data"""
    try:
        year = int(request.form.get('year'))
        current_month = datetime.now().strftime('%B')
        
        # Get current investment data
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
                            price = float(investment.get('price', 0))
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
        
        flash(f'Auto-populated {current_month} {year} with current investment data', 'success')
        return redirect(url_for('yearly_tracker', year=year))
    except Exception as e:
        logging.error(f"Error auto-populating month: {str(e)}")
        flash(f'Error auto-populating month: {str(e)}', 'error')
        return redirect(url_for('yearly_tracker'))

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
        total_cash = 0
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
            total_cash += cash_balance
            
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
        
        # Calculate overall portfolio metrics (investments + cash)
        total_portfolio_value = total_current_value + total_cash
        total_portfolio_pl = total_portfolio_value - total_amount_spent  # Total portfolio gain vs amount spent
        total_portfolio_percentage_pl = (total_portfolio_pl / total_amount_spent * 100) if total_amount_spent > 0 else 0
        
        # Get unique investment names for dropdown
        unique_names = data_manager.get_unique_investment_names()
        
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
                    investments_data = data_manager.get_investments_data()
                    if platform in investments_data and investments_data[platform]:
                        # Get the last added investment (most recent)
                        last_investment = investments_data[platform][-1]
                        if last_investment.get('name') == name:
                            last_investment['current_price'] = price
                            last_investment['symbol'] = symbol  # Update with working symbol
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
