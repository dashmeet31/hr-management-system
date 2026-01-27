from flask import Flask, render_template, request, redirect, session, send_from_directory, send_file
import os
import pandas as pd
import psycopg2
import psycopg2.extras
from urllib.parse import urlparse

# =========================
# BASIC APP CONFIG
# =========================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "fallback-secret-key")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads", "resumes")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# =========================
# DATABASE CONNECTION (PostgreSQL)
# =========================
def get_db(dict_cursor=False):
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise Exception("DATABASE_URL not set")

    result = urlparse(db_url)

    if dict_cursor:
        conn = psycopg2.connect(
            dbname=result.path[1:],
            user=result.username,
            password=result.password,
            host=result.hostname,
            port=result.port,
            sslmode="require",
            cursor_factory=psycopg2.extras.RealDictCursor
        )
    else:
        conn = psycopg2.connect(
            dbname=result.path[1:],
            user=result.username,
            password=result.password,
            host=result.hostname,
            port=result.port,
            sslmode="require"
        )

    return conn

# =========================
# INIT DATABASE
# =========================
def init_db():
    conn = get_db()
    cur = conn.cursor()

    # Create jobs table (basic)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id SERIAL PRIMARY KEY,
            title TEXT,
            description TEXT,
            location TEXT,
            job_type TEXT
        )
    """)

    # Add posted_at column safely (if not exists)
    cur.execute("""
        ALTER TABLE jobs
        ADD COLUMN IF NOT EXISTS posted_at DATE DEFAULT CURRENT_DATE
    """)

    # Create applications table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id SERIAL PRIMARY KEY,
            job_id INTEGER REFERENCES jobs(id),
            applicant_name TEXT,
            email TEXT,
            phone TEXT,
            resume_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


with app.app_context():
    init_db()

# =========================
# AUTH
# =========================
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("email") == "admin@hr.com" and request.form.get("password") == "admin123":
            session.clear()
            session["hr_logged_in"] = True
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

    return render_template("dashboard.html",
        total_jobs=total_jobs,
        total_applications=total_applications
    )

# =========================
# JOB MANAGEMENT
# =========================
@app.route("/jobs", methods=["GET", "POST"])
def jobs():
    if not session.get("hr_logged_in"):
        return redirect("/")

    db = get_db(dict_cursor=True)
    cur = db.cursor()

    if request.method == "POST":
        cur.execute("""
            INSERT INTO jobs (title, description, location, job_type, posted_at)
            VALUES (%s, %s, %s, %s, CURRENT_DATE)
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

# =========================
# SETTINGS
# =========================
@app.route("/settings")
def settings():
    if not session.get("hr_logged_in"):
        return redirect("/")
    return render_template("settings.html")

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

@app.route("/edit-job/<int:id>", methods=["GET", "POST"])
def edit_job(id):
    if not session.get("hr_logged_in"):
        return redirect("/")

    db = get_db(dict_cursor=True)
    cur = db.cursor()

    if request.method == "POST":
        cur.execute("""
            UPDATE jobs
            SET title=%s, description=%s, location=%s, job_type=%s
            WHERE id=%s
        """, (
            request.form.get("title"),
            request.form.get("description"),
            request.form.get("location"),
            request.form.get("job_type"),
            id
        ))
        db.commit()
        db.close()
        return redirect("/jobs")

    cur.execute("SELECT * FROM jobs WHERE id=%s", (id,))
    job = cur.fetchone()
    db.close()
    return render_template("edit_job.html", job=job)

# =========================
# APPLY JOB
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
        filename = resume.filename
        resume.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

        cur.execute("""
            INSERT INTO applications
            (job_id, applicant_name, email, phone, resume_path)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            job_id,
            request.form.get("name"),
            request.form.get("email"),
            request.form.get("phone"),
            filename
        ))
        db.commit()
        db.close()
        return "Application submitted successfully!"

    db.close()
    return render_template("apply.html", job=job)

# =========================
# APPLICATIONS
# =========================
# =========================
# APPLICATIONS
# =========================
@app.route("/applications")
def applications():
    if not session.get("hr_logged_in"):
        return redirect("/")

    selected_job = request.args.get("job_id")

    db = get_db(dict_cursor=True)
    cur = db.cursor()

    # Jobs for dropdown
    cur.execute("SELECT id, title FROM jobs")
    jobs = cur.fetchall()

    # Base query
    query = """
        SELECT applications.*, jobs.title AS job_title
        FROM applications
        JOIN jobs ON applications.job_id = jobs.id
    """
    params = []

    # Apply filter if selected
    if selected_job:
        query += " WHERE jobs.id = %s"
        params.append(selected_job)

    query += " ORDER BY applications.id DESC"

    cur.execute(query, params)
    applications = cur.fetchall()

    db.close()

    return render_template(
        "applications.html",
        applications=applications,
        jobs=jobs,
        selected_job=selected_job
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
        SELECT jobs.title AS Job,
               applications.applicant_name AS Name,
               applications.email AS Email,
               applications.phone AS Phone
        FROM applications
        JOIN jobs ON applications.job_id = jobs.id
        WHERE jobs.id = %s
    """, db, params=(job_id,))

    file_path = os.path.join(BASE_DIR, "filtered_applications.xlsx")
    df.to_excel(file_path, index=False)
    db.close()

    return send_file(file_path, as_attachment=True)
