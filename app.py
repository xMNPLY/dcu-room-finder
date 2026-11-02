import sqlite3
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

LECTURE_THEATRE_UUID = "289a88ea-eaf1-e5be-9044-807575b4286a"

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
    "GLA.Y": "Library / O'Reilly (Y)",
}

def get_room_status(building_code: str, target_dt: datetime, theatres_only: bool = True):
    conn = sqlite3.connect("rooms.db")
    cursor = conn.cursor()

    target_iso = target_dt.strftime("%Y-%m-%dT%H:%M:%S")

    query = "SELECT id, name, parent_categories FROM rooms WHERE "
    params = []

    if building_code == "ALL":
        query += "(name LIKE 'GLA.%' OR (name NOT LIKE 'SPC.%' AND name NOT LIKE 'AHC.%')) "
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
    conn = sqlite3.connect("rooms.db")
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
        
        # Clean title & determine true session type
        clean_module = full_mod_name
        if "(" in full_mod_name and full_mod_name.endswith(")"):
            clean_module, raw_type = full_mod_name.rsplit(" (", 1)
            raw_type = raw_type[:-1].upper()
        else:
            raw_type = full_mod_name.upper()

        # Classify event format based on keywords and codes
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
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>DCU Student Hub</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
        <style>
            body { font-family: 'Plus Jakarta Sans', sans-serif; }
            .glass { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(12px); }
        </style>
    </head>
    <body class="bg-slate-950 text-slate-100 min-h-screen relative overflow-x-hidden">
        <div class="absolute top-0 left-1/4 w-96 h-96 bg-blue-600/10 rounded-full blur-3xl pointer-events-none"></div>
        <div class="absolute bottom-0 right-1/4 w-96 h-96 bg-indigo-600/10 rounded-full blur-3xl pointer-events-none"></div>

        <div class="max-w-4xl mx-auto px-4 py-8 relative z-10">
            <!-- Header -->
            <div class="flex items-center justify-between border-b border-slate-800/80 pb-6 mb-8">
                <div>
                    <h1 class="text-3xl font-extrabold tracking-tight text-white flex items-center gap-3">
                        <span class="bg-blue-600 text-white p-2 rounded-xl text-xl shadow-lg shadow-blue-500/25">🏛️</span>
                        DCU Student Hub
                    </h1>
                    <p class="text-slate-400 text-sm mt-1">Vacant lecture theatre scanner & COMSCI2 timetable</p>
                </div>
                <div class="inline-flex items-center gap-2 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 px-3.5 py-1.5 rounded-full text-xs font-semibold">
                    <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                    Live Schedule Sync
                </div>
            </div>

            <!-- Navigation Tabs -->
            <div class="flex space-x-2 mb-6 border-b border-slate-800/80 pb-3">
                <button id="tabTimetable" class="px-5 py-2.5 rounded-xl font-bold text-sm bg-blue-600 text-white transition shadow-lg shadow-blue-600/20 flex items-center gap-2">
                    <span>📅</span> COMSCI2 Timetable
                </button>
                <button id="tabVacant" class="px-5 py-2.5 rounded-xl font-bold text-sm bg-slate-800/80 text-slate-400 hover:text-white transition flex items-center gap-2">
                    <span>🔍</span> Vacant Halls
                </button>
            </div>

            <!-- Panel 1: COMSCI2 Timetable -->
            <div id="timetablePanel">
                <div class="glass border border-slate-800 rounded-2xl p-5 mb-6 flex flex-col sm:flex-row items-center justify-between gap-4 shadow-xl">
                    <div class="flex items-center gap-2 w-full sm:w-auto">
                        <button id="btnToday" class="bg-blue-600 hover:bg-blue-500 text-white font-semibold text-xs px-3.5 py-2 rounded-xl transition shadow-md shadow-blue-600/20">Today</button>
                        <button id="btnTomorrow" class="bg-slate-800 hover:bg-slate-700 text-slate-300 font-semibold text-xs px-3.5 py-2 rounded-xl transition">Tomorrow</button>
                    </div>
                    <div class="flex items-center gap-3 w-full sm:w-auto">
                        <label class="text-xs font-semibold text-slate-400 whitespace-nowrap">Select Date:</label>
                        <input type="date" id="timetableDate" class="bg-slate-900 border border-slate-700 text-white text-sm font-medium rounded-xl px-3 py-1.5 focus:ring-2 focus:ring-blue-500 focus:outline-none w-full">
                    </div>
                </div>

                <div id="timetableList" class="space-y-4"></div>
            </div>

            <!-- Panel 2: Vacant Rooms -->
            <div id="vacantPanel" class="hidden">
                <div class="glass border border-slate-800 rounded-2xl p-6 mb-8 shadow-xl">
                    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                        <div>
                            <label class="block text-xs font-semibold text-slate-400 mb-1.5">Select Building</label>
                            <select id="buildingSelect" class="w-full bg-slate-900 border border-slate-700 text-white text-sm rounded-xl px-3 py-2.5 focus:ring-2 focus:ring-blue-500 focus:outline-none">
                                {% for code, label in buildings.items() %}
                                <option value="{{ code }}">{{ label }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div>
                            <label class="block text-xs font-semibold text-slate-400 mb-1.5">Target Time Mode</label>
                            <select id="timeMode" class="w-full bg-slate-900 border border-slate-700 text-white text-sm rounded-xl px-3 py-2.5 focus:ring-2 focus:ring-blue-500 focus:outline-none">
                                <option value="now">Right Now (Live)</option>
                                <option value="custom">Custom Date & Time</option>
                            </select>
                        </div>
                        <div id="customTimeWrapper" class="hidden">
                            <label class="block text-xs font-semibold text-slate-400 mb-1.5">Pick Date & Time</label>
                            <input type="datetime-local" id="customDatetime" class="w-full bg-slate-900 border border-slate-700 text-white text-sm rounded-xl px-3 py-2.5 focus:ring-2 focus:ring-blue-500 focus:outline-none">
                        </div>
                    </div>

                    <div class="mt-4 pt-4 border-t border-slate-800 flex items-center justify-between">
                        <label class="flex items-center gap-2 cursor-pointer text-sm text-slate-300">
                            <input type="checkbox" id="theatresOnly" checked class="w-4 h-4 rounded text-blue-600 bg-slate-900 border-slate-700 focus:ring-blue-500 focus:ring-offset-slate-800">
                            Official Lecture Theatres Only
                        </label>
                        <button id="searchBtn" class="bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm px-5 py-2 rounded-xl transition shadow-lg shadow-blue-600/20">
                            Update Results
                        </button>
                    </div>
                </div>

                <div class="flex items-center justify-between mb-4 px-1">
                    <h2 id="querySummary" class="text-slate-300 font-medium text-sm">Searching...</h2>
                    <span id="roomCountBadge" class="text-xs bg-slate-800 text-slate-400 px-3 py-1 rounded-lg border border-slate-700/80">0 Rooms Found</span>
                </div>

                <div id="resultsGrid" class="grid grid-cols-1 md:grid-cols-2 gap-4"></div>
            </div>
        </div>

        <script>
            const now = new Date();
            now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
            const todayIso = now.toISOString().slice(0,10);
            
            const tomorrow = new Date(now);
            tomorrow.setDate(tomorrow.getDate() + 1);
            const tomorrowIso = tomorrow.toISOString().slice(0,10);

            document.getElementById('customDatetime').value = now.toISOString().slice(0,16);
            
            const dateInput = document.getElementById('timetableDate');
            dateInput.value = todayIso;

            // Tab Switching
            const tabVacant = document.getElementById('tabVacant');
            const tabTimetable = document.getElementById('tabTimetable');
            const vacantPanel = document.getElementById('vacantPanel');
            const timetablePanel = document.getElementById('timetablePanel');

            tabTimetable.addEventListener('click', () => {
                tabTimetable.className = 'px-5 py-2.5 rounded-xl font-bold text-sm bg-blue-600 text-white transition shadow-lg shadow-blue-600/20 flex items-center gap-2';
                tabVacant.className = 'px-5 py-2.5 rounded-xl font-bold text-sm bg-slate-800/80 text-slate-400 hover:text-white transition flex items-center gap-2';
                timetablePanel.classList.remove('hidden');
                vacantPanel.classList.add('hidden');
                fetchTimetable();
            });

            tabVacant.addEventListener('click', () => {
                tabVacant.className = 'px-5 py-2.5 rounded-xl font-bold text-sm bg-blue-600 text-white transition shadow-lg shadow-blue-600/20 flex items-center gap-2';
                tabTimetable.className = 'px-5 py-2.5 rounded-xl font-bold text-sm bg-slate-800/80 text-slate-400 hover:text-white transition flex items-center gap-2';
                vacantPanel.classList.remove('hidden');
                timetablePanel.classList.add('hidden');
                fetchVacantRooms();
            });

            document.getElementById('btnToday').addEventListener('click', () => {
                dateInput.value = todayIso;
                fetchTimetable();
            });

            document.getElementById('btnTomorrow').addEventListener('click', () => {
                dateInput.value = tomorrowIso;
                fetchTimetable();
            });

            document.getElementById('timeMode').addEventListener('change', (e) => {
                const customWrap = document.getElementById('customTimeWrapper');
                if (e.target.value === 'custom') {
                    customWrap.classList.remove('hidden');
                } else {
                    customWrap.classList.add('hidden');
                }
            });

            async function fetchTimetable() {
                const dateVal = dateInput.value;
                const url = `/api/timetable?programme=COMSCI2&date=${dateVal}`;
                const list = document.getElementById('timetableList');
                list.innerHTML = '<div class="text-center py-12 text-slate-500 font-medium animate-pulse">Loading classes...</div>';

                try {
                    const res = await fetch(url);
                    const data = await res.json();

                    list.innerHTML = '';
                    if (data.schedule.length === 0) {
                        list.innerHTML = `
                            <div class="text-center py-16 glass rounded-2xl border border-slate-800/80">
                                <span class="text-4xl block mb-2">🎉</span>
                                <h3 class="text-slate-300 font-bold text-base">No Lectures Scheduled</h3>
                                <p class="text-xs text-slate-500 mt-1">Enjoy your free day or check vacant halls to find a quiet study room!</p>
                            </div>`;
                        return;
                    }

                    data.schedule.forEach(item => {
                        let badgeStyle = 'bg-blue-500/10 text-blue-400 border-blue-500/20';
                        if (item.event_type.includes('Lab') || item.event_type.includes('Practical')) {
                            badgeStyle = 'bg-purple-500/10 text-purple-400 border-purple-500/20';
                        } else if (item.event_type.includes('Tutorial')) {
                            badgeStyle = 'bg-amber-500/10 text-amber-400 border-amber-500/20';
                        } else if (item.event_type.includes('Seminar')) {
                            badgeStyle = 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20';
                        }

                        const card = document.createElement('div');
                        card.className = 'glass border border-slate-800/90 hover:border-slate-700 transition rounded-2xl p-5 shadow-lg flex items-center justify-between gap-4 group';
                        
                        card.innerHTML = `
                            <div class="flex items-start gap-4">
                                <div class="bg-blue-600/10 border border-blue-500/20 text-blue-400 rounded-xl px-3.5 py-2 font-bold text-sm text-center shrink-0">
                                    ${item.time_slot}
                                </div>
                                <div>
                                    <div class="flex items-center gap-2 mb-1">
                                        <h3 class="text-base font-bold text-white group-hover:text-blue-400 transition">${item.module}</h3>
                                        <span class="text-[10px] font-extrabold uppercase tracking-wider px-2 py-0.5 rounded-md border ${badgeStyle}">
                                            ${item.event_type}
                                        </span>
                                    </div>
                                    <div class="flex items-center gap-3 text-xs text-slate-400">
                                        <span class="flex items-center gap-1 font-medium text-slate-300">
                                            📍 ${item.room}
                                        </span>
                                    </div>
                                </div>
                            </div>
                        `;
                        list.appendChild(card);
                    });
                } catch (err) {
                    list.innerHTML = '<div class="text-center py-12 text-rose-400">Error loading timetable schedule.</div>';
                }
            }

            async function fetchVacantRooms() {
                const building = document.getElementById('buildingSelect').value;
                const timeMode = document.getElementById('timeMode').value;
                const theatresOnly = document.getElementById('theatresOnly').checked;
                
                let dtParam = timeMode === 'custom' ? document.getElementById('customDatetime').value : '';

                const url = `/api/vacant?building=${building}&datetime=${dtParam}&theatres_only=${theatresOnly}`;
                const grid = document.getElementById('resultsGrid');
                grid.innerHTML = '<div class="col-span-2 text-center py-12 text-slate-500">Checking room availability...</div>';

                try {
                    const res = await fetch(url);
                    const data = await res.json();

                    document.getElementById('querySummary').textContent = `Showing vacancy for ${data.query_time}`;
                    document.getElementById('roomCountBadge').textContent = `${data.vacant.length} / ${data.total} Free`;

                    grid.innerHTML = '';
                    if (data.vacant.length === 0) {
                        grid.innerHTML = `<div class="col-span-2 text-center py-12 glass rounded-2xl border border-slate-800"><p class="text-slate-400 font-medium">No vacant halls found.</p></div>`;
                        return;
                    }

                    data.vacant.forEach(room => {
                        const card = document.createElement('div');
                        card.className = 'glass border border-slate-800 hover:border-slate-700 transition rounded-2xl p-5 flex items-center justify-between group shadow-sm';
                        card.innerHTML = `
                            <div>
                                <h3 class="text-lg font-bold text-white group-hover:text-blue-400 transition">${room.name}</h3>
                                <p class="text-xs text-emerald-400 font-medium mt-1 flex items-center gap-1.5">
                                    <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                                    ${room.until}
                                </p>
                            </div>
                            <span class="bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-xs font-semibold px-3 py-1.5 rounded-xl">Available</span>
                        `;
                        grid.appendChild(card);
                    });
                } catch (err) {
                    grid.innerHTML = '<div class="col-span-2 text-center py-12 text-rose-400">Error fetching room data.</div>';
                }
            }

            document.getElementById('searchBtn').addEventListener('click', fetchVacantRooms);
            document.getElementById('buildingSelect').addEventListener('change', fetchVacantRooms);
            document.getElementById('timetableDate').addEventListener('change', fetchTimetable);

            fetchTimetable();
        </script>
    </body>
    </html>
    """
    return render_template_string(html_code, buildings=BUILDINGS)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
