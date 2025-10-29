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
                'providers': ['hsbc', 'monzo', 'starling', 'lloyds', 'natwest', 'barclays'],
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
        """Test Open Banking connection for multiple UK banks"""
        try:
            provider = credentials.get('provider', 'hsbc')
            access_token = credentials.get('access_token')
            
            if not access_token:
                return {'success': False, 'error': 'Access token required for Open Banking'}
            
            # Test connection with different bank APIs
            if provider.lower() == 'hsbc':
                return self._test_hsbc_connection(access_token)
            elif provider.lower() == 'monzo':
                return self._test_monzo_connection(access_token)
            elif provider.lower() == 'starling':
                return self._test_starling_connection(access_token)
            elif provider.lower() == 'lloyds':
                return self._test_lloyds_connection(access_token)
            elif provider.lower() == 'barclays':
                return self._test_barclays_connection(access_token)
            else:
                return {'success': False, 'error': f'Provider {provider} not yet supported'}
                
        except Exception as e:
            logger.error(f'Open Banking connection test failed: {str(e)}')
            return {'success': False, 'error': str(e)}
    
    def _sync_banking_data(self, credentials: Dict) -> Dict:
        """Sync Open Banking data from multiple UK banks"""
        try:
            provider = credentials.get('provider', 'hsbc')
            access_token = credentials.get('access_token')
            
            if not access_token:
                return {'success': False, 'error': 'Access token required for Open Banking sync'}
            
            # Sync data from different bank APIs
            if provider.lower() == 'hsbc':
                return self._sync_hsbc_accounts(access_token)
            elif provider.lower() == 'monzo':
                return self._sync_monzo_accounts(access_token)
            elif provider.lower() == 'starling':
                return self._sync_starling_accounts(access_token)
            elif provider.lower() == 'lloyds':
                return self._sync_lloyds_accounts(access_token)
            elif provider.lower() == 'barclays':
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
    
    def _test_hsbc_connection(self, access_token: str) -> Dict:
        """Test HSBC Open Banking API connection"""
        try:
            import requests
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            # Test with HSBC accounts endpoint
            response = requests.get(
                'https://api.hsbc.com/open-banking/v3.1/aisp/accounts',
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                accounts = response.json()
                return {
                    'success': True, 
                    'accounts_found': len(accounts.get('Data', {}).get('Account', [])),
                    'message': 'Connected successfully to HSBC Open Banking'
                }
            elif response.status_code == 401:
                return {'success': False, 'error': 'Invalid access token - please re-authenticate'}
            elif response.status_code == 403:
                return {'success': False, 'error': 'Access denied - check account permissions'}
            else:
                return {'success': False, 'error': f'API error: {response.status_code}'}
                
        except Exception as e:
            logger.error(f'HSBC connection test failed: {str(e)}')
            return {'success': False, 'error': str(e)}
    
    def _test_monzo_connection(self, access_token: str) -> Dict:
        """Test Monzo API connection"""
        try:
            import requests
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            # Test with Monzo accounts endpoint
            response = requests.get(
                'https://api.monzo.com/accounts',
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                accounts = response.json()
                return {
                    'success': True, 
                    'accounts_found': len(accounts.get('accounts', [])),
                    'message': 'Connected successfully to Monzo API'
                }
            elif response.status_code == 401:
                return {'success': False, 'error': 'Invalid access token - please re-authenticate'}
            else:
                return {'success': False, 'error': f'API error: {response.status_code}'}
                
        except Exception as e:
            logger.error(f'Monzo connection test failed: {str(e)}')
            return {'success': False, 'error': str(e)}
    
    def _test_starling_connection(self, access_token: str) -> Dict:
        """Test Starling Bank API connection"""
        try:
            import requests
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            # Test with Starling accounts endpoint
            response = requests.get(
                'https://api.starlingbank.com/api/v2/accounts',
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                accounts = response.json()
                return {
                    'success': True, 
                    'accounts_found': len(accounts.get('accounts', [])),
                    'message': 'Connected successfully to Starling Bank API'
                }
            elif response.status_code == 401:
                return {'success': False, 'error': 'Invalid access token - please re-authenticate'}
            else:
                return {'success': False, 'error': f'API error: {response.status_code}'}
                
        except Exception as e:
            logger.error(f'Starling connection test failed: {str(e)}')
            return {'success': False, 'error': str(e)}
    
    def _test_lloyds_connection(self, access_token: str) -> Dict:
        """Test Lloyds Banking Group API connection"""
        try:
            import requests
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            # Test with Lloyds accounts endpoint
            response = requests.get(
                'https://api.lloydsbanking.com/open-banking/v3.1/aisp/accounts',
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                accounts = response.json()
                return {
                    'success': True, 
                    'accounts_found': len(accounts.get('Data', {}).get('Account', [])),
                    'message': 'Connected successfully to Lloyds Banking Group'
                }
            elif response.status_code == 401:
                return {'success': False, 'error': 'Invalid access token - please re-authenticate'}
            else:
                return {'success': False, 'error': f'API error: {response.status_code}'}
                
        except Exception as e:
            logger.error(f'Lloyds connection test failed: {str(e)}')
            return {'success': False, 'error': str(e)}
    
    def _sync_hsbc_accounts(self, access_token: str) -> Dict:
        """Sync account balances from HSBC Open Banking API"""
        try:
            import requests
            from datetime import datetime
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            # Get all accounts
            accounts_response = requests.get(
                'https://api.hsbc.com/open-banking/v3.1/aisp/accounts',
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
                nickname = account.get('Nickname', f'{account_type} Account')
                
                # Get balance for this account
                balance_response = requests.get(
                    f'https://api.hsbc.com/open-banking/v3.1/aisp/accounts/{account_id}/balances',
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
                    
                    total_balance += current_balance
                    account_count += 1
                    logger.info(f'HSBC account {nickname}: £{current_balance:.2f}')
            
            return {
                'success': True,
                'total_balance': total_balance,
                'account_count': account_count,
                'message': f'Successfully synced {account_count} HSBC accounts'
            }
            
        except Exception as e:
            logger.error(f'HSBC sync failed: {str(e)}')
            return {'success': False, 'error': str(e)}
    
    def _sync_monzo_accounts(self, access_token: str) -> Dict:
        """Sync account balances from Monzo API"""
        try:
            import requests
            from datetime import datetime
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            # Get all accounts
            accounts_response = requests.get(
                'https://api.monzo.com/accounts',
                headers=headers,
                timeout=10
            )
            
            if accounts_response.status_code != 200:
                return {'success': False, 'error': f'Failed to fetch accounts: {accounts_response.status_code}'}
            
            accounts_data = accounts_response.json()
            accounts = accounts_data.get('accounts', [])
            total_balance = 0
            account_count = 0
            
            # Process each account
            for account in accounts:
                account_id = account.get('id')
                account_type = account.get('type')
                description = account.get('description', f'{account_type} Account')
                
                # Get balance for this account
                balance_response = requests.get(
                    f'https://api.monzo.com/balance?account_id={account_id}',
                    headers=headers,
                    timeout=10
                )
                
                if balance_response.status_code == 200:
                    balance_data = balance_response.json()
                    # Monzo balance is in pence, convert to pounds
                    current_balance = balance_data.get('balance', 0) / 100
                    
                    total_balance += current_balance
                    account_count += 1
                    logger.info(f'Monzo account {description}: £{current_balance:.2f}')
            
            return {
                'success': True,
                'total_balance': total_balance,
                'account_count': account_count,
                'message': f'Successfully synced {account_count} Monzo accounts'
            }
            
        except Exception as e:
            logger.error(f'Monzo sync failed: {str(e)}')
            return {'success': False, 'error': str(e)}
    
    def _sync_starling_accounts(self, access_token: str) -> Dict:
        """Sync account balances from Starling Bank API"""
        try:
            import requests
            from datetime import datetime
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            # Get all accounts
            accounts_response = requests.get(
                'https://api.starlingbank.com/api/v2/accounts',
                headers=headers,
                timeout=10
            )
            
            if accounts_response.status_code != 200:
                return {'success': False, 'error': f'Failed to fetch accounts: {accounts_response.status_code}'}
            
            accounts_data = accounts_response.json()
            accounts = accounts_data.get('accounts', [])
            total_balance = 0
            account_count = 0
            
            # Process each account
            for account in accounts:
                account_uid = account.get('accountUid')
                default_category = account.get('defaultCategory')
                account_type = account.get('accountType')
                name = account.get('name', f'{account_type} Account')
                
                # Get balance for this account
                balance_response = requests.get(
                    f'https://api.starlingbank.com/api/v2/accounts/{account_uid}/balance',
                    headers=headers,
                    timeout=10
                )
                
                if balance_response.status_code == 200:
                    balance_data = balance_response.json()
                    # Starling balance is in minor units (pence), convert to pounds
                    cleared_balance = balance_data.get('clearedBalance', {}).get('minorUnits', 0)
                    current_balance = cleared_balance / 100
                    
                    total_balance += current_balance
                    account_count += 1
                    logger.info(f'Starling account {name}: £{current_balance:.2f}')
            
            return {
                'success': True,
                'total_balance': total_balance,
                'account_count': account_count,
                'message': f'Successfully synced {account_count} Starling accounts'
            }
            
        except Exception as e:
            logger.error(f'Starling sync failed: {str(e)}')
            return {'success': False, 'error': str(e)}
    
    def _sync_lloyds_accounts(self, access_token: str) -> Dict:
        """Sync account balances from Lloyds Banking Group API"""
        try:
            import requests
            from datetime import datetime
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            # Get all accounts
            accounts_response = requests.get(
                'https://api.lloydsbanking.com/open-banking/v3.1/aisp/accounts',
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
                nickname = account.get('Nickname', f'{account_type} Account')
                
                # Get balance for this account
                balance_response = requests.get(
                    f'https://api.lloydsbanking.com/open-banking/v3.1/aisp/accounts/{account_id}/balances',
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
                    
                    total_balance += current_balance
                    account_count += 1
                    logger.info(f'Lloyds account {nickname}: £{current_balance:.2f}')
            
            return {
                'success': True,
                'total_balance': total_balance,
                'account_count': account_count,
                'message': f'Successfully synced {account_count} Lloyds accounts'
            }
            
        except Exception as e:
            logger.error(f'Lloyds sync failed: {str(e)}')
            return {'success': False, 'error': str(e)}
    
    def _sync_barclays_accounts(self, access_token: str) -> Dict:
        """Sync account balances from Barclays Open Banking API"""
        try:
            import requests
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