from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime
import json

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)

class Investment(db.Model):
    __tablename__ = 'investments'
    
    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.String(100), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    symbol = db.Column(db.String(50))
    holdings = db.Column(db.Float, default=0.0)
    amount_spent = db.Column(db.Float, default=0.0)
    average_buy_price = db.Column(db.Float, default=0.0)
    current_price = db.Column(db.Float, default=0.0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'platform': self.platform,
            'name': self.name,
            'symbol': self.symbol,
            'holdings': self.holdings,
            'amount_spent': self.amount_spent,
            'average_buy_price': self.average_buy_price,
            'current_price': self.current_price,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class PlatformCash(db.Model):
    __tablename__ = 'platform_cash'
    
    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.String(100), nullable=False, unique=True)
    cash_balance = db.Column(db.Float, default=0.0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'platform': self.platform,
            'cash_balance': self.cash_balance,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None
        }

class NetworthEntry(db.Model):
    __tablename__ = 'networth_entries'
    
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.String(20), nullable=False)
    platform_data = db.Column(db.Text)  # JSON string of platform allocations
    total_networth = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Unique constraint for year+month combination
    __table_args__ = (db.UniqueConstraint('year', 'month', name='unique_year_month'),)
    
    def get_platform_data(self):
        if self.platform_data:
            return json.loads(self.platform_data)
        return {}
    
    def set_platform_data(self, data):
        self.platform_data = json.dumps(data)

class Expense(db.Model):
    __tablename__ = 'expenses'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    monthly_amount = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'monthly_amount': self.monthly_amount,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class MonthlyCommitment(db.Model):
    __tablename__ = 'monthly_commitments'
    
    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.String(100), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    monthly_amount = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'platform': self.platform,
            'name': self.name,
            'monthly_amount': self.monthly_amount,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class IncomeData(db.Model):
    __tablename__ = 'income_data'
    
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.String(20), nullable=False)
    income = db.Column(db.Float, default=0.0)
    investment = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Unique constraint for year
    __table_args__ = (db.UniqueConstraint('year', name='unique_year'),)
    
    def to_dict(self):
        return {
            'year': self.year,
            'income': self.income,
            'investment': self.investment,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class MonthlyBreakdown(db.Model):
    __tablename__ = 'monthly_breakdown'
    
    id = db.Column(db.Integer, primary_key=True)
    monthly_income = db.Column(db.Float, default=0.0)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'monthly_income': self.monthly_income,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None
        }

class MonthlyInvestment(db.Model):
    __tablename__ = 'monthly_investments'
    
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)  # 1-12
    month_name = db.Column(db.String(20), nullable=False)  # "January", "February", etc.
    income_received = db.Column(db.Float, default=0.0)
    amount_invested = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Unique constraint for year+month combination
    __table_args__ = (db.UniqueConstraint('year', 'month', name='unique_year_month_investment'),)
    
    def to_dict(self):
        return {
            'id': self.id,
            'year': self.year,
            'month': self.month,
            'month_name': self.month_name,
            'income_received': self.income_received,
            'amount_invested': self.amount_invested,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class Goal(db.Model):
    __tablename__ = 'goals'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    target_amount = db.Column(db.Float, nullable=False)
    target_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='active')  # active, completed, paused
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'target_amount': self.target_amount,
            'target_date': self.target_date.isoformat() if self.target_date else None,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    @property
    def current_amount(self):
        """Get current net worth using real-time calculation (same as dashboard)"""
        from app import calculate_current_net_worth
        return calculate_current_net_worth()
    
    @property
    def remaining_amount(self):
        return max(0, self.target_amount - self.current_amount)
    
    @property
    def progress_percentage(self):
        if self.target_amount <= 0:
            return 0
        return min(100, (self.current_amount / self.target_amount) * 100)
    
    @property
    def status_color(self):
        if self.status == 'completed':
            return 'green'
        elif self.status == 'paused':
            return 'yellow'
        elif self.progress_percentage >= 90:
            return 'green'
        elif self.progress_percentage >= 50:
            return 'blue'
        else:
            return 'gray'