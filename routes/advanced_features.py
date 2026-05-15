"""
API الميزات المتقدمة:
- إدارة المديرين المتعددين
- طلب Overtime حسب اليوم
- نظام الإجازات الكامل
- نظام المهام
- نظام التقييم
- الإشعارات
- ربط البصمة ZK
- تقارير PDF
"""
from flask import Blueprint, request, jsonify, session, send_file
from models.database import db
from models.employee import (
    Employee, employee_managers, OvertimeRequest, Task,
    EmployeeRating, Notification, LeaveRequest, LeaveType
)
from models.timesheet_session import TimesheetSession, Project
from datetime import datetime, date, timedelta
from functools import wraps
import os, io, calendar

advanced_bp = Blueprint('advanced', __name__, url_prefix='/api')


# ═══════════════════════════════════════════════════════════════════════════════
# مساعدات الصلاحيات
# ═══════════════════════════════════════════════════════════════════════════════

def get_current_user():
    """إرجاع المستخدم الحالي أو None"""
    if 'user_id' not in session:
        return None
    return Employee.query.filter_by(user_id=session['user_id']).first()

def require_login(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"error": "غير مسجل دخول"}), 401
        return f(user, *args, **kwargs)
    return decorated

def require_role(*roles):
    """التحقق من أن المستخدم لديه أحد الأدوار المطلوبة"""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user = get_current_user()
            if not user:
                return jsonify({"error": "غير مسجل دخول"}), 401
            # الأدمن الرئيسي يمر دائماً
            if user.is_admin or user.role == 'admin':
                return f(user, *args, **kwargs)
            if user.role not in roles:
                return jsonify({"error": "غير مصرح لك بهذا الإجراء"}), 403
            return f(user, *args, **kwargs)
        return decorated
    return decorator


# ═══════════════════════════════════════════════════════════════════════════════
# 1. إدارة المديرين المتعددين
# ═══════════════════════════════════════════════════════════════════════════════

@advanced_bp.route('/employees/<int:emp_id>/managers', methods=['GET'])
@require_login
def get_employee_managers(current_user, emp_id):
    """عرض مديري موظف معين"""
    emp = Employee.query.get_or_404(emp_id)
    managers = emp.managers.all()
    return jsonify({
        "employee_id": emp.id,
        "employee_name": emp.name,
        "managers": [{"id": m.id, "user_id": m.user_id, "name": m.name, "role": m.role, "email": m.email or ''} for m in managers]
    })

@advanced_bp.route('/employees/<int:emp_id>/managers', methods=['POST'])
@require_role('admin')
def set_employee_managers(current_user, emp_id):
    """تعيين مديرين لموظف (يستبدل القائمة الحالية)"""
    emp = Employee.query.get_or_404(emp_id)
    data = request.get_json()
    manager_ids = data.get('manager_ids', [])
    
    # مسح المديرين الحاليين
    emp.managers = []
    db.session.flush()
    
    # إضافة المديرين الجدد
    for mid in manager_ids:
        if mid == emp_id:
            continue  # لا يمكن أن يكون مدير لنفسه
        mgr = Employee.query.get(mid)
        if mgr:
            emp.managers.append(mgr)
    
    db.session.commit()
    return jsonify({"success": True, "message": "تم تحديث المديرين بنجاح"})

@advanced_bp.route('/my-employees', methods=['GET'])
@require_login
def get_my_employees(current_user):
    """عرض الموظفين التابعين للمدير الحالي"""
    if current_user.is_admin or current_user.role == 'admin':
        # الأدمن يرى الكل
        employees = Employee.query.all()
    else:
        # المدير يرى موظفيه فقط
        employees = current_user.managed_employees.all()
    
    return jsonify({
        "employees": [{
            "id": e.id, "user_id": e.user_id, "name": e.name,
            "department": e.department or '-', "position": e.position or '-',
            "email": e.email or '', "role": e.role
        } for e in employees]
    })


# ═══════════════════════════════════════════════════════════════════════════════
# 2. طلب Overtime حسب اليوم
# ═══════════════════════════════════════════════════════════════════════════════

@advanced_bp.route('/overtime-requests', methods=['POST'])
@require_login
def create_overtime_request(current_user):
    """الموظف يقدم طلب Overtime ليوم معين"""
    data = request.get_json()
    if not data or 'request_date' not in data:
        return jsonify({"error": "تاريخ الطلب مطلوب"}), 400
    
    try:
        req_date = datetime.strptime(data['request_date'], '%Y-%m-%d').date()
    except ValueError:
        return jsonify({"error": "تنسيق التاريخ غير صحيح"}), 400
    
    # التحقق من عدم وجود طلب مسبق لنفس اليوم
    existing = OvertimeRequest.query.filter_by(
        employee_id=current_user.id, request_date=req_date
    ).first()
    if existing:
        return jsonify({"error": "يوجد طلب Overtime لهذا اليوم بالفعل", "status": existing.status}), 400
    
    new_req = OvertimeRequest(
        employee_id=current_user.id,
        request_date=req_date,
        reason=data.get('reason', ''),
        status='pending'
    )
    db.session.add(new_req)
    
    # إنشاء إشعار لكل مدير
    managers = current_user.managers.all()
    for mgr in managers:
        notif = Notification(
            employee_id=mgr.id,
            title='طلب وقت إضافي جديد',
            message=f'{current_user.name} قدم طلب Overtime ليوم {req_date}',
            notification_type='overtime',
            is_sound=True,
            related_type='overtime_request'
        )
        db.session.add(notif)
    
    db.session.commit()
    
    # إعداد بيانات mailto لفتح Outlook
    managers_emails = current_user.get_managers_emails()
    mailto_data = None
    if managers_emails:
        subject = f'طلب وقت إضافي - {current_user.name} - {req_date}'
        body = f'السلام عليكم،\n\nأطلب الموافقة على العمل الإضافي (Overtime) ليوم {req_date}.\nالسبب: {data.get("reason", "غير محدد")}\n\nشكراً،\n{current_user.name}'
        mailto_data = {
            "to": ';'.join(managers_emails),
            "subject": subject,
            "body": body
        }
    
    return jsonify({
        "success": True,
        "message": "تم تقديم طلب Overtime بنجاح",
        "request_id": new_req.id,
        "mailto": mailto_data
    })

@advanced_bp.route('/overtime-requests', methods=['GET'])
@require_login
def get_overtime_requests(current_user):
    """عرض طلبات Overtime"""
    status_filter = request.args.get('status')
    employee_id = request.args.get('employee_id', type=int)
    
    if current_user.is_admin or current_user.role == 'admin':
        query = OvertimeRequest.query
    elif current_user.role == 'planning':
        query = OvertimeRequest.query
    elif current_user.role == 'manager':
        # المدير يرى طلبات موظفيه فقط
        my_emp_ids = [e.id for e in current_user.managed_employees.all()]
        query = OvertimeRequest.query.filter(OvertimeRequest.employee_id.in_(my_emp_ids))
    else:
        # الموظف يرى طلباته فقط
        query = OvertimeRequest.query.filter_by(employee_id=current_user.id)
    
    if status_filter:
        query = query.filter_by(status=status_filter)
    if employee_id:
        query = query.filter_by(employee_id=employee_id)
    
    requests_list = query.order_by(OvertimeRequest.request_date.desc()).all()
    
    result = []
    for r in requests_list:
        emp = Employee.query.get(r.employee_id)
        # جلب تفاصيل جلسات Overtime لهذا اليوم
        day_sessions = TimesheetSession.query.filter(
            TimesheetSession.employee_id == r.employee_id,
            TimesheetSession.date == r.request_date,
            TimesheetSession.hour_type == 'OVERTIME'
        ).all()
        
        sessions_details = []
        total_ot_seconds = 0
        for s in day_sessions:
            proj = Project.query.get(s.project_id) if s.project_id else None
            secs = s.elapsed_seconds or 0
            total_ot_seconds += secs
            sessions_details.append({
                "session_id": s.id,
                "project_name": proj.project_name if proj else '-',
                "project_number": proj.project_number if proj else '-',
                "job_no": s.job_no or '-',
                "task_name": s.task_name or '-',
                "description": s.description or '',
                "hours": f"{secs//3600:02d}:{(secs%3600)//60:02d}"
            })
        
        result.append({
            "id": r.id,
            "employee_id": emp.user_id if emp else '-',
            "employee_name": emp.name if emp else '-',
            "employee_email": emp.email or '',
            "department": emp.department or '-',
            "request_date": str(r.request_date),
            "reason": r.reason or '',
            "status": r.status,
            "approved_by_name": r.approved_by_name or '-',
            "rejection_note": r.rejection_note or '',
            "total_overtime_hours": f"{total_ot_seconds//3600:02d}:{(total_ot_seconds%3600)//60:02d}",
            "sessions": sessions_details,
            "created_at": r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else ''
        })
    
    return jsonify({"overtime_requests": result, "count": len(result)})

@advanced_bp.route('/overtime-requests/<int:req_id>/approve', methods=['POST'])
@require_role('admin', 'planning', 'manager')
def approve_overtime_request(current_user, req_id):
    """موافقة على طلب Overtime ليوم كامل"""
    ot_req = OvertimeRequest.query.get_or_404(req_id)
    
    # التحقق من صلاحية المدير (إذا ليس أدمن)
    if not current_user.is_admin and current_user.role not in ('admin', 'planning'):
        if not current_user.is_manager_of(ot_req.employee_id):
            return jsonify({"error": "لست مديراً لهذا الموظف"}), 403
    
    ot_req.status = 'approved'
    ot_req.approved_by = current_user.id
    ot_req.approved_by_name = current_user.name
    ot_req.approved_at = datetime.utcnow()
    
    # تحديث جميع جلسات Overtime لهذا اليوم
    sessions = TimesheetSession.query.filter(
        TimesheetSession.employee_id == ot_req.employee_id,
        TimesheetSession.date == ot_req.request_date,
        TimesheetSession.hour_type == 'OVERTIME'
    ).all()
    for s in sessions:
        s.overtime_approval_status = 'approved'
        s.overtime_approved_by = current_user.id
        s.overtime_approved_at = datetime.utcnow()
    
    # إشعار للموظف
    notif = Notification(
        employee_id=ot_req.employee_id,
        title='تمت الموافقة على طلب Overtime',
        message=f'تمت الموافقة على طلب Overtime ليوم {ot_req.request_date} بواسطة {current_user.name}',
        notification_type='overtime',
        is_sound=True,
        related_id=ot_req.id,
        related_type='overtime_request'
    )
    db.session.add(notif)
    db.session.commit()
    
    return jsonify({"success": True, "message": "تمت الموافقة على طلب Overtime"})

@advanced_bp.route('/overtime-requests/<int:req_id>/reject', methods=['POST'])
@require_role('admin', 'planning', 'manager')
def reject_overtime_request(current_user, req_id):
    """رفض طلب Overtime — يتحول إلى WORK ORDER"""
    ot_req = OvertimeRequest.query.get_or_404(req_id)
    data = request.get_json() or {}
    
    if not current_user.is_admin and current_user.role not in ('admin', 'planning'):
        if not current_user.is_manager_of(ot_req.employee_id):
            return jsonify({"error": "لست مديراً لهذا الموظف"}), 403
    
    ot_req.status = 'rejected'
    ot_req.approved_by = current_user.id
    ot_req.approved_by_name = current_user.name
    ot_req.approved_at = datetime.utcnow()
    ot_req.rejection_note = data.get('note', '')
    
    # تحويل جلسات Overtime لهذا اليوم إلى WORK ORDER
    sessions = TimesheetSession.query.filter(
        TimesheetSession.employee_id == ot_req.employee_id,
        TimesheetSession.date == ot_req.request_date,
        TimesheetSession.hour_type == 'OVERTIME'
    ).all()
    for s in sessions:
        s.hour_type = 'WORK ORDER'
        s.overtime_approval_status = 'rejected'
        s.overtime_approved_by = current_user.id
        s.overtime_approved_at = datetime.utcnow()
        s.overtime_rejection_note = data.get('note', '')
    
    # إشعار للموظف
    notif = Notification(
        employee_id=ot_req.employee_id,
        title='تم رفض طلب Overtime',
        message=f'تم رفض طلب Overtime ليوم {ot_req.request_date} بواسطة {current_user.name}. السبب: {data.get("note", "غير محدد")}',
        notification_type='overtime',
        is_sound=True,
        related_id=ot_req.id,
        related_type='overtime_request'
    )
    db.session.add(notif)
    db.session.commit()
    
    return jsonify({"success": True, "message": "تم رفض طلب Overtime وتحويل الجلسات إلى WORK ORDER"})


# ═══════════════════════════════════════════════════════════════════════════════
# 3. نظام الإجازات الكامل
# ═══════════════════════════════════════════════════════════════════════════════

@advanced_bp.route('/leave-requests', methods=['POST'])
@require_login
def create_leave_request(current_user):
    """تقديم طلب إجازة"""
    # التحقق من وجود ملف مرفق (للإجازة المرضية)
    leave_category = request.form.get('leave_category') or (request.get_json() or {}).get('leave_category', 'annual')
    
    if request.content_type and 'multipart' in request.content_type:
        data = request.form.to_dict()
    else:
        data = request.get_json() or {}
    
    if not data.get('start_date'):
        return jsonify({"error": "تاريخ البداية مطلوب"}), 400
    
    try:
        start = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
        end = datetime.strptime(data.get('end_date', data['start_date']), '%Y-%m-%d').date()
    except ValueError:
        return jsonify({"error": "تنسيق التاريخ غير صحيح"}), 400
    
    is_half_day = data.get('is_half_day') in ('true', 'True', True, '1', 1)
    leave_category = data.get('leave_category', 'annual')
    
    # حساب عدد الأيام
    if is_half_day:
        duration = 0.5
    else:
        duration = (end - start).days + 1
    
    # التحقق من قواعد التقديم
    today = date.today()
    
    # السنوية: يجب قبلها بيوم تقويمي (إلا إذا كان أدمن)
    if leave_category == 'annual' and not (current_user.is_admin or current_user.role == 'admin'):
        if start <= today:
            return jsonify({"error": "الإجازة السنوية يجب تقديمها قبل موعدها بيوم على الأقل"}), 400
    
    # التحقق من الرصيد (كل الأرصدة تبدأ من 0)
    balances = {
        'annual': current_user.annual_leave_balance or 0,
        'sick': current_user.sick_leave_balance or 0,
        'casual': current_user.casual_leave_balance or 0,
        'marriage': getattr(current_user, 'marriage_leave_balance', 0) or 0,
        'other': getattr(current_user, 'other_leave_balance', 0) or 0,
        'deduction': getattr(current_user, 'deduction_leave_balance', 0) or 0
    }
    
    if leave_category in balances:
        used = db.session.query(db.func.sum(LeaveRequest.duration_days)).filter(
            LeaveRequest.employee_id == current_user.id,
            LeaveRequest.leave_category == leave_category,
            LeaveRequest.status.in_(['pending', 'approved'])
        ).scalar() or 0
        
        # استثناء لإجازة الخصم: يمكن أن تكون سالبة (تخصم من الراتب) ولكن نضع حدا أقصى 5 أيام
        if leave_category == 'deduction':
            if duration > 5:
                return jsonify({"error": "إجازة الخصم لا يمكن أن تتجاوز 5 أيام في الطلب الواحد"}), 400
        else:
            remaining = balances[leave_category] - used
            if duration > remaining:
                cat_name = {'annual':'سنوية','sick':'مرضية','casual':'عارضة','marriage':'زواج','other':'أخرى'}.get(leave_category, leave_category)
                return jsonify({"error": f"رصيد إجازة {cat_name} غير كافٍ. المتبقي: {remaining} يوم"}), 400
    
    # حفظ المرفق (للإجازة المرضية)
    # نتحقق أولاً إذا كان المسار مرسلاً في بيانات JSON (الرفع المنفصل)
    attachment_path = data.get('attachment_path')
    
    # إذا لم يكن مرسلاً كمسار، نتحقق إذا كان مرفوعاً مباشرة مع الطلب (Multipart)
    if not attachment_path and leave_category == 'sick':
        file = request.files.get('attachment')
        if file and file.filename:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            upload_dir = os.path.join(base_dir, 'static', 'uploads', 'leaves')
            os.makedirs(upload_dir, exist_ok=True)
            
            # استخدام نفس منطق التسمية المحسن (اسم الموظف - عدد الأيام - التاريخ)
            clean_emp_name = secure_filename(current_user.name)
            timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            ext = os.path.splitext(file.filename)[1]
            filename = f"{clean_emp_name}_{duration}days_{timestamp}{ext}"
            
            filepath = os.path.join(upload_dir, filename)
            file.save(filepath)
            attachment_path = f"/static/uploads/leaves/{filename}"
    
    # الحصول على leave_type_id (إنشاء إذا لم يوجد)
    lt_name_map = {
        'annual': 'إجازة سنوية', 
        'sick': 'إجازة مرضية', 
        'casual': 'إجازة عارضة',
        'marriage': 'إجازة زواج',
        'other': 'إجازة أخرى',
        'deduction': 'إجازة بخصم'
    }
    lt_name = lt_name_map.get(leave_category, 'إجازة سنوية')
    lt = LeaveType.query.filter_by(name=lt_name).first()
    if not lt:
        lt = LeaveType(name=lt_name)
        db.session.add(lt)
        db.session.flush()
    
    new_leave = LeaveRequest(
        employee_id=current_user.id,
        leave_type_id=lt.id,
        leave_category=leave_category,
        start_date=start,
        end_date=end,
        duration_days=duration,
        reason=data.get('reason', ''),
        is_half_day=is_half_day,
        attachment_path=attachment_path,
        status='pending'
    )
    db.session.add(new_leave)
    
    # إشعار للمديرين
    managers = current_user.managers.all()
    cat_names = {'annual': 'سنوية', 'sick': 'مرضية', 'casual': 'عارضة', 'marriage': 'زواج', 'other': 'أخرى', 'deduction': 'بخصم'}
    for mgr in managers:
        notif = Notification(
            employee_id=mgr.id,
            title='طلب إجازة جديد',
            message=f'{current_user.name} قدم طلب إجازة {cat_names.get(leave_category, "")} من {start} إلى {end}',
            notification_type='leave',
            is_sound=True,
            related_type='leave_request'
        )
        db.session.add(notif)
    
    db.session.commit()
    
    # إعداد mailto
    managers_emails = current_user.get_managers_emails()
    mailto_data = None
    if managers_emails:
        subject = f'طلب إجازة {cat_names.get(leave_category, "")} - {current_user.name}'
        body = f'السلام عليكم،\n\nأطلب إجازة {cat_names.get(leave_category, "")} من {start} إلى {end} ({duration} يوم).\nالسبب: {data.get("reason", "غير محدد")}\n\nشكراً،\n{current_user.name}'
        mailto_data = {
            "to": ';'.join(managers_emails),
            "subject": subject,
            "body": body
        }
    
    return jsonify({
        "success": True,
        "message": "تم تقديم طلب الإجازة بنجاح",
        "leave_id": new_leave.id,
        "mailto": mailto_data
    })

@advanced_bp.route('/leave-requests', methods=['GET'])
@require_login
def get_leave_requests(current_user):
    """عرض طلبات الإجازات"""
    status_filter = request.args.get('status')
    employee_id = request.args.get('employee_id', type=int)
    
    if current_user.is_admin or current_user.role in ('admin', 'hr'):
        query = LeaveRequest.query
    elif current_user.role == 'manager':
        my_emp_ids = [e.id for e in current_user.managed_employees.all()]
        my_emp_ids.append(current_user.id)
        query = LeaveRequest.query.filter(LeaveRequest.employee_id.in_(my_emp_ids))
    else:
        query = LeaveRequest.query.filter_by(employee_id=current_user.id)
    
    if status_filter:
        query = query.filter_by(status=status_filter)
    if employee_id:
        query = query.filter_by(employee_id=employee_id)
    
    leaves = query.order_by(LeaveRequest.created_at.desc()).all()
    
    cat_names = {'annual': 'سنوية', 'sick': 'مرضية', 'casual': 'عارضة', 'marriage': 'زواج', 'other': 'أخرى', 'deduction': 'بخصم'}
    result = []
    for l in leaves:
        emp = Employee.query.get(l.employee_id)
        result.append({
            "id": l.id,
            "employee_id": emp.user_id if emp else '-',
            "employee_name": emp.name if emp else '-',
            "leave_category": l.leave_category or 'annual',
            "leave_category_name": cat_names.get(l.leave_category, 'سنوية'),
            "start_date": str(l.start_date),
            "end_date": str(l.end_date),
            "duration_days": l.duration_days,
            "is_half_day": l.is_half_day,
            "reason": l.reason or '',
            "attachment_path": l.attachment_path or '',
            "status": l.status,
            "approved_by_name": l.approved_by_name or '-',
            "rejection_note": l.rejection_note or '',
            "created_at": l.created_at.strftime('%Y-%m-%d %H:%M') if l.created_at else ''
        })
    
    return jsonify({"leave_requests": result, "count": len(result)})

@advanced_bp.route('/leave-requests/<int:leave_id>/approve', methods=['POST'])
@require_role('admin', 'hr', 'manager')
def approve_leave(current_user, leave_id):
    """موافقة على طلب إجازة"""
    leave = LeaveRequest.query.get_or_404(leave_id)
    
    # نصف اليوم يحتاج موافقة أدمن فقط
    if leave.is_half_day and not (current_user.is_admin or current_user.role in ('admin', 'hr')):
        return jsonify({"error": "نصف اليوم يحتاج موافقة الأدمن أو HR فقط"}), 403
    
    if not current_user.is_admin and current_user.role not in ('admin', 'hr'):
        if not current_user.is_manager_of(leave.employee_id):
            return jsonify({"error": "لست مديراً لهذا الموظف"}), 403
    
    leave.status = 'approved'
    leave.approved_by = current_user.id
    leave.approved_by_name = current_user.name
    
    # إشعار للموظف
    notif = Notification(
        employee_id=leave.employee_id,
        title='تمت الموافقة على الإجازة',
        message=f'تمت الموافقة على إجازتك من {leave.start_date} إلى {leave.end_date} بواسطة {current_user.name}',
        notification_type='leave',
        is_sound=True,
        related_id=leave.id,
        related_type='leave_request'
    )
    db.session.add(notif)
    db.session.commit()
    
    return jsonify({"success": True, "message": "تمت الموافقة على الإجازة"})

@advanced_bp.route('/leave-requests/<int:leave_id>/reject', methods=['POST'])
@require_role('admin', 'hr', 'manager')
def reject_leave(current_user, leave_id):
    """رفض طلب إجازة"""
    leave = LeaveRequest.query.get_or_404(leave_id)
    data = request.get_json() or {}
    
    if not current_user.is_admin and current_user.role not in ('admin', 'hr'):
        if not current_user.is_manager_of(leave.employee_id):
            return jsonify({"error": "لست مديراً لهذا الموظف"}), 403
    
    leave.status = 'rejected'
    leave.approved_by = current_user.id
    leave.approved_by_name = current_user.name
    leave.rejection_note = data.get('note', '')
    
    notif = Notification(
        employee_id=leave.employee_id,
        title='تم رفض الإجازة',
        message=f'تم رفض إجازتك من {leave.start_date} إلى {leave.end_date}. السبب: {data.get("note", "غير محدد")}',
        notification_type='leave',
        is_sound=True,
        related_id=leave.id,
        related_type='leave_request'
    )
    db.session.add(notif)
    db.session.commit()
    
    return jsonify({"success": True, "message": "تم رفض الإجازة"})

