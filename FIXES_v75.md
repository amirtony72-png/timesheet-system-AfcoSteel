# v75 Fixes Analysis

## Issues to fix in index.html:

1. **Timer starts at 02:00:00**: The timer uses `startTimer(new Date(activeSession.start_time))` 
   - Problem: `start_time` from API is UTC, but `new Date()` treats it as local time → 2h offset
   - Fix: Append 'Z' to ISO string or use `today_total_seconds` to calculate elapsed

2. **Break timer not counting correctly**: Break timer works but break duration not saved
   - Need to verify break/start pauses session and break/end resumes

3. **Proj No and Job No are not dropdowns**: 
   - `projSel` IS a dropdown (line 98) ✓
   - `jobSel` IS a dropdown (line 99) ✓
   - But `loadProjects()` uses `/api/admin/projects` which may need auth
   - Need to use `/api/timesheet/projects` instead

4. **Job No should filter by selected project**: Already implemented via `loadJobs()` (line 610-615)
   - But uses `/api/admin/projects/${pid}/jobs` - need to check this endpoint

5. **Break should pause session**: When break starts, session timer should stop
   - Currently break/start in backend pauses running sessions
   - Frontend needs to stop timer display during break

6. **Mandatory break 12:30-13:30**: Auto-start break at 12:30, can only be ended by employee
   - Add auto-break logic in scheduled notifications

7. **OT tab missing in admin**: Need to verify admin.html has OT approval section

8. **Report: Who hasn't started today**: New API endpoint needed

## Issues to fix in Backend:
- `/api/timesheet/projects` endpoint exists and should be used instead of `/api/admin/projects`
- Break duration calculation needs fixing
- Add "not-started-today" report endpoint
