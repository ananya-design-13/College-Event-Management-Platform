"""CampusConnect: College Event Management Platform (Flask + SQLite)."""
import csv
import io
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from functools import wraps

from flask import (Flask, Response, abort, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "frontend"))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "events.db"))
ORGANIZER_CODE = os.environ.get("ORGANIZER_CODE", "ORG2026")
CATEGORIES = ["Technical", "Cultural", "Sports", "Workshop", "Academic", "Social"]
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _load_secret_key():
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    path = os.path.join(BASE_DIR, ".secret_key")
    if os.path.exists(path):
        with open(path) as fh:
            return fh.read().strip()
    key = secrets.token_hex(32)
    with open(path, "w") as fh:
        fh.write(key)
    return key


app = Flask(
    __name__,
    template_folder=os.path.join(FRONTEND_DIR, "templates"),
    static_folder=os.path.join(FRONTEND_DIR, "static"),
)
app.config["SECRET_KEY"] = _load_secret_key()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    usn TEXT,
    department TEXT,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('student', 'organizer')),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    event_date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT,
    venue TEXT NOT NULL,
    capacity INTEGER NOT NULL DEFAULT 0,
    organizer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'confirmed' CHECK (status IN ('confirmed', 'waitlisted')),
    attended INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (event_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_events_date ON events(event_date);
CREATE INDEX IF NOT EXISTS idx_reg_event ON registrations(event_id);
CREATE INDEX IF NOT EXISTS idx_reg_user ON registrations(user_id);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def now_str():
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def today_iso():
    return date.today().isoformat()


# --------------------------------------------------------------------------
# Template helpers
# --------------------------------------------------------------------------
def _d(s):
    return datetime.strptime(s, "%Y-%m-%d")


@app.template_filter("fdate")
def fdate(s):
    d = _d(s)
    return f"{d.strftime('%a')}, {d.day} {d.strftime('%b %Y')}"


@app.template_filter("mon")
def mon(s):
    return _d(s).strftime("%b").upper()


@app.template_filter("dayn")
def dayn(s):
    return str(_d(s).day)


@app.template_filter("ftime")
def ftime(s):
    if not s:
        return ""
    t = datetime.strptime(s, "%H:%M")
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


@app.template_filter("fstamp")
def fstamp(s):
    d = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    return f"{d.day} {d.strftime('%b')}, {ftime(d.strftime('%H:%M'))}"


@app.context_processor
def inject_globals():
    return {"CATEGORIES": CATEGORIES, "today": today_iso(), "csrf_token": csrf_token}


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


# --------------------------------------------------------------------------
# Auth plumbing
# --------------------------------------------------------------------------
@app.before_request
def load_user_and_check_csrf():
    g.user = None
    uid = session.get("user_id")
    if uid:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if g.user is None:
            session.pop("user_id", None)
    if request.method == "POST":
        sent = request.form.get("csrf_token", "")
        if not sent or not secrets.compare_digest(sent, session.get("_csrf", "")):
            abort(400, "Your session expired. Please go back, refresh the page and try again.")


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if g.user is None:
            flash("Please log in to continue.", "info")
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        return view(*a, **kw)
    return wrapped


def organizer_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if g.user is None:
            flash("Please log in to continue.", "info")
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        if g.user["role"] != "organizer":
            abort(403)
        return view(*a, **kw)
    return wrapped


def safe_next(target):
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return None


# --------------------------------------------------------------------------
# Event helpers
# --------------------------------------------------------------------------
EVENT_SQL = """
SELECT e.*, u.name AS organizer_name,
  (SELECT COUNT(*) FROM registrations r WHERE r.event_id = e.id AND r.status = 'confirmed') AS confirmed,
  (SELECT COUNT(*) FROM registrations r WHERE r.event_id = e.id AND r.status = 'waitlisted') AS waitlisted,
  (SELECT COUNT(*) FROM registrations r WHERE r.event_id = e.id AND r.attended = 1) AS attended_count
FROM events e JOIN users u ON u.id = e.organizer_id
"""


def decorate(row):
    e = dict(row)
    cap = e["capacity"]
    e["is_past"] = e["event_date"] < today_iso()
    e["unlimited"] = cap == 0
    e["spots_left"] = None if cap == 0 else max(cap - e["confirmed"], 0)
    e["is_full"] = cap > 0 and e["confirmed"] >= cap
    e["fill_pct"] = 0 if cap == 0 else min(100, round(100 * e["confirmed"] / cap))
    return e


def get_event(event_id):
    row = get_db().execute(EVENT_SQL + " WHERE e.id = ?", (event_id,)).fetchone()
    return decorate(row) if row else None


def own_event_or_404(event_id):
    ev = get_event(event_id)
    if ev is None:
        abort(404)
    if ev["organizer_id"] != g.user["id"]:
        abort(403)
    return ev


def promote_waitlist(db, event_id):
    """Move waitlisted students into free confirmed spots, oldest first."""
    cap = db.execute("SELECT capacity FROM events WHERE id = ?", (event_id,)).fetchone()
    if cap is None:
        return 0
    cap = cap["capacity"]
    waiting = db.execute(
        "SELECT id FROM registrations WHERE event_id = ? AND status = 'waitlisted' ORDER BY created_at, id",
        (event_id,)).fetchall()
    if cap == 0:
        free = len(waiting)
    else:
        confirmed = db.execute(
            "SELECT COUNT(*) c FROM registrations WHERE event_id = ? AND status = 'confirmed'",
            (event_id,)).fetchone()["c"]
        free = max(cap - confirmed, 0)
    ids = [w["id"] for w in waiting[:free]]
    for rid in ids:
        db.execute("UPDATE registrations SET status = 'confirmed' WHERE id = ?", (rid,))
    return len(ids)


def parse_event_form(form, creating):
    errors = []
    title = form.get("title", "").strip()
    description = form.get("description", "").strip()
    category = form.get("category", "")
    event_date = form.get("event_date", "").strip()
    start_time = form.get("start_time", "").strip()
    end_time = form.get("end_time", "").strip() or None
    venue = form.get("venue", "").strip()
    cap_raw = form.get("capacity", "").strip() or "0"

    if not title or len(title) > 120:
        errors.append("Title is required (max 120 characters).")
    if not description:
        errors.append("Please add a description.")
    if category not in CATEGORIES:
        errors.append("Pick a valid category.")
    try:
        d = datetime.strptime(event_date, "%Y-%m-%d").date()
        if creating and d < date.today():
            errors.append("The event date can't be in the past.")
    except ValueError:
        errors.append("Enter a valid date.")
    try:
        st = datetime.strptime(start_time, "%H:%M")
    except ValueError:
        st = None
        errors.append("Enter a valid start time.")
    if end_time:
        try:
            et = datetime.strptime(end_time, "%H:%M")
            if st and et <= st:
                errors.append("End time must be after the start time.")
        except ValueError:
            errors.append("Enter a valid end time.")
    if not venue:
        errors.append("Venue is required.")
    try:
        capacity = int(cap_raw)
        if capacity < 0 or capacity > 100000:
            raise ValueError
    except ValueError:
        capacity = 0
        errors.append("Capacity must be a whole number (0 means unlimited).")

    data = dict(title=title, description=description, category=category,
                event_date=event_date, start_time=start_time, end_time=end_time,
                venue=venue, capacity=capacity)
    return data, errors


# --------------------------------------------------------------------------
# Public pages
# --------------------------------------------------------------------------
@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    cat = request.args.get("category", "")
    when = request.args.get("when", "upcoming")
    sort = request.args.get("sort", "date")
    if when not in ("upcoming", "past", "all"):
        when = "upcoming"
    if sort not in ("date", "popular"):
        sort = "date"

    sql, params = EVENT_SQL + " WHERE 1=1", []
    if q:
        sql += " AND (e.title LIKE ? OR e.description LIKE ? OR e.venue LIKE ?)"
        params += [f"%{q}%"] * 3
    if cat in CATEGORIES:
        sql += " AND e.category = ?"
        params.append(cat)
    if when == "upcoming":
        sql += " AND e.event_date >= ?"
        params.append(today_iso())
    elif when == "past":
        sql += " AND e.event_date < ?"
        params.append(today_iso())

    if sort == "popular":
        sql += " ORDER BY confirmed DESC, e.event_date ASC"
    elif when == "past":
        sql += " ORDER BY e.event_date DESC, e.start_time"
    else:
        sql += " ORDER BY e.event_date ASC, e.start_time ASC"

    db = get_db()
    events = [decorate(r) for r in db.execute(sql, params).fetchall()]
    my_regs = {}
    if g.user and g.user["role"] == "student":
        rows = db.execute("SELECT event_id, status FROM registrations WHERE user_id = ?",
                          (g.user["id"],)).fetchall()
        my_regs = {r["event_id"]: dict(r) for r in rows}
    return render_template("index.html", events=events, my_regs=my_regs,
                           q=q, cat=cat if cat in CATEGORIES else "", when=when, sort=sort)


@app.route("/event/<int:event_id>")
def event_detail(event_id):
    ev = get_event(event_id)
    if ev is None:
        abort(404)
    reg = None
    if g.user and g.user["role"] == "student":
        reg = get_db().execute("SELECT * FROM registrations WHERE event_id = ? AND user_id = ?",
                               (event_id, g.user["id"])).fetchone()
    position = None
    if reg and reg["status"] == "waitlisted":
        position = get_db().execute(
            "SELECT COUNT(*) c FROM registrations WHERE event_id = ? AND status = 'waitlisted' "
            "AND (created_at < ? OR (created_at = ? AND id <= ?))",
            (event_id, reg["created_at"], reg["created_at"], reg["id"])).fetchone()["c"]
    return render_template("event.html", ev=ev, reg=reg, position=position)


@app.route("/event/<int:event_id>.ics")
def event_ics(event_id):
    ev = get_event(event_id)
    if ev is None:
        abort(404)

    def esc(s):
        return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    start = datetime.strptime(f"{ev['event_date']} {ev['start_time']}", "%Y-%m-%d %H:%M")
    if ev["end_time"]:
        end = datetime.strptime(f"{ev['event_date']} {ev['end_time']}", "%Y-%m-%d %H:%M")
    else:
        end = start + timedelta(hours=2)
    fmt = "%Y%m%dT%H%M%S"
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//CampusConnect//Events//EN",
        "BEGIN:VEVENT",
        f"UID:event-{ev['id']}@campusconnect",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART:{start.strftime(fmt)}", f"DTEND:{end.strftime(fmt)}",
        f"SUMMARY:{esc(ev['title'])}", f"LOCATION:{esc(ev['venue'])}",
        f"DESCRIPTION:{esc(ev['description'])}",
        "END:VEVENT", "END:VCALENDAR",
    ]
    return Response("\r\n".join(lines) + "\r\n", mimetype="text/calendar",
                    headers={"Content-Disposition": f"attachment; filename=event-{ev['id']}.ics"})


