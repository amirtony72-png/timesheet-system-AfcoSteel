from main import app, db
import os

# ✅ استيراد كل الموديلات عندك
from models.employee import (
    Employee, Holiday, DeductionRule, LeaveType, LeaveRequest,
    AttendanceRecord, Deduction, employee_managers, OvertimeRequest,
    Task, EmployeeRating, Notification
)

from models.timesheet_session import (
    Project, ProjectJob, TimesheetSession, TimesheetBreak
)

# ✅ كل الجداول
models = [
    Employee,
    Holiday,
    DeductionRule,
    LeaveType,
    LeaveRequest,
    AttendanceRecord,
    Deduction,
    OvertimeRequest,
    Task,
    EmployeeRating,
    Notification,
    Project,
    ProjectJob,
    TimesheetSession,
    TimesheetBreak
]

# ✅ SQLite (source)
sqlite_db = "sqlite:///instance/attendance.db"

# ✅ PostgreSQL (target)
pg_url = "postgresql://afco_user:REPLACE_WITH_NEW_PASSWORD@dpg-d83e2b0js32c73cbolk0-a.oregon-postgres.render.com/afco"

# ✅ إصلاح postgres:// لو موجود
if pg_url.startswith("postgres://"):
    pg_url = pg_url.replace("postgres://", "postgresql://", 1)

# =========================
# ✅ STEP 1: Read from SQLite
# =========================
app.config["SQLALCHEMY_DATABASE_URI"] = sqlite_db

data = {}

with app.app_context():
    for model in models:
        try:
            rows = model.query.all()
            data[model] = rows
            print(f"✅ Read {model.__name__}: {len(rows)} rows")
        except Exception as e:
            print(f"❌ Error reading {model}: {e}")

# =========================
# ✅ STEP 2: Write to PostgreSQL
# =========================
app.config["SQLALCHEMY_DATABASE_URI"] = pg_url

with app.app_context():
    db.create_all()

    for model, rows in data.items():
        for row in rows:
            try:
                db.session.merge(row)   # ✅ مهم لتجنب duplicate
            except Exception as e:
                print(f"❌ Error saving {model}: {e}")

    db.session.commit()

print("🔥✅ ALL DATA MIGRATED SUCCESSFULLY")