@advanced_bp.route('/leave-requests/<int:leave_id>', methods=['PUT'])
@require_role('admin', 'hr')
def update_leave(current_user, leave_id):
    """تعديل إجازة (أدمن/HR فقط)"""
    leave = LeaveRequest.query.get_or_404(leave_id)
    data = request.get_json() or {}
    
    if 'start_date' in data:
        leave.start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
    if 'end_date' in data:
        leave.end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
    if 'duration_days' in data:
        leave.duration_days = float(data['duration_days'])
    if 'is_half_day' in data:
        leave.is_half_day = data['is_half_day'] in (True, 'true', '1', 1)
    if 'leave_category' in data:
        leave.leave_category = data['leave_category']
    if 'reason' in data:
        leave.reason = data['reason']
    if 'status' in data:
        leave.status = data['status']
        if data['status'] == 'approved':
            leave.approved_by = current_user.id
            leave.approved_by_name = current_user.name
    
    db.session.commit()
    return jsonify({"success": True, "message": "تم تعديل الإجازة بنجاح"})

@advanced_bp.route('/leave-balance/<int:emp_id>', methods=['GET'])
@require_login
def get_leave_balance(current_user, emp_id):
    """عرض رصيد إجازات موظف"""
    emp = Employee.query.get_or_404(emp_id)
    
    # حساب المستخدم
    def used(category):
        return db.session.query(db.func.sum(LeaveRequest.duration_days)).filter(
            LeaveRequest.employee_id == emp_id,
            LeaveRequest.leave_category == category,
            LeaveRequest.status.in_(['pending', 'approved'])
        ).scalar() or 0
    
    annual_used = used('annual')
    sick_used = used('sick')
    casual_used = used('casual')
    marriage_used = used('marriage')
    other_used = used('other')
    deduction_used = used('deduction')
    
    return jsonify({
        "employee_name": emp.name,
        "annual": {"total": emp.annual_leave_balance or 0, "used": annual_used, "remaining": (emp.annual_leave_balance or 0) - annual_used},
        "sick": {"total": emp.sick_leave_balance or 0, "used": sick_used, "remaining": (emp.sick_leave_balance or 0) - sick_used},
        "casual": {"total": emp.casual_leave_balance or 0, "used": casual_used, "remaining": (emp.casual_leave_balance or 0) - casual_used},
        "marriage": {"total": getattr(emp, 'marriage_leave_balance', 0) or 0, "used": marriage_used, "remaining": (getattr(emp, 'marriage_leave_balance', 0) or 0) - marriage_used},
        "other": {"total": getattr(emp, 'other_leave_balance', 0) or 0, "used": other_used, "remaining": (getattr(emp, 'other_leave_balance', 0) or 0) - other_used},
        "deduction": {"total": getattr(emp, 'deduction_leave_balance', 0) or 0, "used": deduction_used, "remaining": (getattr(emp, 'deduction_leave_balance', 0) or 0) - deduction_used}
    })

@advanced_bp.route('/leave-balance/<int:emp_id>', methods=['PUT'])
@require_role('admin', 'hr')
def update_leave_balance(current_user, emp_id):
    """تعديل رصيد إجازات موظف (أدمن/HR)"""
    emp = Employee.query.get_or_404(emp_id)
    data = request.get_json() or {}
    
    if 'annual_leave_balance' in data:
        emp.annual_leave_balance = int(data['annual_leave_balance'])
    if 'sick_leave_balance' in data:
        emp.sick_leave_balance = int(data['sick_leave_balance'])
    if 'casual_leave_balance' in data:
        emp.casual_leave_balance = int(data['casual_leave_balance'])
    if 'marriage_leave_balance' in data:
        emp.marriage_leave_balance = int(data['marriage_leave_balance'])
    if 'other_leave_balance' in data:
        emp.other_leave_balance = int(data['other_leave_balance'])
    if 'deduction_leave_balance' in data:
        emp.deduction_leave_balance = float(data['deduction_leave_balance'])
    
    db.session.commit()
    return jsonify({"success": True, "message": "تم تحديث رصيد الإجازات"})


# ═══════════════════════════════════════════════════════════════════════════════
# 4. نظام المهام
# ═══════════════════════════════════════════════════════════════════════════════

@advanced_bp.route('/tasks', methods=['POST'])
@require_role('admin', 'manager', 'planning')
def create_task(current_user):
    """إنشاء مهمة جديدة"""
    data = request.get_json()
    if not data or 'title' not in data or 'assigned_to' not in data:
        return jsonify({"error": "العنوان والموظف المكلف مطلوبان"}), 400
    
    task = Task(
        title=data['title'],
        description=data.get('description', ''),
        assigned_to=data['assigned_to'],
        assigned_by=current_user.id,
        project_id=data.get('project_id'),
        due_date=datetime.strptime(data['due_date'], '%Y-%m-%d').date() if data.get('due_date') else None,
        priority=data.get('priority', 'medium'),
        status='new'
    )
    db.session.add(task)
    
    # إشعار للموظف
    notif = Notification(
        employee_id=data['assigned_to'],
        title='مهمة جديدة',
        message=f'تم تكليفك بمهمة: {data["title"]} بواسطة {current_user.name}',
        notification_type='task',
        is_sound=True,
        related_type='task'
    )
    db.session.add(notif)
    db.session.commit()
    
    return jsonify({"success": True, "message": "تم إنشاء المهمة بنجاح", "task_id": task.id})

