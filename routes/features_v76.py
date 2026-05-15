"""
v76 Features Blueprint
======================
New endpoints for:
1. Audit Log - track all system actions
2. Activity Feed - real-time employee activity
3. Monthly Goals - hour tracking targets
4. Auto Clock-out - end sessions at 18:00
5. Geolocation - record location at session start
6. Employee Profile - comprehensive employee page
7. Organization Chart - hierarchical view
8. Department Widgets - department-level stats
9. Role-based Permissions - fine-grained access control
"""

from flask import Blueprint, request, jsonify, session
from models.database import db
from models.employee import (
    Employee, AuditLog, ActivityFeed, MonthlyGoal,
    LeaveRequest, OvertimeRequest, AttendanceRecord
)
from models.timesheet_session import TimesheetSession, TimesheetBreak, Project
from datetime import datetime, date, timedelta
from functools import wraps
import json

features_v76_bp = Blueprint('features_v76', __name__, url_prefix='/api')


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER: Audit Log Writer
# ═══════════════════════════════════════════════════════════════════════════════

def log_audit(action, entity_type=None, entity_id=None, old_value=None, new_value=None, description=None):
    """
    Write an entry to the audit log.
    Called from any endpoint that modifies data.
    """
    try:
        emp_id = None
        emp_name = None
        if 'user_id' in session:
            emp = Employee.query.filter_by(user_id=session['user_id']).first()
            if emp:
                emp_id = emp.id
                emp_name = emp.name

        entry = AuditLog(
            employee_id=emp_id,
            employee_name=emp_name or 'System',
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            old_value=json.dumps(old_value, default=str) if old_value else None,
            new_value=json.dumps(new_value, default=str) if new_value else None,
            description=description,
            ip_address=request.remote_addr if request else None,
            user_agent=str(request.user_agent)[:500] if request else None
        )
        db.session.add(entry)
        db.session.commit()
    except Exception as e:
        print(f"Audit log error: {e}")


