from flask import Flask, render_template, request, redirect, session
import sqlite3
from werkzeug.security import check_password_hash
import os
from werkzeug.utils import secure_filename
from flask import send_from_directory
import pandas as pd
from flask import send_file
from flask import request
from flask import send_from_directory
import os
from flask import request
from flask import request
from init_db import init_db

init_db()

app = Flask(__name__)
app.secret_key = "secretkey"
UPLOAD_FOLDER = "uploads/resumes"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

def get_db():
    conn = sqlite3.connect("hr_management.db")
    conn.row_factory = sqlite3.Row
    return conn
from flask import send_from_directory
import os

@app.route("/resume/<path:filename>")
def view_resume(filename):
    resume_folder = os.path.join(app.root_path, "uploads", "resumes")
    return send_from_directory(resume_folder, filename)
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        # 🔥 TEMP HARD CODE LOGIN
        if email == "hr@company.com" and password == "admin123":
            session["hr_logged_in"] = True
            return redirect("/dashboard")
        else:
            return render_template(
                "login.html",
                error="Invalid login"
            )

    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if not session.get("hr_logged_in"):
        return redirect("/")

    db = get_db()
    cur = db.cursor()

    total_jobs = cur.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    total_applications = cur.execute("SELECT COUNT(*) FROM applications").fetchone()[0]

    return render_template(
        "dashboard.html",
        total_jobs=total_jobs,
        total_applications=total_applications
    )
@app.route("/settings")
def settings():
    if not session.get("hr_logged_in"):
        return redirect("/")
    return render_template("settings.html", title="Settings")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/jobs", methods=["GET", "POST"])
def jobs():
    if not session.get("hr_logged_in"):
        return redirect("/")

    db = get_db()
    cur = db.cursor()

    if request.method == "POST":
        title = request.form["title"]
        description = request.form["description"]
        location = request.form["location"]
        job_type = request.form["job_type"]

        cur.execute(
            "INSERT INTO jobs (title, description, location, job_type) VALUES (?, ?, ?, ?)",
            (title, description, location, job_type)
        )
        db.commit()

    cur.execute("SELECT * FROM jobs")
    jobs = cur.fetchall()

    return render_template("jobs.html", jobs=jobs)

@app.route("/delete-job/<int:id>")
def delete_job(id):
    if not session.get("hr_logged_in"):
        return redirect("/")

    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM jobs WHERE id=?", (id,))
    db.commit()

    return redirect("/jobs")

@app.route("/edit-job/<int:id>", methods=["GET", "POST"])
def edit_job(id):
    if not session.get("hr_logged_in"):
        return redirect("/")

    db = get_db()
    cur = db.cursor()

    if request.method == "POST":
        title = request.form["title"]
        description = request.form["description"]
        location = request.form["location"]
        job_type = request.form["job_type"]

        cur.execute("""
            UPDATE jobs
            SET title=?, description=?, location=?, job_type=?
            WHERE id=?
        """, (title, description, location, job_type, id))
        db.commit()

        return redirect("/jobs")

    cur.execute("SELECT * FROM jobs WHERE id=?", (id,))
    job = cur.fetchone()

    return render_template("edit_job.html", job=job)

@app.route("/apply/<int:job_id>", methods=["GET", "POST"])
def apply(job_id):
    db = get_db()
    cur = db.cursor()

    job = cur.execute(
        "SELECT * FROM jobs WHERE id = ?",
        (job_id,)
    ).fetchone()

    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        phone = request.form.get("phone")
        resume = request.files.get("resume")

        if not job or not name or not email or not phone or not resume:
            return "Invalid data", 400

        filename = resume.filename
        resume.save(f"uploads/resumes/{filename}")

        cur.execute("""
            INSERT INTO applications
            (job_id, applicant_name, email, phone, resume_path)
            VALUES (?, ?, ?, ?, ?)
        """, (job_id, name, email, phone, filename))

        db.commit()
        return "Application submitted successfully!"

    return render_template("apply.html", job=job)




@app.route("/applications")
def applications():
    if not session.get("hr_logged_in"):
        return redirect("/")

    db = get_db()
    cur = db.cursor()

    jobs = cur.execute("SELECT id, title FROM jobs").fetchall()

    selected_job = request.args.get("job_id")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    query = """
        SELECT applications.*, jobs.title AS job_title
        FROM applications
        JOIN jobs ON applications.job_id = jobs.id
        WHERE 1=1
    """
    params = []

    if selected_job:
        query += " AND jobs.id = ?"
        params.append(selected_job)

    if start_date:
        query += " AND DATE(applications.created_at) >= DATE(?)"
        params.append(start_date)

    if end_date:
        query += " AND DATE(applications.created_at) <= DATE(?)"
        params.append(end_date)

    applications = cur.execute(query, params).fetchall()

    return render_template(
        "applications.html",
        applications=applications,
        jobs=jobs,
        selected_job=selected_job,
        start_date=start_date,
        end_date=end_date
    )



@app.route("/download/<path:filename>")
def download_resume(filename):
    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename,
        as_attachment=True
    )

@app.route("/export-applications")
def export_applications():
    if not session.get("hr_logged_in"):
        return redirect("/")

    db = get_db()
    query = """
        SELECT 
            jobs.title AS Job_Title,
            applications.applicant_name AS Applicant_Name,
            applications.email AS Email,
            applications.phone AS Phone
        FROM applications
        JOIN jobs ON applications.job_id = jobs.id
        ORDER BY applications.id DESC
    """

    df = pd.read_sql_query(query, db)

    file_path = "applications.xlsx"
    df.to_excel(file_path, index=False)

    return send_file(
        file_path,
        as_attachment=True,
        download_name="job_applications.xlsx"
    )
@app.route("/export-applications/<int:job_id>")
def export_filtered_applications(job_id):
    if not session.get("hr_logged_in"):
        return redirect("/")

    import pandas as pd

    db = get_db()
    query = """
        SELECT jobs.title AS Job,
               applications.applicant_name AS Name,
               applications.email AS Email,
               applications.phone AS Phone
        FROM applications
        JOIN jobs ON applications.job_id = jobs.id
        WHERE jobs.id = ?
    """

    df = pd.read_sql_query(query, db, params=(job_id,))

    file_name = f"applications_job_{job_id}.xlsx"
    df.to_excel(file_name, index=False)

    return send_file(file_name, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True)
    
if __name__ == "__main__":
    app.run()