@advanced_bp.route('/tasks', methods=['GET'])
@require_login
def get_tasks(current_user):
    """عرض المهام"""
    if current_user.is_admin or current_user.role == 'admin':
        tasks = Task.query.order_by(Task.created_at.desc()).all()
    elif current_user.role in ('manager', 'planning'):
        # المهام التي أنشأها + المهام المكلف بها
        tasks = Task.query.filter(
            db.or_(Task.assigned_by == current_user.id, Task.assigned_to == current_user.id)
        ).order_by(Task.created_at.desc()).all()
    else:
        # الموظف يرى مهامه فقط
        tasks = Task.query.filter_by(assigned_to=current_user.id).order_by(Task.created_at.desc()).all()
    
    result = []
    for t in tasks:
        assignee = Employee.query.get(t.assigned_to)
        assigner = Employee.query.get(t.assigned_by)
        proj = Project.query.get(t.project_id) if t.project_id else None
        result.append({
            "id": t.id,
            "title": t.title,
            "description": t.description or '',
            "assigned_to_name": assignee.name if assignee else '-',
            "assigned_by_name": assigner.name if assigner else '-',
            "project_name": proj.project_name if proj else '-',
            "due_date": str(t.due_date) if t.due_date else '-',
            "priority": t.priority,
            "status": t.status,
            "created_at": t.created_at.strftime('%Y-%m-%d %H:%M') if t.created_at else ''
        })
    
    return jsonify({"tasks": result})

@advanced_bp.route('/tasks/<int:task_id>', methods=['PUT'])
@require_login
def update_task(current_user, task_id):
    """تحديث مهمة"""
    task = Task.query.get_or_404(task_id)
    data = request.get_json() or {}
    
    # الموظف يمكنه تغيير الحالة فقط
    if not (current_user.is_admin or current_user.role in ('admin', 'manager', 'planning')):
        if task.assigned_to != current_user.id:
            return jsonify({"error": "غير مصرح"}), 403
        if 'status' in data:
            task.status = data['status']
        db.session.commit()
        return jsonify({"success": True})
    
    if 'title' in data: task.title = data['title']
    if 'description' in data: task.description = data['description']
    if 'assigned_to' in data: task.assigned_to = data['assigned_to']
    if 'project_id' in data: task.project_id = data['project_id']
    if 'due_date' in data and data['due_date']:
        task.due_date = datetime.strptime(data['due_date'], '%Y-%m-%d').date()
    if 'priority' in data: task.priority = data['priority']
    if 'status' in data: task.status = data['status']
    
    db.session.commit()
    return jsonify({"success": True, "message": "تم تحديث المهمة"})


# ═══════════════════════════════════════════════════════════════════════════════
# 5. نظام التقييم
# ═══════════════════════════════════════════════════════════════════════════════

@advanced_bp.route('/ratings', methods=['POST'])
@require_role('admin', 'manager')
def create_rating(current_user):
    """تقييم موظف"""
    data = request.get_json()
    if not data or 'employee_id' not in data or 'rating' not in data:
        return jsonify({"error": "بيانات التقييم مطلوبة"}), 400
    
    rating = EmployeeRating(
        employee_id=data['employee_id'],
        rated_by=current_user.id,
        month=data.get('month', date.today().month),
        year=data.get('year', date.today().year),
        rating=int(data['rating']),
        performance_notes=data.get('performance_notes', ''),
        strengths=data.get('strengths', ''),
        improvements=data.get('improvements', '')
    )
    db.session.add(rating)
    
    # إشعار للموظف
    notif = Notification(
        employee_id=data['employee_id'],
        title='تقييم أداء جديد',
        message=f'تم تقييم أدائك لشهر {data.get("month", date.today().month)}/{data.get("year", date.today().year)} بواسطة {current_user.name}',
        notification_type='rating',
        is_sound=True,
        related_type='rating'
    )
    db.session.add(notif)
    db.session.commit()
    
    return jsonify({"success": True, "message": "تم حفظ التقييم"})

@advanced_bp.route('/ratings', methods=['GET'])
@require_login
def get_ratings(current_user):
    """عرض التقييمات"""
    employee_id = request.args.get('employee_id', type=int)
    
    if current_user.is_admin or current_user.role in ('admin', 'manager'):
        query = EmployeeRating.query
    else:
        query = EmployeeRating.query.filter_by(employee_id=current_user.id)
    
    if employee_id:
        query = query.filter_by(employee_id=employee_id)
    
    ratings = query.order_by(EmployeeRating.year.desc(), EmployeeRating.month.desc()).all()
    
    result = []
    for r in ratings:
        emp = Employee.query.get(r.employee_id)
        rater = Employee.query.get(r.rated_by)
        result.append({
            "id": r.id,
            "employee_name": emp.name if emp else '-',
            "rated_by_name": rater.name if rater else '-',
            "month": r.month, "year": r.year,
            "rating": r.rating,
            "performance_notes": r.performance_notes or '',
            "strengths": r.strengths or '',
            "improvements": r.improvements or ''
        })
    
    return jsonify({"ratings": result})


# ═══════════════════════════════════════════════════════════════════════════════
# 6. الإشعارات
# ═══════════════════════════════════════════════════════════════════════════════

@advanced_bp.route('/notifications', methods=['GET'])
@require_login
def get_notifications(current_user):
    """عرض إشعارات المستخدم الحالي"""
    limit = request.args.get('limit', 50, type=int)
    unread_only = request.args.get('unread_only', 'false') == 'true'
    
    query = Notification.query.filter_by(employee_id=current_user.id)
    if unread_only:
        query = query.filter_by(is_read=False)
    
    notifications = query.order_by(Notification.created_at.desc()).limit(limit).all()
    unread_count = Notification.query.filter_by(employee_id=current_user.id, is_read=False).count()
    
    return jsonify({
        "notifications": [{
            "id": n.id, "title": n.title, "message": n.message,
            "type": n.notification_type, "is_read": n.is_read,
            "is_sound": n.is_sound,
            "created_at": n.created_at.strftime('%Y-%m-%d %H:%M') if n.created_at else ''
        } for n in notifications],
        "unread_count": unread_count
    })

