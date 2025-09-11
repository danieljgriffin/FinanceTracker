"""
Enhanced Database Models for API Platform Integration
"""
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime
import json
from cryptography.fernet import Fernet
import os

class Base(DeclarativeBase):
    pass

# Import existing db from models.py
from models import db

class Platform(db.Model):
    """Platform management for both API and manual platforms"""
    __tablename__ = 'platforms'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    platform_type = db.Column(db.String(50), nullable=False)  # 'trading212', 'aj_bell', 'open_banking', 'manual'
    api_type = db.Column(db.String(50))  # 'rest_api', 'oauth2', 'web_scraping', 'manual'
    
    # Encrypted API credentials
    encrypted_credentials = db.Column(db.Text)
    
    # Status tracking
    last_sync = db.Column(db.DateTime)
    sync_status = db.Column(db.String(20), default='pending')  # 'active', 'error', 'disconnected', 'pending'
    error_message = db.Column(db.Text)
    
    # Sync frequency in minutes
    sync_frequency = db.Column(db.Integer, default=360)  # 6 hours default
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    holdings = db.relationship('APIHolding', backref='platform', cascade='all, delete-orphan')
    balances = db.relationship('BankBalance', backref='platform', cascade='all, delete-orphan')
    
    def set_credentials(self, credentials_dict):
        """Encrypt and store API credentials"""
        if not credentials_dict:
            return
        
        key = os.environ.get('ENCRYPTION_KEY')
        if not key:
            raise ValueError("ENCRYPTION_KEY environment variable is required for credential encryption")
        
        try:
            f = Fernet(key.encode() if isinstance(key, str) else key)
            credentials_json = json.dumps(credentials_dict)
            self.encrypted_credentials = f.encrypt(credentials_json.encode()).decode()
        except Exception as e:
            raise ValueError(f"Failed to encrypt credentials: {str(e)}")
    
    def get_credentials(self):
        """Decrypt and return API credentials"""
        if not self.encrypted_credentials:
            return {}
        
        key = os.environ.get('ENCRYPTION_KEY')
        if not key:
            raise ValueError("ENCRYPTION_KEY environment variable is required for credential decryption")
        
        try:
            f = Fernet(key.encode() if isinstance(key, str) else key)
            decrypted = f.decrypt(self.encrypted_credentials.encode())
            return json.loads(decrypted.decode())
        except Exception as e:
            raise ValueError(f"Failed to decrypt credentials: {str(e)}")
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'platform_type': self.platform_type,
            'api_type': self.api_type,
            'last_sync': self.last_sync.isoformat() if self.last_sync else None,
            'sync_status': self.sync_status,
            'sync_frequency': self.sync_frequency,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'has_credentials': bool(self.encrypted_credentials)
        }


class APIHolding(db.Model):
    """Holdings synced from API platforms"""
    __tablename__ = 'api_holdings'
    
    id = db.Column(db.Integer, primary_key=True)
    platform_id = db.Column(db.Integer, db.ForeignKey('platforms.id'), nullable=False)
    
    # Investment identification
    symbol = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(200))
    isin = db.Column(db.String(12))  # International Securities Identification Number
    sedol = db.Column(db.String(7))  # Stock Exchange Daily Official List
    
    # Holding details
    quantity = db.Column(db.Float, nullable=False)
    average_price = db.Column(db.Float)
    total_invested = db.Column(db.Float)
    currency = db.Column(db.String(3), default='GBP')
    
    # Current valuation (calculated)
    current_price = db.Column(db.Float)
    current_value = db.Column(db.Float)
    unrealized_pnl = db.Column(db.Float)
    
    # Timestamps
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    last_price_update = db.Column(db.DateTime)
    
    # Unique constraint for platform + symbol
    __table_args__ = (db.UniqueConstraint('platform_id', 'symbol', name='unique_platform_symbol'),)
    
    def to_dict(self):
        return {
            'id': self.id,
            'platform_id': self.platform_id,
            'symbol': self.symbol,
            'name': self.name,
            'isin': self.isin,
            'sedol': self.sedol,
            'quantity': self.quantity,
            'average_price': self.average_price,
            'total_invested': self.total_invested,
            'currency': self.currency,
            'current_price': self.current_price,
            'current_value': self.current_value,
            'unrealized_pnl': self.unrealized_pnl,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None,
            'last_price_update': self.last_price_update.isoformat() if self.last_price_update else None
        }


class BankBalance(db.Model):
    """Bank account balances from Open Banking APIs"""
    __tablename__ = 'bank_balances'
    
    id = db.Column(db.Integer, primary_key=True)
    platform_id = db.Column(db.Integer, db.ForeignKey('platforms.id'), nullable=False)
    
    # Account details
    account_name = db.Column(db.String(100), nullable=False)
    account_number_masked = db.Column(db.String(20))  # Last 4 digits only
    sort_code_masked = db.Column(db.String(10))  # Masked sort code
    account_type = db.Column(db.String(50))  # 'current', 'savings', 'credit_card'
    
    # Balances
    current_balance = db.Column(db.Float, nullable=False)
    available_balance = db.Column(db.Float)
    credit_limit = db.Column(db.Float)
    currency = db.Column(db.String(3), default='GBP')
    
    # Timestamps
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'platform_id': self.platform_id,
            'account_name': self.account_name,
            'account_number_masked': self.account_number_masked,
            'sort_code_masked': self.sort_code_masked,
            'account_type': self.account_type,
            'current_balance': self.current_balance,
            'available_balance': self.available_balance,
            'credit_limit': self.credit_limit,
            'currency': self.currency,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None
        }


class PriceCache(db.Model):
    """Cache frequently requested prices to reduce API calls"""
    __tablename__ = 'price_cache'
    
    symbol = db.Column(db.String(50), primary_key=True)
    price = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    data_source = db.Column(db.String(50), nullable=False)
    cached_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)
    
    def to_dict(self):
        return {
            'symbol': self.symbol,
            'price': self.price,
            'currency': self.currency,
            'data_source': self.data_source,
            'cached_at': self.cached_at.isoformat() if self.cached_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None
        }


class SyncLog(db.Model):
    """Log of API synchronization attempts"""
    __tablename__ = 'sync_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    platform_id = db.Column(db.Integer, db.ForeignKey('platforms.id'))
    
    sync_type = db.Column(db.String(50), nullable=False)  # 'holdings', 'balances', 'prices'
    sync_status = db.Column(db.String(20), nullable=False)  # 'success', 'partial', 'failed'
    
    items_processed = db.Column(db.Integer, default=0)
    items_successful = db.Column(db.Integer, default=0)
    items_failed = db.Column(db.Integer, default=0)
    
    error_message = db.Column(db.Text)
    execution_time_ms = db.Column(db.Integer)
    
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    
    def to_dict(self):
        return {
            'id': self.id,
            'platform_id': self.platform_id,
            'sync_type': self.sync_type,
            'sync_status': self.sync_status,
            'items_processed': self.items_processed,
            'items_successful': self.items_successful,
            'items_failed': self.items_failed,
            'error_message': self.error_message,
            'execution_time_ms': self.execution_time_ms,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }