import os
import sys

from flask import Flask, send_from_directory, session, redirect, url_for, jsonify
from flask_cors import CORS
from models.database import db

# =========================
# ✅ APP
# =========================
app = Flask(__name__, static_folder=os.path.join(os.path.dirname(__file__), 'static'))

# =========================
# ✅ SETTINGS
# =========================
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = 86400
app.config["SESSION_COOKIE_NAME"] = "attendance_sid"
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False

# =========================
# =========================
# ✅ DATABASE (Force SQLite)
# =========================

base_dir = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(base_dir, "instance"), exist_ok=True)

sqlite_path = os.path.join(base_dir, "instance", "attendance.db")

app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{sqlite_path}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

print("✅ Using SQLite (Render TEST MODE)")

db.init_app(app)

with app.app_context():
    db.create_all()
# =========================
# ✅ CORS
# =========================
CORS(app, supports_credentials=True)

# =========================
# ✅ SESSION HANDLER
# =========================
@app.before_request
def before_request():
    session.permanent = True

# =========================
# ✅ BLUEPRINTS
# =========================
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

# =========================
# ✅ FILES
# =========================
uploads_dir = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(uploads_dir, exist_ok=True)

@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    return send_from_directory(uploads_dir, filename)

# =========================
# ✅ ROUTES
# =========================
@app.route("/")
def index():
    if "user_id" not in session:
        return redirect(url_for("login_page"))
    return send_from_directory(app.static_folder, "index.html")
@app.route("/")
def index():
    if "user_id" not in session:
        return redirect(url_for("login_page"))
    return send_from_directory(app.static_folder, "index.html")


# ✅ هنا بالظبط
@app.route("/admin")
def admin_page():
    if "user_id" not in session:
        return redirect(url_for("login_page"))

    from models.employee import Employee
    user = Employee.query.filter_by(user_id=session["user_id"]).first()

    if not user or not user.is_admin:
        return redirect(url_for("index"))

    return send_from_directory(app.static_folder, "admin.html")

@app.route("/login")
def login_page():
    if "user_id" in session:
        return redirect(url_for("index"))
    return send_from_directory(app.static_folder, "login.html")

@app.route('/api/logout', methods=['POST', 'GET'])
def logout():
    session.clear()
    return jsonify({"success": True})

@app.route('/api/me', methods=['GET'])
def get_me():
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401

    from models.employee import Employee
    user = Employee.query.filter_by(user_id=session['user_id']).first()

    if not user:
        return jsonify({"error": "User not found"}), 404

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

# =========================
# ✅ RUN LOCAL + NETWORK
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)