@app.route("/api/events")
def api_events():
    rows = get_db().execute(EVENT_SQL + " WHERE e.event_date >= ? ORDER BY e.event_date, e.start_time",
                            (today_iso(),)).fetchall()
    keys = ["id", "title", "category", "event_date", "start_time", "end_time", "venue",
            "capacity", "confirmed", "spots_left"]
    return jsonify([{k: decorate(r)[k] for k in keys} for r in rows])


# --------------------------------------------------------------------------
# Student: registration
# --------------------------------------------------------------------------
@app.post("/event/<int:event_id>/register")
@login_required
def register(event_id):
    if g.user["role"] != "student":
        flash("Only student accounts can register for events.", "error")
        return redirect(url_for("event_detail", event_id=event_id))
    db = get_db()
    db.execute("BEGIN IMMEDIATE")  # serialise count + insert so capacity can't be oversold
    ev = get_event(event_id)
    if ev is None:
        db.rollback()
        abort(404)
    if ev["is_past"]:
        db.rollback()
        flash("Registration is closed: this event has already taken place.", "error")
        return redirect(url_for("event_detail", event_id=event_id))
    if db.execute("SELECT 1 FROM registrations WHERE event_id = ? AND user_id = ?",
                  (event_id, g.user["id"])).fetchone():
        db.rollback()
        flash("You're already registered for this event.", "info")
        return redirect(url_for("event_detail", event_id=event_id))

    status = "waitlisted" if ev["is_full"] else "confirmed"
    db.execute("INSERT INTO registrations (event_id, user_id, status, created_at) VALUES (?, ?, ?, ?)",
               (event_id, g.user["id"], status, now_str()))
    clash = db.execute(
        """SELECT e.title FROM registrations r JOIN events e ON e.id = r.event_id
           WHERE r.user_id = ? AND r.status = 'confirmed' AND e.id != ?
             AND e.event_date = ? AND e.start_time = ?""",
        (g.user["id"], event_id, ev["event_date"], ev["start_time"])).fetchone()
    db.commit()

    if status == "confirmed":
        flash(f"You're in! Registered for “{ev['title']}”.", "success")
    else:
        flash("This event is full, so you've been added to the waitlist. "
              "We'll move you up automatically if a spot opens.", "warning")
    if clash:
        flash(f"Heads up: this starts at the same time as “{clash['title']}”, which you're also registered for.",
              "warning")
    return redirect(safe_next(request.form.get("next")) or url_for("event_detail", event_id=event_id))


