from flask import Blueprint, request, jsonify, session, send_file
from datetime import datetime, date, timedelta
from models.database import db
from models.employee import Employee
from models.timesheet_session import TimesheetSession, TimesheetBreak, Project


timesheet_advanced_bp = Blueprint('timesheet_advanced', __name__, url_prefix='/api')

# حد ساعات العمل العادية في اليوم قبل التحول إلى Overtime
REGULAR_HOURS_LIMIT = 8 * 3600  # 8 ساعات بالثواني (تغيير من 8 إلى 8)
HALF_DAY_HOURS = 4 * 3600 + 30 * 60  # 4:30 ساعة بالثواني (نصف اليوم)

# وقت البريك الثابت: 12:30 - 13:30
BREAK_START_HOUR = 12
BREAK_START_MINUTE = 30
BREAK_END_HOUR = 13
BREAK_END_MINUTE = 30


def get_today_total_seconds(employee_id):
    """
    احتساب إجمالي ثواني العمل العادي (غير Overtime) لليوم الحالي للموظف.
    يُستخدم لمعرفة متى يتجاوز الموظف 8 ساعات (أو 4:30 في حالة نصف اليوم).
    """
    today = date.today()
    sessions = TimesheetSession.query.filter(
        TimesheetSession.employee_id == employee_id,
        TimesheetSession.date == today,
        TimesheetSession.hour_type != 'OVERTIME'  # لا نحسب جلسات Overtime
    ).all()

    total = 0
    for s in sessions:
        if s.status == 'completed':
            total += s.elapsed_seconds
        elif s.status == 'running':
            # الجلسة الجارية: نحسب الوقت المنقضي حتى الآن
            elapsed = int((datetime.utcnow() - s.start_time).total_seconds())
            total += s.elapsed_seconds + elapsed
    return total


def get_employee_overtime_threshold(employee_id):
    """
    تحديد حد الساعات قبل التحول إلى Overtime لموظف معين.
    - إذا لديه إجازة نصف يوم اليوم → 4:30 ساعة (16200 ثانية)
    - إذا لم يكن لديه إجازة → 8 ساعات (28800 ثانية)
    """
    from models.employee import LeaveRequest
    today = date.today()
    # التحقق من وجود إجازة نصف يوم مقبولة اليوم
    half_day_leave = LeaveRequest.query.filter(
        LeaveRequest.employee_id == employee_id,
        LeaveRequest.start_date == today,
        LeaveRequest.is_half_day == True,
        LeaveRequest.status == 'approved'
    ).first()
    
    if half_day_leave:
        return HALF_DAY_HOURS  # 4:30 ساعة
    return REGULAR_HOURS_LIMIT  # 8 ساعات


@timesheet_advanced_bp.route('/projects', methods=['GET'])
def get_projects():
    """الحصول على قائمة المشاريع النشطة"""
    projects = Project.query.filter_by(is_active=True).order_by(Project.project_number).all()
    projects_data = []
    for project in projects:
        projects_data.append({
            "id": project.id,
            "project_number": project.project_number,
            "project_name": project.project_name
        })
    return jsonify({"success": True, "projects": projects_data})


@timesheet_advanced_bp.route("/timesheet/active_session", methods=["GET"])
def get_active_session():
    """
    الحصول على الجلسة النشطة للموظف الحالي.
    يتحقق أيضاً إذا تجاوز الموظف 8 ساعات ويُعيد تنبيهاً.
    """
    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401

    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    active_session = TimesheetSession.query.filter_by(
        employee_id=current_user.id,
        status='running'
    ).first()

    # حساب إجمالي ساعات اليوم لإعلام الواجهة
    today_total = get_today_total_seconds(current_user.id)
    threshold = get_employee_overtime_threshold(current_user.id)
    overtime_reached = today_total >= threshold

    if active_session:
        # Get project name for display
        proj = Project.query.get(active_session.project_id)
        proj_name = proj.project_name if proj else '-'
        proj_number = proj.project_number if proj else '-'
        return jsonify({
            "active_session": {
                "id": active_session.id,
                "start_time": active_session.start_time.isoformat() + 'Z',  # UTC marker for correct browser parsing
                "hour_type": active_session.hour_type,
                "project_id": active_session.project_id,
                "project_name": proj_name,
                "project_number": proj_number,
                "task_name": active_session.task_name,
                "job_no": active_session.job_no,
                "description": active_session.description,
                "elapsed_seconds": active_session.elapsed_seconds or 0
            },
            "today_total_seconds": today_total,
            "overtime_reached": overtime_reached,
            "overtime_threshold": threshold
        })
    else:
        return jsonify({
            "active_session": None,
            "today_total_seconds": today_total,
            "overtime_reached": overtime_reached,
            "overtime_threshold": threshold
        })


@timesheet_advanced_bp.route("/timesheet/session/end", methods=["POST"])
def end_session():
    """إنهاء الجلسة النشطة للموظف الحالي"""
    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401

    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    active_session = TimesheetSession.query.filter_by(
        employee_id=current_user.id,
        status='running'
    ).first()

    if not active_session:
        return jsonify({"error": "لا توجد جلسة نشطة لإنهاءها"}), 400

    elapsed = int((datetime.utcnow() - active_session.start_time).total_seconds())
    active_session.elapsed_seconds += elapsed
    active_session.status = 'completed'
    active_session.end_time = datetime.utcnow()
    db.session.commit()

    return jsonify({"success": True, "message": "تم إنهاء الجلسة بنجاح"})


