import sqlite3
import requests
import json
from datetime import datetime, timedelta

TENANT_ID = "a1fdee6b-68eb-47b8-b2ac-a4c60c8e6177"
ROOM_CATEGORY_TYPE = "1e042cb1-547d-41d4-ae93-a1f2c3d34538"
PROGRAMME_CATEGORY_TYPE = "241e4d36-60e0-49f8-b27e-99416745d98d"
COMSCI2_UUID = "e631cb22-e616-9d64-58ba-abd77acfa225"

BASE_FILTER_URL = f"https://scientia-eu-v4-api-d1-03.azurewebsites.net/api/Public/CategoryTypes/{{cat_type}}/Categories/FilterWithCache/{TENANT_ID}"
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS programme_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            programme_code TEXT,
            module_name TEXT,
            room_name TEXT,
            start_iso TEXT,
            end_iso TEXT
        )
    """)
    conn.commit()
    conn.close()

def fetch_and_save_rooms():
    conn = sqlite3.connect("rooms.db")
    cursor = conn.cursor()
    page, total_pages, total_rooms = 1, 1, 0
    url = BASE_FILTER_URL.format(cat_type=ROOM_CATEGORY_TYPE)

    while page <= total_pages:
        res = requests.post(f"{url}?pageNumber={page}", headers=HEADERS, json=[])
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

def fetch_and_save_programme_timetable():
    conn = sqlite3.connect("rooms.db")
    cursor = conn.cursor()

    now = datetime.now()
    monday = now - timedelta(days=now.weekday())
    sunday_4w = monday + timedelta(days=27)

    start_iso = monday.strftime("%Y-%m-%dT00:00:00.000Z")
    end_iso = sunday_4w.strftime("%Y-%m-%dT23:59:59.999Z")

    url = f"{EVENTS_URL}?startRange={start_iso}&endRange={end_iso}"
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
                "CategoryTypeIdentity": PROGRAMME_CATEGORY_TYPE,
                "CategoryIdentities": [COMSCI2_UUID]
            }
        ],
        "FetchBookings": True,
        "FetchPersonalEvents": False
    }

    cursor.execute("DELETE FROM programme_events WHERE programme_code = 'COMSCI2'")
    
    res = requests.post(url, headers=HEADERS, json=payload)
    total_saved = 0
    if res.status_code == 200:
        category_events = res.json().get("CategoryEvents", [])
        for prog_entry in category_events:
            events = prog_entry.get("Results", [])
            for event in events:
                s_iso = event.get("StartDateTime")
                e_iso = event.get("EndDateTime")
                
                module_title = ""
                for prop in event.get("ExtraProperties", []):
                    if prop.get("Name") == "Module Name":
                        module_title = prop.get("Value")
                        break
                
                # Retrieve explicit description (Lecture, Practical, Tutorial)
                event_desc = event.get("Description", "").strip()
                
                # Fallback to activity name tag if description is blank
                if not event_desc:
                    raw_name = event.get("Name", "").upper()
                    if "/P" in raw_name or "LAB" in raw_name:
                        event_desc = "Practical"
                    elif "/T" in raw_name or "TUT" in raw_name:
                        event_desc = "Tutorial"
                    else:
                        event_desc = "Lecture"

                base_title = module_title if module_title else event.get("Name", "COMSCI2 Session")
                full_module_name = f"{base_title} ({event_desc})"

                room_name = event.get("Location", "TBA")
                if not room_name or room_name == "TBA":
                    for prop in event.get("ExtraProperties", []):
                        if prop.get("Name") == "Location UserText5":
                            room_name = prop.get("Value")
                            break

                if s_iso and e_iso:
                    cursor.execute("""
                        INSERT INTO programme_events (programme_code, module_name, room_name, start_iso, end_iso)
                        VALUES (?, ?, ?, ?, ?)
                    """, ("COMSCI2", full_module_name, room_name, s_iso, e_iso))
                    total_saved += 1

    conn.commit()
    conn.close()
    print(f"Successfully saved {total_saved} COMSCI2 timetable events.")

if __name__ == "__main__":
    init_db()
    fetch_and_save_rooms()
    fetch_and_save_bookings()
    fetch_and_save_programme_timetable()
