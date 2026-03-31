"""
Intelligent Price Router System
Automatically detects investment types and routes to appropriate data sources
"""
import re
import logging
import requests
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import yfinance as yf
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class IntelligentPriceRouter:
    """Smart price detection and routing for any investment"""
    
    def __init__(self):
        self.sources = {
            'stock_ticker': [self._try_yfinance, self._try_ft_markets],
            'stock_us': [self._try_yfinance, self._try_morningstar],
            'stock_uk': [self._try_yfinance, self._try_morningstar],
            'fund_uk_isin': [self._try_morningstar, self._try_ft_markets, self._try_hl_scraper],
            'fund_uk_sedol': [self._try_hl_scraper, self._try_morningstar],
            'crypto': [self._try_coingecko, self._try_yfinance],
            'hl_specific': [self._try_hl_scraper, self._try_sedol_converter],
            'international': [self._try_morningstar, self._try_ft_markets]
        }
        
        # Known crypto symbols for quick detection
        self.crypto_symbols = {'BTC', 'ETH', 'ADA', 'DOT', 'SOL', 'MATIC', 'AVAX', 'LINK', 'UNI', 'FET', 'TRX'}
    
    def detect_investment_type(self, identifier: str, platform_context: Optional[str] = None) -> Tuple[str, str]:
        """
        Smart detection of investment type and appropriate data source
        
        Args:
            identifier: Investment identifier (ticker, ISIN, SEDOL, etc.)
            platform_context: Optional platform context for better detection
            
        Returns:
            Tuple of (investment_type, cleaned_identifier)
        """
        identifier = identifier.strip().upper()
        
        # ISIN Detection (12 chars, starts with 2 letters)
        if len(identifier) == 12 and identifier[:2].isalpha():
            country = identifier[:2]
            if country in ['US', 'CA']:
                return 'stock_us', identifier
            elif country in ['GB', 'IE']:
                return 'fund_uk_isin', identifier
            else:
                return 'international', identifier
        
        # SEDOL Detection (7 chars, UK specific)
        elif len(identifier) == 7 and identifier[:-1].isalnum():
            return 'fund_uk_sedol', identifier
        
        # Crypto Detection
        elif identifier in self.crypto_symbols:
            return 'crypto', identifier
        
        # UK Stock Detection (.L suffix)
        elif identifier.endswith('.L'):
            return 'stock_uk', identifier
        
        # Standard Stock Ticker (3-5 chars)
        elif 3 <= len(identifier) <= 5 and identifier.isalpha():
            return 'stock_ticker', identifier
        
        # Platform-specific detection
        elif platform_context == 'hargreaves_lansdown':
            return 'hl_specific', identifier
        
        return 'unknown', identifier
    
    def get_price(self, identifier: str, platform_context: Optional[str] = None) -> Dict:
        """
        Get price for any investment using intelligent routing
        
        Args:
            identifier: Investment identifier
            platform_context: Optional platform context
            
        Returns:
            Dict with price data or error information
        """
        investment_type, clean_id = self.detect_investment_type(identifier, platform_context)
        
        logger.info(f"Detected {clean_id} as {investment_type}")
        
        # Try sources in priority order
        for price_source in self.sources.get(investment_type, []):
            try:
                price_data = price_source(clean_id)
                if price_data:
                    return {
                        'price': price_data['price'],
                        'currency': price_data.get('currency', 'GBP'),
                        'source': price_source.__name__.replace('_try_', ''),
                        'last_updated': datetime.now(),
                        'identifier_type': investment_type,
                        'original_identifier': identifier
                    }
            except Exception as e:
                logger.warning(f"Failed {price_source.__name__} for {clean_id}: {e}")
                continue
        
        # All sources failed
        return {
            'error': f'No price found for {identifier}', 
            'identifier_type': investment_type,
            'original_identifier': identifier
        }
    
    def _try_yfinance(self, identifier: str) -> Optional[Dict]:
        """Try fetching price using yfinance"""
        try:
            ticker = yf.Ticker(identifier)
            info = ticker.info
            
            if 'regularMarketPrice' in info:
                price = info['regularMarketPrice']
            elif 'currentPrice' in info:
                price = info['currentPrice']
            else:
                return None
                
            currency = info.get('currency', 'USD')
            
            # Convert to GBP if needed
            if currency == 'USD':
                price = self._convert_usd_to_gbp(price)
                currency = 'GBP'
            elif currency == 'GBp':  # UK pence
                price = price / 100
                currency = 'GBP'
            
            return {'price': price, 'currency': currency}
            
        except Exception as e:
            logger.debug(f"yfinance failed for {identifier}: {e}")
            return None
    
    def _try_coingecko(self, identifier: str) -> Optional[Dict]:
        """Try fetching crypto price from CoinGecko"""
        try:
            # Map common symbols to CoinGecko IDs
            crypto_map = {
                'BTC': 'bitcoin',
                'ETH': 'ethereum',
                'ADA': 'cardano',
                'SOL': 'solana',
                'DOT': 'polkadot',
                'MATIC': 'matic-network',
                'AVAX': 'avalanche-2',
                'LINK': 'chainlink',
                'UNI': 'uniswap',
                'FET': 'fetch-ai',
                'TRX': 'tron'
            }
            
            coin_id = crypto_map.get(identifier)
            if not coin_id:
                return None
                
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=gbp"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            if coin_id in data and 'gbp' in data[coin_id]:
                return {'price': data[coin_id]['gbp'], 'currency': 'GBP'}
                
        except Exception as e:
            logger.debug(f"CoinGecko failed for {identifier}: {e}")
            return None
    
    def _try_hl_scraper(self, identifier: str) -> Optional[Dict]:
        """Try fetching price from Hargreaves Lansdown website"""
        try:
            # Convert ISIN to SEDOL if needed for HL
            if len(identifier) == 12:
                sedol = identifier[4:11]  # Extract SEDOL from ISIN
            else:
                sedol = identifier
            
            # Try multiple HL URL patterns
            url_patterns = [
                f"https://www.hl.co.uk/funds/fund-discounts/{sedol}",
                f"https://www.hl.co.uk/funds/fund-discounts,-prices--and--factsheets/search-results/{sedol[0].lower()}/{sedol.lower()}"
            ]
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            for url in url_patterns:
                try:
                    response = requests.get(url, headers=headers, timeout=15)
                    response.raise_for_status()
                    soup = BeautifulSoup(response.content, 'html.parser')
                    
                    # Look for price patterns
                    price_patterns = [
                        ('span', {'class': 'price'}),
                        ('td', {'class': re.compile(r'.*price.*')}),
                        ('div', {'class': re.compile(r'.*price.*')})
                    ]
                    
                    for tag, attrs in price_patterns:
                        price_element = soup.find(tag, attrs)
                        if price_element:
                            price_text = price_element.get_text().strip()
                            # Extract price number
                            price_match = re.search(r'[\d,.]+', price_text)
                            if price_match:
                                price = float(price_match.group().replace(',', ''))
                                return {'price': price, 'currency': 'GBP'}
                                
                except requests.RequestException:
                    continue
            
            return None
            
        except Exception as e:
            logger.debug(f"HL scraper failed for {identifier}: {e}")
            return None
    
    def _try_morningstar(self, identifier: str) -> Optional[Dict]:
        """Try fetching price using Morningstar (placeholder for future implementation)"""
        # Placeholder - would implement with mstarpy library
        logger.debug(f"Morningstar API not yet implemented for {identifier}")
        return None
    
    def _try_ft_markets(self, identifier: str) -> Optional[Dict]:
        """Try fetching price from Financial Times (placeholder)"""
        # Placeholder - would implement with FT API
        logger.debug(f"FT Markets API not yet implemented for {identifier}")
        return None
    
    def _try_sedol_converter(self, identifier: str) -> Optional[Dict]:
        """Try converting and looking up SEDOL"""
        # Placeholder for SEDOL conversion logic
        return None
    
    def _convert_usd_to_gbp(self, usd_amount: float) -> float:
        """Convert USD to GBP using approximate exchange rate"""
        # In production, would use live exchange rate API
        # Using approximate rate for now
        gbp_rate = 0.74  # Approximate USD to GBP
        return usd_amount * gbp_rate
    
    def batch_get_prices(self, identifiers: List[str]) -> Dict[str, Dict]:
        """Get prices for multiple investments efficiently"""
        results = {}
        for identifier in identifiers:
            results[identifier] = self.get_price(identifier)
        return results


# Create global instance
price_router = IntelligentPriceRouter()