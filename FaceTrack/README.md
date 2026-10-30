# FaceTrack – Smart Face Recognition Attendance Management System

**FaceTrack** is an offline desktop application built in Python for automated classroom and university attendance management using real-time computer vision. It uses **OpenCV Haar Cascades** for frontal face detection, the **LBPH (Local Binary Patterns Histograms)** algorithm (`cv2.face.LBPHFaceRecognizer`) for face recognition, **SQLite** for persistent relational storage, and **CustomTkinter + Matplotlib + ReportLab** for a clean desktop administration interface.

---

## 1. Problem Statement

Traditional classroom attendance relies on manual roll calls or paper sign-in sheets. This process:
- Consumes 5–10 minutes of every lecture.
- Is vulnerable to proxy ("buddy") attendance.
- Requires manual data entry into spreadsheets before generating department or semester reports.
- Produces errors when calculating student eligibility percentages.

---

## 2. Project Objectives

1. **Automate attendance marking** in real time through a standard laptop webcam without cloud APIs or paid subscriptions.
2. **Prevent duplicate entries** so each student receives at most one automatic attendance entry per day.
3. **Provide complete student & face sample management** with live quality checks (blur, lighting, single-face verification) and explicit consent confirmation.
4. **Persist all data locally** in a normalized SQLite database with automatic backup and safe restore capabilities.
5. **Deliver real-time analytics and exports** (CSV & PDF reports across daily, weekly, monthly, student-wise, and department-wise views).

---

## 3. Technology Stack

| Layer | Technology | Purpose |
| :--- | :--- | :--- |
| Programming Language | Python 3.12 | Core application logic |
| Face Detection | OpenCV Haar Cascade (`haarcascade_frontalface_default.xml`) | Real-time frontal face localization |
| Face Recognition | OpenCV `cv2.face.LBPHFaceRecognizer` (`opencv-contrib-python`) | Local Binary Patterns Histograms recognition |
| Desktop UI | CustomTkinter + Tkinter `ttk.Treeview` | Professional multi-page desktop management interface |
| Image Processing | Pillow (PIL) + NumPy | Image conversion, cropping, resizing, icon rendering |
| Database | SQLite 3 (`sqlite3`) | Local relational database with foreign keys & unique constraints |
| Charts & Analytics | Matplotlib (`FigureCanvasTkAgg`) | Embedded 7-day trend, donut, line, and department bar charts |
| Report Exports | Python `csv` + ReportLab | Excel-compatible CSV exports and formatted PDF reports |

---

## 4. System Requirements

- **Operating System:** Windows 10 / 11 (also compatible with Linux/macOS)
- **Python:** Python 3.10 – 3.12
- **RAM:** 4 GB minimum (8 GB recommended)
- **Camera:** Built-in laptop webcam or USB webcam (for live enrollment and recognition; manual attendance works even without a camera)
- **Display:** 1366×768 resolution or higher

---

## 5. Project Structure

```text
FaceTrack/
├── main.py                         # Application entry point
├── config.py                       # Paths, default settings, color palette, logging
├── requirements.txt                # Pinned Python dependencies
├── README.md                       # Quick-start and usage documentation
├── run.bat                         # One-click Windows launcher
│
├── database/
│   ├── schema.sql                  # SQLite tables, constraints, and indexes
│   └── db_manager.py               # Parameterized SQL queries, settings, backup & restore
│
├── recognition/
│   ├── face_detector.py            # Haar Cascade loader, face preprocessing, box drawing
│   ├── face_recognizer.py          # Thread-safe LBPH model loader and predictor
│   ├── trainer.py                  # Reads stored samples and trains lbph_model.yml
│   ├── camera.py                   # Background-threaded webcam capture
│   ├── enrollment.py               # Quality-checked sample capture session
│   └── live_engine.py              # Multi-frame confirmation, cooldown & auto-attendance
│
├── modules/
│   ├── student_manager.py          # Input validation, student CRUD & sample cleanup
│   ├── attendance_manager.py       # Attendance marking, duplicate prevention, CSV export
│   └── report_manager.py           # Daily/weekly/monthly/student/dept analytics & PDF export
│
├── ui/
│   ├── main_window.py              # Sidebar navigation, live header clock, thread helper
│   ├── components.py               # Reusable cards, buttons, tables, dialogs, toasts
│   ├── charts.py                   # Embedded Matplotlib chart widgets
│   ├── video.py                    # Aspect-ratio-preserving video canvas
│   ├── dashboard.py                # Dashboard page
│   ├── live_attendance.py          # Live Webcam Attendance page + Manual Attendance modal
│   ├── students.py                 # Student Registration & Face Enrollment page
│   ├── attendance_records.py       # Searchable Attendance Records page
│   ├── reports.py                  # Reports & Analytics page
│   └── settings.py                 # Camera, threshold, model training & backup settings
│
├── assets/
│   ├── haarcascades/               # Bundled haarcascade_frontalface_default.xml
│   └── images/                     # Application logo and window icon
│
├── data/
│   ├── facetrack.db                # SQLite database (auto-created on first launch)
│   ├── faces/                      # Grayscale 200x200 face samples per student
│   ├── photos/                     # Student profile photos captured during enrollment
│   ├── models/                     # Trained LBPH model (lbph_model.yml + labels.json)
│   ├── exports/                    # Default folder for CSV & PDF reports
│   ├── backups/                    # Timestamped SQLite database backups
│   └── logs/                       # Rotating application log (facetrack.log)
│
├── docs/
│   ├── project_report.md           # Full 18-section college project report
│   ├── technical_documentation.md  # Architecture and module-by-module reference
│   └── viva_and_code_walkthrough.md# Complete student guide for viva & professor Q&A
│
└── tests/
    ├── test_backend.py             # Automated database, reports, and LBPH recognition tests
    └── test_ui_integration.py      # Automated GUI navigation and workflow smoke test
```

