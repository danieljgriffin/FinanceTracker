import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from models import db, Investment, PlatformCash, NetworthEntry, Expense, MonthlyCommitment, IncomeData, MonthlyBreakdown, MonthlyInvestment

class DatabaseDataManager:
    """Database-based data manager to replace JSON file storage"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def initialize_defaults(self):
        """Initialize default platform cash entries if they don't exist"""
        default_platforms = [
            'Degiro', 'Trading212 ISA', 'EQ (GSK shares)', 
            'InvestEngine ISA', 'Crypto', 'HL Stocks & Shares LISA', 'Cash'
        ]
        
        for platform in default_platforms:
            if not PlatformCash.query.filter_by(platform=platform).first():
                cash_entry = PlatformCash(platform=platform, cash_balance=0.0)
                db.session.add(cash_entry)
        
        # Initialize monthly breakdown if it doesn't exist
        if not MonthlyBreakdown.query.first():
            breakdown = MonthlyBreakdown(monthly_income=0.0)
            db.session.add(breakdown)
        
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error initializing defaults: {e}")
    
    def get_investments_data(self) -> Dict[str, List[Dict]]:
        """Get all investments organized by platform"""
        investments = Investment.query.all()
        data = {}
        
        # Initialize with empty lists for all platforms
        default_platforms = [
            'Degiro', 'Trading212 ISA', 'EQ (GSK shares)', 
            'InvestEngine ISA', 'Crypto', 'HL Stocks & Shares LISA', 'Cash'
        ]
        
        for platform in default_platforms:
            data[platform] = []
        
        # Group investments by platform
        for investment in investments:
            if investment.platform not in data:
                data[investment.platform] = []
            data[investment.platform].append(investment.to_dict())
        
        return data
    
    def get_platform_investment_names(self, platform: str) -> List[str]:
        """Get all unique investment names for a specific platform"""
        investments = Investment.query.filter_by(platform=platform).all()
        names = [inv.name for inv in investments]
        return sorted(set(names))  # Return unique names sorted alphabetically
    
    def get_all_investment_names(self) -> Dict[str, List[str]]:
        """Get all investment names organized by platform"""
        result = {}
        platforms = [
            'Degiro', 'Trading212 ISA', 'EQ (GSK shares)', 
            'InvestEngine ISA', 'Crypto', 'HL Stocks & Shares LISA', 'Cash'
        ]
        
        for platform in platforms:
            result[platform] = self.get_platform_investment_names(platform)
        
        return result
    
    def get_platform_cash(self, platform: str) -> float:
        """Get cash balance for a platform"""
        cash_entry = PlatformCash.query.filter_by(platform=platform).first()
        return cash_entry.cash_balance if cash_entry else 0.0
    
    def update_platform_cash(self, platform: str, amount: float):
        """Update cash balance for a platform"""
        cash_entry = PlatformCash.query.filter_by(platform=platform).first()
        if cash_entry:
            cash_entry.cash_balance = amount
            cash_entry.last_updated = datetime.utcnow()
        else:
            cash_entry = PlatformCash(platform=platform, cash_balance=amount)
            db.session.add(cash_entry)
        
        try:
            db.session.commit()
            self.logger.info(f"Updated cash for {platform}: £{amount}")
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error updating cash for {platform}: {e}")
            raise
    
    def add_investment(self, platform: str, investment_data: Dict):
        """Add a new investment or aggregate with existing one"""
        name = investment_data.get('name', '')
        holdings = investment_data.get('holdings', 0.0)
        amount_spent = investment_data.get('amount_spent', 0.0)
        average_buy_price = investment_data.get('average_buy_price', 0.0)
        symbol = investment_data.get('symbol', '')
        
        # Check if this investment already exists in the platform
        existing_investment = Investment.query.filter_by(platform=platform, name=name).first()
        
        if existing_investment:
            # Calculate new aggregated values
            old_holdings = existing_investment.holdings
            old_amount_spent = existing_investment.amount_spent
            
            # Add new holdings and amount spent
            new_holdings = old_holdings + holdings
            new_amount_spent = old_amount_spent + amount_spent
            
            # Calculate new average buy price
            new_average_buy_price = new_amount_spent / new_holdings if new_holdings > 0 else 0
            
            # Update existing investment
            existing_investment.holdings = new_holdings
            existing_investment.amount_spent = new_amount_spent
            existing_investment.average_buy_price = new_average_buy_price
            existing_investment.last_updated = datetime.utcnow()
            
            # Update symbol if provided and not already set
            if symbol and not existing_investment.symbol:
                existing_investment.symbol = symbol
            
            try:
                db.session.commit()
                self.logger.info(f"Aggregated investment: {name} in {platform}. Holdings: {old_holdings:.8f} + {holdings:.8f} = {new_holdings:.8f}, Avg Price: £{new_average_buy_price:.2f}")
                return existing_investment.to_dict()
            except Exception as e:
                db.session.rollback()
                self.logger.error(f"Error aggregating investment: {e}")
                raise
        else:
            # Create new investment
            investment = Investment(
                platform=platform,
                name=name,
                symbol=symbol,
                holdings=holdings,
                amount_spent=amount_spent,
                average_buy_price=average_buy_price,
                current_price=investment_data.get('current_price', 0.0)
            )
            
            db.session.add(investment)
            try:
                db.session.commit()
                self.logger.info(f"Added new investment: {name} to {platform}")
                return investment.to_dict()
            except Exception as e:
                db.session.rollback()
                self.logger.error(f"Error adding investment: {e}")
                raise
    
    def update_investment(self, investment_id: int, updates: Dict):
        """Update an existing investment"""
        investment = Investment.query.get(investment_id)
        if not investment:
            raise ValueError(f"Investment with ID {investment_id} not found")
        
        for key, value in updates.items():
            if hasattr(investment, key):
                setattr(investment, key, value)
        
        investment.last_updated = datetime.utcnow()
        
        try:
            db.session.commit()
            self.logger.info(f"Updated investment ID {investment_id}")
            return investment.to_dict()
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error updating investment: {e}")
            raise
    
    def delete_investment(self, investment_id: int):
        """Delete an investment"""
        investment = Investment.query.get(investment_id)
        if not investment:
            raise ValueError(f"Investment with ID {investment_id} not found")
        
        db.session.delete(investment)
        try:
            db.session.commit()
            self.logger.info(f"Deleted investment ID {investment_id}")
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error deleting investment: {e}")
            raise
    
    def get_networth_data(self, year: int = 2025) -> Dict:
        """Get networth data for a specific year"""
        entries = NetworthEntry.query.filter_by(year=year).all()
        data = {}
        
        for entry in entries:
            data[entry.month] = entry.get_platform_data()
        
        return data
    
    def save_networth_data(self, year: int, month: str, platform_data: Dict, total_networth: float = 0.0):
        """Save networth data for a specific year and month"""
        entry = NetworthEntry.query.filter_by(year=year, month=month).first()
        
        if entry:
            entry.set_platform_data(platform_data)
            entry.total_networth = total_networth
        else:
            entry = NetworthEntry(
                year=year,
                month=month,
                total_networth=total_networth
            )
            entry.set_platform_data(platform_data)
            db.session.add(entry)
        
        try:
            db.session.commit()
            self.logger.info(f"Saved networth data for {month} {year}")
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error saving networth data: {e}")
            raise
    
    def get_expenses(self) -> List[Dict]:
        """Get all expenses"""
        expenses = Expense.query.all()
        return [expense.to_dict() for expense in expenses]
    
    def add_expense(self, name: str, monthly_amount: float):
        """Add a new expense"""
        expense = Expense(name=name, monthly_amount=monthly_amount)
        db.session.add(expense)
        
        try:
            db.session.commit()
            self.logger.info(f"Added expense: {name}")
            return expense.to_dict()
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error adding expense: {e}")
            raise
    
    def update_expense(self, expense_id: int, name: str, monthly_amount: float):
        """Update an existing expense"""
        expense = Expense.query.get(expense_id)
        if not expense:
            raise ValueError(f"Expense with ID {expense_id} not found")
        
        expense.name = name
        expense.monthly_amount = monthly_amount
        
        try:
            db.session.commit()
            self.logger.info(f"Updated expense ID {expense_id}")
            return expense.to_dict()
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error updating expense: {e}")
            raise
    
    def delete_expense(self, expense_id: int):
        """Delete an expense"""
        expense = Expense.query.get(expense_id)
        if not expense:
            raise ValueError(f"Expense with ID {expense_id} not found")
        
        db.session.delete(expense)
        try:
            db.session.commit()
            self.logger.info(f"Deleted expense ID {expense_id}")
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error deleting expense: {e}")
            raise
    
    def get_monthly_commitments(self) -> Dict[str, List[Dict]]:
        """Get all monthly investment commitments organized by platform"""
        commitments = MonthlyCommitment.query.all()
        data = {}
        
        for commitment in commitments:
            if commitment.platform not in data:
                data[commitment.platform] = []
            data[commitment.platform].append(commitment.to_dict())
        
        return data
    
    def add_monthly_commitment(self, platform: str, name: str, monthly_amount: float):
        """Add a new monthly investment commitment"""
        commitment = MonthlyCommitment(
            platform=platform,
            name=name,
            monthly_amount=monthly_amount
        )
        db.session.add(commitment)
        
        try:
            db.session.commit()
            self.logger.info(f"Added monthly commitment: {name} to {platform}")
            return commitment.to_dict()
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error adding monthly commitment: {e}")
            raise
    
    def update_monthly_commitment(self, commitment_id: int, name: str, monthly_amount: float):
        """Update an existing monthly commitment"""
        commitment = MonthlyCommitment.query.get(commitment_id)
        if not commitment:
            raise ValueError(f"Monthly commitment with ID {commitment_id} not found")
        
        commitment.name = name
        commitment.monthly_amount = monthly_amount
        
        try:
            db.session.commit()
            self.logger.info(f"Updated monthly commitment ID {commitment_id}")
            return commitment.to_dict()
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error updating monthly commitment: {e}")
            raise
    
    def delete_monthly_commitment(self, commitment_id: int):
        """Delete a monthly commitment"""
        commitment = MonthlyCommitment.query.get(commitment_id)
        if not commitment:
            raise ValueError(f"Monthly commitment with ID {commitment_id} not found")
        
        db.session.delete(commitment)
        try:
            db.session.commit()
            self.logger.info(f"Deleted monthly commitment ID {commitment_id}")
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error deleting monthly commitment: {e}")
            raise
    
    def get_income_data(self) -> Dict:
        """Get all income data in format expected by templates"""
        income_entries = IncomeData.query.all()
        data = {}
        
        for entry in income_entries:
            data[entry.year] = {
                'take_home_income': entry.income,
                'amount_invested': entry.investment
            }
        
        return data
    
    def update_income_data(self, year: str, income: float = None, investment: float = None):
        """Update income data for a specific year"""
        entry = IncomeData.query.filter_by(year=year).first()
        
        if entry:
            if income is not None:
                entry.income = income
            if investment is not None:
                entry.investment = investment
        else:
            entry = IncomeData(
                year=year,
                income=income or 0.0,
                investment=investment or 0.0
            )
            db.session.add(entry)
        
        try:
            db.session.commit()
            self.logger.info(f"Updated income data for {year}")
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error updating income data: {e}")
            raise
    
    def save_income_data(self, income_data: Dict):
        """Save income data from template format (take_home_income, amount_invested)"""
        for year, data in income_data.items():
            # Convert template format to database format
            income = data.get('take_home_income', 0.0)
            investment = data.get('amount_invested', 0.0)
            
            # Update or create entry
            entry = IncomeData.query.filter_by(year=year).first()
            if entry:
                entry.income = income
                entry.investment = investment
            else:
                entry = IncomeData(year=year, income=income, investment=investment)
                db.session.add(entry)
        
        try:
            db.session.commit()
            self.logger.info(f"Saved income data for {len(income_data)} years")
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error saving income data: {e}")
            raise
    
    def get_monthly_breakdown(self) -> Dict:
        """Get monthly breakdown data"""
        breakdown = MonthlyBreakdown.query.first()
        if breakdown:
            return breakdown.to_dict()
        return {'monthly_income': 0.0}
    
    def update_monthly_income(self, monthly_income: float):
        """Update monthly income"""
        breakdown = MonthlyBreakdown.query.first()
        
        if breakdown:
            breakdown.monthly_income = monthly_income
            breakdown.last_updated = datetime.utcnow()
        else:
            breakdown = MonthlyBreakdown(monthly_income=monthly_income)
            db.session.add(breakdown)
        
        try:
            db.session.commit()
            self.logger.info(f"Updated monthly income: £{monthly_income}")
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error updating monthly income: {e}")
            raise
    
    def get_monthly_investments(self, year: int = None) -> Dict:
        """Get monthly investment data, optionally filtered by year"""
        if year:
            investments = MonthlyInvestment.query.filter_by(year=year).order_by(MonthlyInvestment.month).all()
        else:
            investments = MonthlyInvestment.query.order_by(MonthlyInvestment.year, MonthlyInvestment.month).all()
        
        data = {}
        for investment in investments:
            if investment.year not in data:
                data[investment.year] = {}
            data[investment.year][investment.month] = investment.to_dict()
        
        return data
    
    def add_monthly_investment(self, year: int, month: int, month_name: str, income_received: float, amount_invested: float):
        """Add or update monthly investment data"""
        existing = MonthlyInvestment.query.filter_by(year=year, month=month).first()
        
        if existing:
            existing.income_received = income_received
            existing.amount_invested = amount_invested
            existing.updated_at = datetime.utcnow()
        else:
            investment = MonthlyInvestment(
                year=year,
                month=month,
                month_name=month_name,
                income_received=income_received,
                amount_invested=amount_invested
            )
            db.session.add(investment)
        
        try:
            db.session.commit()
            self.logger.info(f"Updated monthly investment for {month_name} {year}: Income £{income_received}, Invested £{amount_invested}")
            return existing.to_dict() if existing else investment.to_dict()
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error updating monthly investment: {e}")
            raise
    
    def get_current_net_worth(self) -> float:
        """Get the most recent net worth value"""
        # Get the most recent entry with a positive net worth
        latest_entry = NetworthEntry.query.filter(NetworthEntry.total_networth > 0).order_by(
            NetworthEntry.year.desc(), 
            NetworthEntry.id.desc()
        ).first()
        
        if latest_entry:
            return latest_entry.total_networth
        
        # If no entries found, return 0
        return 0.0
    
    def get_chart_data_with_invested(self):
        """Generate simple chart data showing just portfolio value"""
        # Get data directly from database
        entries = NetworthEntry.query.filter(NetworthEntry.total_networth > 0).all()
        
        chart_data = {
            'labels': [],
            'value_line': []
        }
        
        self.logger.info(f"Found {len(entries)} networth entries with data")
        
        # Create a proper sorting key for chronological order
        def get_sort_key(entry):
            # Month order mapping
            month_order = {
                '1st Jan': 1, '1st Feb': 2, '1st Mar': 3, '1st Apr': 4, 
                '1st May': 5, '1st Jun': 6, '1st Jul': 7, '1st Aug': 8, 
                '1st Sep': 9, '1st Oct': 10, '1st Nov': 11, '1st Dec': 12, 
                '31st Dec': 13
            }
            return (entry.year, month_order.get(entry.month, 0))
        
        # Sort entries chronologically
        sorted_entries = sorted(entries, key=get_sort_key)
        
        for entry in sorted_entries:
            # Add to chart data
            month_label = entry.month.replace('1st ', '').replace('31st ', '')
            chart_data['labels'].append(f"{month_label} {entry.year}")
            chart_data['value_line'].append(entry.total_networth)
        
        self.logger.info(f"Generated chart data with {len(chart_data['labels'])} points")
        self.logger.info(f"Latest entry: {chart_data['labels'][-1] if chart_data['labels'] else 'None'}")
        return chart_data
    
    def _get_month_number_from_key(self, month_key: str) -> int:
        """Convert month key like '1st Jan' to month number 1"""
        month_mapping = {
            'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
            'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
        }
        
        # Extract month name from key like "1st Jan"
        month_part = month_key.replace('1st ', '')
        return month_mapping.get(month_part, 1)
    
    def get_unique_investment_names(self) -> List[str]:
        """Get unique investment names across all platforms"""
        investments = Investment.query.all()
        names = list(set([inv.name for inv in investments if inv.name]))
        return sorted(names)
    
    def get_available_years(self) -> List[int]:
        """Get all available years from networth data"""
        years = db.session.query(NetworthEntry.year).distinct().all()
        return sorted([year[0] for year in years])
    
    def create_new_year(self, year: int):
        """Create a new year with default months"""
        default_months = [
            '1st Jan', '1st Feb', '1st Mar', '1st Apr', '1st May', '1st Jun',
            '1st Jul', '1st Aug', '1st Sep', '1st Oct', '1st Nov', '1st Dec',
            '31st Dec'
        ]
        
        for month in default_months:
            if not NetworthEntry.query.filter_by(year=year, month=month).first():
                entry = NetworthEntry(year=year, month=month, total_networth=0.0)
                entry.set_platform_data({})
                db.session.add(entry)
        
        try:
            db.session.commit()
            self.logger.info(f"Created new year: {year}")
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error creating new year: {e}")
            raise
    
    def save_networth_month_data(self, year: int, month: str, platform_data: Dict):
        """Save networth data for a specific month"""
        total_networth = sum(v for v in platform_data.values() if isinstance(v, (int, float)))
        self.save_networth_data(year, month, platform_data, total_networth)
    
    def get_asset_class_allocation(self):
        """Calculate asset class allocation breakdown by actual investment types"""
        investments = Investment.query.all()
        
        asset_classes = {
            'Individual Stocks': 0.0,
            'Index Funds/ETFs': 0.0,
            'Cryptocurrency': 0.0,
            'Cash': 0.0
        }
        
        # Calculate investment values based on actual investment types
        for investment in investments:
            value = (investment.holdings or 0) * (investment.current_price or 0)
            name = investment.name.lower() if investment.name else ''
            
            # Categorize by actual investment type, not platform
            if investment.platform in ['Crypto']:
                asset_classes['Cryptocurrency'] += value
            elif any(term in name for term in ['s&p', 'sp500', 'index', 'etf', 'fund', 'vanguard', 'ishares', 'spdr']):
                # Index funds and ETFs (regardless of platform)
                asset_classes['Index Funds/ETFs'] += value
            elif any(term in name for term in ['gsk', 'glaxosmithkline']) or investment.platform == 'EQ (GSK shares)':
                # Individual company stocks
                asset_classes['Individual Stocks'] += value
            else:
                # For other investments, try to categorize based on name patterns
                if any(term in name for term in ['apple', 'microsoft', 'tesla', 'nvidia', 'amazon', 'google', 'meta']):
                    asset_classes['Individual Stocks'] += value
                else:
                    # Default to index funds for most ISA/general investments
                    asset_classes['Index Funds/ETFs'] += value
        
        # Add cash balances from platform data
        try:
            cash_platforms = ['Cash']
            for platform in cash_platforms:
                cash_balance = self.get_platform_cash(platform)
                if cash_balance:
                    asset_classes['Cash'] += cash_balance
        except Exception as e:
            self.logger.warning(f"Could not get cash balances: {e}")
        
        # Remove zero values and calculate percentages
        total_value = sum(asset_classes.values())
        if total_value > 0:
            asset_classes = {k: v for k, v in asset_classes.items() if v > 0}
            asset_percentages = {k: (v / total_value) * 100 for k, v in asset_classes.items()}
        else:
            asset_percentages = {}
        
        return {
            'values': asset_classes,
            'percentages': asset_percentages,
            'total': total_value
        }
    
    def get_geographic_sector_allocation(self):
        """Calculate geographic and sector allocation"""
        investments = Investment.query.all()
        
        allocations = {
            'United States (Tech)': 0.0,
            'United States (Healthcare)': 0.0,
            'United Kingdom': 0.0,
            'Cryptocurrency': 0.0,
            'Global/Emerging Markets': 0.0
        }
        
        for investment in investments:
            # Use holdings attribute instead of quantity
            value = (investment.holdings or 0) * (investment.current_price or 0)
            name = investment.name.lower() if investment.name else ''
            
            # Categorize based on investment name and platform
            if investment.platform in ['Crypto']:
                allocations['Cryptocurrency'] += value
            elif 'gsk' in name or investment.platform == 'EQ (GSK shares)':
                allocations['United Kingdom'] += value
            elif any(term in name for term in ['s&p', 'sp500', 'nasdaq', 'apple', 'microsoft', 'tesla', 'nvidia']):
                # S&P 500 and US tech stocks
                if any(term in name for term in ['tech', 'apple', 'microsoft', 'tesla', 'nvidia', 'nasdaq']):
                    allocations['United States (Tech)'] += value
                else:
                    allocations['United States (Tech)'] += value  # S&P 500 is heavily tech-weighted
            elif any(term in name for term in ['emerging', 'world', 'global', 'international']):
                allocations['Global/Emerging Markets'] += value
            else:
                # Default categorization based on platform
                if investment.platform in ['Trading212 ISA', 'InvestEngine ISA']:
                    allocations['United States (Tech)'] += value  # Most ISA investments are US-focused
                else:
                    allocations['United Kingdom'] += value
        
        # Remove zero values and calculate percentages
        total_value = sum(allocations.values())
        if total_value > 0:
            allocations = {k: v for k, v in allocations.items() if v > 0}
            percentages = {k: (v / total_value) * 100 for k, v in allocations.items()}
        else:
            percentages = {}
        
        return {
            'values': allocations,
            'percentages': percentages,
            'total': total_value
        }
    
    def update_investment_price(self, investment_id: int, current_price: float):
        """Update current price for an investment"""
        investment = Investment.query.get(investment_id)
        if investment:
            investment.current_price = current_price
            investment.last_updated = datetime.utcnow()
            try:
                db.session.commit()
                self.logger.info(f"Updated price for investment ID {investment_id}: £{current_price}")
            except Exception as e:
                db.session.rollback()
                self.logger.error(f"Error updating investment price: {e}")
                raise
    
    def remove_investment_by_id(self, investment_id: int):
        """Remove an investment by ID"""
        try:
            investment = Investment.query.get(investment_id)
            
            if not investment:
                raise ValueError(f"Investment with ID {investment_id} not found")
            
            self.logger.info(f"Deleting investment: {investment.name} from {investment.platform}")
            
            # Delete the investment
            db.session.delete(investment)
            db.session.commit()
            
            self.logger.info(f"Successfully deleted investment: {investment.name}")
            
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error deleting investment: {e}")
            raise
    
    def remove_investment(self, platform: str, index: int):
        """Remove an investment by platform and index (legacy method for backward compatibility)"""
        try:
            # Get investments for the platform
            investments = Investment.query.filter_by(platform=platform).all()
            
            if index < 0 or index >= len(investments):
                raise ValueError(f"Investment index {index} out of range for platform {platform}")
            
            # Get the investment to delete
            investment_to_delete = investments[index]
            
            self.logger.info(f"Deleting investment: {investment_to_delete.name} from {platform}")
            
            # Delete the investment
            db.session.delete(investment_to_delete)
            db.session.commit()
            
            self.logger.info(f"Successfully deleted investment: {investment_to_delete.name}")
            
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error deleting investment: {e}")
            raise
    
    def update_monthly_networth(self, year: int, month: str, platform: str, value: float):
        """Update or create networth entry for a specific platform, month, and year"""
        # Find or create the networth entry for this year and month
        entry = NetworthEntry.query.filter_by(year=year, month=month).first()
        
        if not entry:
            # Create new entry if it doesn't exist
            entry = NetworthEntry(year=year, month=month, total_networth=0.0)
            entry.set_platform_data({})
            db.session.add(entry)
        
        # Get current platform data
        platform_data = entry.get_platform_data()
        
        # Update the specific platform value
        platform_data[platform] = value
        
        # Update the entry with new platform data
        entry.set_platform_data(platform_data)
        
        # Recalculate total networth
        total_networth = sum(v for v in platform_data.values() if isinstance(v, (int, float)))
        entry.total_networth = total_networth
        entry.last_updated = datetime.utcnow()
        
        try:
            db.session.commit()
            self.logger.info(f"Updated {platform} networth for {month} {year}: £{value}")
        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Error updating monthly networth: {e}")
            raise
    
    def get_investment_by_symbol(self, symbol: str) -> List[Dict]:
        """Get investments by symbol"""
        investments = Investment.query.filter_by(symbol=symbol).all()
        return [inv.to_dict() for inv in investments]
    
    def find_investment_by_name_and_platform(self, name: str, platform: str) -> Optional[Dict]:
        """Find investment by name and platform"""
        investment = Investment.query.filter_by(name=name, platform=platform).first()
        return investment.to_dict() if investment else None
    
    def get_monthly_breakdown_data(self) -> Dict:
        """Get monthly breakdown data including expenses and investment commitments"""
        breakdown = self.get_monthly_breakdown()
        expenses = self.get_expenses()
        commitments = self.get_monthly_commitments()
        
        # Calculate totals
        total_monthly_expenses = sum(exp['monthly_amount'] for exp in expenses)
        total_annual_expenses = total_monthly_expenses * 12
        
        # Calculate investment commitment totals by platform
        platform_investments = {}
        total_monthly_investments = 0
        
        for platform, commitment_list in commitments.items():
            platform_total = sum(comm['monthly_amount'] for comm in commitment_list)
            if platform_total > 0:
                platform_investments[platform] = {
                    'investments': commitment_list,
                    'total': platform_total,
                    'color': self._get_platform_color(platform)
                }
                total_monthly_investments += platform_total
        
        total_annual_investments = total_monthly_investments * 12
        
        # Calculate free cash
        monthly_income = breakdown.get('monthly_income', 0.0)
        annual_income = monthly_income * 12
        free_cash_monthly = monthly_income - (total_monthly_expenses + total_monthly_investments)
        free_cash_annual = free_cash_monthly * 12
        
        return {
            'monthly_income': monthly_income,
            'annual_income': annual_income,
            'monthly_expenses': expenses,
            'total_monthly_expenses': total_monthly_expenses,
            'total_annual_expenses': total_annual_expenses,
            'platform_investments': platform_investments,
            'total_monthly_investments': total_monthly_investments,
            'total_annual_investments': total_annual_investments,
            'free_cash_monthly': free_cash_monthly,
            'free_cash_annual': free_cash_annual
        }
    
    def _get_platform_color(self, platform: str) -> str:
        """Get color for platform"""
        colors = {
            'Degiro': '#1e3a8a',
            'Trading212 ISA': '#0d9488',
            'EQ (GSK shares)': '#dc2626',
            'InvestEngine ISA': '#ea580c',
            'Crypto': '#7c3aed',
            'HL Stocks & Shares LISA': '#0ea5e9',
            'Cash': '#059669'
        }
        return colors.get(platform, '#6b7280')
    
    def delete_expense_by_name(self, name: str):
        """Delete expense by name"""
        expense = Expense.query.filter_by(name=name).first()
        if expense:
            db.session.delete(expense)
            try:
                db.session.commit()
                self.logger.info(f"Deleted expense: {name}")
            except Exception as e:
                db.session.rollback()
                self.logger.error(f"Error deleting expense: {e}")
                raise
        else:
            raise ValueError(f"Expense '{name}' not found")
    
    def update_expense_by_name(self, old_name: str, new_name: str, monthly_amount: float):
        """Update expense by name"""
        expense = Expense.query.filter_by(name=old_name).first()
        if expense:
            expense.name = new_name
            expense.monthly_amount = monthly_amount
            try:
                db.session.commit()
                self.logger.info(f"Updated expense: {old_name} -> {new_name}")
                return expense.to_dict()
            except Exception as e:
                db.session.rollback()
                self.logger.error(f"Error updating expense: {e}")
                raise
        else:
            raise ValueError(f"Expense '{old_name}' not found")
    
    def delete_commitment_by_platform_and_name(self, platform: str, name: str):
        """Delete monthly commitment by platform and name"""
        commitment = MonthlyCommitment.query.filter_by(platform=platform, name=name).first()
        if commitment:
            db.session.delete(commitment)
            try:
                db.session.commit()
                self.logger.info(f"Deleted commitment: {name} from {platform}")
            except Exception as e:
                db.session.rollback()
                self.logger.error(f"Error deleting commitment: {e}")
                raise
        else:
            raise ValueError(f"Commitment '{name}' not found in {platform}")
    
    def update_commitment_by_platform_and_name(self, platform: str, old_name: str, new_name: str, monthly_amount: float):
        """Update monthly commitment by platform and name"""
        commitment = MonthlyCommitment.query.filter_by(platform=platform, name=old_name).first()
        if commitment:
            commitment.name = new_name
            commitment.monthly_amount = monthly_amount
            try:
                db.session.commit()
                self.logger.info(f"Updated commitment: {old_name} -> {new_name} in {platform}")
                return commitment.to_dict()
            except Exception as e:
                db.session.rollback()
                self.logger.error(f"Error updating commitment: {e}")
                raise
        else:
            raise ValueError(f"Commitment '{old_name}' not found in {platform}")