@advanced_bp.route('/notifications/read', methods=['POST'])
@require_login
def mark_notifications_read(current_user):
    """تحديد الإشعارات كمقروءة"""
    data = request.get_json() or {}
    ids = data.get('ids', [])
    
    if ids:
        Notification.query.filter(
            Notification.id.in_(ids),
            Notification.employee_id == current_user.id
        ).update({Notification.is_read: True}, synchronize_session=False)
    else:
        # تحديد الكل كمقروء
        Notification.query.filter_by(
            employee_id=current_user.id, is_read=False
        ).update({Notification.is_read: True}, synchronize_session=False)
    
    db.session.commit()
    return jsonify({"success": True})


# ═══════════════════════════════════════════════════════════════════════════════
# 7. ربط البصمة ZK
# ═══════════════════════════════════════════════════════════════════════════════

@advanced_bp.route('/fingerprint/attendance', methods=['GET'])
@require_login
def get_fingerprint_attendance(current_user):
    """جلب بيانات البصمة من جهاز ZK"""
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')
    employee_id = request.args.get('employee_id', type=int)
    
    try:
        from zk import ZK
        zk = ZK('172.18.0.249', port=4370, timeout=5)
        conn = zk.connect()
        attendances = conn.get_attendance()
        conn.disconnect()
    except Exception as e:
        # إذا فشل الاتصال بالجهاز، نعيد رسالة خطأ
        return jsonify({"error": f"فشل الاتصال بجهاز البصمة: {str(e)}", "records": []}), 200
    
    records = []
    for att in attendances:
        # إصلاح خطأ day is out of range for month
        try:
            att_date = att.timestamp.date() if att.timestamp else None
        except (ValueError, OverflowError, AttributeError):
            att_date = None
        
        # فلتر التاريخ
        try:
            if from_date and att_date:
                if att_date < datetime.strptime(from_date, '%Y-%m-%d').date():
                    continue
            if to_date and att_date:
                if att_date > datetime.strptime(to_date, '%Y-%m-%d').date():
                    continue
        except (ValueError, Exception):
            pass
        
        try:
            ts_str = att.timestamp.strftime('%Y-%m-%d %H:%M:%S') if att.timestamp and att_date else ''
            time_str = att.timestamp.strftime('%H:%M:%S') if att.timestamp and att_date else ''
        except (ValueError, Exception):
            ts_str = ''
            time_str = ''
        
        # تحديد الحالة بشكل مقروء
        punch_map = {0: 'Check In', 1: 'Check Out', 2: 'Break Out', 3: 'Break In', 4: 'OT In', 5: 'OT Out'}
        punch_label = punch_map.get(att.punch, f'Punch {att.punch}') if hasattr(att, 'punch') else '-'
        
        records.append({
            "user_id": str(att.user_id),
            "timestamp": ts_str,
            "date": str(att_date) if att_date else '',
            "time": time_str,
            "status": att.status if hasattr(att, 'status') else 0,
            "punch": att.punch if hasattr(att, 'punch') else 0,
            "punch_label": punch_label
        })
    
    # فلتر حسب الموظف
    if employee_id:
        emp = Employee.query.get(employee_id)
        if emp:
            records = [r for r in records if r['user_id'] == emp.user_id]
    elif not (current_user.is_admin or current_user.role in ('admin', 'manager')):
        # الموظف يرى بياناته فقط
        records = [r for r in records if r['user_id'] == current_user.user_id]
    elif current_user.role == 'manager' and not current_user.is_admin:
        # المدير يرى موظفيه فقط
        my_emp_ids = [e.user_id for e in current_user.managed_employees.all()]
        my_emp_ids.append(current_user.user_id)
        records = [r for r in records if r['user_id'] in my_emp_ids]
    
    # ترتيب حسب التاريخ والوقت
    records.sort(key=lambda x: x['timestamp'], reverse=True)
    return jsonify({"records": records, "count": len(records)})


@advanced_bp.route('/fingerprint/sync', methods=['POST'])
@require_role('admin', 'manager', 'hr', 'planning')
def sync_fingerprint(current_user):
    """مزامنة بيانات البصمة من الجهاز (زر جلب البصمات)"""
    try:
        from zk import ZK
        zk = ZK('172.18.0.249', port=4370, timeout=10)
        conn = zk.connect()
        attendances = conn.get_attendance()
        users = conn.get_users()
        conn.disconnect()
        user_map = {str(u.user_id): u.name for u in users}
        count = 0
        records_preview = []
        for att in attendances:
            try:
                att_date = att.timestamp.date() if att.timestamp else None
                ts_str = att.timestamp.strftime('%Y-%m-%d %H:%M:%S') if att.timestamp and att_date else ''
                time_str = att.timestamp.strftime('%H:%M:%S') if att.timestamp and att_date else ''
            except (ValueError, OverflowError, AttributeError):
                att_date = None
                ts_str = ''
                time_str = ''
            punch_map = {0: 'Check In', 1: 'Check Out', 2: 'Break Out', 3: 'Break In', 4: 'OT In', 5: 'OT Out'}
            punch_label = punch_map.get(getattr(att, 'punch', 0), f'Punch {getattr(att, "punch", 0)}')
            count += 1
            if len(records_preview) < 5:
                records_preview.append({
                    "user_id": str(att.user_id),
                    "name": user_map.get(str(att.user_id), 'غير معروف'),
                    "date": str(att_date) if att_date else '',
                    "time": time_str,
                    "punch_label": punch_label
                })
        return jsonify({
            "success": True,
            "message": f"تم جلب {count} سجل من جهاز البصمة بنجاح",
            "total_records": count,
            "preview": records_preview
        })
    except Exception as e:
        return jsonify({"success": False, "error": f"فشل الاتصال بجهاز البصمة: {str(e)}"}), 200


# ═══════════════════════════════════════════════════════════════════════════════
# 8. تقرير مقارنة المشاريع
# ═══════════════════════════════════════════════════════════════════════════════

