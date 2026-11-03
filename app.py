import sqlite3
import os
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

LECTURE_THEATRE_UUID = "289a88ea-eaf1-e5be-9044-807575b4286a"
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rooms.db")

EXCLUDED_ROOMS = {
    "GLA.HG00",
    "GLA.HG0017",
    "GLA.HG0018",
    "GLA.HG0019",
    "GLA.HG0020",
}

BUILDINGS = {
    "ALL": "All Glasnevin Buildings",
    "GLA.FT": "Polaris Building (FT)",
    "GLA.S": "Stokes Building (S)",
    "GLA.SA": "Stokes Extension (SA)",
    "GLA.L": "McNulty / Computing (L)",
    "GLA.C": "Henry Grattan (C)",
    "GLA.CA": "Henry Grattan Extension (CA)",
    "GLA.Q": "DCU Business School (Q)",
    "GLA.X": "Lonsdale / Science (X)",
    "GLA.H": "Alice Reeves / Nursing (H)",
    "GLA.N": "Marconi / Engineering (N)",
    "GLA.A": "Albert College (A)",
    "GLA.D": "Bea Orpen (D)",
    "GLA.T": "Terence Larkin Theatre (T)",
    "GLA.F": "Mathematical Sciences (F)",
    "GLA.P": "Pavilion / Invent (P)",
}

def init_db():
    conn = sqlite3.connect(DB_PATH)
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

@app.route("/health")
def health_check():
    return "OK", 200

@app.route("/sw.js")
def service_worker():
    sw_code = """
    self.addEventListener('install', (e) => self.skipWaiting());
    self.addEventListener('activate', (e) => self.clients.claim());
    self.addEventListener('fetch', (e) => e.respondWith(fetch(e.request)));
    """
    return sw_code, 200, {'Content-Type': 'application/javascript'}

@app.route("/manifest.json")
def manifest():
    return jsonify({
        "short_name": "DCU Hub",
        "name": "DCU Student Hub",
        "icons": [
            {
                "src": "/static/images/icon-192.png",
                "type": "image/png",
                "sizes": "192x192"
            },
            {
                "src": "/static/images/icon-512.png",
                "type": "image/png",
                "sizes": "512x512"
            }
        ],
        "start_url": "/",
        "background_color": "#2563eb",
        "theme_color": "#1d4ed8",
        "display": "standalone"
    })

def get_room_status(building_code: str, target_dt: datetime, theatres_only: bool = True):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    target_iso = target_dt.strftime("%Y-%m-%dT%H:%M:%S")

    query = "SELECT id, name, parent_categories FROM rooms WHERE "
    params = []

    if building_code == "ALL":
        query += "(name LIKE 'GLA.%' AND name NOT LIKE 'GLA.Y%') "
    else:
        raw_prefix = building_code.replace("GLA.", "")
        query += "(name LIKE ? OR name LIKE ? OR name LIKE ?) "
        params.extend([f"{building_code}%", f"GLA.{raw_prefix}.%", f"{raw_prefix}%"])

    if theatres_only:
        query += "AND parent_categories LIKE ? "
        params.append(f"%{LECTURE_THEATRE_UUID}%")

    query += "ORDER BY name"
    cursor.execute(query, params)
    all_rooms = cursor.fetchall()

    valid_rooms = [r for r in all_rooms if r[1] not in EXCLUDED_ROOMS]
    vacant_results = []

    for r_id, r_name, _ in valid_rooms:
        cursor.execute("""
            SELECT start_iso, end_iso FROM bookings 
            WHERE room_id = ? 
              AND substr(start_iso, 1, 19) <= ? 
              AND substr(end_iso, 1, 19) > ?
        """, (r_id, target_iso, target_iso))
        
        current_booking = cursor.fetchone()

        if not current_booking:
            end_of_day = target_dt.strftime("%Y-%m-%dT23:59:59")
            cursor.execute("""
                SELECT start_iso FROM bookings 
                WHERE room_id = ? 
                  AND substr(start_iso, 1, 19) > ?
                  AND substr(start_iso, 1, 19) <= ?
                ORDER BY start_iso ASC
                LIMIT 1
            """, (r_id, target_iso, end_of_day))
            
            next_b = cursor.fetchone()
            if next_b:
                next_start_dt = datetime.strptime(next_b[0][:19], "%Y-%m-%dT%H:%M:%S")
                duration = next_start_dt - target_dt
                hours, remainder = divmod(int(duration.total_seconds()), 3600)
                minutes, _ = divmod(remainder, 60)
                
                dur_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
                free_until_str = f"Free until {next_start_dt.strftime('%H:%M')} ({dur_str} left)"
            else:
                free_until_str = "Free for rest of the day"

            vacant_results.append({
                "id": r_id,
                "name": r_name,
                "until": free_until_str
            })

    conn.close()
    return vacant_results, len(valid_rooms)

