"""
ملف قاعدة البيانات - يحتوي على كائن SQLAlchemy المشترك
"""
from flask_sqlalchemy import SQLAlchemy

# كائن قاعدة البيانات المشترك بين جميع النماذج
db = SQLAlchemy()
