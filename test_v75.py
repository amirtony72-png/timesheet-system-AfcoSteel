#!/usr/bin/env python3
"""Comprehensive test for v75"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from main import app
from models.database import db

passed = 0
failed = 0
fails = []

def test(name, response, expect_key=None):
    global passed, failed, fails
    ok = response.status_code in (200, 302)
    if expect_key and ok:
        try:
            d = response.get_json()
            ok = expect_key in d if d else False
        except:
            ok = False
    status = "PASS" if ok else "FAIL"
    if not ok:
        failed += 1
        fails.append(name)
        try:
            detail = response.get_json()
        except:
            detail = response.data[:200]
        print(f"  [{status}] {name}: {response.status_code} {detail}")
    else:
        passed += 1
        print(f"  [{status}] {name}: {response.status_code}")
    return response

with app.test_client() as c:
    # Login
    print("=== LOGIN ===")
    r = c.post('/api/login', json={"user_id": "admin", "password": "admin"})
    test("Login", r, "success")

    # Session Start
    print("=== SESSION ===")
    r = c.post('/api/timesheet/session/start', json={
        "hour_type": "WORK ORDER",
        "project_id": 1,
        "job_no": "J001",
        "task_name": "Test Task"
    })
    test("Session Start", r, "session")

    # Active Session
    r = c.get('/api/timesheet/active-session')
    test("Active Session", r, "active_session")

    # Break Start
    print("=== BREAK ===")
    r = c.post('/api/timesheet/break/start', json={"reason": "Lunch"})
    test("Break Start", r, "break_id")

    # Active Break
    r = c.get('/api/timesheet/break/active')
    test("Active Break", r, "active_break")

    # Break End
    r = c.post('/api/timesheet/break/end')
    test("Break End", r, "message")

    # Session End
    print("=== SESSION END ===")
    r = c.post('/api/timesheet/session/end')
    test("Session End", r, "message")

    # OT Request
    print("=== OT REQUEST ===")
    from datetime import date, timedelta
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    r = c.post('/api/overtime-requests', json={
        "request_date": tomorrow,
        "hours": 2,
        "reason": "Test OT"
    })
    test("OT Request", r, "message")

    # Leave Request
    print("=== LEAVE REQUEST ===")
    next_week = (date.today() + timedelta(days=7)).isoformat()
    r = c.post('/api/leave-requests', json={
        "leave_category": "annual",
        "start_date": next_week,
        "end_date": next_week,
        "duration_days": 1,
        "reason": "Test leave"
    })
    test("Leave Request", r, "message")

    # Admin endpoints
    print("=== ADMIN ===")
    r = c.get('/api/departments')
    test("Departments", r, "departments")

    r = c.get('/api/timesheet/sessions')
    test("Timesheet Sessions", r, "sessions")

    r = c.get('/api/timesheet/breaks')
    test("Breaks List", r, "breaks")

    r = c.get('/api/admin/dashboard/stats')
    test("Dashboard Stats", r, "stats")

    r = c.get('/api/admin/attendance-log')
    test("Attendance Log", r, "records")

    r = c.get('/api/admin/employees')
    test("Employees", r, "employees")

    r = c.get('/api/admin/not-started-today')
    test("Not Started Today", r, "employees")

    # Admin create leave
    r = c.post('/api/admin/leave-requests', json={
        "employee_id": 2,
        "leave_category": "casual",
        "start_date": next_week,
        "auto_approve": True
    })
    test("Admin Leave Create", r, "success")

    # Projects
    r = c.get('/api/projects')
    test("Projects", r, "projects")

    # Reports
    print("=== REPORTS ===")
    for rpt in ['monthly-summary', 'daily-detail', 'overtime-summary', 'leave-summary',
                'project-hours', 'department-summary', 'attendance-rate', 'break-analysis']:
        r = c.get(f'/api/reports/{rpt}')
        test(f"Report {rpt}", r)

    # Exports
    print("=== EXPORTS ===")
    r = c.get('/api/admin/attendance-log/export')
    test("Export Attendance", r)

    r = c.get('/api/admin/leaves/export/excel')
    test("Export Leaves", r)

    print(f"\n=== RESULTS ===")
    print(f"Total: {passed+failed}, Passed: {passed}, Failed: {failed}")
    if fails:
        print(f"Failed tests: {', '.join(fails)}")
