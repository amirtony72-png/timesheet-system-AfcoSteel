import pandas as pd
from datetime import datetime
from flask import Blueprint, request, jsonify, session
from models.database import db
from models.employee import Employee, Holiday, DeductionRule, LeaveType, AttendanceRecord
from models.timesheet_session import TimesheetSession, TimesheetBreak, Project, ProjectJob
from datetime import datetime, date
from models.employee import LeaveRequest
from models.employee import Employee, Holiday, DeductionRule, LeaveType, LeaveRequest
from werkzeug.security import generate_password_hash, check_password_hash


admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')

@admin_bp.route('/change-password', methods=['POST'])
def change_password():

    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user = Employee.query.filter_by(user_id=session['user_id']).first()

    data = request.get_json()
    old_password = data.get('old_password')
    new_password = data.get('new_password')

    if not check_password_hash(user.password, old_password):
        return jsonify({"error": "Old password incorrect"}), 400

    user.password = generate_password_hash(new_password)

    db.session.commit()

    return jsonify({"message": "Password updated successfully ✅"})

@admin_bp.route('/upload-leaves', methods=['POST'])
def upload_leaves():

    # ✅ 🔐 الحماية (حطهم هنا)
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    current_user = Employee.query.filter_by(user_id=session['user_id']).first()

    if not current_user or not (current_user.is_admin or current_user.role.lower() == 'hr'):
        return jsonify({"error": "Unauthorized"}), 403



    if 'file' not in request.files:
        return jsonify({"error": "No file"}), 400

    file = request.files['file']
    df = pd.read_excel(file)

    leaves = []

    for _, row in df.iterrows():

        user_id = str(row['ID']).strip()
        emp = Employee.query.filter_by(user_id=user_id).first()

        if not emp:
            continue

        vtype = str(row['VacationType']).strip()

        if vtype == 'Regular':
            category = 'annual'
            leave_type_id = 1
        elif vtype == 'Casual':
            category = 'casual'
            leave_type_id = 2
        elif vtype == 'Sick':
            category = 'sick'
            leave_type_id = 3
        elif 'Marriage' in vtype:
            category = 'marriage'
            leave_type_id = 4
        else:
            continue

        leave = {
            "employee_id": emp.id,
            "leave_type_id": leave_type_id,
            "leave_category": category,
            "start_date": pd.to_datetime(row['StartDate']).date(),
            "end_date": pd.to_datetime(row['End Date']).date(),
            "duration_days": float(row['Duration']),
            "reason": "Imported Excel",
            "is_half_day": (float(row['Duration']) == 0.5),
            "status": "approved",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }

        leaves.append(leave)

    # ✅ insert مرة واحدة
    db.session.execute(
        LeaveRequest.__table__.insert(),
        leaves
    )

    db.session.commit()

    return jsonify({
        "success": True,
        "message": f"{len(leaves)} leaves inserted ✅"
    })


@admin_bp.route('/holidays', methods=['GET'])
def get_holidays():
    """عرض جميع الإجازات الرسمية"""
    holidays = Holiday.query.filter_by(is_active=True).order_by(Holiday.date).all()
    holidays_data = []
    
    for holiday in holidays:
        holidays_data.append({
            'id': holiday.id,
            'date': holiday.date.strftime('%Y-%m-%d'),
            'name': holiday.name,
            'is_active': holiday.is_active
        })
    
    return jsonify({'holidays': holidays_data})

@admin_bp.route('/holidays', methods=['POST'])
def add_holiday():
    """إضافة إجازة رسمية جديدة"""
    data = request.get_json()
    
    if not data or 'date' not in data or 'name' not in data:
        return jsonify({'error': 'البيانات المطلوبة مفقودة'}), 400
    
    try:
        holiday_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'تنسيق التاريخ غير صحيح'}), 400
    
    # التحقق من عدم وجود إجازة في نفس التاريخ
    existing_holiday = Holiday.query.filter_by(date=holiday_date).first()
    if existing_holiday:
        return jsonify({'error': 'يوجد إجازة رسمية في هذا التاريخ بالفعل'}), 400
    
    # إضافة الإجازة الجديدة
    new_holiday = Holiday(
        date=holiday_date,
        name=data['name'],
        is_active=True
    )
    
    db.session.add(new_holiday)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'تم إضافة الإجازة الرسمية بنجاح'})

@admin_bp.route('/holidays/<int:holiday_id>', methods=['PUT'])
def update_holiday(holiday_id):
    """تحديث إجازة رسمية"""
    data = request.get_json()
    
    holiday = Holiday.query.get_or_404(holiday_id)
    
    if 'date' in data:
        try:
            holiday.date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'تنسيق التاريخ غير صحيح'}), 400
    
    if 'name' in data:
        holiday.name = data['name']
    
    if 'is_active' in data:
        holiday.is_active = data['is_active']
    
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'تم تحديث الإجازة الرسمية بنجاح'})

@admin_bp.route('/holidays/<int:holiday_id>', methods=['DELETE'])
def delete_holiday(holiday_id):
    """حذف إجازة رسمية"""
    holiday = Holiday.query.get_or_404(holiday_id)
    
    # حذف ناعم - تعطيل الإجازة بدلاً من حذفها
    holiday.is_active = False
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'تم حذف الإجازة الرسمية بنجاح'})

@admin_bp.route('/deduction-rules', methods=['GET'])
def get_deduction_rules():
    """عرض جميع قواعد الخصومات"""
    rules = DeductionRule.query.all()
    rules_data = []
    
    for rule in rules:
        rules_data.append({
            'id': rule.id,
            'category': rule.category,
            'violation_1st': rule.violation_1st,
            'violation_2nd': rule.violation_2nd,
            'violation_3rd': rule.violation_3rd,
            'violation_4th': rule.violation_4th
        })
    
    return jsonify({'rules': rules_data})

@admin_bp.route('/deduction-rules/<int:rule_id>', methods=['PUT'])
def update_deduction_rule(rule_id):
    """تحديث قاعدة خصم"""
    data = request.get_json()
    
    rule = DeductionRule.query.get_or_404(rule_id)
    
    if 'violation_1st' in data:
        rule.violation_1st = float(data['violation_1st'])
    if 'violation_2nd' in data:
        rule.violation_2nd = float(data['violation_2nd'])
    if 'violation_3rd' in data:
        rule.violation_3rd = float(data['violation_3rd'])
    if 'violation_4th' in data:
        rule.violation_4th = float(data['violation_4th'])
    
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'تم تحديث قاعدة الخصم بنجاح'})