@timesheet_advanced_bp.route("/timesheet/session/start", methods=["POST"])
def start_session():
    """
    بدء جلسة عمل جديدة مع منطق Overtime التلقائي:
    1. إذا كانت هناك جلسة نشطة، تُغلق تلقائياً.
    2. إذا تجاوز الموظف 8 ساعات عمل عادي اليوم، تُفتح الجلسة الجديدة
       بنوع OVERTIME تلقائياً بنفس بيانات الجلسة (مشروع، Job No، مهمة).
    3. إذا لم يتجاوز 8 ساعات، تُفتح الجلسة بالنوع المحدد من المستخدم.
    """
    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401

    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    data = request.json

    # التحقق من الحقول المطلوبة
    if not data or 'hour_type' not in data:
        return jsonify({"error": "الحقل hour_type مطلوب"}), 400

    if data['hour_type'] == 'WORK ORDER':
        work_order_required_fields = ['project_id', 'job_no', 'task_name']
        for field in work_order_required_fields:
            if field not in data or not data[field]:
                return jsonify({"error": f"الحقل المطلوب مفقود لنوع WORK ORDER: {field}"}), 400

    # إيقاف أي جلسة قيد التنفيذ للموظف وحفظ بياناتها للاستخدام في Overtime
    active_session = TimesheetSession.query.filter_by(
        employee_id=current_user.id,
        status='running'
    ).first()

    prev_session_data = None
    if active_session:
        elapsed = int((datetime.utcnow() - active_session.start_time).total_seconds())
        active_session.elapsed_seconds += elapsed
        active_session.status = 'completed'
        active_session.end_time = datetime.utcnow()
        # حفظ بيانات الجلسة السابقة لاستخدامها عند التحول إلى Overtime
        prev_session_data = {
            "project_id": active_session.project_id,
            "job_no": active_session.job_no,
            "task_name": active_session.task_name,
            "description": active_session.description,
            "hour_type": active_session.hour_type
        }

    # تحديد project_id
    project_id = data.get('project_id')
    if not project_id:
        internal_project = Project.query.filter_by(project_number='INTERNAL').first()
        if internal_project:
            project_id = internal_project.id
        else:
            return jsonify({"error": "المشروع الداخلي الافتراضي غير موجود"}), 500

    # التحقق من إجمالي ساعات اليوم لتحديد نوع الجلسة
    today_total = get_today_total_seconds(current_user.id)
    threshold = get_employee_overtime_threshold(current_user.id)
    final_hour_type = data.get('hour_type')
    overtime_auto_switched = False

    if today_total >= threshold and final_hour_type != 'OVERTIME':
        # تجاوز 8 ساعات → تحويل تلقائي إلى OVERTIME بنفس بيانات الجلسة
        final_hour_type = 'OVERTIME'
        overtime_auto_switched = True

        # إذا كانت هناك جلسة سابقة، نستخدم بياناتها
        if prev_session_data:
            project_id = prev_session_data['project_id'] or project_id
            data['job_no'] = prev_session_data['job_no'] or data.get('job_no')
            data['task_name'] = prev_session_data['task_name'] or data.get('task_name')
            data['description'] = prev_session_data['description'] or data.get('description')

    # تحديد حالة موافقة Overtime:
    # - إذا اختار الموظف OVERTIME يدوياً → pending (بانتظار موافقة المدير)
    # - إذا كانت OVERTIME تلقائية (تجاوز 8 ساعات) → pending أيضاً
    # - أي نوع آخر → None
    ot_approval = 'pending' if final_hour_type == 'OVERTIME' else None

    # بدء الجلسة الجديدة
    new_session = TimesheetSession(
        employee_id=current_user.id,
        project_id=project_id,
        date=date.today(),
        task_name=data.get('task_name', final_hour_type),
        hour_type=final_hour_type,
        job_no=data.get('job_no'),
        description=data.get('description'),
        start_time=datetime.utcnow(),
        status='running',
        overtime_approval_status=ot_approval
    )

    db.session.add(new_session)
    db.session.commit()

    response_data = {
        "success": True,
        "session": {
            "id": new_session.id,
            "start_time": new_session.start_time.isoformat() + 'Z',
            "hour_type": new_session.hour_type,
            "project_id": new_session.project_id,
            "project_name": Project.query.get(new_session.project_id).project_name if Project.query.get(new_session.project_id) else '-',
            "project_number": Project.query.get(new_session.project_id).project_number if Project.query.get(new_session.project_id) else '-',
            "task_name": new_session.task_name,
            "job_no": new_session.job_no,
            "description": new_session.description
        },
        "message": "تم بدء الجلسة بنجاح",
        "overtime_auto_switched": overtime_auto_switched,
        "today_total_seconds": today_total
    }

    if overtime_auto_switched:
        response_data["message"] = "تم تجاوز 8 ساعات عمل - تم التحويل تلقائياً إلى OVERTIME بنفس بيانات المهمة"

    return jsonify(response_data)


@timesheet_advanced_bp.route("/timesheet/check_overtime", methods=["POST"])
def check_overtime():
    """
    نقطة API للتحقق من حالة Overtime أثناء الجلسة الجارية.
    تُستدعى من الواجهة بشكل دوري (كل دقيقة مثلاً).
    إذا تجاوز الموظف 8 ساعات، تُغلق الجلسة الحالية وتُفتح مثلها بنوع OVERTIME.
    """
    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401

    current_user = Employee.query.filter_by(user_id=session['user_id']).first()

    # البحث عن الجلسة الجارية التي ليست Overtime
    active_session = TimesheetSession.query.filter_by(
        employee_id=current_user.id,
        status='running'
    ).first()

    if not active_session or active_session.hour_type == 'OVERTIME':
        # لا توجد جلسة نشطة أو هي بالفعل Overtime
        return jsonify({"switched": False})

    # حساب إجمالي ساعات اليوم
    today_total = get_today_total_seconds(current_user.id)
    threshold = get_employee_overtime_threshold(current_user.id)
    if today_total < threshold:
        # لم يتجاوز الحد بعد
        remaining = threshold - today_total
        return jsonify({
            "switched": False,
            "today_total_seconds": today_total,
            "remaining_seconds": remaining,
            "overtime_threshold": threshold
        })
    # تجاوز 8 ساعات → إغلاق الجلسة الحالية وفتح مثلها بنوع OVERTIME
    elapsed = int((datetime.utcnow() - active_session.start_time).total_seconds())
    active_session.elapsed_seconds += elapsed
    active_session.status = 'completed'
    active_session.end_time = datetime.utcnow()

    # حفظ بيانات الجلسة لفتح مثلها - تبدأ بحالة pending لانتظار موافقة المدير
    overtime_session = TimesheetSession(
        employee_id=current_user.id,
        project_id=active_session.project_id,
        date=date.today(),
        task_name=active_session.task_name,
        hour_type='OVERTIME',
        job_no=active_session.job_no,
        description=active_session.description,
        start_time=datetime.utcnow(),
        status='running',
        overtime_approval_status='pending'
    )

    db.session.add(overtime_session)
    db.session.commit()

    return jsonify({
        "switched": True,
        "message": "تم تجاوز 8 ساعات - تم التحويل تلقائياً إلى OVERTIME",
        "new_session": {
            "id": overtime_session.id,
            "hour_type": overtime_session.hour_type,
            "task_name": overtime_session.task_name,
            "job_no": overtime_session.job_no,
            "project_id": overtime_session.project_id
        }
    })

def get_all_team_ids(manager):
    ids = []

    for emp in manager.subordinates:
        ids.append(emp.id)   # ✅ دي الصح
        ids.extend(get_all_team_ids(emp))  # ✅ دي اللي بتجيب كل المستويات

    return ids
