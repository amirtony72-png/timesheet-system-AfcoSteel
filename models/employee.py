from datetime import datetime, date, time
from models.database import db

# ─── جدول ربط المديرين بالموظفين (Many-to-Many) ─────────────────────────────
employee_managers = db.Table('employee_managers',
    db.Column('employee_id', db.Integer, db.ForeignKey('employees.id'), primary_key=True),
    db.Column('manager_id', db.Integer, db.ForeignKey('employees.id'), primary_key=True),
    db.Column('assigned_at', db.DateTime, default=datetime.utcnow)
)

class Employee(db.Model):
    __tablename__ = 'employees'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    password = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(255), nullable=True)  # إيميل الموظف (Outlook)
    
    # ─── نظام الأدوار الجديد ──────────────────────────────────────────────────
    # admin: أدمن رئيسي (يرى كل شيء)
    # hr: أدمن إجازات (HR)
    # planning: أدمن Overtime (Planning)
    # manager: مدير (يرى موظفيه فقط)
    # employee: موظف عادي
    is_admin = db.Column(db.Boolean, default=False, index=True)
    role = db.Column(db.String(50), default='employee', index=True)
    position = db.Column(db.String(100), index=True)
    department = db.Column(db.String(100), index=True)
    
    # ─── رصيد الإجازات ────────────────────────────────────────────────────────
    annual_leave_balance = db.Column(db.Integer, default=0)  # رصيد الإجازة السنوية
    sick_leave_balance = db.Column(db.Integer, default=0)    # رصيد الإجازة المرضية
    casual_leave_balance = db.Column(db.Integer, default=0)   # رصيد الإجازة العارضة
    marriage_leave_balance = db.Column(db.Integer, default=0) # رصيد إجازة زواج
    other_leave_balance = db.Column(db.Integer, default=0)    # رصيد إجازات أخرى
    deduction_leave_balance = db.Column(db.Float, default=0)  # رصيد إجازة بخصم
    
    # ─── حد Overtime ──────────────────────────────────────────────────────────
    overtime_limit = db.Column(db.Integer, nullable=True)  # حد Overtime الشهري (None = مفتوح)
    
    # ─── حقل قديم للتوافقية ───────────────────────────────────────────────────
    manager_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True, index=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    # ─── العلاقات ─────────────────────────────────────────────────────────────
    attendance_records = db.relationship('AttendanceRecord', backref='employee', lazy=True)
    leave_requests = db.relationship('LeaveRequest', foreign_keys='LeaveRequest.employee_id', backref='employee', lazy=True)
    deductions = db.relationship('Deduction', backref='employee', lazy=True)
    
    # علاقة المدير بالموظفين التابعين له (القديمة - للتوافقية)
    subordinates = db.relationship('Employee', backref=db.backref('manager', remote_side=[id]), lazy=True)
    
    # ─── المديرين المتعددين (Many-to-Many) ────────────────────────────────────
    managers = db.relationship(
        'Employee',
        secondary=employee_managers,
        primaryjoin=(id == employee_managers.c.employee_id),
        secondaryjoin=(id == employee_managers.c.manager_id),
        backref=db.backref('managed_employees', lazy='dynamic'),
        lazy='dynamic'
    )
    
    def get_managers_list(self):
        """إرجاع قائمة المديرين"""
        return self.managers.all()
    
    def get_managers_emails(self):
        """إرجاع إيميلات المديرين"""
        return [m.email for m in self.managers.all() if m.email]
    
    def is_manager_of(self, employee_id):
        """هل هذا الموظف مدير لموظف معين"""
        return self.managed_employees.filter(employee_managers.c.employee_id == employee_id).count() > 0
    
    def has_role(self, *roles):
        """التحقق من صلاحية الدور"""
        if self.is_admin or self.role == 'admin':
            return True
        return self.role in roles