@admin_bp.route('/work-settings', methods=['GET'])
def get_work_settings():
    """عرض إعدادات العمل"""
    # إعدادات افتراضية - يمكن تخزينها في قاعدة البيانات لاحقاً
    settings = {
        'work_start_time': '08:30',
        'work_end_time': '17:30',
        'work_hours_per_day': 9,
        'weekend_days': ['friday', 'saturday'],
        'late_allowance_minutes': 120,  # 2 ساعة شهرياً
        'early_leave_allowance_minutes': 120,  # 2 ساعة شهرياً
        'early_arrival_start': '08:00',
        'early_arrival_end': '08:30'
    }
    
    return jsonify({'settings': settings})

@admin_bp.route('/work-settings', methods=['PUT'])
def update_work_settings():
    """تحديث إعدادات العمل"""
    data = request.get_json()
    
    # هنا يمكن حفظ الإعدادات في قاعدة البيانات
    # حالياً سنعيد رسالة نجاح فقط
    
    return jsonify({'success': True, 'message': 'تم تحديث إعدادات العمل بنجاح'})

@admin_bp.route('/employees', methods=['GET'])
def get_employees():
    """عرض جميع الموظفين"""
    employees = Employee.query.all()
    employees_data = []
    
    for employee in employees:
        employees_data.append({
            'id': employee.id,
            'user_id': employee.user_id,
            'name': employee.name,
            'email': employee.email,
            'role': employee.role,
            'department': employee.department,
            'position': employee.position if employee.position else None,
            'is_admin': employee.is_admin,
            'manager_id': employee.manager_id,
            'manager_name': employee.manager.name if employee.manager else None,
            'created_at': employee.created_at.strftime('%Y-%m-%d') if employee.created_at else None
        })
    
    return jsonify({'success': True, 'employees': employees_data})

@admin_bp.route('/employees', methods=['POST'])
def create_employee():
    """إضافة موظف جديد"""
    data = request.get_json()
    
    if not data or 'user_id' not in data or 'name' not in data:
        return jsonify({'error': 'البيانات المطلوبة مفقودة'}), 400
    
    # التحقق من عدم تكرار معرف المستخدم
    existing_employee = Employee.query.filter_by(user_id=data['user_id']).first()
    if existing_employee:
        return jsonify({'error': 'معرف المستخدم موجود بالفعل'}), 400
    
    new_employee = Employee(
        user_id=data['user_id'],
        name=data['name'],
        role=data.get('role', 'موظف'),
        department=data.get('department'),
        position=data.get('position'),
        password=data.get('password', '123456'),
        is_admin=bool(data.get('is_admin', False)),
        manager_id=data.get('manager_id')
    )
    
    try:
        db.session.add(new_employee)
        db.session.commit()
        return jsonify({'success': True, 'message': 'تم إضافة الموظف بنجاح'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'خطأ في إضافة الموظف: {str(e)}'}), 500

@admin_bp.route('/employees/<int:employee_id>', methods=['PUT'])
def update_employee(employee_id):
    """تحديث بيانات موظف"""
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'البيانات مطلوبة'}), 400
    
    employee = Employee.query.get_or_404(employee_id)
    
    if 'name' in data and data['name'].strip():
        employee.name = data['name'].strip()
    
    if 'role' in data:
        employee.role = data['role']
    
    if 'department' in data:
        employee.department = data['department']
    
    if 'position' in data:
        employee.position = data['position']
    
    if 'manager_id' in data:
        if data['manager_id']:
            if int(data['manager_id']) == employee_id:
                return jsonify({'error': 'لا يمكن للموظف أن يكون مديراً لنفسه'}), 400
            employee.manager_id = data['manager_id']
        else:
            employee.manager_id = None
    
    if 'is_admin' in data:
        employee.is_admin = bool(data['is_admin'])
    
    if 'password' in data and data['password'].strip():
        employee.password = data['password'].strip()
    
    try:
        db.session.commit()
        return jsonify({'success': True, 'message': 'تم تحديث بيانات الموظف بنجاح'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'خطأ في تحديث البيانات: {str(e)}'}), 500

