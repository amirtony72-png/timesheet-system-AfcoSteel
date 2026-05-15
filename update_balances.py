
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
from main import app
from models.database import db
from models.employee import Employee

with app.app_context():
    employees = Employee.query.all()
    for emp in employees:
        emp.annual_leave_balance = 14
        emp.sick_leave_balance = 7
        emp.casual_leave_balance = 7
    db.session.commit()
    print(f"Updated balances for {len(employees)} employees.")
