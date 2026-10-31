# CampusConnect: College Event Management Platform

A Flask + SQLite web app where students discover and register for college events, and organizers create, manage and monitor them.

## Run it

```bash
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000. The database (`events.db`) is created and filled with demo data on first run. Delete `events.db` to reset.

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
- Security basics: hashed passwords, CSRF tokens on every form, parameterized SQL, safe redirects, atomic registration (no overselling of seats).

## Project layout

```
app.py              routes, database, seed data
templates/          Jinja templates
static/style.css    styling
requirements.txt
```

## Configuration (optional environment variables)

`PORT`, `DB_PATH`, `SECRET_KEY`, `ORGANIZER_CODE`, `FLASK_DEBUG=1`.
