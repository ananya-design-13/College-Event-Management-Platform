# CampusConnect: College Event Management Platform

A Flask + SQLite web app where students discover and register for college events, and organizers create, manage and monitor them.

## Run it

### Option 1: From the root directory
```bash
pip install -r backend/requirements.txt
python run.py
```

### Option 2: From the backend directory
```bash
cd backend
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000. The database (`backend/events.db`) is created and filled with demo data on first run. Delete `backend/events.db` to reset.

| Role      | Email                  | Password       |
|-----------|------------------------|----------------|
| Student   | student@bmsce.demo     | student123     |
| Organizer | organizer@bmsce.demo   | organizer123   |

New organizer sign-ups need the access code `ORG2026` (change it with the `ORGANIZER_CODE` environment variable).

## Requirements covered

| # | Requirement | Where |
|---|-------------|-------|
| 1 | Event listing (name, description, date, time, venue, category, organizer) | `/`, `/event/<id>` |
| 2 | Event registration | Register button on the event page; `/my-events` to track |
| 3 | Search and filter | Search box, category pills, Upcoming/Past/All, sort by date or popularity |
| 4 | Organizer dashboard: create, edit, delete | `/dashboard` |
| 5 | Participant management: counts and registration details | `/dashboard/<id>/participants` |
| 6 | Database integration | SQLite: `users`, `events`, `registrations` (foreign keys, unique constraint) |

## Bonus features

- **Capacity and automatic waitlist.** When an event fills up, students join a waitlist with a visible position. If someone cancels, is removed, or the organizer raises capacity, the next student is promoted automatically.
- **Live seat meter** on every card and event page.
- **Attendance check-in** for organizers, with checked-in counts on the dashboard.
- **CSV export** of participants (guarded against spreadsheet formula injection).
- **Add to calendar** (`.ics` download) for any event.
- **Clash warning** when a student registers for two events that start at the same time.
- **Role-based access.** Organizers can only manage their own events.
- **Public JSON feed** of upcoming events at `/api/events`.
- **Unique QR Ticket Pass.** When a student registers for an event, a unique cryptographic QR entry pass is generated and displayed. The student's name, USN, and email address are securely encoded inside the QR payload (not shown as raw text on the pass, but built into the QR code).
- **QR Pass on My Events & Event Details.** Students can view or download their entry pass anytime from `/my-events` or `/event/<id>`.
- **Organizer QR Attendance Scanner.** Organizers can scan attendee QR passes at the venue entrance (via camera or barcode/paste) to instantly verify name, USN, and email, and mark attendance in real time.
- **Light / Dark Mode Toggle.** One-click theme switcher in the top bar with persistence in `localStorage` and zero-flicker loading.
- Security basics: hashed passwords, CSRF tokens on every form, parameterized SQL, safe redirects, atomic registration (no overselling of seats).

## Project layout

```
backend/
  app.py              routes, database, seed data
  requirements.txt    Python dependencies
  events.db           SQLite database
  .secret_key         session secret key
frontend/
  templates/          Jinja HTML templates
  static/style.css    styling and UI assets
run.py                root entrypoint to start the application
```

## Deploy on Render

1. Push your repository to GitHub / GitLab.
2. Go to [Render](https://render.com) and click **New +** > **Web Service**.
3. Connect your GitHub repository.
4. Configure the service settings:
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn run:app`
5. (Optional) In **Environment Variables**, add:
   - `ORGANIZER_CODE`: `ORG2026`
   - `SECRET_KEY`: (any random secret string)
6. Click **Deploy Web Service**.

Alternatively, Render will automatically detect the provided [`render.yaml`](render.yaml) blueprint if you deploy via **New +** > **Blueprint**.

## Configuration (optional environment variables)

`PORT`, `DB_PATH`, `SECRET_KEY`, `ORGANIZER_CODE`, `FLASK_DEBUG=1`.