@timesheet_advanced_bp.route('/timesheet/sessions', methods=['GET'])
def get_sessions():

    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401

    current_user = Employee.query.filter_by(user_id=session["user_id"]).first()

    if not current_user:
        return jsonify({"error": "غير مصرح"}), 403

    # ✅ DEBUG مهم
    print("CURRENT USER:", current_user.id, current_user.name)
    

    # ✅ ACCESS CONTROL
    if current_user.is_admin:

        query = TimesheetSession.query

    # ✅ أي حد عنده team (manager أو team leader)
    elif current_user.role == 'manager' or Employee.query.filter_by(manager_id=current_user.id).count() > 0:

        team_ids = get_all_team_ids(current_user)
        team_ids.append(current_user.id)


        # ✅ DEBUG
        print("TEAM MEMBERS FROM DB:", [(e.id, e.name) for e in team_members])

        team_ids = [e.id for e in team_members]

        # ✅ ضيف نفسه
        team_ids.append(current_user.id)

        print("TEAM IDS:", team_ids)

        query = TimesheetSession.query.filter(
            TimesheetSession.employee_id.in_(team_ids)
        )

    elif current_user.role == 'planning':

        query = TimesheetSession.query

    else:

        query = TimesheetSession.query.filter_by(
            employee_id=current_user.id
        )


    # ✅ FILTERS

    project_id = request.args.get("project_id", type=int)
    if project_id:
        query = query.filter_by(project_id=project_id)

    project_number = request.args.get("project_number", "").strip()
    if project_number:
        from models.timesheet_session import Project
        matched_projects = Project.query.filter(
            Project.project_number.ilike(f"%{project_number}%")
        ).all()
        matched_ids = [p.id for p in matched_projects]
        query = query.filter(TimesheetSession.project_id.in_(matched_ids))

    employee_id = request.args.get("employee_id", type=int)
    if employee_id and current_user.is_admin:
        query = query.filter_by(employee_id=employee_id)

    hour_type = request.args.get("hour_type", "").strip()
    if hour_type:
        query = query.filter_by(hour_type=hour_type)
        
    project_id = request.args.get("project_id", type=int)
    job_no = request.args.get("job_no", "").strip()

    if project_id:
        query = query.filter(TimesheetSession.project_id == project_id)
    if job_no:
        query = query.filter(TimesheetSession.job_no.ilike(f"%{job_no}%"))

    department = request.args.get("department", "").strip()
    if department:
        from models.employee import Employee as Emp
        emp_ids = [
            e.id for e in Emp.query.filter(
                Emp.department.ilike(f"%{department}%")
            ).all()
        ]
        query = query.filter(TimesheetSession.employee_id.in_(emp_ids))

    start_date_str = request.args.get("start_date")
    end_date_str   = request.args.get("end_date")

    if start_date_str:
        query = query.filter(
            TimesheetSession.date >= datetime.strptime(start_date_str, "%Y-%m-%d").date()
        )

    if end_date_str:
        query = query.filter(
            TimesheetSession.date <= datetime.strptime(end_date_str, "%Y-%m-%d").date()
        )


    # ✅ FETCH DATA
    sessions = query.order_by(
        TimesheetSession.date.desc(),
        TimesheetSession.start_time.desc()
    ).all()


    sessions_data = []

    for s in sessions:
        sessions_data.append({
            "id": s.id,
            "date": s.date.strftime('%Y-%m-%d'),
            "employee_id": s.employee_id,
            "employee_user_id": s.employee.user_id if s.employee else "-",
            "employee_name": s.employee.name if s.employee else "-",
            "employee_department": s.employee.department if s.employee else "-",
            "employee_position": s.employee.position if s.employee else "-",
            "project_id": s.project_id,
            "project_number": s.project.project_number if s.project else "-",
            "project_name": s.project.project_name if s.project else "بدون مشروع",
            "task_name": s.task_name,
            "job_no": s.job_no or "-",
            "description": s.description or "",
            "hour_type": s.hour_type,
            "status": s.status,
            "total_time": s.get_formatted_time(),
            "elapsed_seconds": s.elapsed_seconds,
            "start_time": s.start_time.isoformat() if s.start_time else None,
            "end_time": s.end_time.isoformat() if s.end_time else None,
            "overtime_approval_status": s.overtime_approval_status if s.hour_type == 'OVERTIME' else None,
            "overtime_rejection_note": s.overtime_rejection_note or ''
        })


    return jsonify({
        "success": True,
        "sessions": sessions_data
    })

@timesheet_advanced_bp.route("/projects/<int:project_id>/jobs", methods=["GET"])
def get_project_jobs(project_id):
    """جلب Job Numbers من قاعدة البيانات للمشروع المحدد"""
    from models.timesheet_session import ProjectJob
    jobs = ProjectJob.query.filter_by(project_id=project_id, is_active=True).all()
    jobs_data = [{"id": j.id, "job_number": j.job_number, "description": j.description} for j in jobs]
    return jsonify({"success": True, "jobs": jobs_data})


@timesheet_advanced_bp.route("/timesheet/export/excel", methods=["GET"])
def export_timesheet_to_excel():
    """تصدير سجل المهام إلى Excel - للمدير فقط"""
    if "user_id" not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401

    current_user = Employee.query.filter_by(user_id=session["user_id"]).first()
    if not current_user.is_admin:
        return jsonify({"error": "غير مصرح لك بالوصول"}), 403

    project_id = request.args.get("project_id", type=int)
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")

    query = TimesheetSession.query

    if project_id:
        query = query.filter_by(project_id=project_id)

    if start_date_str:
        query = query.filter(TimesheetSession.date >= datetime.strptime(start_date_str, "%Y-%m-%d").date())
    if end_date_str:
        query = query.filter(TimesheetSession.date <= datetime.strptime(end_date_str, "%Y-%m-%d").date())

    sessions = query.order_by(TimesheetSession.date.desc(), TimesheetSession.start_time.desc()).all()

    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Timesheet Data"

    headers = ["ID", "التاريخ", "معرف الموظف", "اسم الموظف", "القسم", "المنصب",
               "رقم المشروع", "اسم المشروع", "Job No", "المهمة", "الوصف",
               "نوع الساعة", "الحالة", "إجمالي الوقت", "وقت البدء", "وقت الانتهاء"]
    ws.append(headers)

    for s in sessions:
        ws.append([
            s.id,
            s.date.strftime("%Y-%m-%d"),
            s.employee.user_id if s.employee else "-",
            s.employee.name if s.employee else "-",
            s.employee.department if s.employee else "-",
            s.employee.position if s.employee else "-",
            s.project.project_number if s.project else "-",
            s.project.project_name if s.project else "بدون مشروع",
            s.job_no or "-",
            s.task_name,
            s.description,
            s.hour_type,
            s.status,
            s.get_formatted_time(),
            s.start_time.strftime("%Y-%m-%d %H:%M:%S") if s.start_time else "",
            s.end_time.strftime("%Y-%m-%d %H:%M:%S") if s.end_time else ""
        ])

    from io import BytesIO
    excel_file = BytesIO()
    wb.save(excel_file)
    excel_file.seek(0)

    from flask import send_file
    return send_file(
        excel_file,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="timesheet_data.xlsx"
    )