class AttendanceRecord(db.Model):
    __tablename__ = 'attendance_records'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    check_in_time = db.Column(db.Time, index=True)
    check_out_time = db.Column(db.Time, index=True)
    work_hours = db.Column(db.String(10))
    overtime_hours = db.Column(db.String(10))
    late_minutes = db.Column(db.Integer, default=0, index=True)
    early_leave_minutes = db.Column(db.Integer, default=0, index=True)
    early_extra_minutes = db.Column(db.Integer, default=0)
    is_weekend = db.Column(db.Boolean, default=False, index=True)
    is_holiday = db.Column(db.Boolean, default=False, index=True)
    leave_type = db.Column(db.String(100), index=True)
    deduction_amount = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        db.Index('idx_employee_date', 'employee_id', 'date'),
        db.Index('idx_date_range', 'date', 'employee_id'),
    )

class LeaveType(db.Model):
    __tablename__ = 'leave_types'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    leave_requests = db.relationship('LeaveRequest', backref='leave_type', lazy=True)

class LeaveRequest(db.Model):
    __tablename__ = 'leave_requests'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False, index=True)
    leave_type_id = db.Column(db.Integer, db.ForeignKey('leave_types.id'), nullable=False)
    
    # ─── نوع الإجازة الجديد ───────────────────────────────────────────────────
    # annual: سنوية | sick: مرضية | casual: عارضة
    leave_category = db.Column(db.String(20), default='annual')
    
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    duration_days = db.Column(db.Float, default=1)  # عدد الأيام (0.5 لنصف يوم)
    reason = db.Column(db.Text)
    is_half_day = db.Column(db.Boolean, default=False)
    
    # ─── مرفقات (صورة منح الإجازة المرضية) ────────────────────────────────────
    attachment_path = db.Column(db.String(500), nullable=True)
    
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    approved_by = db.Column(db.Integer, db.ForeignKey('employees.id'))
    approved_by_name = db.Column(db.String(100))  # اسم من وافق
    rejection_note = db.Column(db.String(500))  # سبب الرفض
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    approved_by_employee = db.relationship('Employee', foreign_keys=[approved_by])


# ─── نظام طلب Overtime حسب اليوم ─────────────────────────────────────────────
class OvertimeRequest(db.Model):
    """طلب Overtime ليوم كامل — الموظف يقدمه والمدير يوافق"""
    __tablename__ = 'overtime_requests'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False, index=True)
    request_date = db.Column(db.Date, nullable=False, index=True)  # اليوم المطلوب فيه Overtime
    reason = db.Column(db.Text)  # سبب الطلب
    
    # الحالة: pending | approved | rejected
    status = db.Column(db.String(20), default='pending', index=True)
    approved_by = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True)
    approved_by_name = db.Column(db.String(100))
    approved_at = db.Column(db.DateTime, nullable=True)
    rejection_note = db.Column(db.String(500))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # العلاقات
    employee = db.relationship('Employee', foreign_keys=[employee_id], backref='overtime_requests')
    approved_by_employee = db.relationship('Employee', foreign_keys=[approved_by])


# ─── نظام المهام ──────────────────────────────────────────────────────────────
class Task(db.Model):
    """نموذج المهام — المدير يوزع مهام على موظفيه"""
    __tablename__ = 'tasks'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    
    assigned_to = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False, index=True)
    assigned_by = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=True)
    
    due_date = db.Column(db.Date, nullable=True)
    priority = db.Column(db.String(20), default='medium')  # low, medium, high, urgent
    
    # new, in_progress, completed, cancelled
    status = db.Column(db.String(20), default='new', index=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # العلاقات
    assignee = db.relationship('Employee', foreign_keys=[assigned_to], backref='assigned_tasks')
    assigner = db.relationship('Employee', foreign_keys=[assigned_by], backref='created_tasks')


# ─── نظام التقييم ─────────────────────────────────────────────────────────────
class EmployeeRating(db.Model):
    """تقييم شهري للموظف من المدير"""
    __tablename__ = 'employee_ratings'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False, index=True)
    rated_by = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    
    month = db.Column(db.Integer, nullable=False)  # 1-12
    year = db.Column(db.Integer, nullable=False)
    
    rating = db.Column(db.Integer, nullable=False)  # 1-5
    performance_notes = db.Column(db.Text)
    strengths = db.Column(db.Text)
    improvements = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    employee = db.relationship('Employee', foreign_keys=[employee_id], backref='ratings')
    rater = db.relationship('Employee', foreign_keys=[rated_by])


