"""
External task endpoints for scheduled jobs when using free hosting (Render)
This allows GitHub Actions to trigger background jobs even when the app is sleeping
"""

import os
import threading
import logging
from datetime import datetime, timedelta
from flask import request, abort, jsonify, Blueprint, current_app

# Create tasks blueprint
tasks_bp = Blueprint('tasks', __name__, url_prefix='/tasks')

# Get cron token from environment
CRON_TOKEN = os.getenv("CRON_TOKEN", "")

def run_price_update_job():
    """15-minute price update job"""
    with current_app.app_context():
        try:
            from app import update_all_prices
            update_all_prices()
            current_app.logger.info("✅ External price update job completed at %s", datetime.utcnow())
        except Exception as e:
            current_app.logger.error(f"Error in external price update job: {str(e)}")

def run_historical_collection_job():
    """15-minute historical data collection job"""
    with current_app.app_context():
        try:
            from app import collect_historical_data
            collect_historical_data()
            current_app.logger.info("✅ External historical collection job completed at %s", datetime.utcnow())
        except Exception as e:
            current_app.logger.error(f"Error in external historical collection job: {str(e)}")

def run_6h_job():
    """6-hour jobs: weekly historical data collection"""
    with current_app.app_context():
        try:
            from app import collect_weekly_historical_data
            collect_weekly_historical_data()
            current_app.logger.info("✅ External 6-hour job completed at %s", datetime.utcnow())
        except Exception as e:
            current_app.logger.error(f"Error in external 6-hour job: {str(e)}")

def run_12h_job():
    """12-hour jobs: monthly historical data collection"""
    with current_app.app_context():
        try:
            from app import collect_monthly_historical_data
            collect_monthly_historical_data()
            current_app.logger.info("✅ External 12-hour job completed at %s", datetime.utcnow())
        except Exception as e:
            current_app.logger.error(f"Error in external 12-hour job: {str(e)}")

def run_daily_job():
    """Daily jobs: daily historical data, cleanup, monthly tracker checks"""
    with current_app.app_context():
        try:
            import pytz
            from app import collect_daily_historical_data, cleanup_old_historical_data, auto_populate_monthly_tracker, auto_populate_dec31_tracker
            
            # Always run daily historical collection
            collect_daily_historical_data()
            
            # Run cleanup
            cleanup_old_historical_data()
            
            # Check if it's the 1st of the month for monthly tracker
            uk_tz = pytz.timezone('Europe/London')
            uk_now = datetime.now().astimezone(uk_tz)
            if uk_now.day == 1 and uk_now.hour == 0:  # 1st of month at midnight
                auto_populate_monthly_tracker()
            
            # Check if it's December 31st for year-end tracker
            if uk_now.month == 12 and uk_now.day == 31 and uk_now.hour == 23:  # Dec 31st at 11 PM
                auto_populate_dec31_tracker()
            
            current_app.logger.info("✅ External daily job completed at %s", datetime.utcnow())
        except Exception as e:
            current_app.logger.error(f"Error in external daily job: {str(e)}")

@tasks_bp.route('/run', methods=['POST'])
def tasks_run():
    """Secure endpoint to run scheduled tasks triggered by GitHub Actions"""
    
    # Verify authentication token
    if not CRON_TOKEN or request.headers.get("Authorization") != f"Bearer {CRON_TOKEN}":
        current_app.logger.warning("Unauthorized task execution attempt")
        abort(401)

    # Get task type from query parameter
    task_type = request.args.get("t") or ""
    
    # Map task types to functions
    task_mapping = {
        "15m-prices": run_price_update_job,
        "15m-historical": run_historical_collection_job,
        "6h": run_6h_job,
        "12h": run_12h_job,
        "daily": run_daily_job
    }
    
    task_function = task_mapping.get(task_type)
    if not task_function:
        current_app.logger.error(f"Unknown task type: {task_type}")
        abort(400, f"Unknown task type: {task_type}")

    # Run task in background thread to return quickly
    threading.Thread(target=task_function, daemon=True).start()
    
    current_app.logger.info(f"Started external task: {task_type}")
    return jsonify({"ok": True, "started": task_type}), 202