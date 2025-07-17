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
        
        # Initialize monthly breakdown data
        breakdown_file = os.path.join(self.data_dir, 'monthly_breakdown.json')
        if not os.path.exists(breakdown_file):
            initial_breakdown = {
                'monthly_income': 0,
                'expenses': [],
                'investment_commitments': {
                    'Degiro': [],
                    'Trading212 ISA': [],
                    'EQ (GSK shares)': [],
                    'InvestEngine ISA': [],
                    'Crypto': [],
                    'HL Stocks & Shares LISA': [],
                    'Cash': []
                }
            }
            self.save_json_file(breakdown_file, initial_breakdown)
        
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
    
    def get_networth_data(self, year: int = 2025) -> Dict[str, Any]:
        """Get net worth data for a specific year"""
        filename = f'networth_{year}.json'
        filepath = os.path.join(self.data_dir, filename)
        
        # Create file if it doesn't exist
        if not os.path.exists(filepath):
            self.save_json_file(filepath, {})
        
        return self.load_json_file(filepath)
    
    def save_networth_data(self, data: Dict[str, Any], year: int = 2025):
        """Save net worth data for a specific year"""
        filename = f'networth_{year}.json'
        self.save_json_file(os.path.join(self.data_dir, filename), data)
    
    def get_available_years(self) -> List[int]:
        """Get list of available years for networth tracking"""
        available_years = []
        for filename in os.listdir(self.data_dir):
            if filename.startswith('networth_') and filename.endswith('.json'):
                try:
                    year = int(filename.replace('networth_', '').replace('.json', ''))
                    available_years.append(year)
                except ValueError:
                    continue
        return sorted(available_years)
    
    def create_new_year(self, year: int):
        """Create a new year for networth tracking"""
        filename = f'networth_{year}.json'
        filepath = os.path.join(self.data_dir, filename)
        
        if not os.path.exists(filepath):
            # Initialize with empty monthly data
            initial_data = {}
            self.save_json_file(filepath, initial_data)
            return True
        return False
    
    def update_monthly_networth(self, year: int, month: str, platform: str, value: float):
        """Update networth value for a specific month and platform"""
        data = self.get_networth_data(year)
        
        if month not in data:
            data[month] = {}
        
        data[month][platform] = value
        
        # Remove any existing total_net_worth field to avoid incorrect calculations
        if 'total_net_worth' in data[month]:
            del data[month]['total_net_worth']
        
        self.save_networth_data(data, year)
    
    def get_yearly_net_worth_increase(self, current_year: int = 2025) -> float:
        """Calculate yearly net worth increase from previous year"""
        try:
            # Get current year end value (31st Dec or latest available)
            current_data = self.get_networth_data(current_year)
            current_value = 0
            
            # Try to get 31st Dec value, fallback to latest month
            if '31st Dec' in current_data:
                month_data = current_data['31st Dec']
                current_value = sum(v for k, v in month_data.items() if k != 'total_net_worth' and isinstance(v, (int, float)))
            else:
                # Find the latest month with data
                months = ['1st Dec', '1st Nov', '1st Oct', '1st Sep', '1st Aug', '1st Jul', 
                         '1st Jun', '1st May', '1st Apr', '1st Mar', '1st Feb', '1st Jan']
                for month in months:
                    if month in current_data:
                        month_data = current_data[month]
                        month_total = sum(v for k, v in month_data.items() if k != 'total_net_worth' and isinstance(v, (int, float)))
                        if month_total > 0:
                            current_value = month_total
                            break
            
            # Get previous year end value
            previous_year = current_year - 1
            previous_data = self.get_networth_data(previous_year)
            previous_value = 0
            
            if '31st Dec' in previous_data:
                month_data = previous_data['31st Dec']
                previous_value = sum(v for k, v in month_data.items() if k != 'total_net_worth' and isinstance(v, (int, float)))
            else:
                # Find the latest month with data from previous year
                for month in months:
                    if month in previous_data:
                        month_data = previous_data[month]
                        month_total = sum(v for k, v in month_data.items() if k != 'total_net_worth' and isinstance(v, (int, float)))
                        if month_total > 0:
                            previous_value = month_total
                            break
            
            # Calculate increase
            if previous_value > 0:
                increase = ((current_value - previous_value) / previous_value) * 100
                return increase
            else:
                return 0.0
                
        except Exception as e:
            self.logger.error(f"Error calculating yearly net worth increase: {str(e)}")
            return 0.0
    
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
            if platform.endswith('_cash'):
                continue  # Skip cash keys
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
    
    def get_monthly_breakdown_data(self) -> Dict[str, Any]:
        """Get monthly breakdown data"""
        return self.load_json_file(os.path.join(self.data_dir, 'monthly_breakdown.json'))
    
    def save_monthly_breakdown_data(self, data: Dict[str, Any]):
        """Save monthly breakdown data"""
        self.save_json_file(os.path.join(self.data_dir, 'monthly_breakdown.json'), data)
    
    def update_monthly_income(self, amount: float):
        """Update monthly income"""
        data = self.get_monthly_breakdown_data()
        data['monthly_income'] = amount
        self.save_monthly_breakdown_data(data)
    
    def add_expense(self, name: str, monthly_amount: float):
        """Add a new expense"""
        data = self.get_monthly_breakdown_data()
        expense = {
            'name': name,
            'monthly_amount': monthly_amount,
            'created_at': datetime.now().isoformat()
        }
        data['expenses'].append(expense)
        self.save_monthly_breakdown_data(data)
    
    def delete_expense(self, name: str):
        """Delete an expense by name"""
        data = self.get_monthly_breakdown_data()
        data['expenses'] = [exp for exp in data['expenses'] if exp['name'] != name]
        self.save_monthly_breakdown_data(data)
    
    def add_investment_commitment(self, platform: str, name: str, monthly_amount: float):
        """Add a new investment commitment"""
        data = self.get_monthly_breakdown_data()
        if platform not in data['investment_commitments']:
            data['investment_commitments'][platform] = []
        
        commitment = {
            'name': name,
            'monthly_amount': monthly_amount,
            'created_at': datetime.now().isoformat()
        }
        data['investment_commitments'][platform].append(commitment)
        self.save_monthly_breakdown_data(data)
    
    def delete_investment_commitment(self, platform: str, name: str):
        """Delete an investment commitment"""
        data = self.get_monthly_breakdown_data()
        if platform in data['investment_commitments']:
            data['investment_commitments'][platform] = [
                inv for inv in data['investment_commitments'][platform] 
                if inv['name'] != name
            ]
        self.save_monthly_breakdown_data(data)
