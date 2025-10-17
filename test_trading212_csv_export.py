#!/usr/bin/env python3
"""
Test Trading 212 CSV Export API
Validate that CSV export gives accurate portfolio data matching user expectation
"""
import os
import requests
import time
import csv
import base64
from io import StringIO
from datetime import datetime, timedelta

def test_csv_export():
    """Test the Trading 212 CSV export workflow"""
    
    API_KEY = os.environ.get('TRADING212_API_KEY')
    API_SECRET = os.environ.get('TRADING212_API_SECRET')
    BASE_URL = "https://live.trading212.com/api/v0"
    
    # Create Basic Auth header
    credentials = f"{API_KEY}:{API_SECRET}"
    encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
    
    headers = {
        'Authorization': f'Basic {encoded_credentials}',
        'Content-Type': 'application/json'
    }
    
    print("=" * 70)
    print("🧪 TESTING TRADING 212 CSV EXPORT API")
    print("=" * 70)
    
    # Step 1: Request CSV export
    print("\n📤 STEP 1: Requesting CSV export...")
    
    # Request last 3 months of data to include current portfolio state
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=90)
    
    export_payload = {
        "dataIncluded": {
            "includeDividends": True,
            "includeInterest": True,
            "includeOrders": True,
            "includeTransactions": True
        },
        "timeFrom": start_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timeTo": end_date.strftime("%Y-%m-%dT%H:%M:%SZ")
    }
    
    print(f"   Time range: {start_date.date()} to {end_date.date()}")
    print(f"   Including: Orders, Dividends, Interest, Transactions")
    
    try:
        response = requests.post(
            f"{BASE_URL}/history/exports",
            headers=headers,
            json=export_payload
        )
        
        if response.status_code == 200:
            report_id = response.json().get('reportId')
            print(f"   ✅ Export requested successfully!")
            print(f"   📋 Report ID: {report_id}")
        else:
            print(f"   ❌ Export request failed: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"   ❌ Error requesting export: {e}")
        return False
    
    # Step 2: Poll for completion
    print("\n⏳ STEP 2: Polling for export completion...")
    
    max_attempts = 30  # 30 attempts = ~2.5 minutes max wait
    attempt = 0
    download_link = None
    
    while attempt < max_attempts:
        attempt += 1
        
        try:
            response = requests.get(
                f"{BASE_URL}/history/exports",
                headers=headers
            )
            
            if response.status_code == 200:
                reports = response.json()
                
                # Find our report
                current_report = next(
                    (r for r in reports if r.get('reportId') == report_id),
                    None
                )
                
                if current_report:
                    status = current_report.get('status')
                    print(f"   Attempt {attempt}: Status = {status}")
                    
                    if status == "Finished":
                        download_link = current_report.get('downloadLink')
                        print(f"   ✅ Export completed!")
                        print(f"   📥 Download link: {download_link[:60]}...")
                        break
                    elif status == "Failed":
                        print(f"   ❌ Export failed!")
                        return False
                    else:
                        # Still processing
                        time.sleep(5)
                else:
                    print(f"   ⚠️ Report {report_id} not found in response")
                    time.sleep(5)
            else:
                print(f"   ❌ Status check failed: {response.status_code}")
                time.sleep(5)
                
        except Exception as e:
            print(f"   ⚠️ Error checking status: {e}")
            time.sleep(5)
    
    if not download_link:
        print(f"   ❌ Timeout: Export did not complete in time")
        return False
    
    # Step 3: Download CSV
    print("\n📥 STEP 3: Downloading CSV file...")
    
    try:
        csv_response = requests.get(download_link, headers=headers)
        
        if csv_response.status_code == 200:
            csv_content = csv_response.text
            print(f"   ✅ CSV downloaded successfully!")
            print(f"   📊 Size: {len(csv_content)} bytes")
            
            # Save to file for inspection
            with open('trading212_export.csv', 'w') as f:
                f.write(csv_content)
            print(f"   💾 Saved to: trading212_export.csv")
        else:
            print(f"   ❌ Download failed: {csv_response.status_code}")
            return False
            
    except Exception as e:
        print(f"   ❌ Error downloading CSV: {e}")
        return False
    
    # Step 4: Parse and analyze CSV
    print("\n📊 STEP 4: Parsing CSV data...")
    
    try:
        csv_reader = csv.DictReader(StringIO(csv_content))
        rows = list(csv_reader)
        
        print(f"   📋 Total transactions: {len(rows)}")
        
        if rows:
            print(f"   📑 CSV Columns: {list(rows[0].keys())}")
            
            # Show sample data
            print(f"\n   📝 Sample transactions (first 5):")
            for i, row in enumerate(rows[:5]):
                action = row.get('Action', 'N/A')
                ticker = row.get('Ticker', 'N/A')
                time = row.get('Time', 'N/A')
                total = row.get('Total', 'N/A')
                print(f"      {i+1}. {action} {ticker} at {time} - Total: {total}")
            
            # Analyze portfolio state from CSV
            print(f"\n   🔍 Analyzing current portfolio from CSV...")
            
            # Group by ticker to calculate current holdings
            holdings = {}
            
            for row in rows:
                action = row.get('Action', '')
                ticker = row.get('Ticker', '')
                shares_str = row.get('No. of shares', '0')
                
                if not ticker or action not in ['Market buy', 'Market sell', 'Limit buy', 'Limit sell']:
                    continue
                
                try:
                    shares = float(shares_str)
                    
                    if ticker not in holdings:
                        holdings[ticker] = 0
                    
                    if 'buy' in action.lower():
                        holdings[ticker] += shares
                    elif 'sell' in action.lower():
                        holdings[ticker] -= shares
                        
                except ValueError:
                    continue
            
            # Remove zero/negative holdings
            holdings = {k: v for k, v in holdings.items() if v > 0}
            
            print(f"   📈 Current holdings from CSV ({len(holdings)} positions):")
            for ticker, quantity in holdings.items():
                print(f"      • {ticker}: {quantity:.4f} shares")
        else:
            print(f"   ⚠️ CSV is empty!")
            
    except Exception as e:
        print(f"   ❌ Error parsing CSV: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Step 5: Compare with live API
    print("\n🔄 STEP 5: Comparing CSV data with Live API...")
    
    try:
        # Get live portfolio
        portfolio_response = requests.get(
            f"{BASE_URL}/equity/portfolio",
            headers=headers
        )
        
        if portfolio_response.status_code == 200:
            live_positions = portfolio_response.json()
            print(f"   📊 Live API shows {len(live_positions)} positions:")
            
            for position in live_positions:
                ticker = position.get('ticker', 'N/A')
                quantity = position.get('quantity', 0)
                print(f"      • {ticker}: {quantity:.4f} shares")
            
            # Compare
            print(f"\n   🔍 Comparison:")
            print(f"      CSV Holdings: {len(holdings)} positions")
            print(f"      Live API: {len(live_positions)} positions")
            
            if len(holdings) == len(live_positions):
                print(f"      ✅ Position count matches!")
            else:
                print(f"      ⚠️ Position count differs")
                print(f"      💡 Note: CSV only includes trades from last 90 days")
                print(f"      💡 For full portfolio state, need longer time range or different approach")
        
    except Exception as e:
        print(f"   ⚠️ Could not compare with live API: {e}")
    
    # Final summary
    print("\n" + "=" * 70)
    print("📋 TEST SUMMARY")
    print("=" * 70)
    print(f"✅ CSV Export API: WORKING")
    print(f"✅ Download: SUCCESS")
    print(f"✅ CSV Parse: SUCCESS")
    print(f"📄 CSV file saved: trading212_export.csv")
    print(f"\n💡 NEXT STEPS:")
    print(f"   1. Inspect trading212_export.csv to understand data format")
    print(f"   2. CSV shows transaction history, not current portfolio snapshot")
    print(f"   3. Need to calculate current positions from transaction history")
    print(f"   4. Alternative: Use live /portfolio API but fix currency conversion")
    print("=" * 70)
    
    return True

if __name__ == "__main__":
    success = test_csv_export()
    exit(0 if success else 1)
