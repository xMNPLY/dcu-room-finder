import sqlite3
import requests
import json
from datetime import datetime, timedelta

TENANT_ID = "a1fdee6b-68eb-47b8-b2ac-a4c60c8e6177"
ROOM_CATEGORY_TYPE = "1e042cb1-547d-41d4-ae93-a1f2c3d34538"
BASE_FILTER_URL = f"https://scientia-eu-v4-api-d1-03.azurewebsites.net/api/Public/CategoryTypes/{ROOM_CATEGORY_TYPE}/Categories/FilterWithCache/{TENANT_ID}"
EVENTS_URL = f"https://scientia-eu-v4-api-d1-03.azurewebsites.net/api/Public/CategoryTypes/Categories/Events/Filter/{TENANT_ID}"

HEADERS = {
    "Authorization": "Anonymous",
    "Content-Type": "application/json",
    "Origin": "https://mytimetable.dcu.ie",
    "Referer": "https://mytimetable.dcu.ie/",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
}

def init_db():
    conn = sqlite3.connect("rooms.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rooms (
            id TEXT PRIMARY KEY,
            name TEXT,
            parent_categories TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id TEXT,
            start_iso TEXT,
            end_iso TEXT,
            FOREIGN KEY(room_id) REFERENCES rooms(id)
        )
    """)
    conn.commit()
    conn.close()

def fetch_and_save_rooms():
    conn = sqlite3.connect("rooms.db")
    cursor = conn.cursor()
    page, total_pages, total_rooms = 1, 1, 0

    while page <= total_pages:
        res = requests.post(f"{BASE_FILTER_URL}?pageNumber={page}", headers=HEADERS, json=[])
        if res.status_code != 200:
            break
        data = res.json()
        total_pages = data.get("TotalPages", 1)
        
        for room in data.get("Results", []):
            if room.get("Identity") and room.get("Name"):
                parents_json = json.dumps(room.get("ParentCategoryIdentities", []))
                cursor.execute("""
                    INSERT OR REPLACE INTO rooms (id, name, parent_categories) 
                    VALUES (?, ?, ?)
                """, (room["Identity"], room["Name"], parents_json))
                total_rooms += 1
        page += 1

    conn.commit()
    conn.close()
    print(f"Saved {total_rooms} rooms with category metadata.")

def fetch_and_save_bookings():
    conn = sqlite3.connect("rooms.db")
    cursor = conn.cursor()

    cursor.execute("DELETE FROM bookings")
    cursor.execute("SELECT id FROM rooms")
    room_ids = [row[0] for row in cursor.fetchall()]

    now = datetime.now()
    monday = now - timedelta(days=now.weekday())
    sunday_4w = monday + timedelta(days=27)

    start_iso = monday.strftime("%Y-%m-%dT00:00:00.000Z")
    end_iso = sunday_4w.strftime("%Y-%m-%dT23:59:59.999Z")

    url = f"{EVENTS_URL}?startRange={start_iso}&endRange={end_iso}"

    batch_size = 10
    total_saved = 0

    print(f"Fetching room schedules from {monday.strftime('%Y-%m-%d')} for 4 weeks...")
    total_batches = (len(room_ids) + batch_size - 1) // batch_size

    for i in range(0, len(room_ids), batch_size):
        chunk = room_ids[i:i + batch_size]
        payload = {
            "ViewOptions": {
                "Days": [
                    {"Name": "Monday", "DayOfWeek": 1},
                    {"Name": "Tuesday", "DayOfWeek": 2},
                    {"Name": "Wednesday", "DayOfWeek": 3},
                    {"Name": "Thursday", "DayOfWeek": 4},
                    {"Name": "Friday", "DayOfWeek": 5},
                    {"Name": "Saturday", "DayOfWeek": 6}
                ],
                "TimePeriods": [{"StartTime": "00:00", "EndTime": "23:59"}]
            },
            "CategoryTypesWithIdentities": [
                {
                    "CategoryTypeIdentity": ROOM_CATEGORY_TYPE,
                    "CategoryIdentities": chunk
                }
            ],
            "FetchBookings": True,
            "FetchPersonalEvents": False
        }

        res = requests.post(url, headers=HEADERS, json=payload)
        if res.status_code == 200:
            category_events = res.json().get("CategoryEvents", [])
            for room_entry in category_events:
                room_uuid = room_entry.get("Identity")
                events = room_entry.get("Results", [])
                
                for event in events:
                    s_iso = event.get("StartDateTime")
                    e_iso = event.get("EndDateTime")
                    
                    if s_iso and e_iso and room_uuid:
                        cursor.execute(
                            "INSERT INTO bookings (room_id, start_iso, end_iso) VALUES (?, ?, ?)",
                            (room_uuid, s_iso, e_iso)
                        )
                        total_saved += 1
                        
        current_batch = i // batch_size + 1
        if current_batch % 10 == 0 or current_batch == total_batches:
            print(f"Processed batch {current_batch}/{total_batches}")

    conn.commit()
    conn.close()
    print(f"Successfully saved {total_saved} booking slots.")

if __name__ == "__main__":
    init_db()
    fetch_and_save_rooms()
    fetch_and_save_bookings()
