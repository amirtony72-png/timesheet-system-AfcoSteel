from flask import Blueprint, request, jsonify, session
from models.database import db
from models.employee import Employee

user_bp = Blueprint('user', __name__, url_prefix='/api')

def get_user_permissions(user):
    """تحديد صلاحيات المستخدم بناءً على دوره"""
    permissions = {
        'can_view_own_data': True,
        'can_view_subordinates': False,
        'can_approve_leaves': False,
        'can_manage_system': False,
        'can_view_all_employees': False
    }
    
    if user.role in ['رئيس قسم', 'مدير اداره', 'مدير عام', 'مدير']:
        permissions['can_view_subordinates'] = True
        permissions['can_approve_leaves'] = True
    
    if user.role in ['مدير عام', 'مدير'] or user.is_admin:
        permissions['can_view_all_employees'] = True
    
    if user.is_admin:
        permissions['can_manage_system'] = True
    
    return permissions

def get_accessible_employees(user):
    """الحصول على قائمة الموظفين الذين يمكن للمستخدم الوصول إليهم"""
    if user.is_admin or user.role == 'مدير':
        # المدير والأدمن يمكنهم الوصول لجميع الموظفين
        return Employee.query.all()
    
    accessible_employees = [user]  # يمكن دائماً الوصول لبياناته الشخصية
    
    if user.role in ['رئيس قسم', 'مدير اداره', 'مدير عام']:
        # الحصول على جميع المرؤوسين بشكل تدريجي
        def get_all_subordinates(manager):
            subordinates = []
            direct_subordinates = Employee.query.filter_by(manager_id=manager.id).all()
            for subordinate in direct_subordinates:
                subordinates.append(subordinate)
                subordinates.extend(get_all_subordinates(subordinate))
            return subordinates
        
        accessible_employees.extend(get_all_subordinates(user))
    
    return accessible_employees

def log_audit(action, entity_type=None, entity_id=None, description=None):
    """دالة مساعدة لتسجيل العمليات في سجل التدقيق"""
    try:
        from models.employee import AuditLog
        from flask import request, session
        employee_id = session.get('employee_id')
        new_log = AuditLog(
            employee_id=employee_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            description=description,
            ip_address=request.remote_addr
        )
        db.session.add(new_log)
        db.session.commit()
    except Exception as e:
        print(f"Error logging audit: {e}")


@user_bp.route('/login', methods=['POST'])
def login():
    """تسجيل الدخول"""
    data = request.json
    username = data.get("user_id")
    password = data.get('password')
    
    employee = Employee.query.filter_by(user_id=username, password=password).first()
    
    if employee:
        # مسح الجلسة القديمة أولاً
        session.clear()
        session['employee_id'] = employee.id
        log_audit('Login', 'User', employee.id, f'User {employee.name} logged in')
        session.permanent = True
        session["user_id"] = employee.user_id
        session["employee_id"] = employee.id
        
        # التأكد من حفظ الجلسة في ملف قاعدة بيانات الجلسات (إذا وجد) أو الذاكرة
        # Flask سيقوم بإرسال Set-Cookie header
        
        permissions = get_user_permissions(employee)
        
        # إضافة معلومات التوجيه مباشرة في الاستجابة لزيادة الموثوقية
        redirect_url = '/admin' if (employee.is_admin or employee.role in ['admin', 'hr', 'planning', 'manager']) else '/'
        
        return jsonify({
            "success": True,
            "message": "تم تسجيل الدخول بنجاح!",
            "redirect_url": redirect_url,
            "user": {
                "id": employee.id,
                "user_id": employee.user_id,
                "name": employee.name,
                "role": employee.role,
                "is_admin": employee.is_admin,
                "permissions": permissions
            }
        })
    else:
        return jsonify({"success": False, "message": "بيانات الدخول غير صحيحة."}), 401

@user_bp.route('/logout', methods=['POST'])
def logout():
    """تسجيل الخروج"""
    log_audit('Logout', 'User', session.get('employee_id'), 'User logged out')
    session.clear()
    return jsonify({"success": True, "message": "تم تسجيل الخروج بنجاح"})

@user_bp.route('/current_user', methods=['GET'])
def get_current_user():
    """الحصول على بيانات المستخدم الحالي"""
    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401
    
    employee = Employee.query.filter_by(user_id=session['user_id']).first()
    if not employee:
        return jsonify({"error": "المستخدم غير موجود"}), 404
    
    permissions = get_user_permissions(employee)
    
    return jsonify({
        "user": {
            "id": employee.id,
            "user_id": employee.user_id,
            "name": employee.name,
            "role": employee.role,
            "is_admin": employee.is_admin,
            "permissions": permissions
        }
    })

@user_bp.route('/accessible_employees', methods=['GET'])
def get_accessible_employees_list():
    """الحصول على قائمة الموظفين المتاحين للمستخدم الحالي"""
    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401
    
    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not current_user:
        return jsonify({"error": "المستخدم غير موجود"}), 404
    
    accessible_employees = get_accessible_employees(current_user)
    
    employees_data = []
    for emp in accessible_employees:
        manager_name = emp.manager.name if emp.manager else None
        employees_data.append({
            'id': emp.id,
            'user_id': emp.user_id,
            'name': emp.name,
            'role': emp.role,
            'manager_name': manager_name,
            'is_admin': emp.is_admin
        })
    
    return jsonify({'employees': employees_data})

