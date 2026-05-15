# نظام الحضور والانصراف - v73

## نظرة عامة
نظام متكامل لإدارة حضور وانصراف الموظفين مع تتبع المشاريع والمهام.

## المتطلبات
- Python 3.11+
- Flask + SQLAlchemy
- المكتبات: انظر requirements.txt

## التثبيت والتشغيل

### 1. ترحيل قاعدة البيانات (للتحديث من نسخة سابقة)
```bash
python3 migrate_db.py --backup
```

### 2. تشغيل التطبيق
```bash
python3 main.py
```

### 3. الوصول للتطبيق
- صفحة الموظف: http://localhost:5000/
- صفحة الأدمن: http://localhost:5000/admin

## بيانات الدخول الافتراضية
| المستخدم | كلمة المرور | الدور |
|----------|-------------|-------|
| admin    | admin       | مدير عام |
| employee | employee    | موظف |

## المميزات الجديدة في v73

### 1. زر Break في صفحة الموظف
- زر "بريك" لتسجيل فترات الراحة
- عداد وقت مباشر أثناء البريك
- إمكانية تحديد سبب البريك
- عرض مدة البريك الحالي

### 2. فلتر القسم في سجل المهام (admin)
- فلتر جديد "كل الأقسام" في تبويب Timesheet
- يتم تحميل الأقسام تلقائياً من قاعدة البيانات

### 3. تبويب Break Log في صفحة الأدمن
- عرض جميع فترات الراحة لجميع الموظفين
- فلتر بالموظف والتاريخ
- إجمالي وقت الراحة
- إمكانية تعديل فترات الراحة

### 4. إصلاح Dashboard
- إصلاح عرض إحصائيات اليوم مع عمود القسم وحالة النشاط
- إصلاح رسوم بيانية الساعات (تحويل HH:MM إلى ساعات عشرية)

### 5. سكريبت الترحيل (migrate_db.py)
- ترحيل آمن من نسخ قاعدة البيانات القديمة
- إنشاء نسخة احتياطية تلقائية
- وضع تجريبي (dry-run) للفحص بدون تغييرات

## هيكل المشروع
```
user_project/
├── main.py                    # نقطة الدخول الرئيسية
├── migrate_db.py              # سكريبت الترحيل
├── models/
│   ├── database.py            # إعداد SQLAlchemy
│   ├── employee.py            # نماذج الموظفين والإجازات
│   └── timesheet_session.py   # نماذج المشاريع والجلسات
├── routes/
│   ├── user.py                # API المستخدم (تسجيل دخول، حضور)
│   ├── admin.py               # API الأدمن
│   ├── timesheet_advanced.py  # API المشاريع والجلسات والبريك
│   └── advanced_features.py   # API المميزات المتقدمة
├── static/
│   ├── index.html             # صفحة الموظف
│   ├── admin.html             # صفحة الأدمن
│   └── login.html             # صفحة تسجيل الدخول
└── instance/
    └── attendance.db          # قاعدة البيانات SQLite
```

## API Endpoints الرئيسية

### Timesheet
- `GET /api/timesheet/sessions` - جلب جلسات المهام
- `POST /api/timesheet/session/start` - بدء جلسة
- `POST /api/timesheet/session/end` - إنهاء جلسة
- `GET /api/timesheet/breaks` - جلب فترات الراحة
- `POST /api/timesheet/break/start` - بدء بريك
- `POST /api/timesheet/break/end` - إنهاء بريك
- `GET /api/timesheet/today-stats` - إحصائيات اليوم
- `GET /api/timesheet/project-totals` - إجمالي المشاريع

### Admin
- `GET /api/admin/employees` - قائمة الموظفين
- `GET /api/admin/dashboard/stats` - إحصائيات الداشبورد
- `PUT /api/admin/sessions/<id>` - تعديل جلسة
- `GET /api/departments` - قائمة الأقسام

