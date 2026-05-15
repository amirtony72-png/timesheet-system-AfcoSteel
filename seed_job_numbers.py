"""
سكريبت لإضافة بيانات Job Numbers الافتراضية (Building: B00-B33)
يمكن تشغيله بعد إنشاء المشاريع لإضافة أرقام الوظائف
"""
from models.database import db
from models.timesheet_session import Project, ProjectJob
from main import app

def seed_building_job_numbers(project_id):
    """
    إضافة أرقام Building من B00 إلى B33 لمشروع معين
    
    Args:
        project_id: معرف المشروع الذي سيتم إضافة Job Numbers له
    """
    with app.app_context():
        # التحقق من وجود المشروع
        project = Project.query.get(project_id)
        if not project:
            print(f"خطأ: المشروع برقم {project_id} غير موجود")
            return
        
        print(f"إضافة Job Numbers للمشروع: {project.project_name}")
        
        # إضافة أرقام Building من B00 إلى B33
        added_count = 0
        for i in range(34):  # من 0 إلى 33
            job_number = f"B{i:02d}"  # تنسيق الرقم بحيث يكون B00, B01, ... B33
            
            # التحقق من عدم وجود الرقم مسبقاً
            existing = ProjectJob.query.filter_by(
                project_id=project_id,
                job_number=job_number
            ).first()
            
            if not existing:
                new_job = ProjectJob(
                    project_id=project_id,
                    job_number=job_number,
                    description=f"Building {job_number}"
                )
                db.session.add(new_job)
                added_count += 1
        
        db.session.commit()
        print(f"تم إضافة {added_count} رقم وظيفة بنجاح")

def seed_all_projects_with_buildings():
    """
    إضافة أرقام Building لجميع المشاريع الموجودة
    """
    with app.app_context():
        projects = Project.query.all()
        
        if not projects:
            print("لا توجد مشاريع في قاعدة البيانات")
            return
        
        print(f"تم العثور على {len(projects)} مشروع")
        
        for project in projects:
            print(f"\nمعالجة المشروع: {project.project_name} (ID: {project.id})")
            seed_building_job_numbers(project.id)

if __name__ == "__main__":
    print("=" * 50)
    print("سكريبت إضافة Job Numbers (Building: B00-B33)")
    print("=" * 50)
    
    # إضافة Job Numbers لجميع المشاريع
    seed_all_projects_with_buildings()
    
    print("\n" + "=" * 50)
    print("تم الانتهاء من إضافة البيانات")
    print("=" * 50)
