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
        
        headers = {'Authorization': f'Bearer {api_key}'}
        
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
        headers = {'Authorization': f'Bearer {api_key}'}
        
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
        """Test Barclays Open Banking connection"""
        try:
            provider = credentials.get('provider', 'barclays')
            access_token = credentials.get('access_token')
            
            if not access_token:
                return {'success': False, 'error': 'Access token required for Open Banking'}
            
            # Test connection with Barclays Open Banking API
            if provider.lower() == 'barclays':
                return self._test_barclays_connection(access_token)
            else:
                return {'success': False, 'error': f'Provider {provider} not yet supported'}
                
        except Exception as e:
            logger.error(f'Open Banking connection test failed: {str(e)}')
            return {'success': False, 'error': str(e)}
    
    def _sync_banking_data(self, credentials: Dict) -> Dict:
        """Sync Barclays Open Banking data"""
        try:
            provider = credentials.get('provider', 'barclays')
            access_token = credentials.get('access_token')
            
            if not access_token:
                return {'success': False, 'error': 'Access token required for Open Banking sync'}
            
            # Sync data from Barclays Open Banking API
            if provider.lower() == 'barclays':
                return self._sync_barclays_accounts(access_token)
            else:
                return {'success': False, 'error': f'Provider {provider} sync not yet supported'}
                
        except Exception as e:
            logger.error(f'Open Banking sync failed: {str(e)}')
            return {'success': False, 'error': str(e)}
    
    def _test_barclays_connection(self, access_token: str) -> Dict:
        """Test Barclays Open Banking API connection"""
        try:
            import requests
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            # Test with accounts endpoint
            response = requests.get(
                'https://atlas.api.barclays/open-banking/v3.1/aisp/accounts',
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                accounts = response.json()
                return {
                    'success': True, 
                    'accounts_found': len(accounts.get('Data', {}).get('Account', [])),
                    'message': 'Connected successfully to Barclays Open Banking'
                }
            elif response.status_code == 401:
                return {'success': False, 'error': 'Invalid access token - please re-authenticate'}
            elif response.status_code == 403:
                return {'success': False, 'error': 'Access denied - check account permissions'}
            else:
                return {'success': False, 'error': f'API error: {response.status_code}'}
                
        except Exception as e:
            logger.error(f'Barclays connection test failed: {str(e)}')
            return {'success': False, 'error': str(e)}
    
    def _sync_barclays_accounts(self, access_token: str) -> Dict:
        """Sync account balances from Barclays Open Banking API"""
        try:
            import requests
            from utils.api_platform_models import BankBalance, db
            from datetime import datetime
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            # Get all accounts
            accounts_response = requests.get(
                'https://atlas.api.barclays/open-banking/v3.1/aisp/accounts',
                headers=headers,
                timeout=10
            )
            
            if accounts_response.status_code != 200:
                return {'success': False, 'error': f'Failed to fetch accounts: {accounts_response.status_code}'}
            
            accounts_data = accounts_response.json()
            accounts = accounts_data.get('Data', {}).get('Account', [])
            total_balance = 0
            account_count = 0
            
            # Process each account
            for account in accounts:
                account_id = account.get('AccountId')
                account_type = account.get('AccountType')
                account_subtype = account.get('AccountSubType')
                nickname = account.get('Nickname', f'{account_type} Account')
                
                # Get balance for this account
                balance_response = requests.get(
                    f'https://atlas.api.barclays/open-banking/v3.1/aisp/accounts/{account_id}/balances',
                    headers=headers,
                    timeout=10
                )
                
                if balance_response.status_code == 200:
                    balance_data = balance_response.json()
                    balances = balance_data.get('Data', {}).get('Balance', [])
                    
                    # Find the current balance
                    current_balance = 0
                    for balance in balances:
                        if balance.get('Type') == 'InterimAvailable':
                            amount = balance.get('Amount', {})
                            current_balance = float(amount.get('Amount', 0))
                            break
                    
                    # Store balance in database
                    # Note: We'll need to associate with the correct Platform instance
                    total_balance += current_balance
                    account_count += 1
                    
                    logger.info(f'Barclays account {nickname}: £{current_balance:.2f}')
            
            return {
                'success': True,
                'total_balance': total_balance,
                'account_count': account_count,
                'message': f'Successfully synced {account_count} Barclays accounts'
            }
            
        except Exception as e:
            logger.error(f'Barclays sync failed: {str(e)}')
            return {'success': False, 'error': str(e)}


# Global instance
platform_connector = PlatformConnector()