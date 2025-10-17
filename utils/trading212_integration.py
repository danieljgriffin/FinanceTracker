#!/usr/bin/env python3
"""
Trading 212 API Integration Module
Syncs portfolio data with existing investment tracking system
"""
import os
import requests
import logging
import base64
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from models import db, Investment, PlatformCash
from utils.api_platform_models import Platform, APIHolding, SyncLog

class Trading212Integration:
    """Trading 212 API integration for portfolio synchronization"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.base_url = "https://live.trading212.com/api/v0/equity"
        self.api_key = os.environ.get('TRADING212_API_KEY')
        self.api_secret = os.environ.get('TRADING212_API_SECRET')
        self.platform_name = "Trading212 ISA"
        
        if not self.api_key or not self.api_secret:
            raise ValueError("TRADING212_API_KEY and TRADING212_API_SECRET environment variables are required")
    
    def _get_headers(self) -> Dict[str, str]:
        """Get API request headers with Basic Auth"""
        if not self.api_key or not self.api_secret:
            raise ValueError("API key and secret are required")
        
        # Create Basic Auth header
        credentials = f"{self.api_key}:{self.api_secret}"
        encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
        
        return {
            'Authorization': f'Basic {encoded_credentials}',
            'Content-Type': 'application/json'
        }
    
    def _make_api_request(self, endpoint: str, timeout: int = 10) -> Tuple[bool, Dict]:
        """Make API request with error handling"""
        try:
            url = f"{self.base_url}/{endpoint}"
            response = requests.get(url, headers=self._get_headers(), timeout=timeout)
            
            if response.status_code == 200:
                return True, response.json()
            else:
                error_msg = f"API Error {response.status_code}: {response.text}"
                self.logger.error(error_msg)
                return False, {"error": error_msg}
                
        except Exception as e:
            error_msg = f"API Exception: {str(e)}"
            self.logger.error(error_msg)
            return False, {"error": error_msg}
    
    def test_connection(self) -> Tuple[bool, str]:
        """Test Trading 212 API connection"""
        success, data = self._make_api_request("account/cash")
        if success:
            return True, f"Connected successfully. Account balance: £{data.get('total', 0):.2f}"
        else:
            return False, data.get('error', 'Unknown connection error')
    
    def get_account_cash(self) -> Optional[float]:
        """Get account cash balance"""
        success, data = self._make_api_request("account/cash")
        if success:
            return data.get('total', 0.0)
        return None
    
    def get_portfolio_positions(self) -> Optional[List[Dict]]:
        """Get current portfolio positions"""
        success, data = self._make_api_request("portfolio")
        if success and isinstance(data, list):
            return data
        return None
    
    def _normalize_symbol(self, ticker: str) -> str:
        """Normalize Trading 212 ticker to standard format"""
        # Trading 212 uses suffixes like _US_EQ, _EQ
        # Convert NVDA_US_EQ -> NVDA, RRl_EQ -> RR.L
        if ticker.endswith('_US_EQ'):
            return ticker.replace('_US_EQ', '')
        elif ticker.endswith('_EQ'):
            base = ticker.replace('_EQ', '')
            # Handle UK stocks with 'l' suffix (e.g., RRl -> RR.L)
            if base.endswith('l'):
                return f"{base[:-1]}.L"
            return base
        return ticker
    
    def _get_company_name(self, ticker: str) -> str:
        """Get human-readable company name from ticker"""
        ticker_to_name = {
            'NVDA': 'NVIDIA Corporation',
            'PLTR': 'Palantir Technologies',
            'TSLA': 'Tesla Inc',
            'RR.L': 'Rolls-Royce Holdings',
            'FB': 'Meta Platforms',
            'AAPL': 'Apple Inc',
            'MSFT': 'Microsoft Corporation',
            'GOOGL': 'Alphabet Inc',
            'AMZN': 'Amazon.com Inc'
        }
        return ticker_to_name.get(ticker, ticker)
    
    def sync_portfolio_data(self) -> Tuple[bool, str, Dict]:
        """
        Sync Trading 212 portfolio data with local database
        Returns: (success, message, sync_summary)
        """
        # Basic sync lock to prevent concurrent operations
        import threading
        if not hasattr(Trading212Integration, '_sync_lock'):
            Trading212Integration._sync_lock = threading.Lock()
        
        if Trading212Integration._sync_lock.locked():
            return False, "Sync already in progress", {}
        
        with Trading212Integration._sync_lock:
            sync_start = datetime.utcnow()
            sync_summary = {
                'total_positions': 0,
                'updated_positions': 0,
                'new_positions': 0,
                'cash_updated': False,
                'total_portfolio_value': 0.0,
                'cash_balance': 0.0
            }
            
            # Initialize variables for error handling
            platform = None
            positions = []
            
            try:
                # Get or create Trading 212 platform entry
                platform = Platform.query.filter_by(
                    name=self.platform_name, 
                    platform_type='trading212'
                ).first()
            
                if not platform:
                    platform = Platform(
                        name=self.platform_name,
                        platform_type='trading212',
                        api_type='rest_api',
                        sync_status='active'
                    )
                    # Store minimal credential info (API key is stored in environment)
                    # Don't store actual credentials since we use TRADING212_API_KEY env var
                    platform.encrypted_credentials = None  # Use env var instead
                    db.session.add(platform)
                    db.session.flush()  # Get platform ID
                
                # 1. Sync Cash Balance
                cash_balance = self.get_account_cash()
                if cash_balance is not None:
                    cash_entry = PlatformCash.query.filter_by(platform=self.platform_name).first()
                    if cash_entry:
                        cash_entry.cash_balance = cash_balance
                        cash_entry.last_updated = datetime.utcnow()
                    else:
                        cash_entry = PlatformCash(
                            platform=self.platform_name, 
                            cash_balance=cash_balance
                        )
                        db.session.add(cash_entry)
                    
                    sync_summary['cash_updated'] = True
                    sync_summary['cash_balance'] = cash_balance
                    self.logger.info(f"Updated {self.platform_name} cash: £{cash_balance:.2f}")
                
                # 2. Sync Portfolio Positions
                positions = self.get_portfolio_positions()
                if positions is None:
                    return False, "Failed to fetch portfolio positions", sync_summary
                
                sync_summary['total_positions'] = len(positions)
                
                for position in positions:
                    try:
                        # Extract position data
                        ticker = position.get('ticker', '')
                        quantity = position.get('quantity', 0.0)
                        current_price_raw = position.get('currentPrice', 0.0)
                        average_price_raw = position.get('averagePrice', 0.0)
                        pnl = position.get('ppl', 0.0)
                        fx_pnl = position.get('fxPpl', 0.0)
                        
                        # CRITICAL FIX: Convert UK stock prices from pence to pounds
                        # UK stocks (ending with _EQ but not _US_EQ) are in pence
                        if ticker.endswith('_EQ') and not ticker.endswith('_US_EQ'):
                            # UK stock - convert pence to pounds
                            current_price = current_price_raw / 100.0
                            average_price = average_price_raw / 100.0
                            self.logger.info(f"UK stock {ticker}: converted {current_price_raw}p to £{current_price:.2f}")
                        else:
                            # US/other stocks - already in correct currency
                            current_price = current_price_raw
                            average_price = average_price_raw
                        
                        # Normalize ticker and get company name
                        normalized_symbol = self._normalize_symbol(ticker)
                        company_name = self._get_company_name(normalized_symbol)
                        
                        # Calculate market value
                        market_value = quantity * current_price
                        total_invested = quantity * average_price
                        
                        sync_summary['total_portfolio_value'] += market_value
                        
                        # Update APIHolding
                        api_holding = APIHolding.query.filter_by(
                            platform_id=platform.id, 
                            symbol=normalized_symbol
                        ).first()
                        
                        if api_holding:
                            # Update existing holding
                            api_holding.quantity = quantity
                            api_holding.average_price = average_price
                            api_holding.total_invested = total_invested
                            api_holding.current_price = current_price
                            api_holding.current_value = market_value
                            api_holding.unrealized_pnl = pnl
                            api_holding.last_updated = datetime.utcnow()
                            api_holding.last_price_update = datetime.utcnow()
                            sync_summary['updated_positions'] += 1
                            
                        else:
                            # Create new holding
                            api_holding = APIHolding(
                                platform_id=platform.id,
                                symbol=normalized_symbol,
                                name=company_name,
                                quantity=quantity,
                                average_price=average_price,
                                total_invested=total_invested,
                                current_price=current_price,
                                current_value=market_value,
                                unrealized_pnl=pnl,
                                currency='GBP'
                            )
                            db.session.add(api_holding)
                            sync_summary['new_positions'] += 1
                        
                        # Also sync with legacy Investment table for backwards compatibility
                        investment = Investment.query.filter_by(
                            platform=self.platform_name, 
                            symbol=normalized_symbol
                        ).first()
                        
                        if investment:
                            # Update existing investment
                            investment.holdings = quantity
                            investment.current_price = current_price
                            investment.average_buy_price = average_price
                            investment.amount_spent = total_invested
                            investment.last_updated = datetime.utcnow()
                        else:
                            # Create new investment
                            investment = Investment(
                                platform=self.platform_name,
                                name=company_name,
                                symbol=normalized_symbol,
                                holdings=quantity,
                                amount_spent=total_invested,
                                average_buy_price=average_price,
                                current_price=current_price
                            )
                            db.session.add(investment)
                        
                        self.logger.info(f"Synced {normalized_symbol}: {quantity:.4f} @ £{current_price:.2f} = £{market_value:.2f}")
                        
                    except Exception as e:
                        self.logger.error(f"Error syncing position {position.get('ticker', 'Unknown')}: {str(e)}")
                        continue
                
                # Update platform sync status
                platform.last_sync = datetime.utcnow()
                platform.sync_status = 'active'
                platform.error_message = None
                
                # Log successful sync
                sync_log = SyncLog(
                    platform_id=platform.id,
                    sync_type='holdings',
                    sync_status='success',
                    items_processed=len(positions),
                    items_successful=sync_summary['updated_positions'] + sync_summary['new_positions'],
                    items_failed=0,
                    execution_time_ms=int((datetime.utcnow() - sync_start).total_seconds() * 1000),
                    completed_at=datetime.utcnow()
                )
                db.session.add(sync_log)
                
                # Commit all changes
                db.session.commit()
                
                message = f"✅ Successfully synced {len(positions)} positions and cash balance"
                return True, message, sync_summary
                
            except Exception as e:
                db.session.rollback()
                error_msg = f"Sync failed: {str(e)}"
                self.logger.error(error_msg)
                
                # Log failed sync if platform exists
                try:
                    if platform:
                        sync_log = SyncLog(
                            platform_id=platform.id,
                            sync_type='holdings',
                            sync_status='failed',
                            error_message=error_msg,
                            execution_time_ms=int((datetime.utcnow() - sync_start).total_seconds() * 1000),
                            completed_at=datetime.utcnow()
                        )
                        db.session.add(sync_log)
                        
                        platform.sync_status = 'error'
                        platform.error_message = error_msg
                        db.session.commit()
                except:
                    pass  # Ignore errors in error handling
                
                return False, error_msg, sync_summary
    
    def get_sync_status(self) -> Dict:
        """Get current sync status and last sync information"""
        platform = Platform.query.filter_by(
            name=self.platform_name, 
            platform_type='trading212'
        ).first()
        
        if not platform:
            return {
                'connected': False,
                'status': 'not_configured',
                'last_sync': None,
                'message': 'Trading 212 not configured'
            }
        
        # Get latest sync log
        latest_sync = SyncLog.query.filter_by(
            platform_id=platform.id
        ).order_by(SyncLog.started_at.desc()).first()
        
        return {
            'connected': True,
            'status': platform.sync_status,
            'last_sync': platform.last_sync.isoformat() if platform.last_sync else None,
            'error_message': platform.error_message,
            'latest_sync': latest_sync.to_dict() if latest_sync else None
        }
    
    def disconnect(self) -> bool:
        """Disconnect Trading 212 integration"""
        try:
            platform = Platform.query.filter_by(
                name=self.platform_name, 
                platform_type='trading212'
            ).first()
            
            if platform:
                platform.sync_status = 'disconnected'
                platform.error_message = 'Manually disconnected'
                db.session.commit()
                return True
            return False
            
        except Exception as e:
            self.logger.error(f"Error disconnecting Trading 212: {str(e)}")
            return False