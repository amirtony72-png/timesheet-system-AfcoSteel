from main import app
from models.database import db
from models.employee import Employee

with app.app_context():
    employee_count = Employee.query.count()
    print(f"Number of employees: {employee_count}")