---

## 6. Installation & How to Run

### Option A: One-Click Launch on Windows (Recommended)
Double-click **`run.bat`** inside the `FaceTrack` folder (or the root `run.bat`). It automatically checks dependencies, installs any missing packages, and launches the application.

### Option B: Manual Terminal Launch
```powershell
cd d:\Face_Recognition\FaceTrack
pip install -r requirements.txt
python main.py
```

---

## 7. Step-by-Step Usage Guide

### Step 1: Register a Student
1. Open **Students** from the left sidebar (or click **Register Student** on the Dashboard).
2. Enter:
   - **Student ID / Roll No.** (e.g., `CS202601` — must be unique)
   - **Full Name** (e.g., `Aarav Patel`)
   - **Department** (select from dropdown or type a custom department)
   - **Course / Class** (e.g., `B.Tech CSE 3rd Year`)
   - **Email** and **Phone** (optional)
3. Click **Register Student**.

### Step 2: Enroll the Student's Face
1. When prompted *"Enroll face now?"*, click **Enroll Now** (or select any student in the Students table and click **Enroll Face** in the right-hand details panel).
2. Sit 40–70 cm in front of the webcam in normal lighting, with only one person in view.
3. Tick the **consent checkbox** (*"The student consents to their face images being captured and stored locally for attendance"*).
4. Click **Start Capture**.
5. Follow the on-screen prompts (look straight, turn slightly left/right, tilt slightly, smile) while FaceTrack captures **15 grayscale 200×200 samples** (`data/faces/<id>/01.png` … `15.png`). Blurry or poorly lit frames are automatically skipped.
6. Click **Save & Train Model**. FaceTrack trains the LBPH model (`data/models/lbph_model.yml`) and updates the sidebar indicator to **Model ready**.

### Step 3: Mark Live Attendance
1. Open **Live Attendance** from the sidebar (or click **Start Attendance** on the Dashboard).
2. Click **Start Camera**.
3. When an enrolled student looks at the webcam:
   - A **green bounding box** appears with their **Full Name**, **Student ID**, and **LBPH distance**.
   - Once confirmed across consecutive frames (default: 3 frames) with distance ≤ threshold (default: `50`), attendance is saved to SQLite, a toast notification appears, and **Today's Check-ins** updates immediately.
   - If the student stays in front of the camera, **duplicate attendance is prevented** and notifications are suppressed during the cooldown period.
   - Unenrolled people or low-confidence matches are highlighted in **red** as **UNKNOWN** and are never marked present.
4. If no webcam is connected, click **Manual Attendance** in the top-right corner to record attendance manually.

### Step 4: View, Filter, Correct & Export Records
- Go to **Attendance Records** to search by student name/ID, filter by date range, department, or status (`Present`, `Late`, `Absent`), view an individual student's full history, correct a record, delete a record with confirmation, or click **Export CSV**.
- Go to **Reports & Analytics** to view **Daily**, **Weekly**, **Monthly**, **Student-wise**, and **Department-wise** reports and export either **CSV** or a formatted **PDF Report**.

---

## 8. Database Design

FaceTrack uses SQLite (`data/facetrack.db`) with `PRAGMA foreign_keys = ON`:
- **`students`**: `id` (PK), `student_id` (UNIQUE), `full_name`, `department`, `course`, `email`, `phone`, `photo_path`, `face_enrolled` (0/1), `created_at`.
- **`attendance`**: `id` (PK), `student_id` (FK → `students.id ON DELETE CASCADE`), `attendance_date` (`YYYY-MM-DD`), `check_in_time` (`HH:MM:SS`), `status` (`Present`/`Late`/`Absent`), `recognition_method` (`Face`/`Manual`), `confidence` (LBPH distance), with **`UNIQUE(student_id, attendance_date)`**.
- **`settings`**: `setting_key` (PK), `setting_value`.

---

## 9. Project Limitations

1. **Lighting Sensitivity:** Extreme backlighting or very dark rooms reduce Haar Cascade detection rates and increase LBPH distance scores (mitigated via histogram equalization `cv2.equalizeHist`).
2. **Pose Angle:** Frontal Haar Cascade works best within roughly ±25° head rotation.
3. **2D Spoofing:** Standard LBPH on a single RGB webcam does not perform 3D depth liveness detection against printed photographs.

---

## 10. Future Enhancements

- Eye-blink / head-turn active liveness detection to prevent photo spoofing.
- Multi-camera classroom RTSP stream support.
- Optional timetable integration for subject-wise / period-wise attendance within the same day.
- Automated email/SMS summary alerts for students falling below 75% attendance.