@app.post("/event/<int:event_id>/cancel")
@login_required
def cancel_registration(event_id):
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    reg = db.execute("SELECT * FROM registrations WHERE event_id = ? AND user_id = ?",
                     (event_id, g.user["id"])).fetchone()
    if reg is None:
        db.rollback()
        flash("You're not registered for this event.", "info")
    else:
        db.execute("DELETE FROM registrations WHERE id = ?", (reg["id"],))
        promoted = promote_waitlist(db, event_id) if reg["status"] == "confirmed" else 0
        db.commit()
        flash("Your registration has been cancelled."
              + (f" {promoted} waitlisted student(s) moved up." if promoted else ""), "success")
    return redirect(safe_next(request.form.get("next")) or url_for("my_events"))


@app.route("/my-events")
@login_required
def my_events():
    if g.user["role"] != "student":
        return redirect(url_for("dashboard"))
    rows = get_db().execute(
        EVENT_SQL.replace("FROM events e", "FROM events e JOIN registrations mr ON mr.event_id = e.id", 1)
        .replace("SELECT e.*,", "SELECT e.*, mr.status AS my_status, mr.created_at AS registered_at,", 1)
        + " WHERE mr.user_id = ? ORDER BY e.event_date, e.start_time", (g.user["id"],)).fetchall()
    items = [decorate(r) for r in rows]
    upcoming = [e for e in items if not e["is_past"]]
    past = [e for e in items if e["is_past"]]
    return render_template("my_events.html", upcoming=upcoming, past=past[::-1])


