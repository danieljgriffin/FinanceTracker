import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from models import db, Investment, PlatformCash, NetworthEntry, Expense, MonthlyCommitment, IncomeData, MonthlyBreakdown

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
        """Add a new investment"""
        investment = Investment(
            platform=platform,
            name=investment_data.get('name', ''),
            symbol=investment_data.get('symbol', ''),
            holdings=investment_data.get('holdings', 0.0),
            amount_spent=investment_data.get('amount_spent', 0.0),
            average_buy_price=investment_data.get('average_buy_price', 0.0),
            current_price=investment_data.get('current_price', 0.0)
        )
        
        db.session.add(investment)
        try:
            db.session.commit()
            self.logger.info(f"Added investment: {investment_data['name']} to {platform}")
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
        """Get all income data"""
        income_entries = IncomeData.query.all()
        data = {}
        
        for entry in income_entries:
            data[entry.year] = {
                'income': entry.income,
                'investment': entry.investment
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
    
    def get_investment_by_symbol(self, symbol: str) -> List[Dict]:
        """Get investments by symbol"""
        investments = Investment.query.filter_by(symbol=symbol).all()
        return [inv.to_dict() for inv in investments]
    
    def find_investment_by_name_and_platform(self, name: str, platform: str) -> Optional[Dict]:
        """Find investment by name and platform"""
        investment = Investment.query.filter_by(name=name, platform=platform).first()
        return investment.to_dict() if investment else None