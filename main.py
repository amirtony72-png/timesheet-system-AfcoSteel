from flask import Flask, send_from_directory, session, redirect, url_for, jsonify
from flask_cors import CORS
from models.database import db
import os
import sys

# =========================
# ✅ APP
# =========================
app = Flask(__name__, static_folder=os.path.join(os.path.dirname(__file__), 'static'))

# =========================
# ✅ SETTINGS
# =========================
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "super-secret-key")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = 86400
app.config["SESSION_COOKIE_NAME"] = "attendance_sid"
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False

# =========================
# ✅ DATABASE
# =========================
db_url = os.environ.get("DATABASE_URL")

print("DATABASE_URL:", db_url)

if not db_url:
    raise Exception("DATABASE_URL is missing ❌")

if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# =========================
# ✅ CORS
# =========================
CORS(app, supports_credentials=True)

# =========================
# ✅ PATH FIX
# =========================
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

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
# ✅ BASIC ROUTES
# =========================
@app.route("/")
def index():
    if "user_id" not in session:
        return redirect(url_for("login_page"))
    return send_from_directory(app.static_folder, "index.html")

@app.route("/login")
def login_page():
    if "user_id" in session:
        return redirect(url_for("index"))
    return send_from_directory(app.static_folder, "login.html")

@app.route('/api/logout', methods=['POST', 'GET'])
def logout():
    session.clear()
    return jsonify({"success": True})

# =========================
# ✅ RUN LOCAL
# =========================
if __name__ == "__main__":
    app.run(debug=True)
