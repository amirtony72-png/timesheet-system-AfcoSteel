from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os

# ✅ App جديد مستقل
app = Flask(__name__)
db = SQLAlchemy()

# ✅ SQLite (source)
sqlite_db = "sqlite:///C:/TimeSheet_AFCO_v76_Final_Ultimate_v6/instance/attendance.db"
# ✅ PostgreSQL (target - حط الرابط هنا)
pg_url = "postgresql://afco_user:YOUR_PASSWORD@dpg-d83e2b0js32c73cbolk0-a.oregon-postgres.render.com/afco"

# ✅ fix لو postgres://
if pg_url.startswith("postgres://"):
    pg_url = pg_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# ✅ استيراد الموديلات
from models.employee import *
from models.timesheet_session import *

# ✅ ربط SQLite
app.config["SQLALCHEMY_DATABASE_URI"] = sqlite_db
db.init_app(app)

data = {}

# ======================
# ✅ قراءة البيانات
# ======================
with app.app_context():
    print("📥 Reading from SQLite...")

    for model in db.Model.__subclasses__():
        try:
            rows = model.query.all()
            data[model] = rows
            print(f"✅ {model.__name__}: {len(rows)} rows")
        except Exception as e:
            print(f"❌ Error reading {model}: {e}")

# ======================
# ✅ كتابة PostgreSQL
# ======================
app.config["SQLALCHEMY_DATABASE_URI"] = pg_url

with app.app_context():
    print("📤 Writing to PostgreSQL...")

    db.create_all()

    for model, rows in data.items():
        for row in rows:
            try:
                db.session.merge(row)
            except Exception as e:
                print(f"❌ Error saving {model}: {e}")

    db.session.commit()

print("🔥✅ MIGRATION DONE SUCCESSFULLY")