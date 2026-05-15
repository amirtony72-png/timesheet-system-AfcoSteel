"""
=============================================================
سكريبت ترحيل قاعدة البيانات - نظام الحضور والانصراف
=============================================================
الغرض: ترحيل البيانات من قاعدة بيانات قديمة إلى الجديدة مع الحفاظ على البيانات الموجودة.

الاستخدام:
    python3 migrate_db.py [--old-db PATH] [--new-db PATH] [--backup]

الخيارات:
    --old-db PATH   مسار قاعدة البيانات القديمة (افتراضي: instance/attendance.db)
    --new-db PATH   مسار قاعدة البيانات الجديدة (افتراضي: نفس المسار القديم)
    --backup        إنشاء نسخة احتياطية قبل الترحيل (موصى به)
    --dry-run       تشغيل تجريبي بدون حفظ التغييرات

مثال:
    python3 migrate_db.py --backup
    python3 migrate_db.py --old-db old_attendance.db --new-db instance/attendance.db --backup

=============================================================
"""

import os
import sys
import shutil
import sqlite3
import argparse
from datetime import datetime

# ─── إعداد المسارات ───────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, 'instance', 'attendance.db')

def log(msg, level='INFO'):
    """طباعة رسالة مع الوقت والمستوى"""
    ts = datetime.now().strftime('%H:%M:%S')
    prefix = {'INFO': '✓', 'WARN': '⚠', 'ERROR': '✗', 'STEP': '→'}.get(level, '•')
    print(f"[{ts}] {prefix} {msg}")


def backup_database(db_path):
    """إنشاء نسخة احتياطية من قاعدة البيانات"""
    if not os.path.exists(db_path):
        log(f"قاعدة البيانات غير موجودة: {db_path}", 'WARN')
        return None
    
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = db_path + f'.backup_{ts}'
    shutil.copy2(db_path, backup_path)
    log(f"تم إنشاء نسخة احتياطية: {backup_path}")
    return backup_path


def get_existing_columns(conn, table_name):
    """جلب أسماء الأعمدة الموجودة في جدول معين"""
    cursor = conn.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}


def get_existing_tables(conn):
    """جلب أسماء الجداول الموجودة في قاعدة البيانات"""
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {row[0] for row in cursor.fetchall()}


def add_column_if_missing(conn, table, column, col_type, default=None):
    """إضافة عمود إذا لم يكن موجوداً"""
    existing = get_existing_columns(conn, table)
    if column not in existing:
        if default is not None:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type} DEFAULT {default}")
        else:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        log(f"  تم إضافة عمود '{column}' إلى جدول '{table}'")
        return True
    return False


def migrate_employees_table(conn, dry_run=False):
    """
    ترحيل جدول الموظفين:
    - إضافة عمود role إذا لم يكن موجوداً
    - إضافة عمود email إذا لم يكن موجوداً
    - إضافة عمود overtime_limit إذا لم يكن موجوداً
    - إضافة أعمدة رصيد الإجازات
    """
    log("ترحيل جدول الموظفين (employees)...", 'STEP')
    tables = get_existing_tables(conn)
    
    if 'employees' not in tables:
        log("جدول employees غير موجود - سيتم إنشاؤه تلقائياً عند تشغيل التطبيق", 'WARN')
        return
    
    changes = []
    
    # إضافة الأعمدة المفقودة
    new_columns = [
        ('role', 'VARCHAR(50)', "'employee'"),
        ('email', 'VARCHAR(255)', 'NULL'),
        ('overtime_limit', 'INTEGER', 'NULL'),
        ('annual_leave_balance', 'INTEGER', '30'),
        ('sick_leave_balance', 'INTEGER', '15'),
        ('casual_leave_balance', 'INTEGER', '7'),
        ('annual_leave_used', 'FLOAT', '0'),
        ('sick_leave_used', 'FLOAT', '0'),
        ('casual_leave_used', 'FLOAT', '0'),
    ]
    
    for col, col_type, default in new_columns:
        if not dry_run:
            added = add_column_if_missing(conn, 'employees', col, col_type, default)
            if added:
                changes.append(col)
        else:
            existing = get_existing_columns(conn, 'employees')
            if col not in existing:
                log(f"  [DRY RUN] سيتم إضافة عمود '{col}' إلى جدول 'employees'")
                changes.append(col)
    
    # تحديث role بناءً على is_admin إذا كان role فارغاً
    if not dry_run and 'role' in changes:
        conn.execute("""
            UPDATE employees 
            SET role = CASE 
                WHEN is_admin = 1 THEN 'admin' 
                ELSE 'employee' 
            END
            WHERE role IS NULL OR role = ''
        """)
        log("  تم تحديث قيم role بناءً على is_admin")
    
    if changes:
        log(f"  تم إضافة {len(changes)} عمود(أعمدة) جديدة: {', '.join(changes)}")
    else:
        log("  جدول employees محدث بالفعل")


