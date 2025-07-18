#!/usr/bin/env python3
"""
Migration script to transfer data from JSON files to PostgreSQL database
"""
import os
import json
import logging
from flask import Flask
from models import db, Investment, PlatformCash, NetworthEntry, Expense, MonthlyCommitment, IncomeData, MonthlyBreakdown
from utils.db_data_manager import DatabaseDataManager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_app():
    """Create Flask app for migration"""
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_recycle': 300,
        'pool_pre_ping': True,
    }
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    return app

def load_json_file(filepath):
    """Load JSON file if it exists"""
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            return json.load(f)
    return {}

def migrate_investments():
    """Migrate investments from JSON to database"""
    logger.info("Migrating investments...")
    
    investments_file = 'data/investments.json'
    data = load_json_file(investments_file)
    
    for platform, investments in data.items():
        if platform.endswith('_cash'):
            # This is a cash balance
            platform_name = platform.replace('_cash', '')
            cash_amount = investments if isinstance(investments, (int, float)) else 0.0
            
            # Update or create cash entry
            cash_entry = PlatformCash.query.filter_by(platform=platform_name).first()
            if cash_entry:
                cash_entry.cash_balance = cash_amount
            else:
                cash_entry = PlatformCash(platform=platform_name, cash_balance=cash_amount)
                db.session.add(cash_entry)
            
            logger.info(f"Migrated cash for {platform_name}: £{cash_amount}")
        
        elif isinstance(investments, list):
            # This is a list of investments
            for inv in investments:
                investment = Investment(
                    platform=platform,
                    name=inv.get('name', ''),
                    symbol=inv.get('symbol', ''),
                    holdings=inv.get('holdings', 0.0),
                    amount_spent=inv.get('amount_spent', 0.0),
                    average_buy_price=inv.get('average_buy_price', 0.0),
                    current_price=inv.get('current_price', 0.0)
                )
                db.session.add(investment)
                logger.info(f"Migrated investment: {inv.get('name')} in {platform}")
    
    db.session.commit()
    logger.info("Investments migration completed")

def migrate_networth():
    """Migrate networth data from JSON to database"""
    logger.info("Migrating networth data...")
    
    # Migrate data for each year
    for year in [2023, 2024, 2025]:
        networth_file = f'data/networth_{year}.json'
        data = load_json_file(networth_file)
        
        for month, platform_data in data.items():
            # Calculate total networth for this entry
            total_networth = 0.0
            if isinstance(platform_data, dict):
                for value in platform_data.values():
                    if isinstance(value, (int, float)):
                        total_networth += value
            
            # Create or update entry
            entry = NetworthEntry.query.filter_by(year=year, month=month).first()
            if entry:
                entry.set_platform_data(platform_data)
                entry.total_networth = total_networth
            else:
                entry = NetworthEntry(
                    year=year,
                    month=month,
                    total_networth=total_networth
                )
                entry.set_platform_data(platform_data)
                db.session.add(entry)
            
            logger.info(f"Migrated networth data for {month} {year}")
    
    db.session.commit()
    logger.info("Networth data migration completed")

def migrate_expenses():
    """Migrate expenses from JSON to database"""
    logger.info("Migrating expenses...")
    
    expenses_file = 'data/expenses.json'
    data = load_json_file(expenses_file)
    
    for expense_name, expense_data in data.items():
        if isinstance(expense_data, dict):
            monthly_amount = expense_data.get('monthly_amount', 0.0)
        else:
            monthly_amount = expense_data
        
        expense = Expense(name=expense_name, monthly_amount=monthly_amount)
        db.session.add(expense)
        logger.info(f"Migrated expense: {expense_name} - £{monthly_amount}")
    
    db.session.commit()
    logger.info("Expenses migration completed")

def migrate_monthly_commitments():
    """Migrate monthly commitments from JSON to database"""
    logger.info("Migrating monthly commitments...")
    
    commitments_file = 'data/monthly_contributions.json'
    data = load_json_file(commitments_file)
    
    for platform, commitments in data.items():
        if isinstance(commitments, list):
            for commitment in commitments:
                if isinstance(commitment, dict):
                    monthly_commitment = MonthlyCommitment(
                        platform=platform,
                        name=commitment.get('name', ''),
                        monthly_amount=commitment.get('monthly_amount', 0.0)
                    )
                    db.session.add(monthly_commitment)
                    logger.info(f"Migrated commitment: {commitment.get('name')} in {platform}")
    
    db.session.commit()
    logger.info("Monthly commitments migration completed")

def migrate_income_data():
    """Migrate income data from JSON to database"""
    logger.info("Migrating income data...")
    
    income_file = 'data/income_tracker.json'
    data = load_json_file(income_file)
    
    for year, year_data in data.items():
        if isinstance(year_data, dict):
            income_entry = IncomeData(
                year=year,
                income=year_data.get('income', 0.0),
                investment=year_data.get('investment', 0.0)
            )
            db.session.add(income_entry)
            logger.info(f"Migrated income data for {year}")
    
    db.session.commit()
    logger.info("Income data migration completed")

def migrate_monthly_breakdown():
    """Migrate monthly breakdown data from JSON to database"""
    logger.info("Migrating monthly breakdown...")
    
    breakdown_file = 'data/monthly_breakdown.json'
    data = load_json_file(breakdown_file)
    
    monthly_income = data.get('monthly_income', 0.0)
    
    breakdown = MonthlyBreakdown(monthly_income=monthly_income)
    db.session.add(breakdown)
    logger.info(f"Migrated monthly breakdown: £{monthly_income}")
    
    db.session.commit()
    logger.info("Monthly breakdown migration completed")

def main():
    """Run the migration"""
    app = create_app()
    
    with app.app_context():
        # Create all tables
        db.create_all()
        
        # Clear existing data
        logger.info("Clearing existing data...")
        Investment.query.delete()
        PlatformCash.query.delete()
        NetworthEntry.query.delete()
        Expense.query.delete()
        MonthlyCommitment.query.delete()
        IncomeData.query.delete()
        MonthlyBreakdown.query.delete()
        db.session.commit()
        
        # Run migrations
        try:
            migrate_investments()
            migrate_networth()
            migrate_expenses()
            migrate_monthly_commitments()
            migrate_income_data()
            migrate_monthly_breakdown()
            
            logger.info("✅ Migration completed successfully!")
            logger.info("Your data is now safely stored in PostgreSQL database.")
            logger.info("Cash amounts and all investment data have been preserved.")
            
        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            db.session.rollback()
            raise

if __name__ == '__main__':
    main()