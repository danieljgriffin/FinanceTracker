"""
Platform Connection Manager
Handles API connections to various financial platforms
"""
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from .intelligent_price_router import price_router

logger = logging.getLogger(__name__)


class PlatformConnector:
    """Manages connections to various financial platforms"""
    
    def __init__(self):
        self.supported_platforms = {
            'trading212': {
                'name': 'Trading 212',
                'type': 'investment',
                'auth_method': 'api_key',
                'endpoints': {
                    'portfolio': 'https://live.trading212.com/api/v0/equity/portfolio',
                    'account': 'https://live.trading212.com/api/v0/equity/account/info'
                },
                'features': ['holdings', 'transactions', 'realtime_prices']
            },
            'ajbell': {
                'name': 'AJ Bell',
                'type': 'investment',
                'auth_method': 'oauth2',
                'endpoints': {
                    'portfolio': 'https://api.ajbell.co.uk/accounts/{accountId}/portfolio',
                    'balances': 'https://api.ajbell.co.uk/accounts/{accountId}/cash-statement'
                },
                'features': ['holdings', 'cash_balances', 'isa_sipp']
            },
            'coinbase': {
                'name': 'Coinbase',
                'type': 'crypto',
                'auth_method': 'api_key',
                'endpoints': {
                    'accounts': 'https://api.coinbase.com/v2/accounts',
                    'prices': 'https://api.coinbase.com/v2/exchange-rates'
                },
                'features': ['crypto_holdings', 'realtime_prices']
            },
            'open_banking': {
                'name': 'Open Banking (UK)',
                'type': 'banking',
                'auth_method': 'oauth2',
                'providers': ['barclays', 'hsbc', 'lloyds', 'natwest'],
                'features': ['account_balances', 'transactions', 'realtime_balances']
            }
        }
    
    def get_supported_platforms(self) -> Dict:
        """Get list of supported platforms for UI display"""
        return {
            'investment': {
                platform_id: info for platform_id, info in self.supported_platforms.items() 
                if info['type'] == 'investment'
            },
            'banking': {
                platform_id: info for platform_id, info in self.supported_platforms.items() 
                if info['type'] == 'banking'
            },
            'crypto': {
                platform_id: info for platform_id, info in self.supported_platforms.items() 
                if info['type'] == 'crypto'
            }
        }
    
    def test_connection(self, platform_type: str, credentials: Dict) -> Dict:
        """Test API connection with provided credentials"""
        try:
            if platform_type == 'trading212':
                return self._test_trading212_connection(credentials)
            elif platform_type == 'ajbell':
                return self._test_ajbell_connection(credentials)
            elif platform_type == 'coinbase':
                return self._test_coinbase_connection(credentials)
            elif platform_type == 'open_banking':
                return self._test_open_banking_connection(credentials)
            else:
                return {'success': False, 'error': f'Unsupported platform: {platform_type}'}
                
        except Exception as e:
            logger.error(f"Connection test failed for {platform_type}: {e}")
            return {'success': False, 'error': str(e)}
    
    def sync_platform_data(self, platform_type: str, credentials: Dict) -> Dict:
        """Sync data from a connected platform"""
        try:
            if platform_type == 'trading212':
                return self._sync_trading212_data(credentials)
            elif platform_type == 'ajbell':
                return self._sync_ajbell_data(credentials)
            elif platform_type == 'coinbase':
                return self._sync_coinbase_data(credentials)
            elif platform_type == 'open_banking':
                return self._sync_banking_data(credentials)
            else:
                return {'success': False, 'error': f'Unsupported platform: {platform_type}'}
                
        except Exception as e:
            logger.error(f"Data sync failed for {platform_type}: {e}")
            return {'success': False, 'error': str(e)}
    
    def _test_trading212_connection(self, credentials: Dict) -> Dict:
        """Test Trading 212 API connection"""
        api_key = credentials.get('api_key')
        if not api_key:
            return {'success': False, 'error': 'API key required'}
        
        headers = {'Authorization': api_key}
        
        try:
            # Test with account info endpoint (lighter than portfolio)
            response = requests.get(
                'https://live.trading212.com/api/v0/equity/account/info',
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'account_info': {
                        'currency': data.get('currencyCode', 'GBP'),
                        'cash': data.get('cash', 0),
                        'total': data.get('total', 0)
                    }
                }
            elif response.status_code == 429:
                return {
                    'success': False, 
                    'error': 'Trading 212 rate limit reached. Please wait a moment and try again.',
                    'error_code': 429
                }
            elif response.status_code == 401:
                return {
                    'success': False, 
                    'error': 'Invalid API key. Please check your Trading 212 API key and try again.',
                    'error_code': 401
                }
            elif response.status_code == 403:
                return {
                    'success': False, 
                    'error': 'API key does not have required permissions. Please ensure all permissions are enabled in Trading 212.',
                    'error_code': 403
                }
            else:
                return {'success': False, 'error': f'Trading 212 API error (status {response.status_code})'}
                
        except requests.RequestException as e:
            return {'success': False, 'error': f'Connection failed: {str(e)}'}
    
    def _sync_trading212_data(self, credentials: Dict) -> Dict:
        """Sync holdings data from Trading 212"""
        api_key = credentials.get('api_key')
        headers = {'Authorization': api_key}
        
        try:
            # Get portfolio data with retry logic
            max_retries = 3
            retry_delay = 1  # Start with 1 second
            
            for attempt in range(max_retries):
                try:
                    response = requests.get(
                        'https://live.trading212.com/api/v0/equity/portfolio',
                        headers=headers,
                        timeout=15
                    )
                    
                    if response.status_code == 200:
                        break
                    elif response.status_code == 429:
                        if attempt < max_retries - 1:
                            logger.warning(f'Trading 212 rate limit hit, retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})')
                            import time
                            time.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff
                            continue
                        else:
                            return {
                                'success': False, 
                                'error': 'Trading 212 rate limit reached. Please try again in a few minutes.',
                                'error_code': 429
                            }
                    elif response.status_code == 401:
                        return {
                            'success': False, 
                            'error': 'Invalid API key. Please check your Trading 212 API key.',
                            'error_code': 401
                        }
                    elif response.status_code == 403:
                        return {
                            'success': False, 
                            'error': 'API key missing required permissions. Please enable all permissions in Trading 212 settings.',
                            'error_code': 403
                        }
                    else:
                        return {'success': False, 'error': f'Trading 212 API error (status {response.status_code})'}
                        
                except requests.RequestException as e:
                    if attempt < max_retries - 1:
                        logger.warning(f'Request failed, retrying in {retry_delay}s: {str(e)}')
                        import time
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    else:
                        return {'success': False, 'error': f'Connection failed after {max_retries} attempts: {str(e)}'}
            
            portfolio_data = response.json()
            holdings = []
            
            # Process open positions - use Trading 212's current prices to avoid external API calls
            for position in portfolio_data.get('open', {}).get('items', []):
                symbol = position.get('code', '')
                
                # Use Trading 212's own price data to avoid rate limiting external APIs
                current_price = position.get('currentPrice', 0)
                quantity = position.get('quantity', 0)
                
                holding = {
                    'symbol': symbol,
                    'name': symbol,  # Trading 212 API doesn't provide full names
                    'quantity': quantity,
                    'average_price': position.get('averagePrice', 0),
                    'total_invested': position.get('investment', 0),
                    'current_price': current_price,
                    'current_value': current_price * quantity if current_price and quantity else 0,
                    'unrealized_pnl': position.get('ppl', 0),
                    'currency': 'GBP'
                }
                
                holdings.append(holding)
            
            return {
                'success': True,
                'holdings': holdings,
                'account_value': portfolio_data.get('total', 0),
                'cash_balance': portfolio_data.get('cash', 0)
            }
            
        except Exception as e:
            logger.error(f'Trading 212 sync failed: {str(e)}')
            return {'success': False, 'error': str(e)}
    
    def _test_ajbell_connection(self, credentials: Dict) -> Dict:
        """Test AJ Bell API connection (placeholder)"""
        # Placeholder for AJ Bell OAuth implementation
        return {'success': False, 'error': 'AJ Bell integration not yet implemented'}
    
    def _sync_ajbell_data(self, credentials: Dict) -> Dict:
        """Sync AJ Bell data (placeholder)"""
        return {'success': False, 'error': 'AJ Bell sync not yet implemented'}
    
    def _test_coinbase_connection(self, credentials: Dict) -> Dict:
        """Test Coinbase API connection (placeholder)"""
        # Placeholder for Coinbase API implementation
        return {'success': False, 'error': 'Coinbase integration not yet implemented'}
    
    def _sync_coinbase_data(self, credentials: Dict) -> Dict:
        """Sync Coinbase data (placeholder)"""
        return {'success': False, 'error': 'Coinbase sync not yet implemented'}
    
    def _test_open_banking_connection(self, credentials: Dict) -> Dict:
        """Test Open Banking connection (placeholder)"""
        # Placeholder for Open Banking implementation
        return {'success': False, 'error': 'Open Banking integration not yet implemented'}
    
    def _sync_banking_data(self, credentials: Dict) -> Dict:
        """Sync banking data (placeholder)"""
        return {'success': False, 'error': 'Open Banking sync not yet implemented'}


# Global instance
platform_connector = PlatformConnector()