@advanced_bp.route('/reports/projects-comparison', methods=['GET'])
@require_role('admin', 'manager', 'planning')
def projects_comparison(current_user):
    """تقرير مقارنة ساعات المشاريع"""
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    query = TimesheetSession.query.filter(
        TimesheetSession.status == 'completed',
        TimesheetSession.project_id.isnot(None)
    )
    
    if start_date_str:
        query = query.filter(TimesheetSession.date >= datetime.strptime(start_date_str, '%Y-%m-%d').date())
    if end_date_str:
        query = query.filter(TimesheetSession.date <= datetime.strptime(end_date_str, '%Y-%m-%d').date())
    
    sessions = query.all()
    
    projects_data = {}
    for s in sessions:
        pid = s.project_id
        if pid not in projects_data:
            proj = Project.query.get(pid)
            projects_data[pid] = {
                "name": proj.project_name if proj else '-',
                "number": proj.project_number if proj else '-',
                "regular": 0, "overtime": 0, "total": 0
            }
        secs = s.elapsed_seconds or 0
        projects_data[pid]["total"] += secs
        if s.hour_type == 'OVERTIME':
            projects_data[pid]["overtime"] += secs
        else:
            projects_data[pid]["regular"] += secs
    
    def fmt(s): return f"{s//3600:02d}:{(s%3600)//60:02d}"
    
    result = sorted([{
        "name": d["name"], "number": d["number"],
        "regular_hours": fmt(d["regular"]), "overtime_hours": fmt(d["overtime"]),
        "total_hours": fmt(d["total"]),
        "regular_seconds": d["regular"], "overtime_seconds": d["overtime"], "total_seconds": d["total"]
    } for d in projects_data.values()], key=lambda x: x["total_seconds"], reverse=True)
    
    return jsonify({"projects": result})


# ═══════════════════════════════════════════════════════════════════════════════
# 9. تحديث بيانات الموظف (إيميل + أدوار)
# ═══════════════════════════════════════════════════════════════════════════════

@advanced_bp.route('/employees/<int:emp_id>/update-advanced', methods=['PUT'])
@require_role('admin')
def update_employee_advanced(current_user, emp_id):
    """تحديث بيانات متقدمة للموظف"""
    emp = Employee.query.get_or_404(emp_id)
    data = request.get_json() or {}
    
    if 'email' in data:
        emp.email = data['email']
    if 'role' in data:
        emp.role = data['role']
    if 'overtime_limit' in data:
        emp.overtime_limit = int(data['overtime_limit']) if data['overtime_limit'] else None
    if 'annual_leave_balance' in data:
        emp.annual_leave_balance = int(data['annual_leave_balance'])
    if 'sick_leave_balance' in data:
        emp.sick_leave_balance = int(data['sick_leave_balance'])
    if 'casual_leave_balance' in data:
        emp.casual_leave_balance = int(data['casual_leave_balance'])
    if 'marriage_leave_balance' in data:
        emp.marriage_leave_balance = int(data['marriage_leave_balance'])
    if 'other_leave_balance' in data:
        emp.other_leave_balance = int(data['other_leave_balance'])
    if 'deduction_leave_balance' in data:
        emp.deduction_leave_balance = float(data['deduction_leave_balance'])
    
    db.session.commit()
    return jsonify({"success": True, "message": "تم تحديث بيانات الموظف"})


# ═══════════════════════════════════════════════════════════════════════════════
# 10. معلومات المستخدم الحالي (للواجهة)
# ═══════════════════════════════════════════════════════════════════════════════

@advanced_bp.route('/me', methods=['GET'])
@require_login
def get_me(current_user):
    """معلومات المستخدم الحالي"""
    managers = current_user.managers.all()
    return jsonify({
        "id": current_user.id,
        "user_id": current_user.user_id,
        "name": current_user.name,
        "email": current_user.email or '',
        "role": current_user.role,
        "is_admin": current_user.is_admin,
        "department": current_user.department or '',
        "position": current_user.position or '',
        "overtime_limit": current_user.overtime_limit,
        "managers": [{"id": m.id, "name": m.name, "email": m.email or ''} for m in managers]
    })

# ═══════════════════════════════════════════════════════════════════════════════
# 11. رفع المرفقات
# ═══════════════════════════════════════════════════════════════════════════════
@advanced_bp.route('/upload-attachment', methods=['POST'])
@require_login
def upload_attachment(current_user):
    """رفع مرفق وحفظه في المجلد المخصص"""
    if 'file' not in request.files:
        return jsonify({"error": "لم يتم إرسال أي ملف"}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "اسم الملف فارغ"}), 400
        
    if file:
        import os
        from datetime import datetime
        from werkzeug.utils import secure_filename
        
        # استخدام مسار مطلق لضمان الحفظ الصحيح
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        upload_dir = os.path.join(base_dir, 'static', 'uploads', 'leaves')
        os.makedirs(upload_dir, exist_ok=True)
        
        # الحصول على عدد أيام الإجازة من الطلب (إذا كان متاحاً)
        duration = request.form.get('duration_days', '0')
        
        # تنظيف اسم الملف وتشكيله (اسم الموظف - عدد الأيام - التاريخ)
        clean_emp_name = secure_filename(current_user.name)
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        ext = os.path.splitext(file.filename)[1]
        filename = f"{clean_emp_name}_{duration}days_{timestamp}{ext}"
        
        filepath = os.path.join(upload_dir, filename)
        file.save(filepath)
        
        # المسار الذي سيتم تخزينه في قاعدة البيانات والوصول إليه عبر المتصفح
        # ملاحظة: يجب أن يبدأ المسار بـ /uploads/ ليتوافق مع معالج الملفات في main.py
        # أو نستخدم /static/uploads/ إذا كان مجلد static يحتوي على uploads
        web_path = f"/static/uploads/leaves/{filename}"
        
        return jsonify({
            "success": True, 
            "message": "تم رفع الملف بنجاح",
            "path": web_path
        })
    
    return jsonify({"error": "فشل رفع الملف"}), 500
