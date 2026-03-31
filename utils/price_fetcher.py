import yfinance as yf
import logging
import requests
import re
from typing import Optional
import trafilatura
from datetime import datetime
import time

class PriceFetcher:
    """Handles fetching live prices from various sources"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.usd_to_gbp_rate = None
        self.last_rate_update = None
        
        # CoinGecko cryptocurrency mappings
        self.crypto_mappings = {
            'BTC': 'bitcoin',
            'ETH': 'ethereum',
            'SOL': 'solana',
            'FET': 'fetch-ai',
            'TRX': 'tron',
            'ADA': 'cardano',
            'DOT': 'polkadot',
            'LINK': 'chainlink',
            'MATIC': 'polygon',
            'AVAX': 'avalanche-2',
            'ATOM': 'cosmos',
            'XRP': 'ripple',
            'LTC': 'litecoin',
            'BCH': 'bitcoin-cash',
            'UNI': 'uniswap',
            'AAVE': 'aave',
            'COMP': 'compound-governance-token',
            'SUSHI': 'sushi',
            'YFI': 'yearn-finance',
            'MKR': 'maker',
            'SNX': 'synthetix-network-token',
            'CRV': 'curve-dao-token',
            'BAL': 'balancer',
            'LUNA': 'terra-luna-2',
            'ALGO': 'algorand',
            'VET': 'vechain',
            'FTM': 'fantom',
            'NEAR': 'near',
            'HBAR': 'hedera-hashgraph',
            'ICP': 'internet-computer',
            'THETA': 'theta-token',
            'XTZ': 'tezos',
            'EOS': 'eos',
            'FLOW': 'flow',
            'FIL': 'filecoin',
            'MANA': 'decentraland',
            'SAND': 'the-sandbox',
            'AXS': 'axie-infinity',
            'CRO': 'crypto-com-chain',
            'SHIB': 'shiba-inu',
            'DOGE': 'dogecoin'
        }
        
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
    
    def get_crypto_price_from_coingecko(self, symbol: str) -> Optional[float]:
        """
        Fetch cryptocurrency price from CoinGecko API with enhanced reliability
        
        Args:
            symbol: Crypto symbol (e.g., BTC, ETH, SOL)
            
        Returns:
            Current price in GBP or None if not found
        """
        try:
            # Remove any -USD suffix and convert to uppercase
            clean_symbol = symbol.replace('-USD', '').upper()
            
            # Check if we have a mapping for this symbol
            if clean_symbol not in self.crypto_mappings:
                self.logger.warning(f"No CoinGecko mapping found for {clean_symbol}")
                return None
                
            coin_id = self.crypto_mappings[clean_symbol]
            
            # CoinGecko API endpoint for price in GBP
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=gbp"
            
            # Add retry mechanism for rate limiting
            for attempt in range(3):
                try:
                    # Add delay between requests to avoid rate limiting
                    if attempt > 0:
                        time.sleep(1.5 * attempt)  # Progressive delay
                    
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Accept': 'application/json',
                        'Accept-Language': 'en-US,en;q=0.9'
                    }
                    
                    response = requests.get(url, headers=headers, timeout=15)
                    
                    if response.status_code == 200:
                        data = response.json()
                        if coin_id in data and 'gbp' in data[coin_id]:
                            price_gbp = float(data[coin_id]['gbp'])
                            
                            # Validate price is reasonable
                            if price_gbp > 0 and price_gbp < 1000000:
                                self.logger.info(f"CoinGecko price for {symbol} ({coin_id}): £{price_gbp}")
                                return price_gbp
                            else:
                                self.logger.error(f"Invalid price returned for {symbol}: £{price_gbp}")
                                return None
                        else:
                            self.logger.error(f"Price data not found in CoinGecko response for {coin_id}")
                    elif response.status_code == 429:
                        self.logger.warning(f"Rate limit hit for {symbol}, attempt {attempt + 1}")
                        if attempt < 2:  # Don't sleep on last attempt
                            time.sleep(3 ** attempt)  # Exponential backoff with longer delays
                        continue
                    else:
                        self.logger.error(f"CoinGecko API request failed with status {response.status_code}")
                        
                except requests.exceptions.RequestException as e:
                    self.logger.error(f"Request error for {symbol}: {str(e)}")
                    if attempt < 2:
                        time.sleep(2)
                        continue
                    
                break
                
        except Exception as e:
            self.logger.error(f"Error fetching CoinGecko price for {symbol}: {str(e)}")
            
        return None

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
            
            # Check if this is a cryptocurrency symbol - ONLY use CoinGecko for crypto
            clean_symbol = symbol.replace('-USD', '').upper()
            if clean_symbol in self.crypto_mappings:
                self.logger.info(f"Cryptocurrency {symbol} detected - using CoinGecko exclusively")
                crypto_price = self.get_crypto_price_from_coingecko(symbol)
                if crypto_price:
                    return crypto_price
                else:
                    # For crypto, NEVER fall back to yfinance as it gives wrong prices
                    self.logger.error(f"CoinGecko failed for cryptocurrency {symbol} - returning None")
                    return None
            
            # Check if this is a special fund that needs web scraping
            if symbol in self.special_funds:
                return self.get_special_fund_price(symbol)
            
            # Remap outdated ticker symbols to current ones
            ticker_remapping = {
                'FB': 'META',  # Meta Platforms changed from FB to META in 2022
            }
            
            # Apply ticker remapping if needed
            lookup_symbol = ticker_remapping.get(symbol, symbol)
            if lookup_symbol != symbol:
                self.logger.info(f"Remapping ticker {symbol} → {lookup_symbol}")
                
            # Use yfinance to get price
            ticker = yf.Ticker(lookup_symbol)
            info = ticker.info
            
            # Try different price fields
            price_fields = ['regularMarketPrice', 'price', 'lastPrice', 'bid', 'ask']
            
            for field in price_fields:
                if field in info and info[field]:
                    price = float(info[field])
                    self.logger.debug(f"Price for {symbol}: {price}")
                    
                    # Handle currency conversions
                    currency = info.get('currency', 'USD')
                    self.logger.debug(f"Currency for {symbol}: {currency}")
                    
                    if currency == 'USD':
                        # Convert USD to GBP
                        gbp_price = self.convert_usd_to_gbp(price)
                        if gbp_price:
                            self.logger.debug(f"Converted {price} USD to {gbp_price} GBP")
                            return gbp_price
                    elif currency == 'GBp' or (symbol.endswith('.L') and currency in ['GBX', 'GBp', 'pence']):
                        # Convert pence to pounds for UK stocks
                        pounds_price = price / 100
                        self.logger.debug(f"Converted {price} pence to {pounds_price} GBP for UK stock {symbol}")
                        return pounds_price
                    elif currency in ['GBP', 'GBP', 'pounds']:
                        # Already in pounds
                        self.logger.debug(f"Price already in GBP: {price}")
                        return price
                    
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
                
                # Convert pence to pounds for UK stocks
                if symbol.endswith('.L') and currency == 'GBp':
                    # UK stocks on Yahoo Finance are typically in pence (GBp)
                    pounds_price = price / 100
                    self.logger.debug(f"Converted {price} pence to {pounds_price} GBP for UK stock {symbol}")
                    return pounds_price
                
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
            
            # Enhanced price patterns with comma support
            price_patterns = [
                # Patterns with comma support (highest priority)
                r'Sell:\s*([1-9][\d,]{3,6}\.?\d*)p',  # Sell: 1,004.50p (with commas)
                r'Buy:\s*([1-9][\d,]{3,6}\.?\d*)p',   # Buy: 1,004.50p (with commas)  
                r'Price:\s*([1-9][\d,]{3,6}\.?\d*)p', # Price: 1,004.50p (with commas)
                r'>([1-9][\d,]{3,6}\.?\d*)p</span>', # <span>1,004.50p</span> (with commas)
                
                # More specific patterns without commas (high priority)
                r'Sell:\s*(\d{3,4}\.?\d*)p',  # Sell: 1004.50p or Sell: 355.10p (3-4 digits)
                r'Buy:\s*(\d{3,4}\.?\d*)p',   # Buy: 1004.50p or Buy: 355.10p (3-4 digits)
                r'Price:\s*(\d{3,4}\.?\d*)p', # Price: 1004.50p (3-4 digits)
                r'(\d{3,4}\.?\d*)p\s+(?:Buy|Sell)', # 1004.50p Buy/Sell (3-4 digits)
                
                # Fallback patterns for shorter prices
                r'Sell:\s*(\d+\.?\d*)p',  # Sell:355.10p or Sell:211.06p
                r'Buy:\s*(\d+\.?\d*)p',   # Buy:355.10p or Buy:211.06p
                r'Price:\s*(\d+\.?\d*)p', # Price:355.10p
                r'(\d+\.?\d*)p\s*(?:Buy|Sell)', # 355.10p Buy or 211.06p Buy/Sell
                
                # Generic patterns (lowest priority)
                r'(\d{3,4}\.\d{1,2})p',  # XXX.XXp or XXXX.XXp (3-4 digits with decimal)
                r'price[\'\"]\s*:\s*[\'\"]\s*(\d+\.?\d*)',
                r'\"price\"\s*:\s*\"(\d+\.?\d*)',
                r'<span[^>]*>(\d+\.?\d*)p</span>'
            ]
            
            all_matches = []
            
            for i, pattern in enumerate(price_patterns):
                matches = re.findall(pattern, html_content, re.IGNORECASE)
                if matches:
                    for match in matches:
                        try:
                            # Remove commas from the match before converting to float
                            clean_match = match.replace(',', '')
                            price = float(clean_match)
                            if 10 <= price <= 500000:  # Reasonable price range for pence (10p-5000p)
                                all_matches.append((price, i, pattern))
                                self.logger.debug(f"HL: Found price {price}p (from '{match}') using pattern {i}: {pattern}")
                        except ValueError:
                            continue
            
            if all_matches:
                # Sort by pattern priority (lower index = higher priority)
                all_matches.sort(key=lambda x: x[1])
                best_price = all_matches[0][0]
                best_pattern_idx = all_matches[0][1]
                
                self.logger.info(f"HL: Selected price {best_price}p from pattern {best_pattern_idx} (total matches: {len(all_matches)})")
                
                # Convert pence to pounds
                final_price = best_price / 100
                self.logger.info(f"HL: Converted {best_price}p to £{final_price}")
                
                # Sanity check - reasonable fund price range
                if 0.01 <= final_price <= 100:  # £0.01 to £100 per unit is reasonable for funds
                    return final_price
                else:
                    self.logger.warning(f"HL: Price £{final_price} outside reasonable fund range, skipping")
                        
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
            self.logger.error(f"Error scraping FT for fund: {str(e)}")
            
        return None
    
    def get_multiple_prices(self, symbols: list) -> dict:
        """
        Fetch prices for multiple symbols with batching for crypto
        
        Args:
            symbols: List of symbols to fetch
            
        Returns:
            Dictionary mapping symbols to prices
        """
        prices = {}
        
        # Separate crypto and non-crypto symbols
        crypto_symbols = []
        non_crypto_symbols = []
        
        for symbol in symbols:
            clean_symbol = symbol.replace('-USD', '').upper()
            if clean_symbol in self.crypto_mappings:
                crypto_symbols.append(symbol)
            else:
                non_crypto_symbols.append(symbol)
        
        # Batch fetch crypto prices with Yahoo Finance fallback
        if crypto_symbols:
            crypto_prices = self.get_batch_crypto_prices(crypto_symbols)
            
            # For any crypto prices that failed, try Yahoo Finance fallback
            failed_symbols = [symbol for symbol in crypto_symbols if symbol not in crypto_prices]
            if failed_symbols:
                self.logger.info(f"Trying Yahoo Finance fallback for {len(failed_symbols)} crypto symbols...")
                yf_crypto_prices = self.get_crypto_prices_from_yahoo(failed_symbols)
                crypto_prices.update(yf_crypto_prices)
            
            prices.update(crypto_prices)
        
        # Fetch non-crypto prices individually
        for symbol in non_crypto_symbols:
            price = self.get_price(symbol)
            if price:
                prices[symbol] = price
                
        return prices
    
    def get_batch_crypto_prices(self, crypto_symbols: list) -> dict:
        """
        Fetch multiple crypto prices in a single CoinGecko API call for efficiency
        
        Args:
            crypto_symbols: List of crypto symbols
            
        Returns:
            Dictionary mapping symbols to prices
        """
        prices = {}
        
        try:
            # Create list of CoinGecko IDs
            coin_ids = []
            symbol_to_id = {}
            
            for symbol in crypto_symbols:
                clean_symbol = symbol.replace('-USD', '').upper()
                if clean_symbol in self.crypto_mappings:
                    coin_id = self.crypto_mappings[clean_symbol]
                    coin_ids.append(coin_id)
                    symbol_to_id[coin_id] = symbol
            
            if not coin_ids:
                return prices
            
            # Single API call for all cryptocurrencies
            ids_string = ','.join(coin_ids)
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids_string}&vs_currencies=gbp"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json',
                'Accept-Language': 'en-US,en;q=0.9'
            }
            
            # Try batch with quick retry to fail fast and use Yahoo Finance fallback
            batch_success = False
            for attempt in range(2):  # Reduced to 2 attempts
                try:
                    if attempt > 0:
                        wait_time = 5  # Just 5 seconds, fail fast for Yahoo fallback
                        self.logger.warning(f"CoinGecko rate limited, waiting {wait_time}s before final attempt")
                        time.sleep(wait_time)
                    
                    response = requests.get(url, headers=headers, timeout=15)
                    
                    if response.status_code == 200:
                        data = response.json()
                        
                        for coin_id, price_data in data.items():
                            if 'gbp' in price_data and coin_id in symbol_to_id:
                                price_gbp = float(price_data['gbp'])
                                if price_gbp > 0 and price_gbp < 1000000:
                                    symbol = symbol_to_id[coin_id]
                                    prices[symbol] = price_gbp
                                    self.logger.info(f"CoinGecko batch {symbol}: £{price_gbp}")
                        batch_success = True
                        break  # Success, exit retry loop
                        
                    elif response.status_code == 429:
                        if attempt == 0:
                            self.logger.warning(f"CoinGecko rate limited, will try Yahoo Finance fallback after one retry")
                        continue  # Try again once
                    else:
                        self.logger.warning(f"CoinGecko failed with status {response.status_code}, falling back to Yahoo Finance")
                        break  # Don't retry for other errors
                        
                except requests.RequestException as e:
                    self.logger.warning(f"CoinGecko batch failed: {str(e)}, falling back to Yahoo Finance")
                    continue
            
            if not batch_success:
                self.logger.info("CoinGecko batch failed completely, Yahoo Finance fallback will handle it")
                
        except Exception as e:
            self.logger.error(f"Error in batch crypto fetch: {str(e)}")
            
        return prices
    
    
    def get_crypto_prices_from_yahoo(self, crypto_symbols: list) -> dict:
        """
        Fallback method to get crypto prices from Yahoo Finance
        Much more reliable than CoinGecko for rate limiting
        """
        prices = {}
        
        # Yahoo Finance crypto symbol mapping
        yahoo_crypto_mapping = {
            'BTC-USD': 'BTC-USD',
            'ETH': 'ETH-USD', 
            'SOL': 'SOL-USD',
            'FET': 'FET-USD',
            'TRX': 'TRX-USD'
        }
        
        for symbol in crypto_symbols:
            try:
                # Map to Yahoo Finance symbol
                clean_symbol = symbol.replace('-USD', '').upper()
                if clean_symbol in ['BTC', 'BITCOIN']:
                    yf_symbol = 'BTC-USD'
                elif clean_symbol in ['ETH', 'ETHEREUM']:
                    yf_symbol = 'ETH-USD'
                elif clean_symbol in ['SOL', 'SOLANA']:
                    yf_symbol = 'SOL-USD'
                elif clean_symbol in ['FET', 'FETCH-AI']:
                    yf_symbol = 'FET-USD'
                elif clean_symbol in ['TRX', 'TRON']:
                    yf_symbol = 'TRX-USD'
                else:
                    continue  # Skip unknown symbols
                
                # Use existing Yahoo Finance method
                ticker = yf.Ticker(yf_symbol)
                info = ticker.info
                
                # Try different price fields
                price_fields = ['regularMarketPrice', 'price', 'lastPrice', 'bid', 'ask']
                
                for field in price_fields:
                    if field in info and info[field]:
                        usd_price = float(info[field])
                        
                        # Convert USD to GBP
                        gbp_price = self.convert_usd_to_gbp(usd_price)
                        if gbp_price and gbp_price > 0:
                            prices[symbol] = gbp_price
                            self.logger.info(f"Yahoo Finance fallback {symbol}: £{gbp_price}")
                            break
                
                # Try history if info fails
                if symbol not in prices:
                    hist = ticker.history(period='1d')
                    if not hist.empty:
                        usd_price = float(hist['Close'].iloc[-1])
                        gbp_price = self.convert_usd_to_gbp(usd_price)
                        if gbp_price and gbp_price > 0:
                            prices[symbol] = gbp_price
                            self.logger.info(f"Yahoo Finance fallback history {symbol}: £{gbp_price}")
                            
            except Exception as e:
                self.logger.warning(f"Yahoo Finance fallback failed for {symbol}: {str(e)}")
                continue
                
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