@timesheet_advanced_bp.route("/timesheet/today-stats", methods=["GET"])
def get_today_stats():
    """
    إحصائية ساعات كل موظف في اليوم الحالي (أو تاريخ محدد).
    للمدير فقط - يُستخدم في لوحة الإحصائيات اليومية.
    يُرجع:
    - اسم الموظف وقسمه
    - إجمالي ساعات العمل العادي اليوم
    - إجمالي ساعات الـ Overtime اليوم
    - عدد الجلسات
    - هل لديه جلسة نشطة الآن؟
    """
    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401

    current_user = Employee.query.filter_by(user_id=session["user_id"]).first()
    if not current_user or not current_user.is_admin:
        return jsonify({"error": "غير مصرح"}), 403

    # التاريخ المطلوب (افتراضي: اليوم)
    date_str = request.args.get("date")
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else date.today()

    employees = Employee.query.filter_by(is_admin=False).all()
    result = []

    for emp in employees:
        sessions = TimesheetSession.query.filter_by(
            employee_id=emp.id,
            date=target_date
        ).all()

        regular_secs  = sum(s.elapsed_seconds for s in sessions if s.hour_type != 'OVERTIME')
        overtime_secs = sum(s.elapsed_seconds for s in sessions if s.hour_type == 'OVERTIME')
        total_secs    = regular_secs + overtime_secs
        active_now    = any(s.status == 'active' for s in sessions)

        def fmt(secs):
            h = secs // 3600
            m = (secs % 3600) // 60
            return f"{h:02d}:{m:02d}"

        result.append({
            "id": emp.id,
            "name": emp.name,
            "department": emp.department or "-",
            "position": emp.position or "-",
            "regular_hours": fmt(regular_secs),
            "regular_seconds": regular_secs,
            "overtime_hours": fmt(overtime_secs),
            "overtime_seconds": overtime_secs,
            "total_hours": fmt(total_secs),
            "total_seconds": total_secs,
            "session_count": len(sessions),
            "active_now": active_now
        })

    # ترتيب حسب إجمالي الساعات تنازلياً
    result.sort(key=lambda x: x['total_seconds'], reverse=True)

    return jsonify({
        "success": True,
        "date": target_date.strftime("%Y-%m-%d"),
        "employees": result
    })


@timesheet_advanced_bp.route("/timesheet/project-totals", methods=["GET"])
def get_project_totals():
    """
    إجمالي الساعات المسجلة لكل مشروع.
    يدعم فلتر التاريخ (start_date / end_date).
    """
    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401

    current_user = Employee.query.filter_by(user_id=session["user_id"]).first()
    if not current_user or not current_user.is_admin:
        return jsonify({"error": "غير مصرح"}), 403

    start_date_str = request.args.get("start_date")
    end_date_str   = request.args.get("end_date")

    query = TimesheetSession.query.filter(
        TimesheetSession.status == 'completed',
        TimesheetSession.project_id != None
    )
    if start_date_str:
        query = query.filter(TimesheetSession.date >= datetime.strptime(start_date_str, "%Y-%m-%d").date())
    if end_date_str:
        query = query.filter(TimesheetSession.date <= datetime.strptime(end_date_str, "%Y-%m-%d").date())

    sessions = query.all()

    # تجميع حسب المشروع
    project_map = {}
    for s in sessions:
        pid = s.project_id
        if pid not in project_map:
            project_map[pid] = {
                "project_id": pid,
                "project_number": s.project.project_number if s.project else "-",
                "project_name": s.project.project_name if s.project else "بدون مشروع",
                "regular_seconds": 0,
                "overtime_seconds": 0,
                "session_count": 0
            }
        if s.hour_type == 'OVERTIME':
            project_map[pid]["overtime_seconds"] += s.elapsed_seconds
        else:
            project_map[pid]["regular_seconds"] += s.elapsed_seconds
        project_map[pid]["session_count"] += 1

    def fmt(secs):
        h = secs // 3600
        m = (secs % 3600) // 60
        return f"{h:02d}:{m:02d}"

    totals = []
    for pid, data in project_map.items():
        total = data["regular_seconds"] + data["overtime_seconds"]
        totals.append({
            **data,
            "total_seconds": total,
            "total_hours": fmt(total),
            "regular_hours": fmt(data["regular_seconds"]),
            "overtime_hours": fmt(data["overtime_seconds"])
        })

    totals.sort(key=lambda x: x["total_seconds"], reverse=True)

    # إجمالي كل المشاريع
    grand_total = sum(t["total_seconds"] for t in totals)
    grand_h = grand_total // 3600
    grand_m = (grand_total % 3600) // 60

    return jsonify({
        "success": True,
        "projects": totals,
        "grand_total_hours": f"{grand_h:02d}:{grand_m:02d}",
        "grand_total_seconds": grand_total
    })


# ═══════════════════════════════════════════════════════════════════════════════
# Break API - إدارة فترات الراحة
# ═══════════════════════════════════════════════════════════════════════════════

@timesheet_advanced_bp.route('/timesheet/break/start', methods=['POST'])
def start_break():
    """
    Start a break period.
    Break time: 12:30 - 13:30 (1 hour = included in 8h work day).
    Automatically pauses any running session.
    """
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401

    current_user = Employee.query.filter_by(user_id=session['user_id']).first()

    # Check for existing active break (by employee_id or session_id)
    active_break = TimesheetBreak.query.filter(
        TimesheetBreak.end_time == None,
        TimesheetBreak.employee_id == current_user.id
    ).first()

    if not active_break:
        # Also check by session_id (legacy)
        today_session_ids = [s.id for s in TimesheetSession.query.filter_by(
            employee_id=current_user.id, date=date.today()
        ).all()]
        if today_session_ids:
            active_break = TimesheetBreak.query.filter(
                TimesheetBreak.end_time == None,
                TimesheetBreak.session_id.in_(today_session_ids)
            ).first()

    if active_break:
        return jsonify({"error": "Break already active"}), 400

    # Find and pause ALL running sessions for this employee
    running_sessions = TimesheetSession.query.filter_by(
        employee_id=current_user.id,
        status='running'
    ).all()

    first_session_id = None
    for rs in running_sessions:
        elapsed = int((datetime.utcnow() - rs.start_time).total_seconds())
        rs.elapsed_seconds += elapsed
        rs.status = 'paused'
        rs.paused_at = datetime.utcnow()
        if first_session_id is None:
            first_session_id = rs.id

    # Create break record
    new_break = TimesheetBreak(
        session_id=first_session_id,
        employee_id=current_user.id,
        break_type='break',
        start_time=datetime.utcnow(),
        reason='Lunch break 12:30 - 13:30'
    )
    db.session.add(new_break)
    db.session.commit()

    return jsonify({
        "success": True,
        "break_id": new_break.id,
        "start_time": new_break.start_time.isoformat() + 'Z',
        "message": "Break started"
    })


