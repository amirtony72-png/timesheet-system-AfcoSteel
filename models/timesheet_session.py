"""
نموذج جلسات الـ Timesheet المتقدم
يدعم جلسات متعددة لكل موظف مع إمكانية الإيقاف والاستئناف
"""
from datetime import datetime
from models.database import db

class Project(db.Model):
    """نموذج المشاريع"""
    __tablename__ = 'projects'
    
    id = db.Column(db.Integer, primary_key=True)
    project_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    project_name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(50), default='Active')  # Active, Inactive, Completed
    is_active = db.Column(db.Boolean, default=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # العلاقات
    timesheet_sessions = db.relationship('TimesheetSession', backref='project', lazy=True, cascade='all, delete-orphan')
    jobs = db.relationship('ProjectJob', backref='project', lazy=True, cascade='all, delete-orphan')

class ProjectJob(db.Model):
    """نموذج أرقام الوظائف (Job Numbers) المرتبطة بكل مشروع"""
    __tablename__ = 'project_jobs'
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)
    job_number = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<ProjectJob {self.job_number}>'


class TimesheetSession(db.Model):
    """
    نموذج جلسات الـ Timesheet
    كل جلسة تمثل مهمة واحدة على مشروع معين
    يمكن أن تكون الجلسة قيد التنفيذ أو موقوفة أو مكتملة
    """
    __tablename__ = 'timesheet_sessions'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)  # تاريخ الجلسة
    
    # معلومات المهمة
    task_name = db.Column(db.String(255), nullable=False)
    hour_type = db.Column(db.String(100))  # WORK ORDER, IDLE, VACATION, etc.
    job_no = db.Column(db.String(100))     # B00 + project_number + B01 etc.
    project_status = db.Column(db.String(50)) # IFA, RIFA, IFC, RML, EVO, IVO, Other
    description = db.Column(db.Text)
    
    # أوقات الجلسة
    start_time = db.Column(db.DateTime, nullable=False)  # وقت البداية
    end_time = db.Column(db.DateTime, nullable=True)  # وقت النهاية (عند الانتهاء)
    
    # حالة الجلسة
    status = db.Column(db.String(50), default='running')  # running, paused, completed
    
    # الوقت المنقضي (بالثواني)
    elapsed_seconds = db.Column(db.Integer, default=0)  # الوقت الفعلي المنقضي
    paused_at = db.Column(db.DateTime, nullable=True)  # وقت الإيقاف
    
    # معلومات إضافية
    notes = db.Column(db.Text)
    is_billable = db.Column(db.Boolean, default=True)  # هل الجلسة قابلة للفواتير

    # ─── نظام موافقة الـ Overtime ───────────────────────────────────────────────
    # overtime_approval_status: pending (بانتظار الموافقة) | approved (موافق) | rejected (مرفوض)
    # يُستخدم فقط عندما يكون hour_type == 'OVERTIME'
    overtime_approval_status = db.Column(
        db.String(20),
        default='pending',
        nullable=True
    )
    # معرف المدير الذي وافق/رفض
    overtime_approved_by = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True)
    # وقت الموافقة/الرفض
    overtime_approved_at = db.Column(db.DateTime, nullable=True)
    # ملاحظة المدير عند الرفض
    overtime_rejection_note = db.Column(db.String(255), nullable=True)
    # ─────────────────────────────────────────────────────────────────────────────

    # ─── Geolocation ──────────────────────────────────────────────────────────
    start_latitude = db.Column(db.Float, nullable=True)   # Latitude at session start
    start_longitude = db.Column(db.Float, nullable=True)  # Longitude at session start
    start_location_name = db.Column(db.String(255), nullable=True)  # Reverse-geocoded name
    end_latitude = db.Column(db.Float, nullable=True)
    end_longitude = db.Column(db.Float, nullable=True)
    # ─────────────────────────────────────────────────────────────────────────────

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # العلاقات — يجب تحديد foreign_keys بشكل صريح لأن هناك مفتاحَين أجنبيَّين لـ employees
    employee = db.relationship('Employee', foreign_keys=[employee_id], backref='timesheet_sessions')
    approved_by_employee = db.relationship('Employee', foreign_keys=[overtime_approved_by])
    
    # فهارس مركبة للبحث السريع
    # __table_args__ = (
    #     db.Index('idx_employee_date', 'employee_id', 'date'),
    #     db.Index('idx_employee_status', 'employee_id', 'status'),
    #     db.Index('idx_project_date', 'project_id', 'date'),
    # )
    
    def __repr__(self):
        return f'<TimesheetSession {self.employee_id} - {self.task_name} - {self.status}>'
    
    def get_total_time(self):
        """حساب إجمالي الوقت المنقضي"""
        if self.status == 'completed' and self.end_time:
            return int((self.end_time - self.start_time).total_seconds())
        elif self.status == 'paused':
            return self.elapsed_seconds
        elif self.status == 'running':
            # حساب الوقت من البداية إلى الآن
            return int((datetime.utcnow() - self.start_time).total_seconds()) + self.elapsed_seconds
        return self.elapsed_seconds
    
    def get_formatted_time(self):
        """تنسيق الوقت بصيغة HH:MM:SS"""
        total_seconds = self.get_total_time()
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class TimesheetBreak(db.Model):
    """نموذج فترات الراحة والتوقف"""
    __tablename__ = 'timesheet_breaks'
    
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('timesheet_sessions.id'), nullable=True, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True, index=True)
    break_type = db.Column(db.String(50), nullable=False)  # break, downtime, maintenance
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=True)
    duration_minutes = db.Column(db.Integer, default=0)
    reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # العلاقات
    session = db.relationship('TimesheetSession', backref='breaks')
    
    def __repr__(self):
        return f'<TimesheetBreak {self.break_type} - {self.duration_minutes}min>'
