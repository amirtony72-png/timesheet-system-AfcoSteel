import os
app.secret_key = os.environ.get("SECRET_KEY", "super-secret-key")
import sys

# DON'T CHANGE THIS !!!
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, send_from_directory, session, redirect, url_for, jsonify, request
from flask_cors import CORS
from models.database import db

app = Flask(__name__, static_folder=os.path.join(os.path.dirname(__file__), 'static'))
app.config["SECRET_KEY"] = "asdf#FGSgvasgf$5$WGT"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = 86400  # 24 hours
app.config["SESSION_COOKIE_NAME"] = "attendance_sid"
# تعطيل القيود الصارمة للكوكيز لضمان عملها خلف الـ Proxy
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(os.path.dirname(__file__), 'instance', 'attendance.db')

print("DB FILE:", app.config['SQLALCHEMY_DATABASE_URI'])  # ✅ هنا
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# تفعيل CORS مع دعم الـ credentials
CORS(app, supports_credentials=True, origins=['*'], allow_headers=['*'])

# معالج لضمان استمرارية الجلسة
@app.before_request
def before_request():
    """Ensure session is marked as permanent to persist across requests"""
    session.permanent = True
    app.permanent_session_lifetime = 86400  # 24 hours

# تهيئة قاعدة البيانات
db.init_app(app)

# تسجيل الـ Blueprints الموجودة فعلاً
from routes.user import user_bp
from routes.admin import admin_bp
from routes.timesheet_advanced import timesheet_advanced_bp
from routes.advanced_features import advanced_bp
from routes.features_v76 import features_v76_bp

app.register_blueprint(user_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(timesheet_advanced_bp)
app.register_blueprint(advanced_bp)
app.register_blueprint(features_v76_bp)

# مسار uploads للمرفقات
uploads_dir = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(uploads_dir, exist_ok=True)

@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    return send_from_directory(uploads_dir, filename)

# إنشاء مجلد قاعدة البيانات إذا لم يكن موجوداً
instance_dir = os.path.join(os.path.dirname(__file__), 'instance')
if not os.path.exists(instance_dir):
    os.makedirs(instance_dir)

with app.app_context():
    # استيراد النماذج لإنشاء الجداول
    from models.employee import (Employee, Holiday, DeductionRule, LeaveType, LeaveRequest, 
                                  AttendanceRecord, Deduction, employee_managers, OvertimeRequest, 
                                  Task, EmployeeRating, Notification)
    from models.timesheet_session import Project, ProjectJob, TimesheetSession, TimesheetBreak
    from datetime import date

    # إنشاء الجداول إذا لم تكن موجودة
    db.create_all()

    # إضافة مدير افتراضي
    admin_user = Employee.query.filter_by(user_id='admin').first()
    if not admin_user:
        admin_user = Employee(
            user_id='admin',
            name='المدير العام',
            password='admin',
            is_admin=True,
            role='admin',
            position='مدير عام',
            department='الإدارة العامة',
            email='admin@afco-steel.com'
        )
        db.session.add(admin_user)
        db.session.commit()

    # إضافة موظف افتراضي
    emp = Employee.query.filter_by(user_id='employee').first()
    if not emp:
        emp = Employee(
            user_id='employee',
            name='موظف تجريبي',
            password='employee',
            is_admin=False,
            role='موظف',
            position='مهندس',
            department='الهندسة',
            annual_leave_balance=14,
            sick_leave_balance=7,
            casual_leave_balance=7
        )
        db.session.add(emp)
        db.session.commit()

    # إضافة مشروع داخلي افتراضي
    internal_project = Project.query.filter_by(project_number='INTERNAL').first()
    if not internal_project:
        internal_project = Project(
            project_number='INTERNAL',
            project_name='مهام داخلية / عامة',
            description='مشروع افتراضي للمهام التي لا ترتبط بمشروع معين مثل IDLE, TRAINING, etc.',
            is_active=True
        )
        db.session.add(internal_project)
        db.session.commit()

    # إضافة الأعياد الافتراضية
    holidays_data = [
        (date(2026, 1, 7), "عيد الميلاد المجيد"),
        (date(2026, 1, 25), "ثورة ٢٥ يناير وعيد الشرطة"),
        (date(2026, 4, 21), "عيد شم النسيم"),
        (date(2026, 4, 25), "عيد تحرير سيناء"),
        (date(2026, 5, 1), "عيد العمال"),
        (date(2026, 7, 3), "ثورة ٣٠ يونيو"),
        (date(2026, 7, 24), "ثورة ٢٣ يوليو"),
        (date(2026, 10, 6), "عيد القوات المسلحة")
    ]

    for holiday_date, holiday_name in holidays_data:
        existing_holiday = Holiday.query.filter_by(date=holiday_date).first()
        if not existing_holiday:
            holiday = Holiday(date=holiday_date, name=holiday_name)
            db.session.add(holiday)

    db.session.commit()


@app.route('/api/logout', methods=['POST', 'GET'])
def logout():
    """تسجيل الخروج"""
    session.clear()
    return jsonify({"success": True, "message": "تم تسجيل الخروج بنجاح"})


@app.route('/api/me', methods=['GET'])
def get_me():
    """بيانات المستخدم الحالي"""
    if 'user_id' not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401
    from models.employee import Employee
    user = Employee.query.filter_by(user_id=session['user_id']).first()
    if not user:
        return jsonify({"error": "المستخدم غير موجود"}), 404
    return jsonify({
        "id": user.id,
        "user_id": user.user_id,
        "name": user.name,
        "role": user.role,
        "is_admin": user.is_admin,
        "department": user.department or '',
        "position": user.position or '',
        "email": user.email or ''
    })


@app.route('/admin')
def admin_page():
    """صفحة الأدمن - تتحقق من الصلاحيات"""
    if "user_id" not in session:
        return redirect(url_for("login_page"))

    from models.employee import Employee
    current_user = Employee.query.filter_by(user_id=session["user_id"]).first()
    if not current_user:
        return redirect(url_for("index"))
    # السماح لـ admin, hr, planning, manager
    allowed_roles = ['admin', 'hr', 'planning', 'manager']
    if not current_user.is_admin and current_user.role not in allowed_roles:
        return redirect(url_for("index"))

    return send_from_directory(app.static_folder, 'admin.html')


@app.route("/")
def index():
    """الصفحة الرئيسية"""
    # إذا لم يكن هناك جلسة، توجه لصفحة تسجيل الدخول
    if "user_id" not in session:
        return redirect(url_for("login_page"))
    
    # السماح للمديرين والأدمن بالوصول لصفحة التيم شيت (index.html) إذا طلبوا المسار الرئيسي
    # وإذا أرادوا الذهاب للوحة الإدارة يمكنهم ذلك عبر رابط مباشر أو زر في الواجهة
    return send_from_directory(app.static_folder, "index.html")


@app.route("/login")
def login_page():
    """صفحة تسجيل الدخول"""
    # إذا كان مسجل دخول بالفعل، وجهه للصفحة المناسبة
    if "user_id" in session:
        return redirect(url_for("index"))
    return send_from_directory(app.static_folder, "login.html")


@app.route("/<path:path>")
def serve_static(path):
    """خدمة الملفات الثابتة"""
    if path == "login.html":
        return send_from_directory(app.static_folder, "login.html")
    if "user_id" not in session:
        return redirect(url_for("index"))
    return send_from_directory(app.static_folder, path)

# ✅ تشغيل محلي فقط
if __name__ == "__main__":
    app.run(debug=True)