@user_bp.route('/change_password', methods=['POST'])
def change_password():
    """تغيير كلمة المرور"""
    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401
    
    data = request.json
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    
    employee = Employee.query.filter_by(user_id=session['user_id']).first()
    if not employee:
        return jsonify({"error": "المستخدم غير موجود"}), 404
    
    if employee.password != current_password:
        return jsonify({"error": "كلمة المرور الحالية غير صحيحة"}), 400
    
    employee.password = new_password
    db.session.commit()
    
    return jsonify({"success": True, "message": "تم تغيير كلمة المرور بنجاح"})

@user_bp.route('/users', methods=['GET'])
def get_users():
    """الحصول على قائمة المستخدمين (للتوافق مع الكود القديم)"""
    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401
    
    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not current_user:
        return jsonify({"error": "المستخدم غير موجود"}), 404
    
    accessible_employees = get_accessible_employees(current_user)
    
    return jsonify([{
        "id": emp.id,
        "user_id": emp.user_id,
        "name": emp.name,
        "role": emp.role,
        "is_admin": emp.is_admin
    } for emp in accessible_employees])

@user_bp.route('/users', methods=['POST'])
def create_user():
    """إنشاء مستخدم جديد (للأدمن فقط)"""
    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401
    
    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not current_user or not current_user.is_admin:
        return jsonify({"error": "غير مصرح لك بهذا الإجراء"}), 403
    
    data = request.json
    
    # التحقق من عدم وجود مستخدم بنفس المعرف
    existing_user = Employee.query.filter_by(user_id=data['user_id']).first()
    if existing_user:
        return jsonify({"error": "معرف المستخدم موجود بالفعل"}), 400
    
    new_employee = Employee(
        user_id=data['user_id'],
        name=data['name'],
        password=data.get('password', data['user_id']),  # كلمة المرور الافتراضية
        role=data.get('role', 'موظف'),
        manager_id=data.get('manager_id')
    )
    
    db.session.add(new_employee)
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "تم إنشاء المستخدم بنجاح",
        "user": {
            "id": new_employee.id,
            "user_id": new_employee.user_id,
            "name": new_employee.name,
            "role": new_employee.role
        }
    }), 201

@user_bp.route('/users/<int:user_id>', methods=['GET'])
def get_user(user_id):
    """الحصول على بيانات مستخدم محدد"""
    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401
    
    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not current_user:
        return jsonify({"error": "المستخدم غير موجود"}), 404
    
    target_user = Employee.query.get_or_404(user_id)
    accessible_employees = get_accessible_employees(current_user)
    
    if target_user not in accessible_employees:
        return jsonify({"error": "غير مصرح لك بالوصول لهذا المستخدم"}), 403
    
    return jsonify({
        "id": target_user.id,
        "user_id": target_user.user_id,
        "name": target_user.name,
        "role": target_user.role,
        "manager_name": target_user.manager.name if target_user.manager else None,
        "is_admin": target_user.is_admin
    })
@user_bp.route('/users/<int:user_id>', methods=['PUT'])
def update_user(user_id):
    """تحديث بيانات مستخدم (للأدمن فقط)"""
    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401
    
    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not current_user or not current_user.is_admin:
        return jsonify({"error": "غير مصرح لك بهذا الإجراء"}), 403
    
    target_user = Employee.query.get_or_404(user_id)
    data = request.json
    
    if 'name' in data:
        target_user.name = data['name']
    if 'role' in data:
        target_user.role = data['role']
    if 'manager_id' in data:
        target_user.manager_id = data['manager_id'] if data['manager_id'] else None
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "تم تحديث المستخدم بنجاح",
        "user": {
            "id": target_user.id,
            "user_id": target_user.user_id,
            "name": target_user.name,
            "role": target_user.role
        }
    })

@user_bp.route('/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    """حذف مستخدم (للأدمن فقط)"""
    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401
    
    current_user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not current_user or not current_user.is_admin:
        return jsonify({"error": "غير مصرح لك بهذا الإجراء"}), 403
    
    target_user = Employee.query.get_or_404(user_id)
    
    # لا يمكن حذف الأدمن الحالي
    if target_user.id == current_user.id:
        return jsonify({"error": "لا يمكن حذف حسابك الشخصي"}), 400
    
    db.session.delete(target_user)
    db.session.commit()
    
    return jsonify({"success": True, "message": "تم حذف المستخدم بنجاح"}), 204

from models.employee import LeaveRequest
from sqlalchemy import func

@user_bp.route('/leave-requests', methods=['GET'])
def get_my_leaves():

    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    employee = Employee.query.filter_by(
        user_id=session['user_id']
    ).first()

    if not employee:
        return jsonify({"error": "User not found"}), 404

    # ✅ أهم خط → إجازاتي فقط
    leaves = LeaveRequest.query.filter_by(
        employee_id=employee.id
    ).all()

    result = []

    for l in leaves:
        result.append({
            "id": l.id,
            "employee_name": employee.name,
            "leave_category": l.leave_category,
            "start_date": str(l.start_date),
            "end_date": str(l.end_date),
            "duration_days": l.duration_days,
            "reason": l.reason or "-",
            "status": l.status,
            "approved_by_name": l.approved_by_name or "-"
        })

    return jsonify({"leave_requests": result})