def migrate_timesheet_sessions_table(conn, dry_run=False):
    """
    ترحيل جدول جلسات الـ Timesheet:
    - إضافة أعمدة Overtime approval إذا لم تكن موجودة
    - إضافة عمود project_status إذا لم يكن موجوداً
    """
    log("ترحيل جدول جلسات المهام (timesheet_sessions)...", 'STEP')
    tables = get_existing_tables(conn)
    
    if 'timesheet_sessions' not in tables:
        log("جدول timesheet_sessions غير موجود - سيتم إنشاؤه تلقائياً", 'WARN')
        return
    
    new_columns = [
        ('overtime_approval_status', 'VARCHAR(20)', "'pending'"),
        ('overtime_approved_by', 'INTEGER', 'NULL'),
        ('overtime_approved_at', 'DATETIME', 'NULL'),
        ('overtime_rejection_note', 'VARCHAR(255)', 'NULL'),
        ('project_status', 'VARCHAR(50)', 'NULL'),
        ('paused_at', 'DATETIME', 'NULL'),
        ('is_billable', 'BOOLEAN', '1'),
        ('notes', 'TEXT', 'NULL'),
        ('start_latitude', 'FLOAT', 'NULL'),
        ('start_longitude', 'FLOAT', 'NULL'),
        ('start_location_name', 'VARCHAR(200)', 'NULL'),
        ('end_latitude', 'FLOAT', 'NULL'),
        ('end_longitude', 'FLOAT', 'NULL'),
    ]
    
    changes = []
    for col, col_type, default in new_columns:
        if not dry_run:
            added = add_column_if_missing(conn, 'timesheet_sessions', col, col_type, default)
            if added:
                changes.append(col)
        else:
            existing = get_existing_columns(conn, 'timesheet_sessions')
            if col not in existing:
                log(f"  [DRY RUN] سيتم إضافة عمود '{col}' إلى جدول 'timesheet_sessions'")
                changes.append(col)
    
    if changes:
        log(f"  تم إضافة {len(changes)} عمود(أعمدة) جديدة: {', '.join(changes)}")
    else:
        log("  جدول timesheet_sessions محدث بالفعل")


def migrate_leave_requests_table(conn, dry_run=False):
    """
    ترحيل جدول طلبات الإجازات:
    - إضافة عمود is_half_day إذا لم يكن موجوداً
    - إضافة عمود attachment_path إذا لم يكن موجوداً
    """
    log("ترحيل جدول طلبات الإجازات (leave_requests)...", 'STEP')
    tables = get_existing_tables(conn)
    
    if 'leave_requests' not in tables:
        log("جدول leave_requests غير موجود - سيتم إنشاؤه تلقائياً", 'WARN')
        return
    
    new_columns = [
        ('is_half_day', 'BOOLEAN', '0'),
        ('attachment_path', 'VARCHAR(500)', 'NULL'),
        ('approved_by', 'INTEGER', 'NULL'),
        ('approved_at', 'DATETIME', 'NULL'),
        ('rejection_note', 'VARCHAR(500)', 'NULL'),
    ]
    
    changes = []
    for col, col_type, default in new_columns:
        if not dry_run:
            added = add_column_if_missing(conn, 'leave_requests', col, col_type, default)
            if added:
                changes.append(col)
        else:
            existing = get_existing_columns(conn, 'leave_requests')
            if col not in existing:
                log(f"  [DRY RUN] سيتم إضافة عمود '{col}' إلى جدول 'leave_requests'")
                changes.append(col)
    
    if changes:
        log(f"  تم إضافة {len(changes)} عمود(أعمدة) جديدة: {', '.join(changes)}")
    else:
        log("  جدول leave_requests محدث بالفعل")