# --------------------------------------------------------------------------
# Auth pages
# --------------------------------------------------------------------------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user:
        return redirect(url_for("index"))
    if request.method == "POST":
        f = request.form
        name = f.get("name", "").strip()
        email = f.get("email", "").strip().lower()
        password = f.get("password", "")
        role = f.get("role", "student")
        usn = f.get("usn", "").strip().upper() or None
        department = f.get("department", "").strip() or None
        errors = []
        if not name:
            errors.append("Please enter your name.")
        if not EMAIL_RE.match(email):
            errors.append("Enter a valid email address.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if role not in ("student", "organizer"):
            errors.append("Choose a valid account type.")
        if role == "organizer" and not secrets.compare_digest(f.get("org_code", ""), ORGANIZER_CODE):
            errors.append("That organizer access code isn't right. Ask your club coordinator for it.")
        if not errors and get_db().execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            errors.append("An account with that email already exists. Try logging in.")
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("signup.html", form=f), 400
        db = get_db()
        cur = db.execute(
            "INSERT INTO users (name, email, usn, department, password_hash, role, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, email, usn, department, generate_password_hash(password), role, now_str()))
        db.commit()
        session.clear()
        session["user_id"] = cur.lastrowid
        flash(f"Welcome, {name.split()[0]}!", "success")
        return redirect(url_for("dashboard" if role == "organizer" else "index"))
    return render_template("signup.html", form={})


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            flash(f"Welcome back, {user['name'].split()[0]}!", "success")
            nxt = safe_next(request.form.get("next") or request.args.get("next"))
            return redirect(nxt or url_for("dashboard" if user["role"] == "organizer" else "index"))
        flash("Incorrect email or password.", "error")
        return render_template("login.html", email=email), 401
    return render_template("login.html", email="")


@app.post("/logout")
def logout():
    session.clear()
    flash("You've been logged out.", "info")
    return redirect(url_for("index"))


# --------------------------------------------------------------------------
# Organizer dashboard
# --------------------------------------------------------------------------
@app.route("/dashboard")
@organizer_required
def dashboard():
    rows = get_db().execute(EVENT_SQL + " WHERE e.organizer_id = ? ORDER BY e.event_date DESC, e.start_time",
                            (g.user["id"],)).fetchall()
    events = [decorate(r) for r in rows]
    upcoming = [e for e in events if not e["is_past"]]
    stats = {
        "events": len(events),
        "upcoming": len(upcoming),
        "registrations": sum(e["confirmed"] for e in events),
        "waitlisted": sum(e["waitlisted"] for e in events),
    }
    upcoming.sort(key=lambda e: (e["event_date"], e["start_time"]))
    past = [e for e in events if e["is_past"]]
    return render_template("dashboard.html", upcoming=upcoming, past=past, stats=stats)


EMPTY_EVENT = dict(title="", description="", category="", event_date="", start_time="",
                   end_time="", venue="", capacity=0)


@app.route("/dashboard/new", methods=["GET", "POST"])
@organizer_required
def event_new():
    if request.method == "POST":
        data, errors = parse_event_form(request.form, creating=True)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("event_form.html", ev=data, mode="new"), 400
        db = get_db()
        cur = db.execute(
            "INSERT INTO events (title, description, category, event_date, start_time, end_time, venue, "
            "capacity, organizer_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (data["title"], data["description"], data["category"], data["event_date"], data["start_time"],
             data["end_time"], data["venue"], data["capacity"], g.user["id"], now_str()))
        db.commit()
        flash("Event published. Students can see it now.", "success")
        return redirect(url_for("event_detail", event_id=cur.lastrowid))
    return render_template("event_form.html", ev=dict(EMPTY_EVENT), mode="new")


@app.route("/dashboard/<int:event_id>/edit", methods=["GET", "POST"])
@organizer_required
def event_edit(event_id):
    ev = own_event_or_404(event_id)
    if request.method == "POST":
        data, errors = parse_event_form(request.form, creating=False)
        if errors:
            for e in errors:
                flash(e, "error")
            data["id"] = event_id
            return render_template("event_form.html", ev=data, mode="edit"), 400
        db = get_db()
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "UPDATE events SET title=?, description=?, category=?, event_date=?, start_time=?, end_time=?, "
            "venue=?, capacity=? WHERE id=?",
            (data["title"], data["description"], data["category"], data["event_date"], data["start_time"],
             data["end_time"], data["venue"], data["capacity"], event_id))
        promoted = promote_waitlist(db, event_id)
        db.commit()
        flash("Event updated." + (f" {promoted} waitlisted student(s) moved into the new spots." if promoted else ""),
              "success")
        return redirect(url_for("dashboard"))
    return render_template("event_form.html", ev=ev, mode="edit")