def log_activity(employee_id, activity_type, description, project_name=None, icon='activity'):
    """
    Write an entry to the activity feed.
    Lightweight, for dashboard display.
    """
    try:
        emp = Employee.query.get(employee_id)
        entry = ActivityFeed(
            employee_id=employee_id,
            employee_name=emp.name if emp else 'Unknown',
            department=emp.department if emp else None,
            activity_type=activity_type,
            description=description,
            project_name=project_name,
            icon=icon
        )
        db.session.add(entry)
        db.session.commit()
    except Exception as e:
        print(f"Activity feed error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# ROLE-BASED PERMISSIONS
# ═══════════════════════════════════════════════════════════════════════════════

# Permission matrix: role -> list of allowed actions
ROLE_PERMISSIONS = {
    'admin': ['*'],  # Full access
    'hr': [
        'view_employees', 'edit_employees',
        'view_leaves', 'approve_leaves', 'reject_leaves', 'create_leaves',
        'view_attendance', 'export_attendance',
        'view_reports', 'view_dashboard',
        'view_audit_log', 'view_activity_feed',
        'view_goals'
    ],
    'planning': [
        'view_employees',
        'view_overtime', 'approve_overtime', 'reject_overtime',
        'view_sessions', 'edit_sessions',
        'view_reports', 'view_dashboard',
        'view_projects', 'edit_projects',
        'view_goals', 'edit_goals'
    ],
    'manager': [
        'view_team', 'view_team_attendance',
        'view_team_leaves', 'approve_team_leaves',
        'view_team_overtime', 'approve_team_overtime',
        'view_team_reports', 'view_dashboard',
        'view_goals'
    ],
    'employee': [
        'view_own_attendance', 'view_own_leaves',
        'create_leave', 'create_overtime',
        'view_own_sessions', 'create_session',
        'view_own_goals'
    ]
}


def check_permission(permission):
    """Decorator to check role-based permissions"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return jsonify({"error": "Not logged in"}), 401
            emp = Employee.query.filter_by(user_id=session['user_id']).first()
            if not emp:
                return jsonify({"error": "Employee not found"}), 404

            role = emp.role or ('admin' if emp.is_admin else 'employee')
            allowed = ROLE_PERMISSIONS.get(role, [])

            if '*' in allowed or permission in allowed:
                return f(*args, **kwargs)
            return jsonify({"error": "Permission denied", "required": permission}), 403
        return decorated_function
    return decorator


@features_v76_bp.route('/permissions', methods=['GET'])
def get_permissions():
    """Get current user's permissions based on role"""
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    emp = Employee.query.filter_by(user_id=session['user_id']).first()
    if not emp:
        return jsonify({"error": "Employee not found"}), 404

    role = emp.role or ('admin' if emp.is_admin else 'employee')
    perms = ROLE_PERMISSIONS.get(role, [])

    return jsonify({
        "success": True,
        "role": role,
        "permissions": perms,
        "is_admin": emp.is_admin or role == 'admin',
        "employee_id": emp.id,
        "employee_name": emp.name
    })


@features_v76_bp.route('/roles', methods=['GET'])
def get_roles():
    """Get all available roles and their permissions"""
    return jsonify({
        "success": True,
        "roles": {k: v for k, v in ROLE_PERMISSIONS.items()}
    })


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT LOG ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@features_v76_bp.route('/audit-log', methods=['GET'])
def get_audit_log():
    """
    Get audit log entries with filtering.
    Query params: employee_id, action, entity_type, start_date, end_date, page, per_page
    """
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401

    emp = Employee.query.filter_by(user_id=session['user_id']).first()
    if not emp or (not emp.is_admin and emp.role not in ('admin', 'hr')):
        return jsonify({"error": "Unauthorized"}), 403

    # Filters
    emp_id = request.args.get('employee_id', type=int)
    action_filter = request.args.get('action')
    entity_filter = request.args.get('entity_type')
    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    query = AuditLog.query

    if emp_id:
        query = query.filter_by(employee_id=emp_id)
    if action_filter:
        query = query.filter(AuditLog.action.like(f'%{action_filter}%'))
    if entity_filter:
        query = query.filter_by(entity_type=entity_filter)
    if start_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d')
            query = query.filter(AuditLog.created_at >= start_date)
        except ValueError:
            pass
    if end_str:
        try:
            end_date = datetime.strptime(end_str, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(AuditLog.created_at < end_date)
        except ValueError:
            pass

    # Paginate
    total = query.count()
    entries = query.order_by(AuditLog.created_at.desc()).offset((page-1)*per_page).limit(per_page).all()

    return jsonify({
        "success": True,
        "total": total,
        "page": page,
        "per_page": per_page,
        "entries": [{
            "id": e.id,
            "employee_id": e.employee_id,
            "employee_name": e.employee_name,
            "action": e.action,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "old_value": e.old_value,
            "new_value": e.new_value,
            "description": e.description,
            "ip_address": e.ip_address,
            "created_at": e.created_at.isoformat() + 'Z' if e.created_at else None
        } for e in entries]
    })


# ═══════════════════════════════════════════════════════════════════════════════
# ACTIVITY FEED ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@features_v76_bp.route('/activity-feed', methods=['GET'])
def get_activity_feed():
    """
    Get real-time activity feed.
    Query params: limit (default 50), department, since (ISO datetime)
    """
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401

    limit = request.args.get('limit', 50, type=int)
    dept = request.args.get('department')
    since_str = request.args.get('since')

    query = ActivityFeed.query

    if dept:
        query = query.filter_by(department=dept)
    if since_str:
        try:
            since = datetime.fromisoformat(since_str.replace('Z', '+00:00'))
            query = query.filter(ActivityFeed.created_at > since)
        except ValueError:
            pass

    activities = query.order_by(ActivityFeed.created_at.desc()).limit(limit).all()

    return jsonify({
        "success": True,
        "activities": [{
            "id": a.id,
            "employee_id": a.employee_id,
            "employee_name": a.employee_name,
            "department": a.department,
            "activity_type": a.activity_type,
            "description": a.description,
            "project_name": a.project_name,
            "icon": a.icon,
            "created_at": a.created_at.isoformat() + 'Z' if a.created_at else None
        } for a in activities]
    })


# ═══════════════════════════════════════════════════════════════════════════════
# MONTHLY GOALS ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@features_v76_bp.route('/goals', methods=['GET'])
def get_goals():
    """
    Get monthly goals.
    Query params: employee_id, month, year
    """
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401

    emp = Employee.query.filter_by(user_id=session['user_id']).first()
    month = request.args.get('month', date.today().month, type=int)
    year = request.args.get('year', date.today().year, type=int)
    emp_id = request.args.get('employee_id', type=int)

    # Non-admin can only see own goals
    if not emp.is_admin and emp.role not in ('admin', 'hr', 'planning'):
        emp_id = emp.id

    query = MonthlyGoal.query.filter_by(month=month, year=year)
    if emp_id:
        query = query.filter_by(employee_id=emp_id)

    goals = query.all()

    # Calculate actual hours for each goal
    result = []
    for g in goals:
        # Calculate actual hours from sessions
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        sessions = TimesheetSession.query.filter(
            TimesheetSession.employee_id == g.employee_id,
            TimesheetSession.date >= start_date,
            TimesheetSession.date <= end_date,
            TimesheetSession.status == 'completed'
        ).all()

        actual = sum(s.elapsed_seconds or 0 for s in sessions) / 3600.0
        billable = sum(s.elapsed_seconds or 0 for s in sessions if s.is_billable) / 3600.0

        # Update stored values
        g.actual_hours = round(actual, 2)
        g.billable_hours = round(billable, 2)

        emp_obj = Employee.query.get(g.employee_id)
        result.append({
            "id": g.id,
            "employee_id": g.employee_id,
            "employee_name": emp_obj.name if emp_obj else '-',
            "department": emp_obj.department if emp_obj else '-',
            "month": g.month,
            "year": g.year,
            "target_hours": g.target_hours,
            "actual_hours": round(actual, 2),
            "billable_hours": round(billable, 2),
            "progress_pct": round((actual / g.target_hours * 100), 1) if g.target_hours > 0 else 0,
            "notes": g.notes
        })

    db.session.commit()

    return jsonify({"success": True, "goals": result})


@features_v76_bp.route('/goals', methods=['POST'])
def create_or_update_goal():
    """Create or update a monthly goal for an employee"""
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401

    emp = Employee.query.filter_by(user_id=session['user_id']).first()
    if not emp or (not emp.is_admin and emp.role not in ('admin', 'planning')):
        return jsonify({"error": "Unauthorized"}), 403

    data = request.json
    emp_id = data.get('employee_id')
    month = data.get('month', date.today().month)
    year = data.get('year', date.today().year)
    target = data.get('target_hours', 176)
    notes = data.get('notes', '')

    if not emp_id:
        return jsonify({"error": "employee_id required"}), 400

    # Upsert
    goal = MonthlyGoal.query.filter_by(employee_id=emp_id, month=month, year=year).first()
    if goal:
        goal.target_hours = target
        goal.notes = notes
    else:
        goal = MonthlyGoal(employee_id=emp_id, month=month, year=year, target_hours=target, notes=notes)
        db.session.add(goal)

    db.session.commit()

    log_audit('goal_set', 'goal', goal.id, description=f"Set goal {target}h for employee {emp_id} ({month}/{year})")

    return jsonify({"success": True, "message": "Goal saved", "goal_id": goal.id})


@features_v76_bp.route('/goals/bulk', methods=['POST'])
def bulk_create_goals():
    """Create goals for all employees at once"""
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401

    emp = Employee.query.filter_by(user_id=session['user_id']).first()
    if not emp or (not emp.is_admin and emp.role not in ('admin', 'planning')):
        return jsonify({"error": "Unauthorized"}), 403

    data = request.json
    month = data.get('month', date.today().month)
    year = data.get('year', date.today().year)
    target = data.get('target_hours', 176)

    employees = Employee.query.filter_by(is_admin=False).all()
    created = 0
    for e in employees:
        existing = MonthlyGoal.query.filter_by(employee_id=e.id, month=month, year=year).first()
        if not existing:
            goal = MonthlyGoal(employee_id=e.id, month=month, year=year, target_hours=target)
            db.session.add(goal)
            created += 1

    db.session.commit()

    return jsonify({"success": True, "message": f"Created {created} goals", "total_employees": len(employees)})


# ═══════════════════════════════════════════════════════════════════════════════
# AUTO CLOCK-OUT
# ═══════════════════════════════════════════════════════════════════════════════

@features_v76_bp.route('/auto-clockout', methods=['POST'])
def auto_clockout():
    """
    Auto clock-out: end all running sessions that started before today or before 18:00.
    Called by a scheduled job or manually by admin.
    """
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401

    emp = Employee.query.filter_by(user_id=session['user_id']).first()
    if not emp or (not emp.is_admin and emp.role not in ('admin',)):
        return jsonify({"error": "Unauthorized"}), 403

    now = datetime.utcnow()
    cutoff_time = now.replace(hour=16, minute=0, second=0, microsecond=0)  # 18:00 local (UTC+2)

    # Find all running sessions
    running = TimesheetSession.query.filter_by(status='running').all()
    closed = 0

    for s in running:
        # Close if session started before cutoff or started before today
        if s.start_time < cutoff_time or s.date < now.date():
            s.status = 'completed'
            s.end_time = cutoff_time if s.start_time.date() == now.date() else s.start_time.replace(hour=16, minute=0)
            s.elapsed_seconds = int((s.end_time - s.start_time).total_seconds())
            closed += 1

            # Also end any active breaks
            active_breaks = TimesheetBreak.query.filter(
                TimesheetBreak.session_id == s.id,
                TimesheetBreak.end_time == None
            ).all()
            for b in active_breaks:
                b.end_time = s.end_time
                b.duration_minutes = int((b.end_time - b.start_time).total_seconds() / 60)

            log_activity(s.employee_id, 'auto_clockout',
                        f'Session auto-closed at 18:00', icon='clock')

    # Also close orphan breaks (breaks without session)
    orphan_breaks = TimesheetBreak.query.filter(
        TimesheetBreak.end_time == None,
        TimesheetBreak.start_time < cutoff_time
    ).all()
    for b in orphan_breaks:
        b.end_time = cutoff_time
        b.duration_minutes = int((b.end_time - b.start_time).total_seconds() / 60)

    db.session.commit()

    log_audit('auto_clockout', 'system', description=f"Auto clock-out: closed {closed} sessions")

    return jsonify({
        "success": True,
        "message": f"Auto clock-out completed: {closed} sessions closed",
        "closed_count": closed,
        "orphan_breaks_closed": len(orphan_breaks)
    })


@features_v76_bp.route('/auto-clockout/check', methods=['GET'])
def check_auto_clockout():
    """Check how many sessions would be affected by auto clock-out"""
    now = datetime.utcnow()
    cutoff_time = now.replace(hour=16, minute=0, second=0, microsecond=0)

    running = TimesheetSession.query.filter_by(status='running').all()
    would_close = [s for s in running if s.start_time < cutoff_time or s.date < now.date()]

    return jsonify({
        "success": True,
        "running_sessions": len(running),
        "would_close": len(would_close),
        "sessions": [{
            "id": s.id,
            "employee_id": s.employee_id,
            "employee_name": s.employee.name if s.employee else '-',
            "task_name": s.task_name,
            "start_time": s.start_time.isoformat() + 'Z'
        } for s in would_close]
    })


# ═══════════════════════════════════════════════════════════════════════════════
# GEOLOCATION
# ═══════════════════════════════════════════════════════════════════════════════

@features_v76_bp.route('/geolocation/save', methods=['POST'])
def save_geolocation():
    """Save geolocation data for a session"""
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401

    data = request.json
    session_id = data.get('session_id')
    lat = data.get('latitude')
    lng = data.get('longitude')
    location_name = data.get('location_name', '')
    event_type = data.get('type', 'start')  # start or end

    if not session_id or lat is None or lng is None:
        return jsonify({"error": "session_id, latitude, longitude required"}), 400

    ts = TimesheetSession.query.get(session_id)
    if not ts:
        return jsonify({"error": "Session not found"}), 404

    if event_type == 'start':
        ts.start_latitude = lat
        ts.start_longitude = lng
        ts.start_location_name = location_name
    else:
        ts.end_latitude = lat
        ts.end_longitude = lng

    db.session.commit()

    return jsonify({"success": True, "message": "Location saved"})


@features_v76_bp.route('/geolocation/history', methods=['GET'])
def get_geolocation_history():
    """Get geolocation history for an employee"""
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401

    emp = Employee.query.filter_by(user_id=session['user_id']).first()
    emp_id = request.args.get('employee_id', emp.id, type=int)

    # Non-admin can only see own
    if not emp.is_admin and emp.role not in ('admin', 'hr') and emp_id != emp.id:
        return jsonify({"error": "Unauthorized"}), 403

    sessions = TimesheetSession.query.filter(
        TimesheetSession.employee_id == emp_id,
        TimesheetSession.start_latitude != None
    ).order_by(TimesheetSession.start_time.desc()).limit(100).all()

    return jsonify({
        "success": True,
        "locations": [{
            "session_id": s.id,
            "date": s.date.isoformat(),
            "task_name": s.task_name,
            "start_lat": s.start_latitude,
            "start_lng": s.start_longitude,
            "start_location": s.start_location_name,
            "end_lat": s.end_latitude,
            "end_lng": s.end_longitude,
            "start_time": s.start_time.isoformat() + 'Z' if s.start_time else None
        } for s in sessions]
    })


# ═══════════════════════════════════════════════════════════════════════════════
# EMPLOYEE PROFILE
# ═══════════════════════════════════════════════════════════════════════════════

@features_v76_bp.route('/employee-profile/<int:emp_id>', methods=['GET'])
def get_employee_profile(emp_id):
    """
    Comprehensive employee profile with all stats and history.
    """
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401

    current_user = Employee.query.filter_by(user_id=session['user_id']).first()

    # Permission check: admin sees all, employee sees own
    if not current_user.is_admin and current_user.role not in ('admin', 'hr') and current_user.id != emp_id:
        return jsonify({"error": "Unauthorized"}), 403

    emp = Employee.query.get(emp_id)
    if not emp:
        return jsonify({"error": "Employee not found"}), 404

    today = date.today()
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)

    # ── Monthly stats ──
    month_sessions = TimesheetSession.query.filter(
        TimesheetSession.employee_id == emp_id,
        TimesheetSession.date >= month_start,
        TimesheetSession.status == 'completed'
    ).all()
    month_hours = sum(s.elapsed_seconds or 0 for s in month_sessions) / 3600.0

    # ── Year stats ──
    year_sessions = TimesheetSession.query.filter(
        TimesheetSession.employee_id == emp_id,
        TimesheetSession.date >= year_start,
        TimesheetSession.status == 'completed'
    ).all()
    year_hours = sum(s.elapsed_seconds or 0 for s in year_sessions) / 3600.0

    # ── Leave stats ──
    leaves_used = LeaveRequest.query.filter(
        LeaveRequest.employee_id == emp_id,
        LeaveRequest.status == 'approved',
        LeaveRequest.start_date >= year_start
    ).all()
    annual_used = sum(l.duration_days or 0 for l in leaves_used if l.leave_category == 'annual')
    sick_used = sum(l.duration_days or 0 for l in leaves_used if l.leave_category == 'sick')
    casual_used = sum(l.duration_days or 0 for l in leaves_used if l.leave_category == 'casual')

    # ── OT stats ──
    ot_approved = OvertimeRequest.query.filter(
        OvertimeRequest.employee_id == emp_id,
        OvertimeRequest.status == 'approved',
        OvertimeRequest.request_date >= month_start
    ).count()

    # ── Attendance rate ──
    working_days = 0
    present_days = 0
    d = month_start
    while d <= today:
        if d.weekday() < 5:  # Mon-Fri
            working_days += 1
            has_session = TimesheetSession.query.filter(
                TimesheetSession.employee_id == emp_id,
                TimesheetSession.date == d
            ).first()
            if has_session:
                present_days += 1
        d += timedelta(days=1)

    attendance_rate = round(present_days / working_days * 100, 1) if working_days > 0 else 0

    # ── Recent sessions ──
    recent_sessions = TimesheetSession.query.filter_by(
        employee_id=emp_id
    ).order_by(TimesheetSession.start_time.desc()).limit(10).all()

    # ── Monthly goal ──
    goal = MonthlyGoal.query.filter_by(
        employee_id=emp_id, month=today.month, year=today.year
    ).first()

    # ── Manager info ──
    manager_info = None
    if emp.manager_id:
        mgr = Employee.query.get(emp.manager_id)
        if mgr:
            manager_info = {"id": mgr.id, "name": mgr.name, "position": mgr.position}

    # ── Subordinates ──
    subs = Employee.query.filter_by(manager_id=emp_id).all()

    return jsonify({
        "success": True,
        "profile": {
            "id": emp.id,
            "user_id": emp.user_id,
            "name": emp.name,
            "email": emp.email,
            "department": emp.department,
            "position": emp.position,
            "role": emp.role,
            "is_admin": emp.is_admin,
            "created_at": emp.created_at.isoformat() + 'Z' if emp.created_at else None,
            "manager": manager_info,
            "subordinates": [{"id": s.id, "name": s.name, "position": s.position} for s in subs]
        },
        "stats": {
            "month_hours": round(month_hours, 2),
            "year_hours": round(year_hours, 2),
            "attendance_rate": attendance_rate,
            "present_days": present_days,
            "working_days": working_days,
            "ot_approved_this_month": ot_approved
        },
        "leave_balance": {
            "annual": {"total": emp.annual_leave_balance, "used": annual_used, "remaining": emp.annual_leave_balance - annual_used},
            "sick": {"total": emp.sick_leave_balance, "used": sick_used, "remaining": emp.sick_leave_balance - sick_used},
            "casual": {"total": emp.casual_leave_balance, "used": casual_used, "remaining": emp.casual_leave_balance - casual_used}
        },
        "goal": {
            "target_hours": goal.target_hours if goal else 176,
            "actual_hours": round(month_hours, 2),
            "progress_pct": round(month_hours / goal.target_hours * 100, 1) if goal and goal.target_hours > 0 else round(month_hours / 176 * 100, 1)
        },
        "recent_sessions": [{
            "id": s.id,
            "date": s.date.isoformat(),
            "task_name": s.task_name,
            "hour_type": s.hour_type,
            "elapsed": s.elapsed_seconds or 0,
            "status": s.status,
            "project_name": s.project.project_name if s.project else '-'
        } for s in recent_sessions]
    })


# ═══════════════════════════════════════════════════════════════════════════════
# ORGANIZATION CHART
# ═══════════════════════════════════════════════════════════════════════════════

@features_v76_bp.route('/org-chart', methods=['GET'])
def get_org_chart():
    """
    Get organization chart data as a tree structure.
    Returns hierarchical data: admin -> managers -> employees
    """
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401

    employees = Employee.query.all()

    # Build tree
    emp_map = {e.id: {
        "id": e.id,
        "name": e.name,
        "position": e.position or e.role or 'Employee',
        "department": e.department or '-',
        "role": e.role or ('admin' if e.is_admin else 'employee'),
        "email": e.email,
        "manager_id": e.manager_id,
        "children": []
    } for e in employees}

    roots = []
    for e in employees:
        node = emp_map[e.id]
        if e.manager_id and e.manager_id in emp_map:
            emp_map[e.manager_id]["children"].append(node)
        else:
            roots.append(node)

    # Sort: admins first, then by name
    roots.sort(key=lambda x: (0 if x['role'] == 'admin' else 1, x['name']))

    return jsonify({
        "success": True,
        "chart": roots,
        "total_employees": len(employees)
    })


# ═══════════════════════════════════════════════════════════════════════════════
# DEPARTMENT WIDGETS
# ═══════════════════════════════════════════════════════════════════════════════

@features_v76_bp.route('/department-widgets', methods=['GET'])
def get_department_widgets():
    """
    Get department-level statistics for dashboard widgets.
    Each department shows: total employees, active now, on break, on leave, avg hours
    """
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401

    today = date.today()
    departments = db.session.query(Employee.department).filter(
        Employee.department != None,
        Employee.is_admin == False
    ).distinct().all()

    widgets = []
    for (dept,) in departments:
        if not dept:
            continue

        dept_employees = Employee.query.filter_by(department=dept, is_admin=False).all()
        dept_ids = [e.id for e in dept_employees]

        # Active sessions now
        active_count = TimesheetSession.query.filter(
            TimesheetSession.employee_id.in_(dept_ids),
            TimesheetSession.status == 'running'
        ).count() if dept_ids else 0

        # On break now
        on_break = TimesheetBreak.query.filter(
            TimesheetBreak.employee_id.in_(dept_ids),
            TimesheetBreak.end_time == None
        ).count() if dept_ids else 0

        # On leave today
        on_leave = LeaveRequest.query.filter(
            LeaveRequest.employee_id.in_(dept_ids),
            LeaveRequest.start_date <= today,
            LeaveRequest.end_date >= today,
            LeaveRequest.status == 'approved'
        ).count() if dept_ids else 0

        # Average hours this month
        month_start = today.replace(day=1)
        total_hours = 0
        for eid in dept_ids:
            sessions = TimesheetSession.query.filter(
                TimesheetSession.employee_id == eid,
                TimesheetSession.date >= month_start,
                TimesheetSession.status == 'completed'
            ).all()
            total_hours += sum(s.elapsed_seconds or 0 for s in sessions) / 3600.0

        avg_hours = round(total_hours / len(dept_ids), 1) if dept_ids else 0

        widgets.append({
            "department": dept,
            "total_employees": len(dept_ids),
            "active_now": active_count,
            "on_break": on_break,
            "on_leave": on_leave,
            "absent": len(dept_ids) - active_count - on_break - on_leave,
            "avg_monthly_hours": avg_hours,
            "total_monthly_hours": round(total_hours, 1)
        })

    # Sort by department name
    widgets.sort(key=lambda x: x['department'])

    return jsonify({"success": True, "departments": widgets})