@timesheet_advanced_bp.route('/timesheet/break/end', methods=['POST'])
def end_break():
    """
    End break and resume paused sessions.
    """
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401

    current_user = Employee.query.filter_by(user_id=session['user_id']).first()

    # Find active break by employee_id first
    active_break = TimesheetBreak.query.filter(
        TimesheetBreak.end_time == None,
        TimesheetBreak.employee_id == current_user.id
    ).first()

    if not active_break:
        # Fallback: check by session_id
        today_session_ids = [s.id for s in TimesheetSession.query.filter_by(
            employee_id=current_user.id, date=date.today()
        ).all()]
        if today_session_ids:
            active_break = TimesheetBreak.query.filter(
                TimesheetBreak.end_time == None,
                TimesheetBreak.session_id.in_(today_session_ids)
            ).first()

    if not active_break:
        return jsonify({"error": "No active break"}), 400

    # End break
    now = datetime.utcnow()
    active_break.end_time = now
    duration_seconds = int((now - active_break.start_time).total_seconds())
    active_break.duration_minutes = duration_seconds // 60

    # Resume ALL paused sessions
    paused_sessions = TimesheetSession.query.filter_by(
        employee_id=current_user.id,
        status='paused'
    ).all()

    for ps in paused_sessions:
        ps.status = 'running'
        ps.start_time = now  # Reset start time for correct calculation
        ps.paused_at = None

    db.session.commit()

    return jsonify({
        "success": True,
        "duration_minutes": active_break.duration_minutes,
        "message": f"Break ended ({active_break.duration_minutes} min)"
    })


@timesheet_advanced_bp.route('/timesheet/break/active', methods=['GET'])
def get_active_break():
    """Check if employee has an active break"""
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401

    current_user = Employee.query.filter_by(user_id=session['user_id']).first()

    # Check by employee_id first
    active_break = TimesheetBreak.query.filter(
        TimesheetBreak.end_time == None,
        TimesheetBreak.employee_id == current_user.id
    ).first()

    if not active_break:
        # Fallback: check by session_id
        today_session_ids = [s.id for s in TimesheetSession.query.filter_by(
            employee_id=current_user.id, date=date.today()
        ).all()]
        if today_session_ids:
            active_break = TimesheetBreak.query.filter(
                TimesheetBreak.end_time == None,
                TimesheetBreak.session_id.in_(today_session_ids)
            ).first()

    if active_break:
        elapsed = int((datetime.utcnow() - active_break.start_time).total_seconds())
        return jsonify({
            "active_break": {
                "id": active_break.id,
                "start_time": active_break.start_time.isoformat() + 'Z',
                "elapsed_seconds": elapsed
            }
        })
    return jsonify({"active_break": None})


@timesheet_advanced_bp.route('/timesheet/breaks', methods=['GET'])
def get_breaks():
    """
    جلب سجل البريك.
    - الموظف يرى بريكاته فقط.
    - الأدمن يرى الكل مع فلتر الموظف والتاريخ.
    """
    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401

    current_user = Employee.query.filter_by(user_id=session['user_id']).first()

    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    employee_id = request.args.get('employee_id', type=int)

    # Build query
    query = TimesheetBreak.query
    if current_user.is_admin or current_user.role in ('admin', 'hr', 'planning'):
        # Admin sees all
        if employee_id:
            query = query.filter(
                db.or_(
                    TimesheetBreak.employee_id == employee_id,
                    TimesheetBreak.session_id.in_(
                        [s.id for s in TimesheetSession.query.filter_by(employee_id=employee_id).all()]
                    )
                )
            )
    else:
        # Employee sees own breaks only
        own_session_ids = [s.id for s in TimesheetSession.query.filter_by(employee_id=current_user.id).all()]
        query = query.filter(
            db.or_(
                TimesheetBreak.employee_id == current_user.id,
                TimesheetBreak.session_id.in_(own_session_ids) if own_session_ids else False
            )
        )

    # فلتر التاريخ
    if start_date_str:
        start_dt = datetime.strptime(start_date_str, '%Y-%m-%d')
        query = query.filter(TimesheetBreak.start_time >= start_dt)
    if end_date_str:
        end_dt = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        query = query.filter(TimesheetBreak.start_time <= end_dt)

    breaks = query.order_by(TimesheetBreak.start_time.desc()).all()

    result = []
    for b in breaks:
        # Resolve employee from employee_id or session
        emp = None
        if b.employee_id:
            emp = Employee.query.get(b.employee_id)
        elif b.session_id:
            sess = TimesheetSession.query.get(b.session_id)
            if sess:
                emp = Employee.query.get(sess.employee_id)
        result.append({
            "id": b.id,
            "session_id": b.session_id,
            "employee_name": emp.name if emp else '-',
            "employee_id": emp.id if emp else None,
            "break_type": b.break_type,
            "start_time": b.start_time.strftime('%Y-%m-%d %H:%M') if b.start_time else '',
            "end_time": b.end_time.strftime('%Y-%m-%d %H:%M') if b.end_time else 'Active...',
            "duration_minutes": b.duration_minutes or 0,
            "reason": b.reason or '',
            "is_active": b.end_time is None
        })

    # إجمالي وقت البريك
    total_minutes = sum(b['duration_minutes'] for b in result if not b['is_active'])

    return jsonify({
        "success": True,
        "breaks": result,
        "total_minutes": total_minutes,
        "total_hours": f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"
    })


@timesheet_advanced_bp.route('/timesheet/breaks/<int:break_id>', methods=['PUT'])
def update_break(break_id):
    """تعديل بريك (للأدمن فقط)"""
    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401

    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not (current_user.is_admin or current_user.role == 'admin'):
        return jsonify({"error": "Unauthorized - Admin only"}), 403

    b = TimesheetBreak.query.get_or_404(break_id)
    data = request.get_json() or {}

    if 'start_time' in data and data['start_time']:
        b.start_time = datetime.strptime(data['start_time'], '%Y-%m-%dT%H:%M')
    if 'end_time' in data and data['end_time']:
        b.end_time = datetime.strptime(data['end_time'], '%Y-%m-%dT%H:%M')
        if b.start_time and b.end_time:
            b.duration_minutes = int((b.end_time - b.start_time).total_seconds()) // 60
    if 'reason' in data:
        b.reason = data['reason']

    db.session.commit()
    return jsonify({"success": True, "message": "Break updated"})


# ═══════════════════════════════════════════════════════════════════════════════
# API للأقسام - جلب قائمة الأقسام للفلاتر
# ═══════════════════════════════════════════════════════════════════════════════

@timesheet_advanced_bp.route('/departments', methods=['GET'])
def get_departments():
    """جلب قائمة الأقسام الفريدة من جدول الموظفين"""
    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401

    # جلب الأقسام الفريدة غير الفارغة
    departments = db.session.query(Employee.department).filter(
        Employee.department != None,
        Employee.department != ''
    ).distinct().order_by(Employee.department).all()

    dept_list = [d[0] for d in departments if d[0]]
    return jsonify({"success": True, "departments": dept_list})


# ═══════════════════════════════════════════════════════════════════════════════
# إصلاح API البصمة ZK - مع معالجة خطأ التاريخ
# ═══════════════════════════════════════════════════════════════════════════════

