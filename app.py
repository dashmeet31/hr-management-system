from flask import Flask, render_template, request, redirect, session, send_file
from functools import wraps
import os
import pandas as pd
from datetime import datetime
import psycopg2
import psycopg2.extras
from psycopg2 import pool
from dotenv import load_dotenv
from flask import send_from_directory

load_dotenv()

# =========================
# APP CONFIG
# =========================
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret")

UPLOAD_FOLDER = "uploads/resumes"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL")

# =========================
# DB POOL
# =========================
db_pool = None

def init_db_pool():
    global db_pool
    if not db_pool:
        db_pool = pool.SimpleConnectionPool(
            minconn=1,
            maxconn=5,
            dsn=DATABASE_URL,
            sslmode="require"
        )

def get_db(dict_cursor=False):
    init_db_pool()
    conn = db_pool.getconn()
    if dict_cursor:
        return conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn, conn.cursor()

def release_db(conn, cur):
    cur.close()
    db_pool.putconn(conn)

# =========================
# LOGIN REQUIRED
# =========================
def login_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if not session.get("hr_logged_in"):
            return redirect("/")
        return f(*args, **kwargs)
    return wrap

# =========================
# AUTH
# =========================
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        conn, cur = get_db(True)
        cur.execute("SELECT * FROM admins WHERE email=%s", (email,))
        admin = cur.fetchone()
        release_db(conn, cur)

        if admin and admin["password"] == password:
            session.clear()
            session["hr_logged_in"] = True
            return redirect("/dashboard")

        return "Invalid Login", 401

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# =========================
# DASHBOARD
# =========================
@app.route("/dashboard")
@login_required
def dashboard():
    conn, cur = get_db(True)

    cur.execute("SELECT COUNT(*) AS total FROM jobs")
    total_jobs = cur.fetchone()["total"]

    cur.execute("SELECT COUNT(*) AS total FROM applications")
    total_applications = cur.fetchone()["total"]

    release_db(conn, cur)

    return render_template(
        "dashboard.html",
        total_jobs=total_jobs,
        total_applications=total_applications
    )

# =========================
# JOBS
# =========================
@app.route("/jobs", methods=["GET", "POST"])
@login_required
def jobs():
    conn, cur = get_db(True)

    if request.method == "POST":
        cur.execute("""
            INSERT INTO jobs (title, description, location, job_type)
            VALUES (%s, %s, %s, %s)
        """, (
            request.form["title"],
            request.form["description"],
            request.form["location"],
            request.form["job_type"]
        ))
        conn.commit()

    cur.execute("SELECT * FROM jobs ORDER BY id DESC")
    jobs = cur.fetchall()
    release_db(conn, cur)

    return render_template("jobs.html", jobs=jobs)

@app.route("/delete-job/<int:job_id>")
@login_required
def delete_job(job_id):
    conn, cur = get_db()
    cur.execute("DELETE FROM jobs WHERE id=%s", (job_id,))
    conn.commit()
    release_db(conn, cur)
    return redirect("/jobs")

# =========================
# EDIT JOB
# =========================
@app.route("/edit-job/<int:job_id>", methods=["GET", "POST"])
@login_required
def edit_job(job_id):
    conn, cur = get_db(True)

    if request.method == "POST":
        cur.execute("""
            UPDATE jobs
            SET title=%s, description=%s, location=%s, job_type=%s
            WHERE id=%s
        """, (
            request.form["title"],
            request.form["description"],
            request.form["location"],
            request.form["job_type"],
            job_id
        ))
        conn.commit()
        release_db(conn, cur)
        return redirect("/jobs")

    cur.execute("SELECT * FROM jobs WHERE id=%s", (job_id,))
    job = cur.fetchone()
    release_db(conn, cur)

    if not job:
        return "Job not found", 404

    return render_template("edit_job.html", job=job)

# =========================
# APPLY JOB (URL APPROACH FINAL)
# =========================
@app.route("/apply/<int:job_id>", methods=["GET", "POST"])
def apply(job_id):
    conn, cur = get_db(True)

    cur.execute("SELECT * FROM jobs WHERE id=%s", (job_id,))
    job = cur.fetchone()

    if not job:
        release_db(conn, cur)
        return "Job not found", 404

    if request.method == "POST":
        resume = request.files.get("resume")
        resume_url = None

        if resume and resume.filename:
            filename = f"{int(datetime.now().timestamp())}_{resume.filename}"
            resume.save(os.path.join(UPLOAD_FOLDER, filename))
            resume_url = f"/uploads/resumes/{filename}"

        cur.execute("""
            INSERT INTO applications (job_id, applicant_name, email, phone, resume_url)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            job_id,
            request.form["name"],
            request.form["email"],
            request.form["phone"],
            resume_url
        ))

        conn.commit()
        release_db(conn, cur)
        return "Application submitted successfully!"

    release_db(conn, cur)
    return render_template("apply.html", job=job)

# =========================
# APPLICATIONS
# =========================
@app.route("/applications")
@login_required
def applications():
    selected_job = request.args.get("job_id")

    conn, cur = get_db(True)

    cur.execute("SELECT id, title FROM jobs")
    jobs = cur.fetchall()

    query = """
        SELECT applications.*, jobs.title AS job_title
        FROM applications
        JOIN jobs ON applications.job_id = jobs.id
    """

    params = ()
    if selected_job:
        query += " WHERE jobs.id = %s"
        params = (selected_job,)

    query += " ORDER BY applications.id DESC"

    cur.execute(query, params)
    applications = cur.fetchall()

    release_db(conn, cur)

    return render_template(
        "applications.html",
        applications=applications,
        jobs=jobs,
        selected_job=selected_job
    )

# =========================
# SETTINGS
# =========================
@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    message = None

    if request.method == "POST":
        old = request.form["old_password"]
        new = request.form["new_password"]
        confirm = request.form["confirm_password"]

        if new != confirm:
            message = "Passwords do not match"
        else:
            conn, cur = get_db(True)
            cur.execute("SELECT * FROM admins LIMIT 1")
            admin = cur.fetchone()

            if admin and admin["password"] == old:
                cur.execute("UPDATE admins SET password=%s", (new,))
                conn.commit()
                message = "Password updated successfully"
            else:
                message = "Old password incorrect"

            release_db(conn, cur)

    return render_template("settings.html", message=message)

# =========================
# EXCEL DOWNLOAD
# =========================
@app.route("/download-excel")
@login_required
def download_excel():
    job_id = request.args.get("job_id")

    conn, _ = get_db()

    query = """
        SELECT j.title, a.applicant_name, a.email, a.phone, a.created_at
        FROM applications a
        JOIN jobs j ON a.job_id = j.id
    """

    params = ()
    if job_id:
        query += " WHERE j.id = %s"
        params = (job_id,)

    df = pd.read_sql(query, conn, params=params)

    file_path = "applications.xlsx"
    df.to_excel(file_path, index=False)
    return send_file(file_path, as_attachment=True)

# =========================
# RESUME SERVE
# =========================
@app.route("/uploads/resumes/<path:filename>")
def serve_resume(filename):
    return send_from_directory("uploads/resumes", filename)

# =========================
if __name__ == "__main__":
    app.run(debug=True)
