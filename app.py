from flask import Flask, render_template, request, redirect, session, send_file
from werkzeug.security import generate_password_hash, check_password_hash
import os
import pandas as pd
from datetime import datetime
import psycopg2
import psycopg2.extras
from urllib.parse import urlparse

# =========================
# APP CONFIG
# =========================
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "fallback-secret")

# =========================
# DATABASE CONNECTION (SUPABASE POOLER)
# =========================
def get_db(dict_cursor=False):
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise Exception("DATABASE_URL not set")

    result = urlparse(db_url)

    return psycopg2.connect(
        dbname=result.path[1:],
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port,
        sslmode="require",
        cursor_factory=psycopg2.extras.RealDictCursor if dict_cursor else None
    )

# =========================
# INIT DATABASE (SAFE)
# =========================
def init_db():
    db = get_db()
    cur = db.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id SERIAL PRIMARY KEY,
            title TEXT,
            description TEXT,
            location TEXT,
            job_type TEXT,
            posted_at DATE DEFAULT CURRENT_DATE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id SERIAL PRIMARY KEY,
            job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
            applicant_name TEXT,
            email TEXT,
            phone TEXT,
            resume_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Default admin (PLAIN PASSWORD – stable for now)
    cur.execute("""
        INSERT INTO admins (email, password)
        VALUES (%s, %s)
        ON CONFLICT (email) DO NOTHING
    """, ("admin@hr.com", "admin123"))

    db.commit()
    db.close()

with app.app_context():
    init_db()

# =========================
# AUTH
# =========================
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        db = get_db(dict_cursor=True)
        cur = db.cursor()
        cur.execute("SELECT * FROM admins WHERE email=%s", (email,))
        admin = cur.fetchone()
        db.close()

        if admin and admin["password"] == password:
            session.clear()
            session["hr_logged_in"] = True
            session["admin_email"] = email
            return redirect("/dashboard")

        return "Invalid login", 401

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# =========================
# DASHBOARD
# =========================
@app.route("/dashboard")
def dashboard():
    if not session.get("hr_logged_in"):
        return redirect("/")

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM jobs")
    total_jobs = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM applications")
    total_applications = cur.fetchone()[0]
    db.close()

    return render_template(
        "dashboard.html",
        total_jobs=total_jobs,
        total_applications=total_applications
    )

# =========================
# JOBS
# =========================
@app.route("/jobs", methods=["GET", "POST"])
def jobs():
    if not session.get("hr_logged_in"):
        return redirect("/")

    db = get_db(dict_cursor=True)
    cur = db.cursor()

    if request.method == "POST":
        cur.execute("""
            INSERT INTO jobs (title, description, location, job_type)
            VALUES (%s, %s, %s, %s)
        """, (
            request.form.get("title"),
            request.form.get("description"),
            request.form.get("location"),
            request.form.get("job_type")
        ))
        db.commit()

    cur.execute("SELECT * FROM jobs ORDER BY id DESC")
    jobs = cur.fetchall()
    db.close()

    return render_template("jobs.html", jobs=jobs)

@app.route("/delete-job/<int:id>")
def delete_job(id):
    if not session.get("hr_logged_in"):
        return redirect("/")

    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM jobs WHERE id=%s", (id,))
    db.commit()
    db.close()
    return redirect("/jobs")

# =========================
# APPLY JOB (NO CLOUDINARY / NO SUPABASE SDK)
# =========================
@app.route("/apply/<int:job_id>", methods=["GET", "POST"])
def apply(job_id):
    db = get_db(dict_cursor=True)
    cur = db.cursor()

    cur.execute("SELECT * FROM jobs WHERE id=%s", (job_id,))
    job = cur.fetchone()

    if not job:
        db.close()
        return "Job not found", 404

    if request.method == "POST":
        resume = request.files.get("resume")
        resume_url = resume.filename if resume else None

        cur.execute("""
            INSERT INTO applications (job_id, applicant_name, email, phone, resume_url)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            job_id,
            request.form.get("name"),
            request.form.get("email"),
            request.form.get("phone"),
            resume_url
        ))

        db.commit()
        db.close()
        return "Application submitted successfully!"

    db.close()
    return render_template("apply.html", job=job)

# =========================
# APPLICATIONS
# =========================
@app.route("/applications")
def applications():
    if not session.get("hr_logged_in"):
        return redirect("/")

    db = get_db(dict_cursor=True)
    cur = db.cursor()

    cur.execute("""
        SELECT applications.*, jobs.title AS job_title
        FROM applications
        JOIN jobs ON applications.job_id = jobs.id
        ORDER BY applications.id DESC
    """)
    applications = cur.fetchall()

    cur.execute("SELECT id, title FROM jobs")
    jobs = cur.fetchall()

    db.close()

    return render_template(
        "applications.html",
        applications=applications,
        jobs=jobs,
        selected_job=None
    )

# =========================
# EXPORT
# =========================
@app.route("/export-applications/<int:job_id>")
def export_filtered_applications(job_id):
    if not session.get("hr_logged_in"):
        return redirect("/")

    db = get_db()
    df = pd.read_sql("""
        SELECT applicant_name, email, phone
        FROM applications
        WHERE job_id = %s
    """, db, params=(job_id,))

    file_path = "applications.xlsx"
    df.to_excel(file_path, index=False)
    db.close()

    return send_file(file_path, as_attachment=True)