@timesheet_advanced_bp.route('/fingerprint/fetch', methods=['POST'])
def fetch_fingerprint():
    """
    جلب بيانات البصمة من جهاز ZK يدوياً (زر جلب البصمات).
    يعالج خطأ 'day is out of range for month' بتجاهل السجلات ذات التواريخ غير الصالحة.
    """
    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401

    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not (current_user.is_admin or current_user.role in ('admin', 'manager', 'planning')):
        return jsonify({"error": "غير مصرح"}), 403

    try:
        from zk import ZK
        zk = ZK('172.18.0.249', port=4370, timeout=10)
        conn = zk.connect()
        attendances = conn.get_attendance()
        conn.disconnect()
    except Exception as e:
        return jsonify({
            "error": f"فشل الاتصال بجهاز البصمة: {str(e)}",
            "records": [],
            "count": 0
        }), 200

    from_date = request.get_json().get('from_date') if request.is_json else None
    to_date = request.get_json().get('to_date') if request.is_json else None

    records = []
    skipped = 0

    for att in attendances:
        try:
            # معالجة خطأ التاريخ غير الصالح
            if att.timestamp is None:
                skipped += 1
                continue

            att_date = att.timestamp.date()
            att_time_str = att.timestamp.strftime('%Y-%m-%d %H:%M:%S')
            date_str = str(att_date)

            # فلتر التاريخ
            if from_date:
                if att_date < datetime.strptime(from_date, '%Y-%m-%d').date():
                    continue
            if to_date:
                if att_date > datetime.strptime(to_date, '%Y-%m-%d').date():
                    continue

            records.append({
                "user_id": str(att.user_id),
                "timestamp": att_time_str,
                "date": date_str,
                "time": att.timestamp.strftime('%H:%M:%S'),
                "status": att.status,
                "punch": att.punch
            })
        except (ValueError, OverflowError, OSError):
            # تجاهل السجلات ذات التواريخ غير الصالحة
            skipped += 1
            continue

    return jsonify({
        "success": True,
        "records": records,
        "count": len(records),
        "skipped": skipped,
        "message": f"تم جلب {len(records)} سجل بنجاح، تم تجاهل {skipped} سجل بتاريخ غير صالح"
    })



# ═══════════════════════════════════════════════════════════════════════════════
# REPORTS API v74
# ═══════════════════════════════════════════════════════════════════════════════

@timesheet_advanced_bp.route('/reports/monthly-summary', methods=['GET'])
def report_monthly_summary():
    """Monthly summary report: total hours, OT, breaks per employee"""
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not current_user or not current_user.is_admin:
        return jsonify({"error": "Unauthorized"}), 403

    import calendar
    year = request.args.get('year', date.today().year, type=int)
    month = request.args.get('month', date.today().month, type=int)
    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])

    employees = Employee.query.filter_by(is_admin=False).all()
    data = []
    for emp in employees:
        sessions = TimesheetSession.query.filter(
            TimesheetSession.employee_id == emp.id,
            TimesheetSession.date >= first_day,
            TimesheetSession.date <= last_day,
            TimesheetSession.status == 'completed'
        ).all()
        total_sec = sum(s.elapsed_seconds or 0 for s in sessions)
        ot_sec = sum(s.elapsed_seconds or 0 for s in sessions if s.hour_type == 'OVERTIME')
        reg_sec = total_sec - ot_sec
        work_days = len(set(s.date for s in sessions))

        # Breaks
        sess_ids = [s.id for s in sessions]
        brk_min = 0
        if sess_ids:
            brks = TimesheetBreak.query.filter(TimesheetBreak.session_id.in_(sess_ids)).all()
            brk_min = sum(b.duration_minutes or 0 for b in brks)

        def fmt(s):
            return f"{s//3600:02d}:{(s%3600)//60:02d}"

        data.append({
            'employee_id': emp.id, 'name': emp.name, 'department': emp.department or '-',
            'work_days': work_days, 'regular_hours': fmt(reg_sec), 'overtime_hours': fmt(ot_sec),
            'total_hours': fmt(total_sec), 'break_minutes': brk_min,
            'total_seconds': total_sec, 'regular_seconds': reg_sec, 'overtime_seconds': ot_sec
        })

    data.sort(key=lambda x: x['total_seconds'], reverse=True)
    return jsonify({'success': True, 'data': data, 'year': year, 'month': month})


@timesheet_advanced_bp.route('/reports/daily-detail', methods=['GET'])
def report_daily_detail():
    """Daily detail report for a specific date"""
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not current_user or not current_user.is_admin:
        return jsonify({"error": "Unauthorized"}), 403

    target_date = request.args.get('date', date.today().isoformat())
    target = date.fromisoformat(target_date)

    employees = Employee.query.filter_by(is_admin=False).all()
    data = []
    for emp in employees:
        sessions = TimesheetSession.query.filter(
            TimesheetSession.employee_id == emp.id,
            TimesheetSession.date == target,
            TimesheetSession.status.in_(['completed', 'running'])
        ).all()
        total_sec = sum(s.elapsed_seconds or 0 for s in sessions)
        running = any(s.status == 'running' for s in sessions)
        first_in = min((s.start_time for s in sessions), default=None)
        last_out = max((s.end_time for s in sessions if s.end_time), default=None)

        def fmt(s):
            return f"{s//3600:02d}:{(s%3600)//60:02d}"

        data.append({
            'employee_id': emp.id, 'name': emp.name, 'department': emp.department or '-',
            'check_in': first_in.strftime('%H:%M') if first_in else '-',
            'check_out': last_out.strftime('%H:%M') if last_out else ('-' if not running else 'Active'),
            'total_hours': fmt(total_sec), 'total_seconds': total_sec,
            'sessions_count': len(sessions), 'is_active': running
        })

    return jsonify({'success': True, 'data': data, 'date': target_date})


