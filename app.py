from flask import Flask, render_template, request, redirect, session, send_file
from functools import wraps
import os
import pandas as pd
from datetime import datetime
import psycopg2
import psycopg2.extras
from psycopg2 import pool
from urllib.parse import urlparse

# =========================
# APP CONFIG
# =========================
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "fallback-secret")

# =========================
# DB CONNECTION POOL (SPEED FIX)
# =========================
DATABASE_URL = os.getenv("DATABASE_URL")

db_pool = None

def init_db_pool():
    global db_pool
    if db_pool is None:
        db_pool = pool.SimpleConnectionPool(
            minconn=1,
            maxconn=5,
            dsn=os.getenv("DATABASE_URL"),
            sslmode="require"
        )


def get_db(dict_cursor=False):
    init_db_pool()
    conn = db_pool.getconn()
    if dict_cursor:
        conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


def release_db(conn):
    db_pool.putconn(conn)

# =========================
# LOGIN REQUIRED DECORATOR
# =========================
def login_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if not session.get("hr_logged_in"):
            return redirect("/")
        return f(*args, **kwargs)
    return wrap

# =========================
# INIT DB
# =========================
def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE,
            password TEXT
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

    cur.execute("""
        INSERT INTO admins (email, password)
        VALUES (%s, %s)
        ON CONFLICT (email) DO NOTHING
    """, ("admin@hr.com", "admin123"))

    conn.commit()
    release_db(conn)

with app.app_context():
    init_db()

# =========================
# AUTH
# =========================
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        conn = get_db(True)
        cur = conn.cursor()
        cur.execute("SELECT * FROM admins WHERE email=%s", (email,))
        admin = cur.fetchone()
        release_db(conn)

        if admin and admin["password"] == password:
            session.clear()
            session["hr_logged_in"] = True
            session["admin_email"] = email
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
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM jobs")
    total_jobs = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM applications")
    total_applications = cur.fetchone()[0]
    release_db(conn)

    return render_template(
        "dashboard.html",
        total_jobs=total_jobs,
        total_applications=total_applications
    )

# =========================
# MANAGE JOBS
# =========================
@app.route("/manage-jobs", methods=["GET", "POST"])
@login_required
def manage_jobs():
    conn = get_db(True)
    cur = conn.cursor()

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
    release_db(conn)

    return render_template("jobs.html", jobs=jobs)

@app.route("/delete-job/<int:job_id>")
@login_required
def delete_job(job_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM jobs WHERE id=%s", (job_id,))
    conn.commit()
    release_db(conn)
    return redirect("/manage-jobs")

# =========================
# EDIT / UPDATE JOB
# =========================
@app.route("/edit-job/<int:job_id>")
@login_required
def edit_job(job_id):
    conn = get_db(True)
    cur = conn.cursor()
    cur.execute("SELECT * FROM jobs WHERE id=%s", (job_id,))
    job = cur.fetchone()
    release_db(conn)

    if not job:
        return "Job not found", 404

    return render_template("edit_job.html", job=job)

@app.route("/update-job/<int:job_id>", methods=["POST"])
@login_required
def update_job(job_id):
    conn = get_db()
    cur = conn.cursor()
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
    release_db(conn)
    return redirect("/manage-jobs")

# =========================
# APPLY JOB
# =========================
@app.route("/apply/<int:job_id>", methods=["GET", "POST"])
def apply(job_id):
    conn = get_db(True)
    cur = conn.cursor()
    cur.execute("SELECT * FROM jobs WHERE id=%s", (job_id,))
    job = cur.fetchone()

    if not job:
        release_db(conn)
        return "Job not found", 404

    if request.method == "POST":
        resume = request.files.get("resume")
        resume_url = resume.filename if resume else ""

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
        release_db(conn)
        return "Application submitted successfully!"

    release_db(conn)
    return render_template("apply.html", job=job)

# =========================
# APPLICATIONS
# =========================
@app.route("/applications")
@login_required
def applications():
    conn = get_db(True)
    cur = conn.cursor()

    cur.execute("""
        SELECT applications.*, jobs.title AS job_title
        FROM applications
        JOIN jobs ON applications.job_id = jobs.id
        ORDER BY applications.id DESC
    """)
    applications = cur.fetchall()

    release_db(conn)

    return render_template("applications.html", applications=applications)

# =========================
# DOWNLOAD ALL EXCEL
# =========================
@app.route("/download-excel")
@login_required
def download_excel():
    conn = get_db()
    df = pd.read_sql("""
        SELECT j.title, a.applicant_name, a.email, a.phone, a.created_at
        FROM applications a
        JOIN jobs j ON a.job_id = j.id
    """, conn)
    release_db(conn)

    file_path = "applications.xlsx"
    df.to_excel(file_path, index=False)

    return send_file(file_path, as_attachment=True)

# =========================
# SETTINGS
# =========================
@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    ...
    return render_template("settings.html")
