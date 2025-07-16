import yfinance as yf
import logging
from typing import Optional

class PriceFetcher:
    """Handles fetching live prices from various sources"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def get_price(self, symbol: str) -> Optional[float]:
        """
        Fetch current price for a given symbol
        
        Args:
            symbol: Stock/crypto symbol (e.g., AAPL, BTC-USD)
            
        Returns:
            Current price or None if not found
        """
        try:
            if not symbol:
                return None
                
            # Use yfinance to get price
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            # Try different price fields
            price_fields = ['regularMarketPrice', 'price', 'lastPrice', 'bid', 'ask']
            
            for field in price_fields:
                if field in info and info[field]:
                    price = float(info[field])
                    self.logger.debug(f"Price for {symbol}: {price}")
                    return price
            
            # If info doesn't work, try history
            hist = ticker.history(period='1d')
            if not hist.empty:
                price = float(hist['Close'].iloc[-1])
                self.logger.debug(f"Price for {symbol} from history: {price}")
                return price
                
        except Exception as e:
            self.logger.error(f"Error fetching price for {symbol}: {str(e)}")
            
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