@admin_bp.route('/employees/<int:employee_id>', methods=['DELETE'])
def delete_employee(employee_id):
    """حذف موظف"""
    try:
        employee = Employee.query.get_or_404(employee_id)
        
        # حذف السجلات المرتبطة (تبسيطاً سنقوم بحذف الموظف فقط إذا كانت قاعدة البيانات تدعم حذف الشلال)
        # أو يمكن تنفيذ الحذف اليدوي للسجلات المرتبطة هنا
        
        db.session.delete(employee)
        db.session.commit()
        return jsonify({'success': True, 'message': 'تم حذف الموظف بنجاح'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@admin_bp.route('/statistics', methods=['GET'])
def get_statistics():
    """عرض إحصائيات عامة"""
    total_employees = Employee.query.count()
    # يمكن إضافة المزيد من الإحصائيات هنا
    return jsonify({
        'total_employees': total_employees,
        'present_today': 0,
        'absent_today': 0,
        'late_today': 0
    })

@admin_bp.route('/fingerprint', methods=['POST'])
def record_fingerprint():
    """تسجيل بصمة"""
    data = request.get_json()
    if not data or 'user_id' not in data:
        return jsonify({'error': 'معرف المستخدم مطلوب'}), 400
    
    employee = Employee.query.filter_by(user_id=data['user_id']).first()
    if not employee:
        return jsonify({'error': 'الموظف غير موجود'}), 404
    
    # منطق تسجيل الحضور والانصراف
    return jsonify({'success': True, 'message': 'تم تسجيل البصمة بنجاح'})

# Old attendance-log endpoint removed - replaced by comprehensive version below

@admin_bp.route("/employees-list", methods=["GET"])
def get_employees_list():
    """عرض قائمة الموظفين للبصمة اليدوية"""
    employees = Employee.query.order_by(Employee.name).all()
    employees_data = []
    for employee in employees:
        employees_data.append({
            'user_id': employee.user_id,
            'name': employee.name,
            'role': employee.role
        })
    return jsonify({'success': True, 'employees': employees_data})

@admin_bp.route('/projects', methods=['GET'])
def get_projects():
    """عرض جميع المشاريع"""
    projects = Project.query.all()
    projects_data = []
    for project in projects:
        projects_data.append({
            'id': project.id,
            'project_number': project.project_number,
            'project_name': project.project_name
        })
    return jsonify({'projects': projects_data})

@admin_bp.route('/projects', methods=['POST'])
def create_project():
    """إضافة مشروع جديد"""
    data = request.get_json()
    if not data or 'project_number' not in data or 'project_name' not in data:
        return jsonify({'error': 'البيانات المطلوبة مفقودة'}), 400
    
    existing_project = Project.query.filter_by(project_number=data['project_number']).first()
    if existing_project:
        return jsonify({'error': 'رقم المشروع موجود بالفعل'}), 400

    new_project = Project(
        project_number=data['project_number'],
        project_name=data['project_name']
    )
    db.session.add(new_project)
    db.session.commit()
    return jsonify({'success': True, 'message': 'تم إضافة المشروع بنجاح'}) 

@admin_bp.route('/projects/<int:project_id>', methods=['PUT'])
def update_project(project_id):
    """تحديث بيانات مشروع"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'البيانات مطلوبة'}), 400
    
    project = Project.query.get_or_404(project_id)
    if 'project_number' in data:
        project.project_number = data['project_number']
    if 'project_name' in data:
        project.project_name = data['project_name']
    
    db.session.commit()
    return jsonify({'success': True, 'message': 'تم تحديث المشروع بنجاح'})

@admin_bp.route('/projects/<int:project_id>', methods=['DELETE'])
def delete_project(project_id):
    """حذف مشروع"""
    project = Project.query.get_or_404(project_id)
    db.session.delete(project)
    db.session.commit()
    return jsonify({'success': True, 'message': 'تم حذف المشروع بنجاح'})

@admin_bp.route('/projects/<int:project_id>/jobs', methods=['GET'])
def get_project_jobs(project_id):
    """عرض جميع Job Numbers لمشروع معين"""
    project = Project.query.get_or_404(project_id)
    jobs = ProjectJob.query.filter_by(project_id=project_id, is_active=True).all()
    jobs_data = []
    for job in jobs:
        jobs_data.append({
            'id': job.id,
            'job_number': job.job_number,
            'description': job.description
        })
    return jsonify({'jobs': jobs_data})

@admin_bp.route('/projects/<int:project_id>/jobs', methods=['POST'])
def create_project_job(project_id):
    """إضافة Job Number جديد لمشروع"""
    project = Project.query.get_or_404(project_id)
    data = request.get_json()
    
    if not data or 'job_number' not in data:
        return jsonify({'error': 'رقم الوظيفة (Job Number) مطلوب'}), 400
    
    existing_job = ProjectJob.query.filter_by(project_id=project_id, job_number=data['job_number']).first()
    if existing_job:
        return jsonify({'error': 'رقم الوظيفة هذا موجود بالفعل لهذا المشروع'}), 400
        
    new_job = ProjectJob(
        project_id=project_id,
        job_number=data['job_number'],
        description=data.get('description', '')
    )
    
    db.session.add(new_job)
    db.session.commit()
    return jsonify({'success': True, 'message': 'تم إضافة رقم الوظيفة بنجاح'})

@admin_bp.route('/jobs/<int:job_id>', methods=['PUT'])
def update_project_job(job_id):
    """تحديث بيانات Job Number"""
    job = ProjectJob.query.get_or_404(job_id)
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'البيانات مطلوبة'}), 400
        
    if 'job_number' in data:
        # التحقق من عدم التكرار في نفس المشروع
        existing = ProjectJob.query.filter(
            ProjectJob.project_id == job.project_id, 
            ProjectJob.job_number == data['job_number'],
            ProjectJob.id != job_id
        ).first()
        
        if existing:
            return jsonify({'error': 'رقم الوظيفة هذا موجود بالفعل لهذا المشروع'}), 400
            
        job.job_number = data['job_number']
        
    if 'description' in data:
        job.description = data['description']
        
    if 'is_active' in data:
        job.is_active = data['is_active']
        
    db.session.commit()
    return jsonify({'success': True, 'message': 'تم تحديث رقم الوظيفة بنجاح'})

@admin_bp.route('/jobs/<int:job_id>', methods=['DELETE'])
def delete_project_job(job_id):
    """حذف Job Number"""
    job = ProjectJob.query.get_or_404(job_id)
    db.session.delete(job)
    db.session.commit()
    return jsonify({'success': True, 'message': 'تم حذف رقم الوظيفة بنجاح'})


# ─────────────────────────────────────────────────────────────────────────────
# API: لوحة الإحصائيات للمدير
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route('/dashboard/stats', methods=['GET'])
def get_dashboard_stats():
    """
    إحصائيات شاملة للمدير:
    - إجمالي ساعات العمل لكل موظف في الشهر الحالي
    - إجمالي ساعات الـ Overtime لكل موظف
    - قائمة الموظفين الذين تجاوزوا 50 ساعة Overtime في الشهر
    """
    from models.timesheet_session import TimesheetSession
    from sqlalchemy import func
    import calendar

    # التحقق من صلاحيات المدير
    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401
    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not current_user or not (current_user.is_admin or current_user.role.lower() == 'hr'):
        return jsonify({"error": "Unauthorized"}), 403

    # تحديد نطاق الشهر المطلوب (افتراضي: الشهر الحالي)
    year = request.args.get('year', date.today().year, type=int)
    month = request.args.get('month', date.today().month, type=int)
    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])

    employees = Employee.query.filter_by(is_admin=False).all()
    stats = []
    overtime_alerts = []  # الموظفون الذين تجاوزوا 50 ساعة Overtime

    OVERTIME_ALERT_LIMIT = 50 * 3600  # 50 ساعة بالثواني

    for emp in employees:
        # جلسات العمل العادي
        regular_sessions = TimesheetSession.query.filter(
            TimesheetSession.employee_id == emp.id,
            TimesheetSession.date >= first_day,
            TimesheetSession.date <= last_day,
            TimesheetSession.hour_type != 'OVERTIME',
            TimesheetSession.status == 'completed'
        ).all()

        # جلسات الـ Overtime
        overtime_sessions = TimesheetSession.query.filter(
            TimesheetSession.employee_id == emp.id,
            TimesheetSession.date >= first_day,
            TimesheetSession.date <= last_day,
            TimesheetSession.hour_type == 'OVERTIME',
            TimesheetSession.status == 'completed'
        ).all()

        regular_seconds = sum(s.elapsed_seconds for s in regular_sessions)
        overtime_seconds = sum(s.elapsed_seconds for s in overtime_sessions)

        # تحويل الثواني إلى ساعات ودقائق
        def fmt(secs):
            h = secs // 3600
            m = (secs % 3600) // 60
            return f"{h:02d}:{m:02d}"

        emp_stat = {
            "id": emp.id,
            "name": emp.name,
            "department": emp.department or "-",
            "position": emp.position or "-",
            "regular_hours": fmt(regular_seconds),
            "regular_seconds": regular_seconds,
            "overtime_hours": fmt(overtime_seconds),
            "overtime_seconds": overtime_seconds,
            "total_hours": fmt(regular_seconds + overtime_seconds),
            "total_seconds": regular_seconds + overtime_seconds,
            "overtime_alert": overtime_seconds >= OVERTIME_ALERT_LIMIT
        }
        stats.append(emp_stat)

        # إضافة للقائمة التنبيهية إذا تجاوز 50 ساعة
        if overtime_seconds >= OVERTIME_ALERT_LIMIT:
            overtime_alerts.append({
                "name": emp.name,
                "department": emp.department or "-",
                "overtime_hours": fmt(overtime_seconds),
                "overtime_seconds": overtime_seconds
            })

    # ترتيب حسب إجمالي الساعات تنازلياً
    stats.sort(key=lambda x: x['total_seconds'], reverse=True)
    overtime_alerts.sort(key=lambda x: x['overtime_seconds'], reverse=True)

    return jsonify({
        "success": True,
        "year": year,
        "month": month,
        "stats": stats,
        "overtime_alerts": overtime_alerts,
        "overtime_alert_limit_hours": 50
    })


@admin_bp.route('/dashboard/daily', methods=['GET'])
def get_daily_stats():
    """
    إحصائيات يومية لموظف معين أو جميع الموظفين لأسبوع محدد.
    يُستخدم لرسم الرسم البياني الأسبوعي.
    """
    from models.timesheet_session import TimesheetSession
    from datetime import timedelta

    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401
    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not current_user or not (current_user.is_admin or current_user.role.lower() == 'hr'):
        return jsonify({"error": "Unauthorized"}), 403

    # نطاق التاريخ (افتراضي: آخر 7 أيام)
    end_date = date.today()
    start_date = end_date - timedelta(days=6)

    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')
    if start_str:
        start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
    if end_str:
        end_date = datetime.strptime(end_str, '%Y-%m-%d').date()

    employee_id = request.args.get('employee_id', type=int)

    # بناء قائمة الأيام
    days = []
    current = start_date
    while current <= end_date:
        days.append(current)
        current += timedelta(days=1)

    result = []
    for d in days:
        query = TimesheetSession.query.filter(
            TimesheetSession.date == d,
            TimesheetSession.status == 'completed'
        )
        if employee_id:
            query = query.filter(TimesheetSession.employee_id == employee_id)

        sessions = query.all()
        regular = sum(s.elapsed_seconds for s in sessions if s.hour_type != 'OVERTIME')
        overtime = sum(s.elapsed_seconds for s in sessions if s.hour_type == 'OVERTIME')

        result.append({
            "date": d.strftime('%Y-%m-%d'),
            "day_name": ['الاثنين','الثلاثاء','الأربعاء','الخميس','الجمعة','السبت','الأحد'][d.weekday()],
            "regular_hours": round(regular / 3600, 2),
            "overtime_hours": round(overtime / 3600, 2)
        })

    return jsonify({"success": True, "daily": result})


# ─────────────────────────────────────────────────────────────────────────────
# API: تعديل الجلسة بعد إغلاقها (للمدير فقط)
# ─────────────────────────────────────────────────────────────────────────────
@admin_bp.route('/sessions/<int:session_id>', methods=['GET'])
def get_session(session_id):

    from models.timesheet_session import TimesheetSession

    try:
        if 'user_id' not in session:
            return jsonify({"error": "غير مسجل دخول"}), 401

        current_user = Employee.query.filter_by(user_id=session['user_id']).first()
        if not current_user or not (
            current_user.is_admin or current_user.role.lower() in ['planning']):
            return jsonify({"error": "Unauthorized"}), 403

        s = TimesheetSession.query.get_or_404(session_id)

        return jsonify({
            "id": s.id,
            "task_name": s.task_name or "",
            "description": s.description or "",
            "project_id": s.project_id,
            "job_no": s.job_no or "",
            "hour_type": s.hour_type or "",
            "start_time": s.start_time.isoformat() if s.start_time else None,
            "end_time": s.end_time.isoformat() if s.end_time else None
        })

    except Exception as e:
        print("🔥 ERROR:", str(e))
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/sessions/<int:session_id>', methods=['PUT'])
def update_session(session_id):

    from models.timesheet_session import TimesheetSession  # ✅ أضف السطر ده

    try:
        if 'user_id' not in session:
            return jsonify({"error": "غير مسجل دخول"}), 401

        current_user = Employee.query.filter_by(user_id=session['user_id']).first()
        if not current_user or not (
            current_user.is_admin or current_user.role.lower() in ['planning']):
            return jsonify({"error": "Unauthorized"}), 403

        ts = TimesheetSession.query.get_or_404(session_id)
        data = request.get_json()

        print("UPDATE DATA:", data)  # ✅ debug

        if not data:
            return jsonify({"error": "البيانات مطلوبة"}), 400

        if 'hour_type' in data:
            ts.hour_type = data['hour_type']

        if 'project_id' in data:
            ts.project_id = data['project_id']

        if 'job_no' in data:
            ts.job_no = data['job_no']

        if 'task_name' in data:
            ts.task_name = data['task_name']

        if 'description' in data:
            ts.description = data['description']

        # تعديل الوقت
        if 'start_time' in data:
            ts.start_time = datetime.fromisoformat(data['start_time'])

        if 'end_time' in data and data['end_time']:
            ts.end_time = datetime.fromisoformat(data['end_time'])

        # حساب الوقت
        if ts.start_time and ts.end_time:
            ts.elapsed_seconds = int((ts.end_time - ts.start_time).total_seconds())

        db.session.commit()

        return jsonify({"success": True})

    except Exception as e:
        db.session.rollback()
        print("🔥 PUT ERROR:", str(e))
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/sessions/<int:session_id>', methods=['DELETE'])

def delete_session(session_id):

    from models.timesheet_session import TimesheetSession  # ✅ مهم

    try:
        if 'user_id' not in session:
            return jsonify({"error": "غير مسجل دخول"}), 401

        current_user = Employee.query.filter_by(user_id=session['user_id']).first()
        if not current_user or not (
            current_user.is_admin or current_user.role.lower() in ['planning']):
            return jsonify({"error": "Unauthorized"}), 403

        ts = TimesheetSession.query.get_or_404(session_id)

        db.session.delete(ts)
        db.session.commit()

        return jsonify({"success": True})

    except Exception as e:
        db.session.rollback()
        print("🔥 DELETE ERROR:", str(e))
        return jsonify({"error": str(e)}), 500

# ═══════════════════════════════════════════════════════════════════════════════
# نظام موافقة الـ Overtime
# ═══════════════════════════════════════════════════════════════════════════════

@admin_bp.route('/overtime/pending', methods=['GET'])
def get_pending_overtime():
    """
    جلب جميع جلسات الـ Overtime بانتظار الموافقة.
    للمدير فقط.
    """
    from models.timesheet_session import TimesheetSession, Project

    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401
    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not current_user or not (
        current_user.is_admin or current_user.role.lower() in ['planning']):
        return jsonify({"error": "Unauthorized"}), 403

    # جلب جلسات OVERTIME بانتظار الموافقة
    pending = TimesheetSession.query.filter_by(
        hour_type='OVERTIME',
        overtime_approval_status='pending'
    ).order_by(TimesheetSession.date.desc()).all()

    result = []
    for s in pending:
        emp = Employee.query.get(s.employee_id)
        proj = Project.query.get(s.project_id) if s.project_id else None
        # حساب الوقت
        h = s.elapsed_seconds // 3600
        m = (s.elapsed_seconds % 3600) // 60
        total_time = f"{h:02d}:{m:02d}"
        result.append({
            "id":           s.id,
            "employee_id":  emp.user_id if emp else '-',
            "employee_name": emp.name if emp else '-',
            "date":         str(s.date),
            "project_number": proj.project_number if proj else '-',
            "project_name": proj.project_name if proj else '-',
            "job_no":       s.job_no or '-',
            "task_name":    s.task_name or '-',
            "description":  s.description or '',
            "total_time":   total_time,
            "elapsed_seconds": s.elapsed_seconds,
            "status":       s.overtime_approval_status
        })

    return jsonify({"pending_overtime": result, "count": len(result)})


@admin_bp.route('/overtime/<int:session_id>/approve', methods=['POST'])
def approve_overtime(session_id):
    """
    موافقة المدير على جلسة Overtime.
    يُبقي hour_type = 'OVERTIME' ويُحدّث حالة الموافقة.
    يسمح بتغيير الحالة حتى لو كانت مرفوضة مسبقاً.
    """
    from models.timesheet_session import TimesheetSession
    from routes.user import log_audit

    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401
    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not current_user or not (
        current_user.is_admin or current_user.role.lower() in ['planning']):
        return jsonify({"error": "Unauthorized"}), 403

    ts = TimesheetSession.query.get_or_404(session_id)
    
    old_status = ts.overtime_approval_status
    ts.hour_type = 'OVERTIME'
    ts.overtime_approval_status = 'approved'
    ts.overtime_approved_by     = current_user.id
    ts.overtime_approved_at     = datetime.utcnow()
    ts.overtime_rejection_note  = None

    try:
        db.session.commit()
        log_audit('Approve OT', 'TimesheetSession', ts.id, f'OT Approved (Previous: {old_status}) for session {ts.id}')
        return jsonify({"success": True, "message": "تمت الموافقة على الـ Overtime"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@admin_bp.route('/overtime/<int:session_id>/reject', methods=['POST'])
def reject_overtime(session_id):
    """
    رفض المدير لجلسة Overtime.
    يُحوّل hour_type إلى 'WORK ORDER' ويُحدّث حالة الموافقة.
    يسمح بتغيير الحالة حتى لو كانت مقبولة مسبقاً.
    """
    from models.timesheet_session import TimesheetSession
    from routes.user import log_audit

    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401
    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not current_user or not (current_user.is_admin or current_user.role.lower() == 'hr'):
        return jsonify({"error": "Unauthorized"}), 403

    ts = TimesheetSession.query.get_or_404(session_id)
    
    data = request.get_json() or {}
    rejection_note = data.get('note', '')

    old_status = ts.overtime_approval_status
    # تحويل نوع الساعة إلى WORK ORDER عند الرفض
    ts.hour_type                = 'WORK ORDER'
    ts.overtime_approval_status = 'rejected'
    ts.overtime_approved_by     = current_user.id
    ts.overtime_approved_at     = datetime.utcnow()
    ts.overtime_rejection_note  = rejection_note

    try:
        db.session.commit()
        log_audit('Reject OT', 'TimesheetSession', ts.id, f'OT Rejected (Previous: {old_status}) for session {ts.id}. Note: {rejection_note}')
        return jsonify({"success": True, "message": "تم رفض الـ Overtime وتحويله إلى WORK ORDER"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# إحصائية المشاريع التفصيلية
# ═══════════════════════════════════════════════════════════════════════════════

@admin_bp.route('/stats/projects', methods=['GET'])
def get_project_stats():
    """
    إحصائية تفصيلية للمشاريع:
    - إجمالي ساعات العمل العادية والـ Overtime لكل مشروع
    - تفصيل لكل موظف داخل المشروع
    - فلترة حسب التاريخ (start_date, end_date)
    """
    from models.timesheet_session import TimesheetSession, Project
    from sqlalchemy import func

    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401
    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not current_user or not (
    current_user.is_admin or current_user.role.lower() in ['planning']):
        return jsonify({"error": "Unauthorized"}), 403

    # فلاتر التاريخ
    start_date_str = request.args.get('start_date')
    end_date_str   = request.args.get('end_date')

    query = TimesheetSession.query.filter(
        TimesheetSession.status == 'completed',
        TimesheetSession.project_id.isnot(None)
    )

    if start_date_str:
        try:
            from datetime import date
            sd = date.fromisoformat(start_date_str)
            query = query.filter(TimesheetSession.date >= sd)
        except ValueError:
            pass

    if end_date_str:
        try:
            from datetime import date
            ed = date.fromisoformat(end_date_str)
            query = query.filter(TimesheetSession.date <= ed)
        except ValueError:
            pass

    sessions = query.all()

    # تجميع البيانات حسب المشروع
    project_map = {}
    for s in sessions:
        pid = s.project_id
        if pid not in project_map:
            proj = Project.query.get(pid)
            project_map[pid] = {
                "project_id":     pid,
                "project_number": proj.project_number if proj else '-',
                "project_name":   proj.project_name   if proj else '-',
                "total_seconds":  0,
                "regular_seconds": 0,
                "overtime_seconds": 0,
                "employees": {}
            }

        secs = s.elapsed_seconds or 0
        project_map[pid]["total_seconds"] += secs

        if s.hour_type == 'OVERTIME':
            project_map[pid]["overtime_seconds"] += secs
        else:
            project_map[pid]["regular_seconds"] += secs

        # تفصيل الموظف داخل المشروع
        eid = s.employee_id
        if eid not in project_map[pid]["employees"]:
            emp = Employee.query.get(eid)
            project_map[pid]["employees"][eid] = {
                "employee_id":   emp.user_id if emp else '-',
                "employee_name": emp.name    if emp else '-',
                "regular_seconds":  0,
                "overtime_seconds": 0,
                "total_seconds":    0
            }

        emp_data = project_map[pid]["employees"][eid]
        emp_data["total_seconds"] += secs
        if s.hour_type == 'OVERTIME':
            emp_data["overtime_seconds"] += secs
        else:
            emp_data["regular_seconds"] += secs

    # تحويل الثواني إلى HH:MM وترتيب النتائج
    def secs_to_hhmm(secs):
        h = secs // 3600
        m = (secs % 3600) // 60
        return f"{h:02d}:{m:02d}"

    result = []
    for pid, data in sorted(project_map.items(), key=lambda x: x[1]["total_seconds"], reverse=True):
        employees_list = []
        for eid, edata in sorted(data["employees"].items(), key=lambda x: x[1]["total_seconds"], reverse=True):
            employees_list.append({
                "employee_id":    edata["employee_id"],
                "employee_name":  edata["employee_name"],
                "regular_hours":  secs_to_hhmm(edata["regular_seconds"]),
                "overtime_hours": secs_to_hhmm(edata["overtime_seconds"]),
                "total_hours":    secs_to_hhmm(edata["total_seconds"]),
                "regular_seconds":  edata["regular_seconds"],
                "overtime_seconds": edata["overtime_seconds"],
                "total_seconds":    edata["total_seconds"]
            })

        result.append({
            "project_id":      data["project_id"],
            "project_number":  data["project_number"],
            "project_name":    data["project_name"],
            "regular_hours":   secs_to_hhmm(data["regular_seconds"]),
            "overtime_hours":  secs_to_hhmm(data["overtime_seconds"]),
            "total_hours":     secs_to_hhmm(data["total_seconds"]),
            "regular_seconds":  data["regular_seconds"],
            "overtime_seconds": data["overtime_seconds"],
            "total_seconds":    data["total_seconds"],
            "employees":       employees_list
        })

    return jsonify({
        "projects": result,
        "filter": {
            "start_date": start_date_str or "all",
            "end_date":   end_date_str   or "all"
        }
    })



# ═══════════════════════════════════════════════════════════════════════════════
# NEW ENDPOINTS v74
# ═══════════════════════════════════════════════════════════════════════════════

@admin_bp.route('/attendance-log', methods=['GET'])
def get_comprehensive_attendance_log():
    """
    Comprehensive attendance log with:
    - Employee ID, Name, Date, Check In, Check Out
    - Total Time, Project Time, Break Time
    - Day Type (Present/Leave/Absent/No Fingerprint)
    - OT hours (after 9h), OT approval status
    """
    from models.timesheet_session import TimesheetSession, TimesheetBreak
    from models.employee import LeaveRequest, OvertimeRequest

    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not current_user or not (current_user.is_admin or current_user.role.lower() == 'hr'):
        return jsonify({"error": "Unauthorized"}), 403

    # Filters
    emp_id = request.args.get('employee_id', type=int)
    dept = request.args.get('department')
    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')

    # Default date range: last 30 days
    if not start_str:
        from datetime import timedelta
        start_date = date.today() - timedelta(days=30)
    else:
        start_date = date.fromisoformat(start_str)
    end_date = date.fromisoformat(end_str) if end_str else date.today()

    # Get employees
    emp_query = Employee.query.filter_by(is_admin=False)
    if emp_id:
        emp_query = emp_query.filter_by(id=emp_id)
    if dept:
        emp_query = emp_query.filter_by(department=dept)
    employees = emp_query.all()

    records = []
    from datetime import timedelta
    current_date = start_date
    while current_date <= end_date:
        for emp in employees:
            # Get sessions for this employee on this date
            day_sessions = TimesheetSession.query.filter(
                TimesheetSession.employee_id == emp.id,
                TimesheetSession.date == current_date,
                TimesheetSession.status == 'completed'
            ).all()

            # Get breaks for this date
            # Get breaks by employee_id OR by session_id
            day_break_ids = [s.id for s in TimesheetSession.query.filter(
                TimesheetSession.employee_id == emp.id,
                TimesheetSession.date == current_date
            ).all()]
            day_breaks = TimesheetBreak.query.filter(
                db.or_(
                    TimesheetBreak.session_id.in_(day_break_ids) if day_break_ids else db.false(),
                    db.and_(TimesheetBreak.employee_id == emp.id, db.func.date(TimesheetBreak.start_time) == current_date)
                )
            ).all()

            # Check if on leave
            leave = LeaveRequest.query.filter(
                LeaveRequest.employee_id == emp.id,
                LeaveRequest.start_date <= current_date,
                LeaveRequest.end_date >= current_date,
                LeaveRequest.status == 'approved'
            ).first()

            # Check attendance record (fingerprint)
            att = AttendanceRecord.query.filter_by(
                employee_id=emp.id,
                date=current_date
            ).first()

            # Calculate total time
            total_seconds = sum(s.elapsed_seconds or 0 for s in day_sessions)
            regular_seconds = sum(s.elapsed_seconds or 0 for s in day_sessions if s.hour_type != 'OVERTIME')
            ot_seconds = sum(s.elapsed_seconds or 0 for s in day_sessions if s.hour_type == 'OVERTIME')
            break_minutes = sum(b.duration_minutes or 0 for b in day_breaks)
            project_seconds = sum(s.elapsed_seconds or 0 for s in day_sessions if s.hour_type in ('WORK ORDER', 'OVERTIME'))

            # Determine day type
            if leave:
                day_type = 'Leave'
            elif not day_sessions and not att:
                # Skip weekends (Friday/Saturday) - optional
                if current_date.weekday() in (4, 5):  # Friday=4, Saturday=5
                    current_date += timedelta(days=1)
                    continue
                day_type = 'Absent'
            elif att and not day_sessions:
                day_type = 'No Fingerprint'
            else:
                day_type = 'Present'

            # OT after 9 hours (32400 seconds)
            ot_after_9h = max(0, total_seconds - 32400) if total_seconds > 32400 else 0

            # Check OT approval
            ot_request = OvertimeRequest.query.filter_by(
                employee_id=emp.id,
                request_date=current_date
            ).first()
            ot_approval_status = ot_request.status if ot_request else None

            # Format times
            def fmt_secs(s):
                if s <= 0: return '-'
                h = s // 3600
                m = (s % 3600) // 60
                return f"{h:02d}:{m:02d}"

            check_in = att.check_in_time.strftime('%H:%M') if att and att.check_in_time else (day_sessions[0].start_time.strftime('%H:%M') if day_sessions else '-')
            check_out = att.check_out_time.strftime('%H:%M') if att and att.check_out_time else (day_sessions[-1].end_time.strftime('%H:%M') if day_sessions and day_sessions[-1].end_time else '-')

            records.append({
                'employee_id': emp.id,
                'user_id': emp.user_id,
                'employee_name': emp.name,
                'department': emp.department or '-',
                'date': current_date.strftime('%Y-%m-%d'),
                'check_in': check_in,
                'check_out': check_out,
                'total_time': fmt_secs(total_seconds),
                'total_seconds': total_seconds,
                'project_time': fmt_secs(project_seconds),
                'break_time': f"{break_minutes} min" if break_minutes else '-',
                'day_type': day_type,
                'overtime_hours': fmt_secs(ot_after_9h) if ot_after_9h > 0 else '-',
                'ot_approval_status': ot_approval_status
            })

        current_date += timedelta(days=1)

    # Sort by date desc, then name
    records.sort(key=lambda r: (r['date'], r['employee_name']), reverse=True)

    return jsonify({'success': True, 'records': records})


@admin_bp.route('/attendance-log/export', methods=['GET'])
def export_attendance_log():
    """Export attendance log as Excel file"""
    import io
    try:
        import openpyxl
    except ImportError:
        return jsonify({"error": "openpyxl not installed"}), 500

    from flask import send_file

    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401

    # Reuse the same logic
    with __import__('flask').current_app.test_request_context(request.url):
        # Get data from the attendance log endpoint
        pass

    # Simple approach: generate Excel directly
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Attendance Log"
    headers = ['ID', 'Name', 'Department', 'Date', 'Check In', 'Check Out', 'Total Time', 'Project Time', 'Break Time', 'Day Type', 'OT Hours', 'OT Status']
    ws.append(headers)

    # Get data
    from models.timesheet_session import TimesheetSession, TimesheetBreak
    from models.employee import LeaveRequest, OvertimeRequest
    from datetime import timedelta

    emp_id = request.args.get('employee_id', type=int)
    dept_filter = request.args.get('department')
    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')

    start_date = date.fromisoformat(start_str) if start_str else date.today() - timedelta(days=30)
    end_date = date.fromisoformat(end_str) if end_str else date.today()

    emp_query = Employee.query.filter_by(is_admin=False)
    if emp_id:
        emp_query = emp_query.filter_by(id=emp_id)
    if dept_filter:
        emp_query = emp_query.filter_by(department=dept_filter)
    employees = emp_query.all()

    current_date = start_date
    while current_date <= end_date:
        for emp in employees:
            day_sessions = TimesheetSession.query.filter(
                TimesheetSession.employee_id == emp.id,
                TimesheetSession.date == current_date,
                TimesheetSession.status == 'completed'
            ).all()

            # Get breaks by employee_id OR by session_id
            day_break_ids = [s.id for s in TimesheetSession.query.filter(
                TimesheetSession.employee_id == emp.id,
                TimesheetSession.date == current_date
            ).all()]
            day_breaks = TimesheetBreak.query.filter(
                db.or_(
                    TimesheetBreak.session_id.in_(day_break_ids) if day_break_ids else db.false(),
                    db.and_(TimesheetBreak.employee_id == emp.id, db.func.date(TimesheetBreak.start_time) == current_date)
                )
            ).all()

            leave = LeaveRequest.query.filter(
                LeaveRequest.employee_id == emp.id,
                LeaveRequest.start_date <= current_date,
                LeaveRequest.end_date >= current_date,
                LeaveRequest.status == 'approved'
            ).first()

            att = AttendanceRecord.query.filter_by(employee_id=emp.id, date=current_date).first()

            total_seconds = sum(s.elapsed_seconds or 0 for s in day_sessions)
            break_minutes = sum(b.duration_minutes or 0 for b in day_breaks)
            project_seconds = sum(s.elapsed_seconds or 0 for s in day_sessions if s.hour_type in ('WORK ORDER', 'OVERTIME'))

            if leave:
                day_type = 'Leave'
            elif not day_sessions and not att:
                if current_date.weekday() in (4, 5):
                    current_date += timedelta(days=1)
                    continue
                day_type = 'Absent'
            elif att and not day_sessions:
                day_type = 'No Fingerprint'
            else:
                day_type = 'Present'

            ot_after_9h = max(0, total_seconds - 32400) if total_seconds > 32400 else 0
            ot_request = OvertimeRequest.query.filter_by(employee_id=emp.id, request_date=current_date).first()

            def fmt_s(s):
                if s <= 0: return '-'
                return f"{s//3600:02d}:{(s%3600)//60:02d}"

            check_in = att.check_in_time.strftime('%H:%M') if att and att.check_in_time else (day_sessions[0].start_time.strftime('%H:%M') if day_sessions else '-')
            check_out = att.check_out_time.strftime('%H:%M') if att and att.check_out_time else (day_sessions[-1].end_time.strftime('%H:%M') if day_sessions and day_sessions[-1].end_time else '-')

            ws.append([
                emp.user_id, emp.name, emp.department or '-', current_date.strftime('%Y-%m-%d'),
                check_in, check_out, fmt_s(total_seconds), fmt_s(project_seconds),
                f"{break_minutes} min" if break_minutes else '-', day_type,
                fmt_s(ot_after_9h) if ot_after_9h > 0 else '-',
                ot_request.status if ot_request else '-'
            ])
        current_date += timedelta(days=1)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, download_name='attendance_log.xlsx', as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')



@admin_bp.route('/leaves/export/excel', methods=['GET'])
def export_leaves_excel():
    """Export leave requests as Excel file"""
    import io
    try:
        import openpyxl
    except ImportError:
        return jsonify({"error": "openpyxl not installed"}), 500

    from flask import send_file
    from models.employee import LeaveRequest

    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401

    leaves = LeaveRequest.query.order_by(LeaveRequest.created_at.desc()).all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Leave Requests"
    headers = ['ID', 'Employee', 'Type', 'From', 'To', 'Duration', 'Half Day', 'Reason', 'Status', 'Approved By']
    ws.append(headers)

    cat_names = {'annual': 'Annual', 'sick': 'Sick', 'casual': 'Casual'}
    for l in leaves:
        emp = Employee.query.get(l.employee_id)
        ws.append([
            l.id,
            emp.name if emp else '-',
            cat_names.get(l.leave_category, l.leave_category),
            l.start_date.strftime('%Y-%m-%d'),
            l.end_date.strftime('%Y-%m-%d'),
            l.duration_days,
            'Yes' if l.is_half_day else 'No',
            l.reason or '-',
            l.status,
            l.approved_by_name or '-'
        ])

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, download_name='leave_requests.xlsx', as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

from sqlalchemy import func

@admin_bp.route('/leave-requests', methods=['GET'])
def admin_get_leaves():

    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    current_user = Employee.query.filter_by(
        user_id=session['user_id']
    ).first()

    if not current_user:
        return jsonify({"error": "User not found"}), 404

    # ✅ Query base
    query = LeaveRequest.query

    # ✅ Role logic
    if current_user.is_admin or current_user.role in ['hr', 'HR']:
        pass  # يشوف كل حاجة

    elif current_user.role in ['manager', 'مدير', 'رئيس قسم']:
        team_ids = [
            e.id for e in Employee.query.filter_by(manager_id=current_user.id).all()
        ]
        team_ids.append(current_user.id)

        query = query.filter(LeaveRequest.employee_id.in_(team_ids))

    else:
        query = query.filter_by(employee_id=current_user.id)

    # ✅ Filters (Search)
    status = request.args.get('status')
    category = request.args.get('category')

    if status:
        query = query.filter(LeaveRequest.status == status)

    if category and category != "all":
        query = query.filter(LeaveRequest.leave_category == category)

    leaves = query.order_by(LeaveRequest.id.desc()).all()

    result = []

    for l in leaves:
        emp = Employee.query.get(l.employee_id)

        result.append({
            "id": l.id,
            "employee_name": emp.name if emp else "-",
            "leave_category": l.leave_category,
            "start_date": str(l.start_date),
            "end_date": str(l.end_date),
            "duration_days": l.duration_days,
            "is_half_day": l.is_half_day,
            "reason": l.reason or "-",
            "attachment_path": getattr(l, "attachment_path", None),
            "status": l.status,
            "approved_by_name": l.approved_by_name or "-"
        })

    return jsonify({
        "leave_requests": result
    })

@admin_bp.route('/leave-requests', methods=['POST'])
def admin_create_leave():
    """
    Admin can create and auto-approve a leave request for any employee.
    """
    from models.employee import LeaveRequest, LeaveType

    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not current_user or not (current_user.is_admin or current_user.role.lower() == 'hr'):
        return jsonify({"error": "Unauthorized"}), 403

    data = request.json
    emp_id = data.get('employee_id')
    if not emp_id:
        return jsonify({"error": "employee_id is required"}), 400

    target_emp = Employee.query.get(emp_id)
    if not target_emp:
        return jsonify({"error": "Employee not found"}), 404

    leave_category = data.get('leave_category', 'annual')
    start = date.fromisoformat(data['start_date'])
    end = date.fromisoformat(data.get('end_date', data['start_date']))
    is_half_day = data.get('is_half_day', False)
    duration = float(data.get('duration_days', 0.5 if is_half_day else (end - start).days + 1))

    # Get or create leave type
    lt_map = {'annual': 'Annual Leave', 'sick': 'Sick Leave', 'casual': 'Casual Leave'}
    lt = LeaveType.query.filter_by(name=lt_map.get(leave_category, 'Annual Leave')).first()
    if not lt:
        lt = LeaveType(name=lt_map.get(leave_category, 'Annual Leave'))
        db.session.add(lt)
        db.session.flush()

    auto_approve = data.get('auto_approve', False)

    new_leave = LeaveRequest(
        employee_id=emp_id,
        leave_type_id=lt.id,
        leave_category=leave_category,
        start_date=start,
        end_date=end,
        duration_days=duration,
        reason=data.get('reason', f'Requested by admin ({current_user.name})'),
        is_half_day=is_half_day,
        status='approved' if auto_approve else 'pending',
        approved_by=current_user.id if auto_approve else None,
        approved_by_name=current_user.name if auto_approve else None
    )
    db.session.add(new_leave)
    db.session.commit()

    return jsonify({
        "success": True,
        "message": f"Leave request created for {target_emp.name}" + (" and auto-approved" if auto_approve else ""),
        "leave_id": new_leave.id
    })


@admin_bp.route('/not-started-today', methods=['GET'])
def get_not_started_today():
    """Report: employees who haven't started a session today"""
    from models.timesheet_session import TimesheetSession
    from models.employee import LeaveRequest

    date_str = request.args.get('date', date.today().isoformat())
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except Exception:
        target_date = date.today()

    # Get all employees (exclude admins from report)
    all_employees = Employee.query.filter_by(is_admin=False).all()
    all_count = len(all_employees)

    # Get employee IDs who started a session today
    started_ids = set()
    sessions_today = TimesheetSession.query.filter(
        db.func.date(TimesheetSession.start_time) == target_date
    ).all()
    for s in sessions_today:
        started_ids.add(s.employee_id)

    # Get employees on approved leave today
    on_leave_ids = set()
    try:
        leaves = LeaveRequest.query.filter(
            LeaveRequest.start_date <= target_date,
            LeaveRequest.end_date >= target_date,
            LeaveRequest.status == 'approved'
        ).all()
        for lv in leaves:
            on_leave_ids.add(lv.employee_id)
    except Exception:
        pass

    # Build list of employees who haven't started and are not on leave
    not_started = []
    for emp in all_employees:
        if emp.id not in started_ids and emp.id not in on_leave_ids:
            not_started.append({
                "employee_id": emp.id,
                "user_id": emp.user_id,
                "name": emp.name,
                "department": emp.department or '-',
                "position": emp.position or '-',
                "phone": getattr(emp, 'phone', '-') or '-'
            })

    return jsonify({
        "success": True,
        "date": date_str,
        "all_count": all_count,
        "not_started_count": len(not_started),
        "on_leave_count": len(on_leave_ids),
        "employees": not_started
    })

@admin_bp.route('/audit-logs', methods=['GET'])
def get_audit_logs():
    """عرض سجل التدقيق"""
    from models.employee import AuditLog
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(500).all()
    logs_data = []
    for log in logs:
        emp = Employee.query.get(log.employee_id) if log.employee_id else None
        logs_data.append({
            'id': log.id,
            'employee_name': emp.name if emp else 'System',
            'action': log.action,
            'entity_type': log.entity_type,
            'description': log.description,
            'ip_address': log.ip_address,
            'created_at': log.created_at.strftime('%Y-%m-%d %H:%M:%S')
        })
    return jsonify({'success': True, 'logs': logs_data})
