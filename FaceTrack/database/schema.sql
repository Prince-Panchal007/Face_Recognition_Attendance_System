-- FaceTrack SQLite schema
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS students (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id    TEXT    NOT NULL UNIQUE,
    full_name     TEXT    NOT NULL,
    department    TEXT    NOT NULL,
    course        TEXT    NOT NULL,
    email         TEXT,
    phone         TEXT,
    photo_path    TEXT,
    face_enrolled INTEGER NOT NULL DEFAULT 0 CHECK (face_enrolled IN (0, 1)),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_students_department ON students(department);
CREATE INDEX IF NOT EXISTS idx_students_name ON students(full_name);

CREATE TABLE IF NOT EXISTS attendance (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id         INTEGER NOT NULL,           -- FK -> students.id
    attendance_date    TEXT    NOT NULL,           -- YYYY-MM-DD
    check_in_time      TEXT,                       -- HH:MM:SS
    status             TEXT    NOT NULL DEFAULT 'Present'
                               CHECK (status IN ('Present', 'Late', 'Absent')),
    recognition_method TEXT    NOT NULL DEFAULT 'Face'
                               CHECK (recognition_method IN ('Face', 'Manual')),
    confidence         REAL,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    UNIQUE (student_id, attendance_date)
);

CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(attendance_date);
CREATE INDEX IF NOT EXISTS idx_attendance_student ON attendance(student_id);

CREATE TABLE IF NOT EXISTS settings (
    setting_key   TEXT PRIMARY KEY,
    setting_value TEXT
);