def create_missing_tables(conn, dry_run=False):
    """
    إنشاء الجداول الجديدة إذا لم تكن موجودة:
    - employee_managers (جدول ربط المديرين)
    - timesheet_breaks (فترات الراحة)
    - overtime_requests (طلبات الوقت الإضافي)
    - tasks (المهام)
    - employee_ratings (التقييمات)
    - notifications (الإشعارات)
    - projects (المشاريع)
    - project_jobs (أرقام الوظائف)
    """
    log("إنشاء الجداول المفقودة...", 'STEP')
    tables = get_existing_tables(conn)
    
    # جدول ربط الموظفين بالمديرين
    if 'employee_managers' not in tables:
        if not dry_run:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS employee_managers (
                    employee_id INTEGER NOT NULL,
                    manager_id INTEGER NOT NULL,
                    PRIMARY KEY (employee_id, manager_id),
                    FOREIGN KEY (employee_id) REFERENCES employees(id),
                    FOREIGN KEY (manager_id) REFERENCES employees(id)
                )
            """)
            log("  تم إنشاء جدول employee_managers")
        else:
            log("  [DRY RUN] سيتم إنشاء جدول employee_managers")
    
    # جدول فترات الراحة
    if 'timesheet_breaks' not in tables:
        if not dry_run:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS timesheet_breaks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    employee_id INTEGER,
                    break_type VARCHAR(50) NOT NULL,
                    start_time DATETIME NOT NULL,
                    end_time DATETIME,
                    duration_minutes INTEGER DEFAULT 0,
                    reason TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES timesheet_sessions(id),
                    FOREIGN KEY (employee_id) REFERENCES employees(id)
                )
            """)
            log("  تم إنشاء جدول timesheet_breaks")
        else:
            log("  [DRY RUN] سيتم إنشاء جدول timesheet_breaks")
    
    # جدول طلبات الوقت الإضافي
    if 'overtime_requests' not in tables:
        if not dry_run:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS overtime_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id INTEGER NOT NULL,
                    request_date DATE NOT NULL,
                    reason TEXT,
                    status VARCHAR(20) DEFAULT 'pending',
                    approved_by INTEGER,
                    approved_at DATETIME,
                    rejection_note VARCHAR(500),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (employee_id) REFERENCES employees(id),
                    FOREIGN KEY (approved_by) REFERENCES employees(id)
                )
            """)
            log("  تم إنشاء جدول overtime_requests")
        else:
            log("  [DRY RUN] سيتم إنشاء جدول overtime_requests")
    
    # جدول المهام
    if 'tasks' not in tables:
        if not dry_run:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title VARCHAR(255) NOT NULL,
                    description TEXT,
                    assigned_to INTEGER NOT NULL,
                    assigned_by INTEGER NOT NULL,
                    project_id INTEGER,
                    due_date DATE,
                    priority VARCHAR(20) DEFAULT 'medium',
                    status VARCHAR(20) DEFAULT 'new',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (assigned_to) REFERENCES employees(id),
                    FOREIGN KEY (assigned_by) REFERENCES employees(id)
                )
            """)
            log("  تم إنشاء جدول tasks")
        else:
            log("  [DRY RUN] سيتم إنشاء جدول tasks")
    
    # جدول التقييمات
    if 'employee_ratings' not in tables:
        if not dry_run:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS employee_ratings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id INTEGER NOT NULL,
                    rated_by INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    year INTEGER NOT NULL,
                    rating INTEGER NOT NULL,
                    performance_notes TEXT,
                    strengths TEXT,
                    improvements TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (employee_id) REFERENCES employees(id),
                    FOREIGN KEY (rated_by) REFERENCES employees(id)
                )
            """)
            log("  تم إنشاء جدول employee_ratings")
        else:
            log("  [DRY RUN] سيتم إنشاء جدول employee_ratings")
    
    # جدول الإشعارات
    if 'notifications' not in tables:
        if not dry_run:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    notification_type VARCHAR(50),
                    is_read BOOLEAN DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (employee_id) REFERENCES employees(id)
                )
            """)
            log("  تم إنشاء جدول notifications")
        else:
            log("  [DRY RUN] سيتم إنشاء جدول notifications")
    
    # جدول المشاريع
    if 'projects' not in tables:
        if not dry_run:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_number VARCHAR(50) UNIQUE NOT NULL,
                    project_name VARCHAR(255) NOT NULL,
                    description TEXT,
                    status VARCHAR(50) DEFAULT 'Active',
                    is_active BOOLEAN DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # إضافة مشروع داخلي افتراضي
            conn.execute("""
                INSERT OR IGNORE INTO projects (project_number, project_name, description, is_active)
                VALUES ('INTERNAL', 'مهام داخلية / عامة', 'مشروع افتراضي للمهام العامة', 1)
            """)
            log("  تم إنشاء جدول projects مع مشروع INTERNAL الافتراضي")
        else:
            log("  [DRY RUN] سيتم إنشاء جدول projects")
    
    # جدول أرقام الوظائف
    if 'project_jobs' not in tables:
        if not dry_run:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS project_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    job_number VARCHAR(100) NOT NULL,
                    description VARCHAR(255),
                    is_active BOOLEAN DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                )
            """)
            log("  تم إنشاء جدول project_jobs")
        else:
            log("  [DRY RUN] سيتم إنشاء جدول project_jobs")


def create_v76_tables(conn, dry_run=False):
    """
    Create v76 new tables: audit_logs, activity_feed, monthly_goals
    """
    log("Creating v76 tables (audit_logs, activity_feed, monthly_goals)...", 'STEP')
    tables = get_existing_tables(conn)
    
    if 'audit_logs' not in tables:
        if not dry_run:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id INTEGER,
                    action VARCHAR(100) NOT NULL,
                    entity_type VARCHAR(50),
                    entity_id INTEGER,
                    description TEXT,
                    ip_address VARCHAR(50),
                    user_agent TEXT,
                    old_values TEXT,
                    new_values TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (employee_id) REFERENCES employees(id)
                )
            """)
            log("  Created audit_logs table")
        else:
            log("  [DRY RUN] Will create audit_logs table")
    
    if 'activity_feed' not in tables:
        if not dry_run:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS activity_feed (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id INTEGER NOT NULL,
                    activity_type VARCHAR(50) NOT NULL,
                    description TEXT,
                    project_id INTEGER,
                    session_id INTEGER,
                    metadata TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (employee_id) REFERENCES employees(id)
                )
            """)
            log("  Created activity_feed table")
        else:
            log("  [DRY RUN] Will create activity_feed table")
    
    if 'monthly_goals' not in tables:
        if not dry_run:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS monthly_goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    year INTEGER NOT NULL,
                    target_hours FLOAT DEFAULT 176,
                    billable_target FLOAT,
                    notes TEXT,
                    created_by INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (employee_id) REFERENCES employees(id)
                )
            """)
            log("  Created monthly_goals table")
        else:
            log("  [DRY RUN] Will create monthly_goals table")