def get_programme_timetable(programme_code: str = "COMSCI2", target_date: str = None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if not target_date:
        target_date = datetime.now().strftime("%Y-%m-%d")

    cursor.execute("""
        SELECT id, module_name, room_name, start_iso, end_iso 
        FROM programme_events 
        WHERE programme_code = ? AND substr(start_iso, 1, 10) = ?
        ORDER BY start_iso ASC
    """, (programme_code, target_date))
    
    rows = cursor.fetchall()
    conn.close()

    timetable_items = []
    for row in rows:
        b_id, full_mod_name, room_name, start_iso, end_iso = row
        start_dt = datetime.strptime(start_iso[:19], "%Y-%m-%dT%H:%M:%S")
        end_dt = datetime.strptime(end_iso[:19], "%Y-%m-%dT%H:%M:%S")
        
        if "(" in full_mod_name and full_mod_name.endswith(")"):
            clean_module, raw_type = full_mod_name.rsplit(" (", 1)
            raw_type = raw_type[:-1].upper()
        else:
            clean_module = full_mod_name
            raw_type = full_mod_name.upper()

        if "TUTORIAL" in raw_type or "/T" in raw_type or "TUT" in raw_type:
            event_type = "Tutorial"
        elif "PRACTICAL" in raw_type or "LAB" in raw_type or "/P" in raw_type:
            event_type = "Practical / Lab"
        elif "SEMINAR" in raw_type:
            event_type = "Seminar"
        else:
            event_type = "Lecture"

        timetable_items.append({
            "id": b_id,
            "programme": programme_code,
            "module": clean_module,
            "event_type": event_type,
            "room": room_name,
            "start": start_dt.strftime("%H:%M"),
            "end": end_dt.strftime("%H:%M"),
            "date": target_date,
            "time_slot": f"{start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}"
        })

    return timetable_items

@app.route("/api/vacant")
def api_vacant():
    b_code = request.args.get("building", "ALL")
    dt_str = request.args.get("datetime")
    theatres_only = request.args.get("theatres_only", "true").lower() == "true"

    if dt_str:
        try:
            target_dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M")
        except ValueError:
            target_dt = datetime.now()
    else:
        target_dt = datetime.now()

    vacant, total = get_room_status(b_code, target_dt, theatres_only)
    return jsonify({
        "vacant": vacant,
        "total": total,
        "query_time": target_dt.strftime("%A, %b %d at %H:%M")
    })

@app.route("/api/timetable")
def api_timetable():
    prog = request.args.get("programme", "COMSCI2")
    date_str = request.args.get("date")
    schedule = get_programme_timetable(prog, date_str)
    return jsonify({
        "programme": prog,
        "schedule": schedule,
        "date": date_str or datetime.now().strftime("%Y-%m-%d")
    })

@app.route("/")
def index():
    html_code = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>DCU Student Hub</title>
        <link rel="manifest" href="/manifest.json">
        <meta name="theme-color" content="#1d4ed8">
        <meta name="mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-title" content="DCU Hub">
        <script src="https://cdn.tailwindcss.com"></script>
        <script>
            tailwind.config = {
                darkMode: 'class',
            }
        </script>
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
        <style>
            body { font-family: 'Plus Jakarta Sans', sans-serif; }
            .card-shadow { box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.05), 0 2px 6px -1px rgba(0, 0, 0, 0.02); }
            .dark .card-shadow { box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.4); }
        </style>
    </head>
    <body class="bg-slate-50 dark:bg-slate-900 text-slate-800 dark:text-slate-100 min-h-screen flex flex-col transition-colors duration-200">

        <!-- Header -->
        <header class="bg-blue-700 dark:bg-slate-950 text-white shadow-lg sticky top-0 z-50 transition-colors duration-200">
            <div class="max-w-4xl mx-auto px-4 py-4 flex items-center justify-between">
                <div class="flex items-center gap-3">
                    <div class="bg-white/10 dark:bg-slate-800/60 p-2 rounded-xl backdrop-blur-md">
                        <img src="/static/images/logo.png" alt="DCU Logo" class="w-8 h-8 object-contain" onerror="this.style.display='none'">
                    </div>
                    <div>
                        <h1 class="text-xl font-extrabold tracking-tight">DCU Student Hub</h1>
                        <p class="text-blue-200 dark:text-slate-400 text-xs font-medium">COMSCI2 & Campus Live Availability</p>
                    </div>
                </div>

                <!-- Theme Toggle Button -->
                <button id="themeToggle" class="bg-white/10 hover:bg-white/20 dark:bg-slate-800 dark:hover:bg-slate-700 text-white p-2.5 rounded-xl backdrop-blur-md transition flex items-center justify-center">
                    <svg id="sunIcon" class="w-5 h-5 hidden" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"></path></svg>
                    <svg id="moonIcon" class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"></path></svg>
                </button>
            </div>

            <!-- Navigation Tabs -->
            <div class="max-w-4xl mx-auto px-4 flex space-x-1 pt-2">
                <button id="tabTimetable" class="px-5 py-3 border-b-2 border-white font-bold text-sm text-white flex items-center gap-2">
                    Timetable
                </button>
                <button id="tabVacant" class="px-5 py-3 border-b-2 border-transparent font-medium text-sm text-blue-200 dark:text-slate-400 hover:text-white flex items-center gap-2">
                    Vacant Halls
                </button>
            </div>
        </header>

        <!-- Main Body -->
        <main class="max-w-4xl mx-auto px-4 py-6 flex-1 w-full">

            <!-- PANEL 1: Timetable -->
            <div id="timetablePanel">
                <div class="bg-white dark:bg-slate-800 border border-slate-200/80 dark:border-slate-700/80 rounded-2xl p-4 mb-6 card-shadow space-y-3 transition-colors">
                    <div class="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 dark:border-slate-700/60 pb-3">
                        <div class="flex items-center gap-2">
                            <button id="btnToday" class="bg-blue-600 hover:bg-blue-700 text-white font-bold text-xs px-4 py-2 rounded-xl transition shadow-sm">Today</button>
                            <button id="btnTomorrow" class="bg-slate-100 hover:bg-slate-200 dark:bg-slate-700 dark:hover:bg-slate-600 text-slate-700 dark:text-slate-200 font-bold text-xs px-4 py-2 rounded-xl transition">Tomorrow</button>
                        </div>
                        <div class="flex items-center gap-2 w-full sm:w-auto cursor-pointer" id="timetableDateWrapper">
                            <label class="text-xs font-semibold text-slate-500 dark:text-slate-400 whitespace-nowrap cursor-pointer">Specific Date:</label>
                            <input type="date" id="timetableDate" class="bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-100 text-xs font-semibold rounded-xl px-3 py-1.5 focus:ring-2 focus:ring-blue-600 focus:outline-none w-full cursor-pointer">
                        </div>
                    </div>

                    <!-- Week Day Selector Bar -->
                    <div class="flex items-center justify-between gap-1 pt-1">
                        <button class="week-day-btn flex-1 py-2 rounded-xl text-xs font-bold text-slate-600 dark:text-slate-300 hover:bg-blue-50 dark:hover:bg-slate-700 transition text-center" data-day="1">Mon</button>
                        <button class="week-day-btn flex-1 py-2 rounded-xl text-xs font-bold text-slate-600 dark:text-slate-300 hover:bg-blue-50 dark:hover:bg-slate-700 transition text-center" data-day="2">Tue</button>
                        <button class="week-day-btn flex-1 py-2 rounded-xl text-xs font-bold text-slate-600 dark:text-slate-300 hover:bg-blue-50 dark:hover:bg-slate-700 transition text-center" data-day="3">Wed</button>
                        <button class="week-day-btn flex-1 py-2 rounded-xl text-xs font-bold text-slate-600 dark:text-slate-300 hover:bg-blue-50 dark:hover:bg-slate-700 transition text-center" data-day="4">Thu</button>
                        <button class="week-day-btn flex-1 py-2 rounded-xl text-xs font-bold text-slate-600 dark:text-slate-300 hover:bg-blue-50 dark:hover:bg-slate-700 transition text-center" data-day="5">Fri</button>
                    </div>
                </div>

                <div id="timetableList" class="space-y-3"></div>
            </div>

            <!-- PANEL 2: Vacant Halls -->
            <div id="vacantPanel" class="hidden">
                <div class="bg-white dark:bg-slate-800 border border-slate-200/80 dark:border-slate-700/80 rounded-2xl p-5 mb-6 card-shadow transition-colors">
                    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                        <div>
                            <label class="block text-xs font-bold text-slate-600 dark:text-slate-300 mb-1.5">Select Building</label>
                            <select id="buildingSelect" class="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-100 text-xs font-semibold rounded-xl px-3 py-2.5 focus:ring-2 focus:ring-blue-600 focus:outline-none cursor-pointer">
                                {% for code, label in buildings.items() %}
                                <option value="{{ code }}">{{ label }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div>
                            <label class="block text-xs font-bold text-slate-600 dark:text-slate-300 mb-1.5">Target Time Mode</label>
                            <select id="timeMode" class="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-100 text-xs font-semibold rounded-xl px-3 py-2.5 focus:ring-2 focus:ring-blue-600 focus:outline-none cursor-pointer">
                                <option value="now">Right Now (Live)</option>
                                <option value="custom">Custom Date & Time</option>
                            </select>
                        </div>
                        <div id="customTimeWrapper" class="hidden">
                            <label class="block text-xs font-bold text-slate-600 dark:text-slate-300 mb-1.5">Pick Date & Time</label>
                            <input type="datetime-local" id="customDatetime" class="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-100 text-xs font-semibold rounded-xl px-3 py-2.5 focus:ring-2 focus:ring-blue-600 focus:outline-none cursor-pointer">
                        </div>
                    </div>

                    <div class="mt-4 pt-4 border-t border-slate-100 dark:border-slate-700/60 flex items-center justify-between flex-wrap gap-3">
                        <label class="flex items-center gap-2 cursor-pointer text-xs font-semibold text-slate-600 dark:text-slate-300">
                            <input type="checkbox" id="theatresOnly" checked class="w-4 h-4 rounded text-blue-600 bg-slate-100 dark:bg-slate-900 border-slate-300 dark:border-slate-700 focus:ring-blue-600">
                            Lecture Theatres Only
                        </label>
                        <button id="searchBtn" class="bg-blue-600 hover:bg-blue-700 text-white font-bold text-xs px-5 py-2.5 rounded-xl transition shadow-md shadow-blue-600/20">
                            Update Availability
                        </button>
                    </div>
                </div>

                <div class="flex items-center justify-between mb-4 px-1">
                    <h2 id="querySummary" class="text-slate-600 dark:text-slate-400 font-semibold text-xs">Searching...</h2>
                    <span id="roomCountBadge" class="text-xs font-bold bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 px-3 py-1 rounded-full border border-blue-100 dark:border-blue-800">0 Rooms Found</span>
                </div>

                <div id="resultsGrid" class="grid grid-cols-1 md:grid-cols-2 gap-3"></div>
            </div>
        </main>

        <script>
            // Dark Mode Initialization & Toggle
            const themeToggleBtn = document.getElementById('themeToggle');
            const sunIcon = document.getElementById('sunIcon');
            const moonIcon = document.getElementById('moonIcon');

            function applyTheme(isDark) {
                if (isDark) {
                    document.documentElement.classList.add('dark');
                    sunIcon.classList.remove('hidden');
                    moonIcon.classList.add('hidden');
                } else {
                    document.documentElement.classList.remove('dark');
                    sunIcon.classList.add('hidden');
                    moonIcon.classList.remove('hidden');
                }
            }

            const storedTheme = localStorage.getItem('theme');
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            const isInitiallyDark = storedTheme === 'dark' || (!storedTheme && prefersDark);
            applyTheme(isInitiallyDark);

            themeToggleBtn.addEventListener('click', () => {
                const isCurrentDark = document.documentElement.classList.contains('dark');
                const newTheme = !isCurrentDark;
                applyTheme(newTheme);
                localStorage.setItem('theme', newTheme ? 'dark' : 'light');
            });

            if ('serviceWorker' in navigator) {
                navigator.serviceWorker.register('/sw.js');
            }

            const now = new Date();
            now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
            const todayIso = now.toISOString().slice(0,10);
            
            const tomorrow = new Date(now);
            tomorrow.setDate(tomorrow.getDate() + 1);
            const tomorrowIso = tomorrow.toISOString().slice(0,10);

            const customDtInput = document.getElementById('customDatetime');
            customDtInput.value = now.toISOString().slice(0,16);

            const dateInput = document.getElementById('timetableDate');
            dateInput.value = todayIso;

            document.getElementById('timetableDateWrapper').addEventListener('click', () => {
                if ('showPicker' in HTMLInputElement.prototype) {
                    dateInput.showPicker();
                } else {
                    dateInput.focus();
                }
            });

            const tabTimetable = document.getElementById('tabTimetable');
            const tabVacant = document.getElementById('tabVacant');

            const timetablePanel = document.getElementById('timetablePanel');
            const vacantPanel = document.getElementById('vacantPanel');

            function resetTabs() {
                [tabTimetable, tabVacant].forEach(t => {
                    t.className = 'px-5 py-3 border-b-2 border-transparent font-medium text-sm text-blue-200 dark:text-slate-400 hover:text-white flex items-center gap-2';
                });
                [timetablePanel, vacantPanel].forEach(p => p.classList.add('hidden'));
            }

            tabTimetable.addEventListener('click', () => {
                resetTabs();
                tabTimetable.className = 'px-5 py-3 border-b-2 border-white font-bold text-sm text-white flex items-center gap-2';
                timetablePanel.classList.remove('hidden');
                fetchTimetable();
            });

            tabVacant.addEventListener('click', () => {
                resetTabs();
                tabVacant.className = 'px-5 py-3 border-b-2 border-white font-bold text-sm text-white flex items-center gap-2';
                vacantPanel.classList.remove('hidden');
                fetchVacantRooms();
            });

            document.getElementById('btnToday').addEventListener('click', () => {
                dateInput.value = todayIso;
                updateWeekSelection(new Date(todayIso).getDay());
                fetchTimetable();
            });

            document.getElementById('btnTomorrow').addEventListener('click', () => {
                dateInput.value = tomorrowIso;
                updateWeekSelection(new Date(tomorrowIso).getDay());
                fetchTimetable();
            });

            document.querySelectorAll('.week-day-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const targetDay = parseInt(btn.getAttribute('data-day'));
                    const curr = new Date();
                    const distance = targetDay - curr.getDay();
                    const targetDt = new Date(curr.setDate(curr.getDate() + distance));
                    targetDt.setMinutes(targetDt.getMinutes() - targetDt.getTimezoneOffset());
                    
                    dateInput.value = targetDt.toISOString().slice(0,10);
                    updateWeekSelection(targetDay);
                    fetchTimetable();
                });
            });

            function updateWeekSelection(dayNum) {
                document.querySelectorAll('.week-day-btn').forEach(btn => {
                    if (parseInt(btn.getAttribute('data-day')) === dayNum) {
                        btn.className = 'week-day-btn flex-1 py-2 rounded-xl text-xs font-extrabold bg-blue-600 text-white shadow-sm transition text-center';
                    } else {
                        btn.className = 'week-day-btn flex-1 py-2 rounded-xl text-xs font-bold text-slate-600 dark:text-slate-300 hover:bg-blue-50 dark:hover:bg-slate-700 transition text-center';
                    }
                });
            }

            document.getElementById('timeMode').addEventListener('change', (e) => {
                const customWrap = document.getElementById('customTimeWrapper');
                if (e.target.value === 'custom') {
                    customWrap.classList.remove('hidden');
                    setTimeout(() => {
                        if ('showPicker' in HTMLInputElement.prototype) {
                            customDtInput.showPicker();
                        } else {
                            customDtInput.focus();
                        }
                    }, 50);
                } else {
                    customWrap.classList.add('hidden');
                    fetchVacantRooms();
                }
            });

            customDtInput.addEventListener('change', fetchVacantRooms);

            async function fetchTimetable() {
                const dateVal = dateInput.value;
                const url = `/api/timetable?programme=COMSCI2&date=${dateVal}`;
                const list = document.getElementById('timetableList');
                list.innerHTML = '<div class="text-center py-12 text-slate-400 font-medium animate-pulse">Loading schedule...</div>';

                try {
                    const res = await fetch(url);
                    const data = await res.json();

                    list.innerHTML = '';
                    if (data.schedule.length === 0) {
                        list.innerHTML = `
                            <div class="text-center py-16 bg-white dark:bg-slate-800 border border-slate-200/80 dark:border-slate-700/80 rounded-2xl card-shadow">
                                <h3 class="text-slate-700 dark:text-slate-200 font-bold text-base">No Classes Scheduled</h3>
                                <p class="text-xs text-slate-400 mt-1">Enjoy your free time or check vacant halls!</p>
                            </div>`;
                        return;
                    }

                    data.schedule.forEach(item => {
                        let badgeStyle = 'bg-blue-50 dark:bg-blue-950 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-800';
                        if (item.event_type.includes('Lab') || item.event_type.includes('Practical')) {
                            badgeStyle = 'bg-purple-50 dark:bg-purple-950 text-purple-700 dark:text-purple-300 border-purple-200 dark:border-purple-800';
                        } else if (item.event_type.includes('Tutorial')) {
                            badgeStyle = 'bg-amber-50 dark:bg-amber-950 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800';
                        }

                        const card = document.createElement('div');
                        card.className = 'bg-white dark:bg-slate-800 border border-slate-200/80 dark:border-slate-700/80 rounded-2xl p-4 card-shadow flex items-center justify-between gap-4 transition-colors';
                        
                        card.innerHTML = `
                            <div class="flex items-start gap-3.5">
                                <div class="bg-blue-50 dark:bg-slate-900 border border-blue-100 dark:border-slate-700 text-blue-700 dark:text-blue-400 rounded-xl px-3 py-2 font-bold text-xs text-center shrink-0">
                                    ${item.time_slot}
                                </div>
                                <div>
                                    <div class="flex flex-wrap items-center gap-2 mb-1">
                                        <h3 class="text-sm font-bold text-slate-800 dark:text-slate-100">${item.module}</h3>
                                        <span class="text-[10px] font-extrabold uppercase px-2 py-0.5 rounded-md border ${badgeStyle}">
                                            ${item.event_type}
                                        </span>
                                    </div>
                                    <p class="text-xs font-semibold text-slate-500 dark:text-slate-400">Location: ${item.room}</p>
                                </div>
                            </div>
                        `;
                        list.appendChild(card);
                    });
                } catch (err) {
                    list.innerHTML = '<div class="text-center py-12 text-rose-500 font-medium">Error loading schedule.</div>';
                }
            }

            async function fetchVacantRooms() {
                const building = document.getElementById('buildingSelect').value;
                const timeMode = document.getElementById('timeMode').value;
                const theatresOnly = document.getElementById('theatresOnly').checked;
                
                let dtParam = timeMode === 'custom' ? customDtInput.value : '';

                const url = `/api/vacant?building=${building}&datetime=${dtParam}&theatres_only=${theatresOnly}`;
                const grid = document.getElementById('resultsGrid');
                grid.innerHTML = '<div class="col-span-2 text-center py-12 text-slate-400 font-medium">Checking available halls...</div>';

                try {
                    const res = await fetch(url);
                    const data = await res.json();

                    document.getElementById('querySummary').textContent = `Showing vacancy for ${data.query_time}`;
                    document.getElementById('roomCountBadge').textContent = `${data.vacant.length} / ${data.total} Free`;

                    grid.innerHTML = '';
                    if (data.vacant.length === 0) {
                        grid.innerHTML = `<div class="col-span-2 text-center py-12 bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700"><p class="text-slate-500 dark:text-slate-400 font-medium">No vacant halls found.</p></div>`;
                        return;
                    }

                    data.vacant.forEach(room => {
                        const card = document.createElement('div');
                        card.className = 'bg-white dark:bg-slate-800 border border-slate-200/80 dark:border-slate-700/80 rounded-2xl p-4 card-shadow flex items-center justify-between transition-colors';
                        card.innerHTML = `
                            <div>
                                <h3 class="text-base font-bold text-slate-800 dark:text-slate-100">${room.name}</h3>
                                <p class="text-xs text-emerald-600 dark:text-emerald-400 font-semibold mt-0.5 flex items-center gap-1.5">
                                    <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                                    ${room.until}
                                </p>
                            </div>
                            <span class="bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800 text-xs font-bold px-3 py-1 rounded-xl">Available</span>
                        `;
                        grid.appendChild(card);
                    });
                } catch (err) {
                    grid.innerHTML = '<div class="col-span-2 text-center py-12 text-rose-500 font-medium">Error loading room availability.</div>';
                }
            }

            document.getElementById('searchBtn').addEventListener('click', fetchVacantRooms);
            document.getElementById('buildingSelect').addEventListener('change', fetchVacantRooms);
            document.getElementById('timetableDate').addEventListener('change', () => {
                updateWeekSelection(new Date(dateInput.value).getDay());
                fetchTimetable();
            });

            updateWeekSelection(new Date(todayIso).getDay());
            fetchTimetable();
        </script>
    </body>
    </html>
    """
    return render_template_string(html_code, buildings=BUILDINGS)

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