@app.post("/dashboard/<int:event_id>/delete")
@organizer_required
def event_delete(event_id):
    ev = own_event_or_404(event_id)
    db = get_db()
    db.execute("DELETE FROM events WHERE id = ?", (event_id,))
    db.commit()
    flash(f"Deleted “{ev['title']}” and its {ev['confirmed'] + ev['waitlisted']} registration(s).", "success")
    return redirect(url_for("dashboard"))


def _participants(event_id, status=None):
    sql = ("SELECT r.id AS reg_id, r.status, r.attended, r.created_at AS registered_at, "
           "u.name, u.email, u.usn, u.department "
           "FROM registrations r JOIN users u ON u.id = r.user_id WHERE r.event_id = ?")
    params = [event_id]
    if status in ("confirmed", "waitlisted"):
        sql += " AND r.status = ?"
        params.append(status)
    sql += " ORDER BY r.status = 'waitlisted', r.created_at, r.id"
    return get_db().execute(sql, params).fetchall()


@app.route("/dashboard/<int:event_id>/participants")
@organizer_required
def participants(event_id):
    ev = own_event_or_404(event_id)
    status = request.args.get("status", "")
    regs = _participants(event_id, status)
    return render_template("participants.html", ev=ev, regs=regs, status=status)


@app.route("/dashboard/<int:event_id>/participants.csv")
@organizer_required
def participants_csv(event_id):
    ev = own_event_or_404(event_id)

    def safe(v):
        v = "" if v is None else str(v)
        return "'" + v if v[:1] in ("=", "+", "-", "@") else v  # block spreadsheet formula injection

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Name", "Email", "USN", "Department", "Status", "Attended", "Registered at"])
    for r in _participants(event_id):
        w.writerow([safe(r["name"]), safe(r["email"]), safe(r["usn"]), safe(r["department"]),
                    r["status"], "Yes" if r["attended"] else "No", r["registered_at"]])
    slug = re.sub(r"[^a-z0-9]+", "-", ev["title"].lower()).strip("-") or "event"
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={slug}-participants.csv"})