# ─── نظام الإشعارات ───────────────────────────────────────────────────────────
class Notification(db.Model):
    """إشعارات داخلية للموظفين"""
    __tablename__ = 'notifications'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False, index=True)
    
    title = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text, nullable=False)
    notification_type = db.Column(db.String(50))  # overtime, leave, task, rating, general
    
    is_read = db.Column(db.Boolean, default=False, index=True)
    is_sound = db.Column(db.Boolean, default=True)  # تشغيل صوت
    
    # رابط للعنصر المرتبط
    related_id = db.Column(db.Integer, nullable=True)
    related_type = db.Column(db.String(50), nullable=True)  # overtime_request, leave_request, task
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    employee_rel = db.relationship('Employee', backref='notifications')


class Holiday(db.Model):
    __tablename__ = 'holidays'
    
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Deduction(db.Model):
    __tablename__ = 'deductions'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    violation_count = db.Column(db.Integer, default=1)
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class DeductionRule(db.Model):
    __tablename__ = 'deduction_rules'
    
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)
    violation_1st = db.Column(db.Float, nullable=False)
    violation_2nd = db.Column(db.Float, nullable=False)
    violation_3rd = db.Column(db.Float, nullable=False)
    violation_4th = db.Column(db.Float, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ─── سجل التدقيق (Audit Log) ─────────────────────────────────────────────────
class AuditLog(db.Model):
    """
    Tracks every important action in the system.
    Who did what, when, and what changed.
    """
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True, index=True)
    employee_name = db.Column(db.String(100))  # Cached for fast display

    # Action details
    action = db.Column(db.String(100), nullable=False, index=True)
    # e.g.: session_start, session_end, break_start, break_end,
    #        leave_request, leave_approve, leave_reject,
    #        ot_request, ot_approve, ot_reject,
    #        employee_create, employee_edit, employee_delete,
    #        login, logout, settings_change
    entity_type = db.Column(db.String(50), index=True)  # session, break, leave, overtime, employee, settings
    entity_id = db.Column(db.Integer, nullable=True)

    # What changed (JSON string)
    old_value = db.Column(db.Text, nullable=True)  # JSON of old values
    new_value = db.Column(db.Text, nullable=True)  # JSON of new values
    description = db.Column(db.Text)  # Human-readable description

    # Context
    ip_address = db.Column(db.String(50), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    employee = db.relationship('Employee', backref='audit_logs')


# ─── بث النشاط المباشر (Activity Feed) ──────────────────────────────────────
class ActivityFeed(db.Model):
    """
    Real-time activity feed showing what employees are doing.
    Lightweight entries for dashboard display.
    """
    __tablename__ = 'activity_feed'

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False, index=True)
    employee_name = db.Column(db.String(100))  # Cached
    department = db.Column(db.String(100))  # Cached

    # Activity type
    activity_type = db.Column(db.String(50), nullable=False, index=True)
    # e.g.: session_start, session_end, break_start, break_end,
    #        check_in, check_out, leave_request, ot_request
    description = db.Column(db.String(500))  # e.g. "Started working on Project ABC"

    # Optional metadata
    project_name = db.Column(db.String(255), nullable=True)
    icon = db.Column(db.String(50), default='activity')  # CSS icon class

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    employee = db.relationship('Employee', backref='activities')


# ─── أهداف الساعات الشهرية (Monthly Goals) ───────────────────────────────────
class MonthlyGoal(db.Model):
    """
    Monthly hour targets per employee.
    Admin sets target, system tracks actual hours.
    """
    __tablename__ = 'monthly_goals'

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False, index=True)

    month = db.Column(db.Integer, nullable=False)  # 1-12
    year = db.Column(db.Integer, nullable=False)

    target_hours = db.Column(db.Float, nullable=False, default=176)  # Default: 22 days * 8h
    actual_hours = db.Column(db.Float, default=0)  # Updated periodically
    billable_hours = db.Column(db.Float, default=0)  # Hours on billable projects

    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    employee = db.relationship('Employee', backref='monthly_goals')

    __table_args__ = (
        db.UniqueConstraint('employee_id', 'month', 'year', name='uq_employee_month_year'),
    )
