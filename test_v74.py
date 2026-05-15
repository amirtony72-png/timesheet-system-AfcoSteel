"""Comprehensive test for v74"""
import sys, os
sys.path.insert(0, '.')
os.environ.setdefault('FLASK_ENV', 'testing')

from main import app
client = app.test_client()

results = []
def test(name, r, check_key='success'):
    j = r.get_json() if r.content_type and 'json' in r.content_type else None
    ok = r.status_code == 200 and (j.get(check_key) if j and check_key else True)
    status = 'PASS' if ok else 'FAIL'
    detail = ''
    if j and not ok:
        detail = str(j.get('error', j.get('message', '')))[:80]
    elif not j and r.status_code == 200:
        detail = f'binary {len(r.data)} bytes'
        status = 'PASS'
    print(f'  [{status}] {name}: {r.status_code} {detail}')
    results.append((name, status))
    return j

# Login uses user_id not username
print('=== LOGIN ===')
j = test('Login admin', client.post('/api/login', json={'user_id':'admin','password':'admin'}))

print('\n=== SESSION ===')
test('Session Start', client.post('/api/timesheet/session/start', json={'project_id':1,'task_name':'Test','hour_type':'REGULAR','session_type':'design'}))
test('Active Session', client.get('/api/timesheet/active-session'))

print('\n=== BREAK ===')
test('Break Start', client.post('/api/timesheet/break/start'))
test('Active Break', client.get('/api/timesheet/break/active'))
test('Break End', client.post('/api/timesheet/break/end'))

print('\n=== SESSION END ===')
test('Session End', client.post('/api/timesheet/session/end'))

print('\n=== OT REQUEST ===')
test('OT Request', client.post('/api/overtime-requests', json={'request_date':'2026-04-21','reason':'Extra work'}))

print('\n=== LEAVE REQUEST ===')
test('Leave Request', client.post('/api/leave-requests', json={'leave_category':'annual','start_date':'2026-05-01','end_date':'2026-05-02','reason':'Vacation'}))

print('\n=== ADMIN ENDPOINTS ===')
test('Departments', client.get('/api/departments'))
test('Timesheet Sessions', client.get('/api/timesheet/sessions'))
test('Breaks List', client.get('/api/timesheet/breaks'))
test('Dashboard Stats', client.get('/api/admin/dashboard/stats'))
test('Attendance Log', client.get('/api/admin/attendance-log'))
test('Admin Leave Req', client.post('/api/admin/leave-requests', json={'employee_id':2,'leave_category':'annual','start_date':'2026-06-01','end_date':'2026-06-02','reason':'Admin req'}))
test('Employees', client.get('/api/admin/employees'))

print('\n=== REPORTS ===')
for rpt in ['monthly-summary','daily-detail','overtime-summary','leave-summary','project-hours','department-summary','attendance-rate','break-analysis']:
    test(f'Report {rpt}', client.get(f'/api/reports/{rpt}'))

print('\n=== EXPORTS ===')
r = client.get('/api/admin/attendance-log/export')
test('Export Attendance', r, check_key=None)
r = client.get('/api/admin/leaves/export/excel')
test('Export Leaves', r, check_key=None)

print('\n=== RESULTS ===')
passed = sum(1 for _, s in results if s == 'PASS')
failed = sum(1 for _, s in results if s == 'FAIL')
print(f'Total: {len(results)}, Passed: {passed}, Failed: {failed}')
if failed:
    print('Failed tests:')
    for name, s in results:
        if s == 'FAIL':
            print(f'  - {name}')
