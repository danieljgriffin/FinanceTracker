import json
import os
import logging
from typing import Dict, Any, Optional
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
            self.save_json_file(investments_file, initial_investments)
        
        # Initialize expenses data
        expenses_file = os.path.join(self.data_dir, 'expenses.json')
        if not os.path.exists(expenses_file):
            self.save_json_file(expenses_file, {})
    
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
    
    def add_investment(self, platform: str, name: str, monthly_amount: float, symbol: str = ''):
        """Add a new investment"""
        investments_data = self.get_investments_data()
        
        if platform not in investments_data:
            investments_data[platform] = []
        
        investment = {
            'name': name,
            'monthly_amount': monthly_amount,
            'symbol': symbol,
            'created_at': datetime.now().isoformat()
        }
        
        investments_data[platform].append(investment)
        self.save_investments_data(investments_data)
    
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