def migrate_timesheet_breaks_table(conn, dry_run=False):
    """Add employee_id column to timesheet_breaks if missing"""
    log("Migrating timesheet_breaks table...", 'STEP')
    tables = get_existing_tables(conn)
    if 'timesheet_breaks' not in tables:
        log("  timesheet_breaks table not found - will be created automatically")
        return
    
    changes = []
    new_columns = [
        ('employee_id', 'INTEGER', 'NULL'),
    ]
    for col, col_type, default in new_columns:
        if not dry_run:
            added = add_column_if_missing(conn, 'timesheet_breaks', col, col_type, default)
            if added:
                changes.append(col)
        else:
            existing = get_existing_columns(conn, 'timesheet_breaks')
            if col not in existing:
                log(f"  [DRY RUN] Will add column '{col}' to 'timesheet_breaks'")
                changes.append(col)
    
    if changes:
        log(f"  Added {len(changes)} new column(s): {', '.join(changes)}")
    else:
        log("  timesheet_breaks table is up to date")


def migrate_fingerprint_records(conn, dry_run=False):
    """
    ترحيل جدول سجلات البصمة إذا كان موجوداً بهيكل قديم
    """
    log("فحص جدول سجلات البصمة (fingerprint_records)...", 'STEP')
    tables = get_existing_tables(conn)
    
    if 'fingerprint_records' not in tables:
        log("  جدول fingerprint_records غير موجود - لا يحتاج ترحيل")
        return
    
    new_columns = [
        ('punch_label', 'VARCHAR(50)', 'NULL'),
        ('synced_at', 'DATETIME', 'NULL'),
    ]
    
    changes = []
    for col, col_type, default in new_columns:
        if not dry_run:
            added = add_column_if_missing(conn, 'fingerprint_records', col, col_type, default)
            if added:
                changes.append(col)
    
    if changes:
        log(f"  تم إضافة {len(changes)} عمود(أعمدة) جديدة: {', '.join(changes)}")
    else:
        log("  جدول fingerprint_records محدث بالفعل")


