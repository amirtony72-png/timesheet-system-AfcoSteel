# Analysis of Issues & Required Changes

## Files Read:
- index.html (705 lines) - Employee page
- admin.html (1011 lines) - Admin page
- timesheet_advanced.py - Backend API
- admin.py - Admin API
- main.py - App entry

## API Routes Available:
### timesheet_advanced_bp (prefix: /api/timesheet)
- POST /session/start, /session/end, /active_session, /check_overtime
- GET /sessions (with filters)
- POST /break/start, /break/end, GET /break/active
- GET /breaks (list), PUT /breaks/<id>
- GET /today-stats, /project-totals
- GET /export/excel

### admin_bp (prefix: /api/admin)
- CRUD /employees, /projects, /projects/<id>/jobs
- PUT /sessions/<id>
- GET /dashboard/stats

### advanced_bp (prefix: /api)
- CRUD /overtime-requests, /leave-requests
- /ratings, /tasks, /notifications
- /departments, /leave-balance/<id>
- /fingerprint/attendance, /fingerprint/sync

## Issues to Fix:

### 1. Session not working
- Check: tsForm submit handler looks correct, calls /api/timesheet/session/start
- Possible: hourType select might not have proper options or toggleFields issue
- Need to verify hour_type options match backend expectations

### 2. Break not working  
- Check: startBreak/endBreak call correct URLs
- Possible: break/active endpoint may not exist or return wrong format
- Need to verify backend break endpoints

### 3. OT request not working
- Check: submitOTRequest calls /api/overtime-requests POST
- Possible: request_date format or missing fields

### 4. Leave request not working
- Check: submitLeave calls /api/leave-requests POST
- Possible: validation or field name mismatch

### 5. Attendance log needs more columns
- Need: ID, Name, Date, Check-in, Check-out, Total time, Total project time, Total break, Day type (leave/no fingerprint/absent), Total OT after 9h if approved, OT approval status
- This is a NEW comprehensive attendance register feature

### 6. Job search missing in employee/admin history
- Need: Add Job filter in history sub-tab and admin timesheet

### 7. Description field for TRAINING/IDLE/VACATION/MEETING
- When selecting these types, project and job should show as their names not "Internal"
- Description field should appear

### 8. Reports tab missing - need comprehensive reports
- Need to create a Reports tab with multiple report types

### 9. Dashboard needs more stats
- Add more statistics and visualizations

### 10. Emails in English
- All mailto: functions should use English text

### 11. Default language = English
- Change default from 'ar' to 'en'

### 12. Export Excel for leaves + annual leave reminder
- Add Excel export for leaves
- Send reminder day before annual leave

### 13. Admin should be able to request leave for any employee
- Add admin leave request feature

### 14. Break timer showing remaining time
- Show countdown of remaining break time (e.g., 60 min - elapsed)

### 15. 9 hours includes break - auto break
- Break is mandatory within 9 hours
- Auto-close open tasks and start break
- Break only ends when employee manually ends it

### 16. Sound notifications at specific times
- 12:30 - Break reminder
- 13:30 - Work reminder  
- 10:00 - Start reminder
- 17:00 - End reminder