@app.post("/dashboard/<int:event_id>/participants/<int:reg_id>/attendance")
@organizer_required
def toggle_attendance(event_id, reg_id):
    own_event_or_404(event_id)
    db = get_db()
    db.execute("UPDATE registrations SET attended = 1 - attended WHERE id = ? AND event_id = ? "
               "AND status = 'confirmed'", (reg_id, event_id))
    db.commit()
    return redirect(url_for("participants", event_id=event_id, status=request.form.get("status") or None))


@app.post("/dashboard/<int:event_id>/participants/<int:reg_id>/remove")
@organizer_required
def remove_participant(event_id, reg_id):
    own_event_or_404(event_id)
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    reg = db.execute("SELECT * FROM registrations WHERE id = ? AND event_id = ?", (reg_id, event_id)).fetchone()
    if reg:
        db.execute("DELETE FROM registrations WHERE id = ?", (reg_id,))
        promoted = promote_waitlist(db, event_id) if reg["status"] == "confirmed" else 0
        db.commit()
        flash("Participant removed." + (f" {promoted} waitlisted student(s) moved up." if promoted else ""),
              "success")
    else:
        db.rollback()
    return redirect(url_for("participants", event_id=event_id, status=request.form.get("status") or None))


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
def http_error(err):
    messages = {
        400: err.description if getattr(err, "description", None) else "Bad request.",
        403: "You don't have permission to do that.",
        404: "We couldn't find that page.",
    }
    return render_template("error.html", code=err.code, message=messages[err.code]), err.code