def print_summary(conn):
    """طباعة ملخص قاعدة البيانات بعد الترحيل"""
    log("\n" + "="*50)
    log("ملخص قاعدة البيانات بعد الترحيل:")
    log("="*50)
    
    tables = get_existing_tables(conn)
    for table in sorted(tables):
        cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        cols = get_existing_columns(conn, table)
        log(f"  {table}: {count} سجل، {len(cols)} عمود")


def run_migration(db_path, dry_run=False, backup=True):
    """
    تشغيل عملية الترحيل الكاملة
    
    الخطوات:
    1. إنشاء نسخة احتياطية (اختياري)
    2. فتح اتصال بقاعدة البيانات
    3. ترحيل كل جدول
    4. إنشاء الجداول المفقودة
    5. حفظ التغييرات
    """
    log("="*60)
    log("بدء عملية ترحيل قاعدة البيانات")
    log(f"قاعدة البيانات: {db_path}")
    if dry_run:
        log("وضع التجريب (DRY RUN) - لن يتم حفظ أي تغييرات", 'WARN')
    log("="*60)
    
    # التحقق من وجود قاعدة البيانات
    if not os.path.exists(db_path):
        log(f"قاعدة البيانات غير موجودة: {db_path}", 'WARN')
        log("سيتم إنشاء قاعدة بيانات جديدة عند تشغيل التطبيق")
        return True
    
    # إنشاء نسخة احتياطية
    if backup and not dry_run:
        backup_path = backup_database(db_path)
        if backup_path:
            log(f"النسخة الاحتياطية محفوظة في: {backup_path}")
    
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = OFF")  # تعطيل مؤقت للمفاتيح الأجنبية أثناء الترحيل
        
        # تشغيل خطوات الترحيل
        migrate_employees_table(conn, dry_run)
        migrate_timesheet_sessions_table(conn, dry_run)
        migrate_leave_requests_table(conn, dry_run)
        create_missing_tables(conn, dry_run)
        migrate_timesheet_breaks_table(conn, dry_run)
        migrate_fingerprint_records(conn, dry_run)
        create_v76_tables(conn, dry_run)
        
        if not dry_run:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.commit()
            log("\n✅ تم الترحيل بنجاح وحفظ جميع التغييرات")
        else:
            log("\n✅ انتهى الفحص التجريبي - لم يتم حفظ أي تغييرات")
        
        # طباعة ملخص
        print_summary(conn)
        conn.close()
        return True
        
    except Exception as e:
        log(f"خطأ أثناء الترحيل: {e}", 'ERROR')
        import traceback
        traceback.print_exc()
        return False


def main():
    """نقطة الدخول الرئيسية"""
    parser = argparse.ArgumentParser(
        description='سكريبت ترحيل قاعدة بيانات نظام الحضور والانصراف',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
أمثلة:
  python3 migrate_db.py                          # ترحيل مع نسخة احتياطية تلقائية
  python3 migrate_db.py --dry-run                # فحص تجريبي بدون تغييرات
  python3 migrate_db.py --no-backup              # ترحيل بدون نسخة احتياطية
  python3 migrate_db.py --old-db /path/to/old.db # ترحيل من مسار محدد
        """
    )
    parser.add_argument('--old-db', default=DEFAULT_DB_PATH, help='مسار قاعدة البيانات')
    parser.add_argument('--backup', action='store_true', default=True, help='إنشاء نسخة احتياطية (افتراضي: نعم)')
    parser.add_argument('--no-backup', action='store_true', help='تخطي النسخة الاحتياطية')
    parser.add_argument('--dry-run', action='store_true', help='تشغيل تجريبي بدون تغييرات')
    
    args = parser.parse_args()
    
    do_backup = args.backup and not args.no_backup
    
    success = run_migration(
        db_path=args.old_db,
        dry_run=args.dry_run,
        backup=do_backup
    )
    
    if success:
        log("\n🎉 اكتملت عملية الترحيل بنجاح!")
        log("يمكنك الآن تشغيل التطبيق: python3 main.py")
    else:
        log("\n❌ فشلت عملية الترحيل - راجع الأخطاء أعلاه", 'ERROR')
        sys.exit(1)


if __name__ == '__main__':
    main()
