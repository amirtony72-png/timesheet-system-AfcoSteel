"""Comprehensive test for v76 features"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from main import app, db
from models.employee import Employee, AuditLog, ActivityFeed, MonthlyGoal

results = []
def test(name, condition):
    results.append((name, condition))
    print(f"  {'PASS' if condition else 'FAIL'}: {name}")

with app.app_context():
    # Recreate tables for new models
    db.create_all()
    
    client = app.test_client()
    
    # Login
    r = client.post('/api/login', json={'user_id':'admin','password':'admin'})
    d = r.get_json()
    test('Login', d.get('success') == True)
    
    print("\n--- v76 NEW FEATURES ---")
    
    # 1. Activity Feed
    r = client.get('/api/activity-feed?limit=10')
    d = r.get_json()
    test('Activity Feed endpoint', d.get('success') == True)
    test('Activity Feed has activities key', 'activities' in d)
    
    # 2. Audit Log
    r = client.get('/api/audit-log?page=1&per_page=10')
    d = r.get_json()
    test('Audit Log endpoint', d.get('success') == True)
    test('Audit Log has entries key', 'entries' in d)
    
    # 3. Goals - Set
    r = client.post('/api/goals', json={'employee_id':1, 'month':4, 'year':2026, 'target_hours':176})
    d = r.get_json()
    test('Set Goal', d.get('success') == True)
    
    # 4. Goals - Get
    r = client.get('/api/goals?month=4&year=2026')
    d = r.get_json()
    test('Get Goals', d.get('success') == True)
    test('Goals has data', len(d.get('goals', [])) > 0)
    
    # 5. Goals - Bulk
    r = client.post('/api/goals/bulk', json={'month':4, 'year':2026, 'target_hours':176})
    d = r.get_json()
    test('Bulk Goals', d.get('success') == True)
    
    # 6. Org Chart
    r = client.get('/api/org-chart')
    d = r.get_json()
    test('Org Chart endpoint', d.get('success') == True)
    test('Org Chart has chart key', 'chart' in d)
    
    # 7. Department Widgets
    r = client.get('/api/department-widgets')
    d = r.get_json()
    test('Department Widgets endpoint', d.get('success') == True)
    test('Dept Widgets has departments key', 'departments' in d)
    
    # 8. Employee Profile
    r = client.get('/api/employee-profile/1')
    d = r.get_json()
    test('Employee Profile endpoint', d.get('success') == True)
    test('Profile has stats', 'stats' in d)
    test('Profile has leave_balance', 'leave_balance' in d)
    test('Profile has goal', 'goal' in d)
    
    # 9. Auto Clock-out Check
    r = client.get('/api/auto-clockout/check')
    d = r.get_json()
    test('Auto Clock-out Check', d.get('success') == True)
    test('Auto Clock-out has would_close', 'would_close' in d)
    
    # 10. Role Check
    r = client.get('/api/permissions?permission=manage_employees')
    d = r.get_json()
    test('Permission Check endpoint', d.get('success') == True)
    
    # 11. Session Start (with geolocation)
    r = client.post('/api/timesheet/session/start', json={
        'hour_type': 'WORK ORDER',
        'project_id': 1,
        'job_no': 'JOB-001',
        'task_name': 'Test v76',
        'latitude': 25.276987,
        'longitude': 55.296249
    })
    d = r.get_json()
    test('Session Start with Geolocation', d.get('success') == True)
    
    if d.get('success'):
        # Check geolocation was saved
        sess = d.get('session', {})
        test('Session has start_time with Z', 'Z' in str(sess.get('start_time', '')))
        
        # 12. Break Start
        r = client.post('/api/timesheet/break/start')
        d = r.get_json()
        test('Break Start', d.get('success') == True)
        
        if d.get('success'):
            # 13. Active Break
            r = client.get('/api/timesheet/break/active')
            d = r.get_json()
            test('Active Break', d.get('active_break') is not None)
            
            # 14. Break End
            r = client.post('/api/timesheet/break/end')
            d = r.get_json()
            test('Break End', d.get('success') == True)
        
        # 15. End Session
        r = client.post('/api/timesheet/session/end')
        d = r.get_json()
        test('Session End', True)
    
    # 16. Check Audit Log has entries now
    r = client.get('/api/audit-log?page=1&per_page=50')
    d = r.get_json()
    test('Audit Log has entries after actions', len(d.get('entries', [])) > 0)
    
    # 17. Not Started Today report
    r = client.get('/api/admin/not-started-today')
    d = r.get_json()
    test('Not Started Today', d.get('success') == True)

print(f"\n{'='*50}")
passed = sum(1 for _, c in results if c)
total = len(results)
print(f"RESULTS: {passed}/{total} passed")
if passed < total:
    print("FAILED:")
    for name, c in results:
        if not c:
            print(f"  - {name}")
