"""CampusConnect entry point for running from the repository root."""
import os
import sys

# Ensure backend directory is in Python path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

from app import app, init_db

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  CampusConnect running at http://127.0.0.1:{port}")
    print("  Demo logins:  student@bmsce.demo / student123   |   organizer@bmsce.demo / organizer123\n")
    app.run(host="127.0.0.1", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")