@timesheet_advanced_bp.route('/reports/overtime-summary', methods=['GET'])
def report_overtime_summary():
    """Overtime summary report"""
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not current_user or not current_user.is_admin:
        return jsonify({"error": "Unauthorized"}), 403

    from models.employee import OvertimeRequest
    import calendar
    year = request.args.get('year', date.today().year, type=int)
    month = request.args.get('month', date.today().month, type=int)
    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])

    employees = Employee.query.filter_by(is_admin=False).all()
    data = []
    for emp in employees:
        ot_sessions = TimesheetSession.query.filter(
            TimesheetSession.employee_id == emp.id,
            TimesheetSession.date >= first_day,
            TimesheetSession.date <= last_day,
            TimesheetSession.hour_type == 'OVERTIME',
            TimesheetSession.status == 'completed'
        ).all()
        ot_sec = sum(s.elapsed_seconds or 0 for s in ot_sessions)
        approved_sec = sum(s.elapsed_seconds or 0 for s in ot_sessions if s.overtime_approval_status == 'approved')
        pending_sec = sum(s.elapsed_seconds or 0 for s in ot_sessions if s.overtime_approval_status == 'pending')
        rejected_sec = sum(s.elapsed_seconds or 0 for s in ot_sessions if s.overtime_approval_status == 'rejected')

        ot_requests = OvertimeRequest.query.filter(
            OvertimeRequest.employee_id == emp.id,
            OvertimeRequest.request_date >= first_day,
            OvertimeRequest.request_date <= last_day
        ).all()

        def fmt(s):
            return f"{s//3600:02d}:{(s%3600)//60:02d}"

        if ot_sec > 0 or ot_requests:
            data.append({
                'employee_id': emp.id, 'name': emp.name, 'department': emp.department or '-',
                'total_ot_hours': fmt(ot_sec), 'approved_hours': fmt(approved_sec),
                'pending_hours': fmt(pending_sec), 'rejected_hours': fmt(rejected_sec),
                'ot_days': len(set(s.date for s in ot_sessions)),
                'requests_count': len(ot_requests),
                'total_ot_seconds': ot_sec
            })

    data.sort(key=lambda x: x['total_ot_seconds'], reverse=True)
    return jsonify({'success': True, 'data': data, 'year': year, 'month': month})


@timesheet_advanced_bp.route('/reports/leave-summary', methods=['GET'])
def report_leave_summary():
    """Leave summary report"""
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not current_user or not current_user.is_admin:
        return jsonify({"error": "Unauthorized"}), 403

    from models.employee import LeaveRequest
    import calendar
    year = request.args.get('year', date.today().year, type=int)

    employees = Employee.query.filter_by(is_admin=False).all()
    data = []
    for emp in employees:
        leaves = LeaveRequest.query.filter(
            LeaveRequest.employee_id == emp.id,
            db.extract('year', LeaveRequest.start_date) == year
        ).all()

        annual_used = sum(l.duration_days for l in leaves if l.leave_category == 'annual' and l.status in ('approved', 'pending'))
        sick_used = sum(l.duration_days for l in leaves if l.leave_category == 'sick' and l.status in ('approved', 'pending'))
        casual_used = sum(l.duration_days for l in leaves if l.leave_category == 'casual' and l.status in ('approved', 'pending'))

        data.append({
            'employee_id': emp.id, 'name': emp.name, 'department': emp.department or '-',
            'annual_balance': emp.annual_leave_balance or 30,
            'annual_used': annual_used, 'annual_remaining': (emp.annual_leave_balance or 30) - annual_used,
            'sick_balance': emp.sick_leave_balance or 15,
            'sick_used': sick_used, 'sick_remaining': (emp.sick_leave_balance or 15) - sick_used,
            'casual_balance': emp.casual_leave_balance or 7,
            'casual_used': casual_used, 'casual_remaining': (emp.casual_leave_balance or 7) - casual_used,
            'total_leaves': len(leaves),
            'pending_count': len([l for l in leaves if l.status == 'pending'])
        })

    return jsonify({'success': True, 'data': data, 'year': year})


@timesheet_advanced_bp.route('/reports/project-hours', methods=['GET'])
def report_project_hours():
    """Project hours breakdown report"""
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not current_user or not current_user.is_admin:
        return jsonify({"error": "Unauthorized"}), 403

    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')

    query = TimesheetSession.query.filter(TimesheetSession.status == 'completed')
    if start_str:
        query = query.filter(TimesheetSession.date >= date.fromisoformat(start_str))
    if end_str:
        query = query.filter(TimesheetSession.date <= date.fromisoformat(end_str))

    sessions = query.all()
    projects = {}
    for s in sessions:
        pid = s.project_id
        if pid not in projects:
            proj = Project.query.get(pid) if pid else None
            projects[pid] = {
                'project_id': pid, 'project_number': proj.project_number if proj else 'N/A',
                'project_name': proj.project_name if proj else 'Internal',
                'total_seconds': 0, 'employees': set(), 'sessions_count': 0
            }
        projects[pid]['total_seconds'] += s.elapsed_seconds or 0
        projects[pid]['employees'].add(s.employee_id)
        projects[pid]['sessions_count'] += 1

    def fmt(s):
        return f"{s//3600:02d}:{(s%3600)//60:02d}"

    data = []
    for p in sorted(projects.values(), key=lambda x: x['total_seconds'], reverse=True):
        data.append({
            'project_id': p['project_id'], 'project_number': p['project_number'],
            'project_name': p['project_name'], 'total_hours': fmt(p['total_seconds']),
            'total_seconds': p['total_seconds'], 'employees_count': len(p['employees']),
            'sessions_count': p['sessions_count']
        })

    return jsonify({'success': True, 'data': data})


@timesheet_advanced_bp.route('/reports/employee-detail', methods=['GET'])
def report_employee_detail():
    """Detailed report for a specific employee"""
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not current_user or not current_user.is_admin:
        return jsonify({"error": "Unauthorized"}), 403

    emp_id = request.args.get('employee_id', type=int)
    if not emp_id:
        return jsonify({"error": "employee_id required"}), 400

    emp = Employee.query.get(emp_id)
    if not emp:
        return jsonify({"error": "Employee not found"}), 404

    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')

    query = TimesheetSession.query.filter(
        TimesheetSession.employee_id == emp_id,
        TimesheetSession.status == 'completed'
    )
    if start_str:
        query = query.filter(TimesheetSession.date >= date.fromisoformat(start_str))
    if end_str:
        query = query.filter(TimesheetSession.date <= date.fromisoformat(end_str))

    sessions = query.order_by(TimesheetSession.date.desc()).all()

    def fmt(s):
        return f"{s//3600:02d}:{(s%3600)//60:02d}"

    data = []
    for s in sessions:
        proj = Project.query.get(s.project_id) if s.project_id else None
        data.append({
            'date': s.date.strftime('%Y-%m-%d'), 'project_name': proj.project_name if proj else '-',
            'project_number': proj.project_number if proj else '-',
            'job_no': s.job_no or '-', 'task_name': s.task_name or '-',
            'hour_type': s.hour_type or '-', 'total_time': fmt(s.elapsed_seconds or 0),
            'total_seconds': s.elapsed_seconds or 0,
            'ot_status': s.overtime_approval_status or '-'
        })

    return jsonify({
        'success': True, 'employee': {'id': emp.id, 'name': emp.name, 'department': emp.department},
        'data': data
    })


