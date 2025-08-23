# scripts/init_db.py
import os
from app import app, db  # your app.py defines 'app' and 'db = SQLAlchemy(app)'

def run_custom_sql_if_present():
    path = "create_historical_table.sql"
    if os.path.exists(path):
        from sqlalchemy import text
        with open(path, "r", encoding="utf-8") as f:
            sql = f.read()
        # Execute whole file (idempotent if your SQL uses IF NOT EXISTS)
        db.session.execute(text(sql))
        db.session.commit()

if __name__ == "__main__":
    with app.app_context():
        db.create_all()           # creates tables from your models
        run_custom_sql_if_present()
    print("✅ DB initialized / up-to-date")
