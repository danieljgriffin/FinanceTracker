import json
import os
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

class DataManager:
    """Handles data persistence and retrieval"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.data_dir = 'data'
        self.ensure_data_dir()
        self.initialize_data_files()
    
    def ensure_data_dir(self):
        """Create data directory if it doesn't exist"""
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
    
    def initialize_data_files(self):
        """Initialize data files with empty structures if they don't exist"""
        
        # Initialize networth data
        networth_file = os.path.join(self.data_dir, 'networth_2025.json')
        if not os.path.exists(networth_file):
            self.save_json_file(networth_file, {})
        
        # Initialize income data
        income_file = os.path.join(self.data_dir, 'income_tracker.json')
        if not os.path.exists(income_file):
            self.save_json_file(income_file, {})
        
        # Initialize investments data
        investments_file = os.path.join(self.data_dir, 'investments.json')
        if not os.path.exists(investments_file):
            initial_investments = {
                'Degiro': [],
                'Trading212 ISA': [],
                'EQ (GSK shares)': [],
                'InvestEngine ISA': [],
                'Crypto': [],
                'HL Stocks & Shares LISA': [],
                'Cash': []
            }
            # Initialize cash balances
            for platform in initial_investments.keys():
                if platform != 'Cash':
                    initial_investments[platform + '_cash'] = 0.0
            self.save_json_file(investments_file, initial_investments)
        
        # Initialize expenses data
        expenses_file = os.path.join(self.data_dir, 'expenses.json')
        if not os.path.exists(expenses_file):
            self.save_json_file(expenses_file, {})
        
        # Initialize monthly contributions data
        contributions_file = os.path.join(self.data_dir, 'monthly_contributions.json')
        if not os.path.exists(contributions_file):
            initial_contributions = {
                'Degiro': [],
                'Trading212 ISA': [],
                'EQ (GSK shares)': [],
                'InvestEngine ISA': [],
                'Crypto': [],
                'HL Stocks & Shares LISA': [],
                'Cash': []
            }
            self.save_json_file(contributions_file, initial_contributions)
        
        # Initialize transaction history data
        history_file = os.path.join(self.data_dir, 'transaction_history.json')
        if not os.path.exists(history_file):
            self.save_json_file(history_file, [])
    
    def load_json_file(self, filepath: str) -> Dict[str, Any]:
        """Load JSON data from file"""
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            self.logger.warning(f"File not found: {filepath}")
            return {}
        except json.JSONDecodeError as e:
            self.logger.error(f"Error parsing JSON from {filepath}: {str(e)}")
            return {}
    
    def save_json_file(self, filepath: str, data: Dict[str, Any]):
        """Save data to JSON file"""
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Error saving data to {filepath}: {str(e)}")
    
    def get_networth_data(self) -> Dict[str, Any]:
        """Get net worth data"""
        return self.load_json_file(os.path.join(self.data_dir, 'networth_2025.json'))
    
    def save_networth_data(self, data: Dict[str, Any]):
        """Save net worth data"""
        self.save_json_file(os.path.join(self.data_dir, 'networth_2025.json'), data)
    
    def get_income_data(self) -> Dict[str, Any]:
        """Get income data"""
        return self.load_json_file(os.path.join(self.data_dir, 'income_tracker.json'))
    
    def save_income_data(self, data: Dict[str, Any]):
        """Save income data"""
        self.save_json_file(os.path.join(self.data_dir, 'income_tracker.json'), data)
    
    def get_investments_data(self) -> Dict[str, Any]:
        """Get investments data"""
        return self.load_json_file(os.path.join(self.data_dir, 'investments.json'))
    
    def save_investments_data(self, data: Dict[str, Any]):
        """Save investments data"""
        self.save_json_file(os.path.join(self.data_dir, 'investments.json'), data)
    
    def get_expenses_data(self) -> Dict[str, Any]:
        """Get expenses data"""
        return self.load_json_file(os.path.join(self.data_dir, 'expenses.json'))
    
    def save_expenses_data(self, data: Dict[str, Any]):
        """Save expenses data"""
        self.save_json_file(os.path.join(self.data_dir, 'expenses.json'), data)
    
    def add_investment(self, platform: str, name: str, holdings: float, amount_spent: float = None, average_buy_price: float = None, symbol: str = ''):
        """Add a new investment transaction"""
        investments_data = self.get_investments_data()
        
        if platform not in investments_data:
            investments_data[platform] = []
        
        # Calculate missing value (amount_spent or average_buy_price)
        if amount_spent is None and average_buy_price is not None:
            amount_spent = holdings * average_buy_price
        elif average_buy_price is None and amount_spent is not None:
            average_buy_price = amount_spent / holdings if holdings > 0 else 0
        elif amount_spent is None and average_buy_price is None:
            raise ValueError("Either amount_spent or average_buy_price must be provided")
        
        # Check if this investment already exists
        existing_investment = None
        for investment in investments_data[platform]:
            if investment['name'] == name:
                existing_investment = investment
                break
        
        transaction_id = f"txn_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        if existing_investment:
            # Record transaction history
            old_holdings = existing_investment['holdings']
            old_amount_spent = existing_investment['amount_spent']
            
            # Update existing investment
            existing_investment['holdings'] += holdings
            existing_investment['amount_spent'] += amount_spent
            existing_investment['average_buy_price'] = existing_investment['amount_spent'] / existing_investment['holdings']
            existing_investment['last_updated'] = datetime.now().isoformat()
            
            # Log transaction
            self.log_transaction(
                transaction_id=transaction_id,
                action="ADD",
                platform=platform,
                investment_name=name,
                holdings=holdings,
                amount_spent=amount_spent,
                average_buy_price=average_buy_price,
                symbol=symbol,
                old_holdings=old_holdings,
                new_holdings=existing_investment['holdings'],
                old_amount_spent=old_amount_spent,
                new_amount_spent=existing_investment['amount_spent']
            )
        else:
            # Create new investment
            investment = {
                'name': name,
                'holdings': holdings,
                'amount_spent': amount_spent,
                'average_buy_price': average_buy_price,
                'symbol': symbol,
                'current_price': 0,  # Will be updated by price fetcher
                'created_at': datetime.now().isoformat(),
                'last_updated': datetime.now().isoformat()
            }
            investments_data[platform].append(investment)
            
            # Log transaction
            self.log_transaction(
                transaction_id=transaction_id,
                action="CREATE",
                platform=platform,
                investment_name=name,
                holdings=holdings,
                amount_spent=amount_spent,
                average_buy_price=average_buy_price,
                symbol=symbol,
                new_holdings=holdings,
                new_amount_spent=amount_spent
            )
        
        self.save_investments_data(investments_data)
    
    def get_unique_investment_names(self) -> list:
        """Get list of unique investment names across all platforms"""
        investments_data = self.get_investments_data()
        names = set()
        
        for platform, investments in investments_data.items():
            for investment in investments:
                names.add(investment['name'])
        
        return sorted(list(names))
    
    def update_investment(self, platform: str, investment_index: int, updates: Dict[str, Any]):
        """Update an existing investment"""
        investments_data = self.get_investments_data()
        
        if platform in investments_data and 0 <= investment_index < len(investments_data[platform]):
            investments_data[platform][investment_index].update(updates)
            investments_data[platform][investment_index]['updated_at'] = datetime.now().isoformat()
            self.save_investments_data(investments_data)
    
    def remove_investment(self, platform: str, investment_index: int):
        """Remove an investment"""
        investments_data = self.get_investments_data()
        
        if platform in investments_data and 0 <= investment_index < len(investments_data[platform]):
            del investments_data[platform][investment_index]
            self.save_investments_data(investments_data)
    
    def get_monthly_contributions_data(self) -> Dict[str, Any]:
        """Get monthly contributions data"""
        return self.load_json_file(os.path.join(self.data_dir, 'monthly_contributions.json'))
    
    def save_monthly_contributions_data(self, data: Dict[str, Any]):
        """Save monthly contributions data"""
        self.save_json_file(os.path.join(self.data_dir, 'monthly_contributions.json'), data)
    
    def add_monthly_contribution(self, platform: str, name: str, monthly_amount: float, symbol: str = ''):
        """Add a new monthly contribution"""
        contributions_data = self.get_monthly_contributions_data()
        
        if platform not in contributions_data:
            contributions_data[platform] = []
        
        contribution = {
            'name': name,
            'monthly_amount': monthly_amount,
            'symbol': symbol,
            'created_at': datetime.now().isoformat()
        }
        
        contributions_data[platform].append(contribution)
        self.save_monthly_contributions_data(contributions_data)
    
    def log_transaction(self, transaction_id: str, action: str, platform: str, investment_name: str, 
                       holdings: float = None, amount_spent: float = None, average_buy_price: float = None,
                       symbol: str = '', old_holdings: float = None, new_holdings: float = None,
                       old_amount_spent: float = None, new_amount_spent: float = None):
        """Log a transaction to the history"""
        history_data = self.get_transaction_history()
        
        transaction = {
            'transaction_id': transaction_id,
            'timestamp': datetime.now().isoformat(),
            'action': action,  # CREATE, ADD, UPDATE, REMOVE
            'platform': platform,
            'investment_name': investment_name,
            'holdings_change': holdings,
            'amount_spent_change': amount_spent,
            'average_buy_price': average_buy_price,
            'symbol': symbol,
            'old_holdings': old_holdings,
            'new_holdings': new_holdings,
            'old_amount_spent': old_amount_spent,
            'new_amount_spent': new_amount_spent
        }
        
        history_data.append(transaction)
        self.save_transaction_history(history_data)
    
    def get_transaction_history(self) -> List[Dict[str, Any]]:
        """Get transaction history data"""
        return self.load_json_file(os.path.join(self.data_dir, 'transaction_history.json'))
    
    def save_transaction_history(self, data: List[Dict[str, Any]]):
        """Save transaction history data"""
        self.save_json_file(os.path.join(self.data_dir, 'transaction_history.json'), data)
    
    def get_platform_cash(self, platform: str) -> float:
        """Get cash balance for a platform"""
        investments = self.get_investments_data()
        cash_key = platform + '_cash'
        return investments.get(cash_key, 0.0)
    
    def update_platform_cash(self, platform: str, amount: float):
        """Update cash balance for a platform"""
        investments = self.get_investments_data()
        cash_key = platform + '_cash'
        investments[cash_key] = amount
        self.save_investments_data(investments)