# --------------------------------------------------------------------------
# Seed data
# --------------------------------------------------------------------------
def seed_demo(db):
    pw_org = generate_password_hash("organizer123")
    pw_stu = generate_password_hash("student123")
    ts = now_str()

    def add_user(name, email, role, pw, usn=None, dept=None):
        return db.execute(
            "INSERT INTO users (name, email, usn, department, password_hash, role, created_at) "
            "VALUES (?,?,?,?,?,?,?)", (name, email, usn, dept, pw, role, ts)).lastrowid

    tech = add_user("Tech Club", "organizer@bmsce.demo", "organizer", pw_org)
    council = add_user("Cultural & Sports Council", "council@bmsce.demo", "organizer", pw_org)

    names = ["Ananya Galagali", "Rohan Kulkarni", "Meera Iyer", "Arjun Nair", "Sneha Reddy", "Karthik Rao",
             "Divya Shetty", "Imran Pasha", "Pooja Hegde", "Vikram Joshi", "Nisha Menon", "Aditya Bhat",
             "Tanvi Desai", "Sahil Gowda"]
    depts = ["CSE", "ISE", "ECE", "ME", "EEE"]
    students = []
    for i, n in enumerate(names):
        email = "student@bmsce.demo" if i == 0 else n.lower().replace(" ", ".") + "@bmsce.demo"
        students.append(add_user(n, email, "student", pw_stu, f"1BM24{depts[i % 5]}{i + 1:03d}", depts[i % 5]))

    d = date.today()

    def day(offset):
        return (d + timedelta(days=offset)).isoformat()

    events = [
        # (owner, title, category, offset, start, end, venue, cap, description, n_registered)
        (tech, "Hack the Campus: 24-hour Hackathon", "Technical", 9, "09:00", "09:00", "Main Auditorium", 120,
         "Form a team of up to four and build something useful for campus life in 24 hours. Mentors from "
         "industry, free meals, and prizes for the top three teams.\n\nBring your laptop and charger.", 9),
        (tech, "Intro to Machine Learning Workshop", "Workshop", 4, "14:00", "17:00", "CS Seminar Hall", 40,
         "A hands-on beginner session: train your first model in Python with scikit-learn. No prior ML "
         "experience needed, but basic Python helps.", 6),
        (council, "Rangotsav: Cultural Night", "Cultural", 14, "18:00", "21:30", "Open Air Theatre", 500,
         "An evening of dance, music and theatre from every department. Come cheer for your friends and "
         "stay for the food stalls.", 11),
        (council, "Inter-Department Cricket League", "Sports", 6, "08:00", None, "College Sports Ground", 64,
         "T10 knockout format. Each department fields one team of up to 11 players. Captains register "
         "their squads at the sports office.", 5),
        (tech, "Resume & LinkedIn Clinic", "Workshop", 2, "16:00", "17:30", "Placement Cell", 30,
         "Bring your resume and get 1-on-1 feedback from final-year placement coordinators and alumni.", 4),
        (tech, "Robotics Showcase", "Technical", 20, "10:00", "16:00", "Mechanical Block Lab", 80,
         "See line-followers, robotic arms and drones built by student teams, then try the controls "
         "yourself.", 3),
        (council, "Lalbagh Photography Walk", "Social", 8, "06:30", "09:00", "Lalbagh Botanical Garden, Gate 1", 8,
         "A sunrise walk for photographers of every level. Phones welcome. Only 8 spots, so a waitlist "
         "will open once it's full.", 14),
        (tech, "Research Paper Writing Seminar", "Academic", 11, "11:00", "13:00", "Library Conference Room", 100,
         "How to pick a problem, structure a paper and get through peer review, from faculty who "
         "publish regularly.", 2),
        (council, "Badminton Doubles Tournament", "Sports", 16, "09:00", None, "Indoor Stadium", 32,
         "Mixed and same-gender doubles brackets. Bring your own racket; shuttles provided.", 7),
        (council, "BMSCE Trivia Night", "Social", 1, "15:00", "17:00", "Student Activity Centre", 0,
         "Teams of three battle it out over pop culture, campus history, sports and science. Open to "
         "everyone, with no cap on seats.", 8),
        (tech, "Tech Quiz Finals", "Technical", -12, "15:00", "17:00", "CS Seminar Hall", 60,
         "The finals of this year's inter-college tech quiz.", 6),
    ]
    for owner, title, cat, off, st, et, venue, cap, desc, n in events:
        eid = db.execute(
            "INSERT INTO events (title, description, category, event_date, start_time, end_time, venue, "
            "capacity, organizer_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (title, desc, cat, day(off), st, et, venue, cap, owner, ts)).lastrowid
        for i, sid in enumerate(students[:n]):
            status = "confirmed" if cap == 0 or i < cap else "waitlisted"
            attended = 1 if (off < 0 and i % 4 != 3) else 0
            created = (datetime.now() - timedelta(hours=len(students) - i)).isoformat(sep=" ", timespec="seconds")
            db.execute("INSERT INTO registrations (event_id, user_id, status, attended, created_at) "
                       "VALUES (?,?,?,?,?)", (eid, sid, status, attended, created))
    db.commit()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
    if db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] == 0:
        seed_demo(db)
    db.close()


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  CampusConnect running at http://127.0.0.1:{port}")
    print("  Demo logins:  student@bmsce.demo / student123   |   organizer@bmsce.demo / organizer123\n")
    app.run(host="127.0.0.1", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