@timesheet_advanced_bp.route('/reports/department-summary', methods=['GET'])
def report_department_summary():
    """Department-level summary report"""
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not current_user or not current_user.is_admin:
        return jsonify({"error": "Unauthorized"}), 403

    import calendar
    year = request.args.get('year', date.today().year, type=int)
    month = request.args.get('month', date.today().month, type=int)
    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])

    employees = Employee.query.filter_by(is_admin=False).all()
    depts = {}
    for emp in employees:
        dept = emp.department or 'Unassigned'
        if dept not in depts:
            depts[dept] = {'department': dept, 'employees': 0, 'total_seconds': 0, 'ot_seconds': 0, 'work_days': set()}
        depts[dept]['employees'] += 1

        sessions = TimesheetSession.query.filter(
            TimesheetSession.employee_id == emp.id,
            TimesheetSession.date >= first_day,
            TimesheetSession.date <= last_day,
            TimesheetSession.status == 'completed'
        ).all()

        for s in sessions:
            depts[dept]['total_seconds'] += s.elapsed_seconds or 0
            if s.hour_type == 'OVERTIME':
                depts[dept]['ot_seconds'] += s.elapsed_seconds or 0
            depts[dept]['work_days'].add((emp.id, s.date))

    def fmt(s):
        return f"{s//3600:02d}:{(s%3600)//60:02d}"

    data = []
    for d in sorted(depts.values(), key=lambda x: x['total_seconds'], reverse=True):
        data.append({
            'department': d['department'], 'employees': d['employees'],
            'total_hours': fmt(d['total_seconds']), 'overtime_hours': fmt(d['ot_seconds']),
            'total_seconds': d['total_seconds'], 'avg_hours_per_employee': fmt(d['total_seconds'] // max(d['employees'], 1)),
            'total_work_days': len(d['work_days'])
        })

    return jsonify({'success': True, 'data': data, 'year': year, 'month': month})


@timesheet_advanced_bp.route('/reports/attendance-rate', methods=['GET'])
def report_attendance_rate():
    """Attendance rate report"""
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not current_user or not current_user.is_admin:
        return jsonify({"error": "Unauthorized"}), 403

    from models.employee import LeaveRequest
    import calendar
    year = request.args.get('year', date.today().year, type=int)
    month = request.args.get('month', date.today().month, type=int)
    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])

    # Count working days (exclude Fri/Sat)
    from datetime import timedelta
    working_days = 0
    d = first_day
    while d <= min(last_day, date.today()):
        if d.weekday() not in (4, 5):
            working_days += 1
        d += timedelta(days=1)

    employees = Employee.query.filter_by(is_admin=False).all()
    data = []
    for emp in employees:
        present_days = len(set(
            s.date for s in TimesheetSession.query.filter(
                TimesheetSession.employee_id == emp.id,
                TimesheetSession.date >= first_day,
                TimesheetSession.date <= last_day,
                TimesheetSession.status == 'completed'
            ).all()
        ))
        leave_days = sum(
            l.duration_days for l in LeaveRequest.query.filter(
                LeaveRequest.employee_id == emp.id,
                LeaveRequest.start_date >= first_day,
                LeaveRequest.end_date <= last_day,
                LeaveRequest.status == 'approved'
            ).all()
        )
        absent_days = max(0, working_days - present_days - leave_days)
        rate = round((present_days / max(working_days, 1)) * 100, 1)

        data.append({
            'employee_id': emp.id, 'name': emp.name, 'department': emp.department or '-',
            'working_days': working_days, 'present_days': present_days,
            'leave_days': leave_days, 'absent_days': absent_days,
            'attendance_rate': rate
        })

    data.sort(key=lambda x: x['attendance_rate'], reverse=True)
    return jsonify({'success': True, 'data': data, 'year': year, 'month': month, 'working_days': working_days})


@timesheet_advanced_bp.route('/reports/break-analysis', methods=['GET'])
def report_break_analysis():
    """Break analysis report"""
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not current_user or not current_user.is_admin:
        return jsonify({"error": "Unauthorized"}), 403

    import calendar
    year = request.args.get('year', date.today().year, type=int)
    month = request.args.get('month', date.today().month, type=int)
    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])

    start_dt = datetime(year, month, 1)
    end_dt = datetime(year, month, last_day.day, 23, 59, 59)

    employees = Employee.query.filter_by(is_admin=False).all()
    data = []
    for emp in employees:
        sess_ids = [s.id for s in TimesheetSession.query.filter(
            TimesheetSession.employee_id == emp.id,
            TimesheetSession.date >= first_day,
            TimesheetSession.date <= last_day
        ).all()]

        breaks = []
        if sess_ids:
            breaks = TimesheetBreak.query.filter(
                TimesheetBreak.session_id.in_(sess_ids),
                TimesheetBreak.end_time != None
            ).all()

        # Also check by employee_id
        emp_breaks = TimesheetBreak.query.filter(
            TimesheetBreak.employee_id == emp.id,
            TimesheetBreak.start_time >= start_dt,
            TimesheetBreak.start_time <= end_dt,
            TimesheetBreak.end_time != None
        ).all()

        all_breaks = {b.id: b for b in breaks + emp_breaks}
        total_min = sum(b.duration_minutes or 0 for b in all_breaks.values())
        count = len(all_breaks)
        avg_min = round(total_min / max(count, 1), 1)

        if count > 0:
            data.append({
                'employee_id': emp.id, 'name': emp.name, 'department': emp.department or '-',
                'break_count': count, 'total_minutes': total_min,
                'avg_minutes': avg_min, 'total_hours': f"{total_min//60:02d}:{total_min%60:02d}"
            })

    data.sort(key=lambda x: x['total_minutes'], reverse=True)
    return jsonify({'success': True, 'data': data, 'year': year, 'month': month})


@timesheet_advanced_bp.route('/reports/export/excel', methods=['GET'])
def export_report_excel():
    """Generic report export to Excel"""
    import io
    try:
        import openpyxl
    except ImportError:
        return jsonify({"error": "openpyxl not installed"}), 500

    from flask import send_file

    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401

    report_type = request.args.get('type', 'monthly-summary')

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = report_type.replace('-', ' ').title()

    # Get data from the corresponding report endpoint
    # For simplicity, we'll handle the most common case
    if report_type == 'monthly-summary':
        ws.append(['Name', 'Department', 'Work Days', 'Regular Hours', 'OT Hours', 'Total Hours', 'Break Min'])
        import calendar
        year = request.args.get('year', date.today().year, type=int)
        month = request.args.get('month', date.today().month, type=int)
        first_day = date(year, month, 1)
        last_day = date(year, month, calendar.monthrange(year, month)[1])

        for emp in Employee.query.filter_by(is_admin=False).all():
            sessions = TimesheetSession.query.filter(
                TimesheetSession.employee_id == emp.id,
                TimesheetSession.date >= first_day, TimesheetSession.date <= last_day,
                TimesheetSession.status == 'completed'
            ).all()
            total = sum(s.elapsed_seconds or 0 for s in sessions)
            ot = sum(s.elapsed_seconds or 0 for s in sessions if s.hour_type == 'OVERTIME')
            reg = total - ot
            days = len(set(s.date for s in sessions))
            def fmt(s): return f"{s//3600:02d}:{(s%3600)//60:02d}"
            ws.append([emp.name, emp.department or '-', days, fmt(reg), fmt(ot), fmt(total), 0])

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, download_name=f'{report_type}_{date.today()}.xlsx', as_attachment=True,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
