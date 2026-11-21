import os
import sqlite3
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-key-before-deployment")
DATABASE = os.path.join(app.root_path, "skillswap.db")

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = sqlite3.connect(DATABASE)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            reg_no TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            department TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            teach_skills TEXT NOT NULL DEFAULT '',
            learn_skills TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(sender_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY(receiver_id) REFERENCES students(id) ON DELETE CASCADE,
            UNIQUE(sender_id, receiver_id)
        );
    """)
    db.commit()
    db.close()

def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if "student_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(**kwargs)
    return wrapped_view

@app.route("/")
def index():
    if "student_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        reg_no = request.form.get("reg_no", "").strip()
        email = request.form.get("email", "").strip().lower()
        department = request.form.get("department", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not all([name, reg_no, email, department, password, confirm_password]):
            flash("Please fill in every field.", "error")
        elif len(password) < 8:
            flash("Password must contain at least 8 characters.", "error")
        elif password != confirm_password:
            flash("Passwords do not match.", "error")
        else:
            db = get_db()
            try:
                db.execute(
                    "INSERT INTO students (name, reg_no, email, department, password_hash) VALUES (?, ?, ?, ?, ?)",
                    (name, reg_no, email, department, generate_password_hash(password))
                )
                db.commit()
                flash("Account created successfully. Please log in.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("That registration number or email is already registered.", "error")

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        reg_no = request.form.get("reg_no", "").strip()
        password = request.form.get("password", "")
        student = get_db().execute(
            "SELECT * FROM students WHERE reg_no = ?", (reg_no,)
        ).fetchone()

        if student and check_password_hash(student["password_hash"], password):
            session.clear()
            session["student_id"] = student["id"]
            session["student_name"] = student["name"]
            return redirect(url_for("dashboard"))

        flash("Invalid registration number or password.", "error")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    student = db.execute(
        "SELECT * FROM students WHERE id = ?", (session["student_id"],)
    ).fetchone()
    sent_count = db.execute(
        "SELECT COUNT(*) FROM requests WHERE sender_id = ?", (student["id"],)
    ).fetchone()[0]
    received_count = db.execute(
        "SELECT COUNT(*) FROM requests WHERE receiver_id = ? AND status = 'Pending'",
        (student["id"],)
    ).fetchone()[0]
    student_count = db.execute(
        "SELECT COUNT(*) FROM students WHERE id != ?", (student["id"],)
    ).fetchone()[0]
    return render_template(
        "dashboard.html", student=student, sent_count=sent_count,
        received_count=received_count, student_count=student_count
    )

@app.route("/profile/update", methods=["POST"])
@login_required
def update_profile():
    teach = request.form.get("teach_skills", "").strip()
    learn = request.form.get("learn_skills", "").strip()
    get_db().execute(
        "UPDATE students SET teach_skills = ?, learn_skills = ? WHERE id = ?",
        (teach, learn, session["student_id"])
    )
    get_db().commit()
    flash("Your skills have been updated.", "success")
    return redirect(url_for("dashboard"))

@app.route("/students")
@login_required
def students():
    db = get_db()
    current_id = session["student_id"]
    search = request.args.get("q", "").strip()
    query = """
        SELECT id, name, reg_no, department, teach_skills, learn_skills
        FROM students WHERE id != ?
    """
    params = [current_id]
    if search:
        query += """ AND (name LIKE ? OR department LIKE ?
                    OR teach_skills LIKE ? OR learn_skills LIKE ?)"""
        term = f"%{search}%"
        params.extend([term, term, term, term])
    query += " ORDER BY name"
    student_list = db.execute(query, params).fetchall()
    return render_template("students.html", students=student_list, search=search)

@app.route("/request/<int:receiver_id>", methods=["POST"])
@login_required
def send_request(receiver_id):
    sender_id = session["student_id"]
    message = request.form.get("message", "").strip()[:500]
    if receiver_id == sender_id:
        flash("You cannot send a request to yourself.", "error")
    else:
        db = get_db()
        exists = db.execute(
            "SELECT id FROM students WHERE id = ?", (receiver_id,)
        ).fetchone()
        if not exists:
            flash("Student not found.", "error")
        else:
            try:
                db.execute(
                    "INSERT INTO requests (sender_id, receiver_id, message) VALUES (?, ?, ?)",
                    (sender_id, receiver_id, message)
                )
                db.commit()
                flash("Skill exchange request sent.", "success")
            except sqlite3.IntegrityError:
                flash("You have already sent this student a request.", "error")
    return redirect(url_for("students"))

@app.route("/requests")
@login_required
def requests_page():
    db = get_db()
    current_id = session["student_id"]
    received = db.execute("""
        SELECT r.*, s.name AS student_name, s.reg_no, s.department
        FROM requests r JOIN students s ON s.id = r.sender_id
        WHERE r.receiver_id = ? ORDER BY r.created_at DESC
    """, (current_id,)).fetchall()
    sent = db.execute("""
        SELECT r.*, s.name AS student_name, s.reg_no, s.department
        FROM requests r JOIN students s ON s.id = r.receiver_id
        WHERE r.sender_id = ? ORDER BY r.created_at DESC
    """, (current_id,)).fetchall()
    return render_template("requests.html", received=received, sent=sent)

@app.route("/request/<int:request_id>/<action>", methods=["POST"])
@login_required
def update_request(request_id, action):
    if action not in ["accept", "reject"]:
        flash("Invalid request action.", "error")
        return redirect(url_for("requests_page"))
    status = "Accepted" if action == "accept" else "Rejected"
    result = get_db().execute(
        "UPDATE requests SET status = ? WHERE id = ? AND receiver_id = ? AND status = 'Pending'",
        (status, request_id, session["student_id"])
    )
    get_db().commit()
    if result.rowcount:
        flash(f"Request {status.lower()}.", "success")
    else:
        flash("That request could not be updated.", "error")
    return redirect(url_for("requests_page"))

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
