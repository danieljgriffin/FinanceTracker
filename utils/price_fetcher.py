import yfinance as yf
import logging
import requests
import re
from typing import Optional
import trafilatura
from datetime import datetime

class PriceFetcher:
    """Handles fetching live prices from various sources"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.usd_to_gbp_rate = None
        self.last_rate_update = None
        
        # Special fund mappings for funds that don't work with yfinance
        self.special_funds = {
            'GB00BYVGKV59': {
                'name': 'Baillie Gifford Positive Change Class B - Acc',
                'morningstar_id': 'F00000Z2H1',
                'hl_url': 'https://www.hl.co.uk/funds/fund-discounts,-prices--and--factsheets/search-results/b/baillie-gifford-positive-change-class-b-accumulation'
            },
            'LU1033663649': {
                'name': 'Fidelity Global Technology Class W - Acc',
                'morningstar_id': 'F00000QYQT',
                'hl_url': 'https://www.hl.co.uk/funds/fund-discounts,-prices--and--factsheets/search-results/f/fidelity-global-technology-w-gbp-accumulation'
            },
            'LU0345781172': {
                'name': 'Ninety One GSF Global Natural Resources Class I - Acc',
                'morningstar_id': 'F0GBR04S0N',
                'ft_url': 'https://markets.ft.com/data/funds/tearsheet/performance?s=LU0954591375:GBP',
                'hl_url': 'https://www.hl.co.uk/funds/fund-discounts,-prices--and--factsheets/search-results/n/ninety-one-gsf-global-natural-resources-class-i-accumulation'
            },
            'GB00BMN91T34': {
                'name': 'UBS S&P 500 Index Class C - Acc',
                'morningstar_id': 'F00000UE1Z',
                'hl_url': 'https://www.hl.co.uk/funds/fund-discounts,-prices--and--factsheets/search-results/u/ubs-s-and-p-500-index-accumulation'
            }
        }
    
    def get_price(self, symbol: str) -> Optional[float]:
        """
        Fetch current price for a given symbol
        
        Args:
            symbol: Stock/crypto symbol (e.g., AAPL, BTC-USD) or ISIN
            
        Returns:
            Current price or None if not found
        """
        try:
            if not symbol:
                return None
            
            # Check if this is a special fund that needs web scraping
            if symbol in self.special_funds:
                return self.get_special_fund_price(symbol)
                
            # Use yfinance to get price
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            # Try different price fields
            price_fields = ['regularMarketPrice', 'price', 'lastPrice', 'bid', 'ask']
            
            for field in price_fields:
                if field in info and info[field]:
                    price = float(info[field])
                    self.logger.debug(f"Price for {symbol}: {price}")
                    
                    # Convert USD to GBP if needed
                    currency = info.get('currency', 'USD')
                    if currency == 'USD':
                        gbp_price = self.convert_usd_to_gbp(price)
                        if gbp_price:
                            self.logger.debug(f"Converted {price} USD to {gbp_price} GBP")
                            return gbp_price
                    
                    return price
            
            # If info doesn't work, try history
            hist = ticker.history(period='1d')
            if not hist.empty:
                price = float(hist['Close'].iloc[-1])
                self.logger.debug(f"Price for {symbol} from history: {price}")
                
                # Convert USD to GBP if needed (assume USD if not specified)
                currency = info.get('currency', 'USD')
                if currency == 'USD':
                    gbp_price = self.convert_usd_to_gbp(price)
                    if gbp_price:
                        self.logger.debug(f"Converted {price} USD to {gbp_price} GBP")
                        return gbp_price
                
                return price
                
        except Exception as e:
            self.logger.error(f"Error fetching price for {symbol}: {str(e)}")
            
        return None
    
    def get_special_fund_price(self, isin: str) -> Optional[float]:
        """
        Get price for special funds using web scraping with fallback prices
        
        Args:
            isin: Fund ISIN code
            
        Returns:
            Current price or None if not found
        """
        fund_info = self.special_funds.get(isin)
        if not fund_info:
            return None
            
        # Fallback prices (manually updated as needed - these are from July 16, 2025)
        fallback_prices = {
            'GB00BYVGKV59': 3.5510,  # Baillie Gifford Positive Change (355.10p)
            'LU1033663649': 9.334,   # Fidelity Global Technology (933.40p)
            'LU0345781172': 48.24,   # Ninety One Natural Resources (£48.24)
            'GB00BMN91T34': 2.1106   # UBS S&P 500 (211.06p)
        }
        
        # Try Yahoo Finance first if available
        if 'yahoo_symbol' in fund_info:
            try:
                self.logger.info(f"Trying to fetch price for {fund_info['name']} from Yahoo Finance")
                ticker = yf.Ticker(fund_info['yahoo_symbol'])
                info = ticker.info
                
                # Try different price fields
                price_fields = ['regularMarketPrice', 'price', 'lastPrice', 'bid', 'ask']
                
                for field in price_fields:
                    if field in info and info[field]:
                        price = float(info[field])
                        # Convert pence to pounds for UK funds if needed
                        if isin.startswith('GB') and price > 10:  # Likely in pence
                            price = price / 100
                        self.logger.info(f"Successfully fetched price {price} for {fund_info['name']} from Yahoo Finance")
                        return price
                
                # Try history if info doesn't work
                hist = ticker.history(period='1d')
                if not hist.empty:
                    price = float(hist['Close'].iloc[-1])
                    # Convert pence to pounds for UK funds if needed
                    if isin.startswith('GB') and price > 10:  # Likely in pence
                        price = price / 100
                    self.logger.info(f"Successfully fetched price {price} for {fund_info['name']} from Yahoo Finance history")
                    return price
                    
            except Exception as e:
                self.logger.error(f"Error fetching from Yahoo Finance: {str(e)}")
        
        # Try web scraping
        sources = []
        if 'hl_url' in fund_info:
            sources.append(('Hargreaves Lansdown', self.scrape_hl_price, fund_info['hl_url']))
        if 'ft_url' in fund_info:
            sources.append(('FT Markets', self.scrape_ft_price, fund_info['ft_url']))
        if not sources and 'hl_url' in fund_info:
            sources.append(('FT Markets', self.scrape_ft_price, isin))
        
        for source_name, scraper_func, identifier in sources:
            try:
                self.logger.info(f"Trying to fetch price for {fund_info['name']} from {source_name}")
                price = scraper_func(identifier)
                if price:
                    self.logger.info(f"Successfully fetched price {price} for {fund_info['name']} from {source_name}")
                    return price
            except Exception as e:
                self.logger.error(f"Error fetching from {source_name}: {str(e)}")
                continue
                
        # Use fallback price if web scraping fails
        if isin in fallback_prices:
            fallback_price = fallback_prices[isin]
            self.logger.warning(f"Using fallback price {fallback_price} for {fund_info['name']} ({isin})")
            return fallback_price
                
        return None
    
    def scrape_morningstar_price(self, fund_id: str) -> Optional[float]:
        """Scrape price from Morningstar"""
        try:
            url = f"https://www.morningstar.co.uk/uk/funds/snapshot/snapshot.aspx?id={fund_id}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            # Extract text content
            content = trafilatura.extract(response.content)
            if not content:
                return None
                
            # Look for price patterns in the content
            price_patterns = [
                r'NAV\s*[:\-]?\s*£?(\d+\.?\d*)',
                r'Price\s*[:\-]?\s*£?(\d+\.?\d*)',
                r'£(\d+\.?\d*)\s*NAV',
                r'£(\d+\.?\d*)\s*Price',
                r'(\d+\.?\d*)\s*GBP'
            ]
            
            for pattern in price_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                if matches:
                    price = float(matches[0])
                    if 0.01 <= price <= 10000:  # Reasonable price range
                        return price
                        
        except Exception as e:
            self.logger.error(f"Error scraping Morningstar for {fund_id}: {str(e)}")
            
        return None
    
    def scrape_hl_price(self, url: str) -> Optional[float]:
        """Scrape price from Hargreaves Lansdown"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=5)
            response.raise_for_status()
            
            # Try to extract price from raw HTML first
            html_content = response.text
            
            # Look for price patterns in the HTML
            price_patterns = [
                r'Sell:(\d+\.?\d*)p',  # Sell:355.10p or Sell:211.06p
                r'Buy:(\d+\.?\d*)p',   # Buy:355.10p or Buy:211.06p
                r'Price:(\d+\.?\d*)p', # Price:355.10p
                r'(\d+\.?\d*)p\s*Buy', # 355.10p Buy or 211.06p Buy
                r'(\d+\.?\d*)p\s*Sell', # 355.10p Sell or 211.06p Sell
                r'(\d{2,3}\.\d{2})p',  # Generic pattern for XXX.XXp like 211.06p
                r'price[\'\"]\s*:\s*[\'\"]\s*(\d+\.?\d*)',
                r'\"price\"\s*:\s*\"(\d+\.?\d*)',
                r'<span[^>]*>(\d+\.?\d*)p</span>'
            ]
            
            for pattern in price_patterns:
                matches = re.findall(pattern, html_content, re.IGNORECASE)
                if matches:
                    price = float(matches[0])
                    if 0.01 <= price <= 10000:  # Reasonable price range
                        # Convert pence to pounds if necessary
                        if price > 100:  # Likely in pence
                            price = price / 100
                        return price
                        
        except Exception as e:
            self.logger.error(f"Error scraping HL for {url}: {str(e)}")
            
        return None
    
    def scrape_ft_price(self, url_or_isin: str) -> Optional[float]:
        """Scrape price from Financial Times Markets"""
        try:
            # Check if it's already a URL or if we need to construct one
            if url_or_isin.startswith('http'):
                url = url_or_isin
            else:
                url = f"https://markets.ft.com/data/funds/tearsheet/summary?s={url_or_isin}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            # Extract text content
            content = trafilatura.extract(response.content)
            if not content:
                return None
                
            # Look for price patterns in the content
            price_patterns = [
                r'Price\s*\(GBP\)\s*(\d+\.?\d*)',  # Price (GBP)48.24
                r'Price\s*[:\-]?\s*£?(\d+\.?\d*)',
                r'NAV\s*[:\-]?\s*£?(\d+\.?\d*)',
                r'£(\d+\.?\d*)\s*NAV',
                r'£(\d+\.?\d*)\s*Price',
                r'(\d+\.?\d*)\s*GBP'
            ]
            
            for pattern in price_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                if matches:
                    price = float(matches[0])
                    if 0.01 <= price <= 10000:  # Reasonable price range
                        return price
                        
        except Exception as e:
            self.logger.error(f"Error scraping FT for {isin}: {str(e)}")
            
        return None
    
    def get_multiple_prices(self, symbols: list) -> dict:
        """
        Fetch prices for multiple symbols
        
        Args:
            symbols: List of symbols to fetch
            
        Returns:
            Dictionary mapping symbols to prices
        """
        prices = {}
        
        for symbol in symbols:
            price = self.get_price(symbol)
            if price:
                prices[symbol] = price
                
        return prices
    
    def get_usd_to_gbp_rate(self) -> Optional[float]:
        """Get current USD to GBP exchange rate"""
        try:
            # Check if we have a recent rate (within 1 hour)
            if (self.usd_to_gbp_rate and self.last_rate_update and 
                (datetime.now() - self.last_rate_update).seconds < 3600):
                return self.usd_to_gbp_rate
            
            # Fetch new rate from Yahoo Finance
            ticker = yf.Ticker('GBPUSD=X')
            info = ticker.info
            
            # Try different price fields
            price_fields = ['regularMarketPrice', 'price', 'lastPrice', 'bid', 'ask']
            
            for field in price_fields:
                if field in info and info[field]:
                    # GBPUSD=X gives us USD per GBP (how many USD for 1 GBP)
                    # We need GBP per USD, so take the reciprocal
                    usd_per_gbp = float(info[field])
                    gbp_per_usd = 1 / usd_per_gbp
                    
                    self.usd_to_gbp_rate = gbp_per_usd
                    self.last_rate_update = datetime.now()
                    self.logger.debug(f"Updated USD/GBP rate: {self.usd_to_gbp_rate}")
                    return self.usd_to_gbp_rate
            
            # Try history if info doesn't work
            hist = ticker.history(period='1d')
            if not hist.empty:
                usd_per_gbp = float(hist['Close'].iloc[-1])
                gbp_per_usd = 1 / usd_per_gbp
                self.usd_to_gbp_rate = gbp_per_usd
                self.last_rate_update = datetime.now()
                self.logger.debug(f"Updated USD/GBP rate from history: {self.usd_to_gbp_rate}")
                return self.usd_to_gbp_rate
                
        except Exception as e:
            self.logger.error(f"Error fetching USD/GBP rate: {str(e)}")
            
        # Fallback rate if all else fails
        return 0.79  # Approximate USD to GBP rate
    
    def convert_usd_to_gbp(self, usd_price: float) -> Optional[float]:
        """Convert USD price to GBP"""
        try:
            rate = self.get_usd_to_gbp_rate()
            if rate:
                gbp_price = usd_price * rate
                return gbp_price
        except Exception as e:
            self.logger.error(f"Error converting USD to GBP: {str(e)}")
        return None
    
    def get_mutual_fund_price(self, fund_name: str) -> Optional[float]:
        """
        Get price for mutual funds (simplified mapping)
        
        Args:
            fund_name: Name of the mutual fund
            
        Returns:
            Price or None if not found
        """
        # Mapping of fund names to Yahoo Finance symbols
        fund_symbols = {
            'Baillie Gifford Positive Change B - Acc': 'BGPCB.L',
            'Fidelity Global Technology W - Acc': 'FGTW.L',
            'Ninety One GSF Global Natural Resources I - Acc': 'NOGNR.L',
            'UBS S&P 500 Index C - Acc': 'USPSC.L'
        }
        
        symbol = fund_symbols.get(fund_name)
        if symbol:
            return self.get_price(symbol)
        
        return None
