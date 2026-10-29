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

    # Fetch room query
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

    # Filter out blacklisted pods
    valid_rooms = [r for r in all_rooms if r[1] not in EXCLUDED_ROOMS]

    vacant_results = []

    for r_id, r_name, _ in valid_rooms:
        # Check if occupied at target_dt
        cursor.execute("""
            SELECT start_iso, end_iso FROM bookings 
            WHERE room_id = ? 
              AND substr(start_iso, 1, 19) <= ? 
              AND substr(end_iso, 1, 19) > ?
        """, (r_id, target_iso, target_iso))
        
        current_booking = cursor.fetchone()

        if not current_booking:
            # Room is free! Find next booking starting after target_dt on same day
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

@app.route("/")
def index():
    html_code = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>DCU Vacant Lecture Halls</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
        <style>
            body { font-family: 'Inter', sans-serif; }
        </style>
    </head>
    <body class="bg-slate-900 text-slate-100 min-h-screen">
        <div class="max-w-4xl mx-auto px-4 py-8">
            <!-- Header -->
            <div class="flex items-center justify-between border-b border-slate-800 pb-6 mb-8">
                <div>
                    <h1 class="text-3xl font-bold tracking-tight text-white flex items-center gap-3">
                        <span class="bg-blue-600 text-white p-2 rounded-xl text-xl">🏛️</span>
                        DCU Room Finder
                    </h1>
                    <p class="text-slate-400 text-sm mt-1">Real-time vacant lecture theatre scanner for Glasnevin</p>
                </div>
                <div class="inline-flex items-center gap-2 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 px-3 py-1.5 rounded-full text-xs font-semibold">
                    <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                    Live Schedule Sync
                </div>
            </div>

            <!-- Controls Panel -->
            <div class="bg-slate-800/60 border border-slate-700/60 rounded-2xl p-6 mb-8 backdrop-blur-xl shadow-xl">
                <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    <!-- Building Select -->
                    <div>
                        <label class="block text-xs font-medium text-slate-400 mb-1.5">Select Building</label>
                        <select id="buildingSelect" class="w-full bg-slate-900 border border-slate-700 text-white text-sm rounded-xl px-3 py-2.5 focus:ring-2 focus:ring-blue-500 focus:outline-none">
                            {% for code, label in buildings.items() %}
                            <option value="{{ code }}">{{ label }}</option>
                            {% endfor %}
                        </select>
                    </div>

                    <!-- Date/Time Mode -->
                    <div>
                        <label class="block text-xs font-medium text-slate-400 mb-1.5">Target Time</label>
                        <select id="timeMode" class="w-full bg-slate-900 border border-slate-700 text-white text-sm rounded-xl px-3 py-2.5 focus:ring-2 focus:ring-blue-500 focus:outline-none">
                            <option value="now">Right Now (Live)</option>
                            <option value="custom">Custom Date & Time</option>
                        </select>
                    </div>

                    <!-- Custom Datetime Picker (Hidden by default) -->
                    <div id="customTimeWrapper" class="hidden">
                        <label class="block text-xs font-medium text-slate-400 mb-1.5">Pick Date & Time</label>
                        <input type="datetime-local" id="customDatetime" class="w-full bg-slate-900 border border-slate-700 text-white text-sm rounded-xl px-3 py-2.5 focus:ring-2 focus:ring-blue-500 focus:outline-none">
                    </div>
                </div>

                <!-- Toggle Options -->
                <div class="mt-4 pt-4 border-t border-slate-700/40 flex items-center justify-between">
                    <label class="flex items-center gap-2 cursor-pointer text-sm text-slate-300">
                        <input type="checkbox" id="theatresOnly" checked class="w-4 h-4 rounded text-blue-600 bg-slate-900 border-slate-700 focus:ring-blue-500 focus:ring-offset-slate-800">
                        Official Lecture Theatres Only
                    </label>
                    <button id="searchBtn" class="bg-blue-600 hover:bg-blue-500 text-white font-medium text-sm px-5 py-2 rounded-xl transition shadow-lg shadow-blue-600/20">
                        Update Results
                    </button>
                </div>
            </div>

            <!-- Status Banner -->
            <div class="flex items-center justify-between mb-4 px-1">
                <h2 id="querySummary" class="text-slate-300 font-medium text-sm">Searching...</h2>
                <span id="roomCountBadge" class="text-xs bg-slate-800 text-slate-400 px-2.5 py-1 rounded-lg border border-slate-700">0 Rooms Found</span>
            </div>

            <!-- Results Grid -->
            <div id="resultsGrid" class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <!-- Cards injected dynamically -->
            </div>
        </div>

        <script>
            // Set default datetime to now in local ISO string format
            const now = new Date();
            now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
            document.getElementById('customDatetime').value = now.toISOString().slice(0,16);

            document.getElementById('timeMode').addEventListener('change', (e) => {
                const customWrap = document.getElementById('customTimeWrapper');
                if (e.target.value === 'custom') {
                    customWrap.classList.remove('hidden');
                } else {
                    customWrap.classList.add('hidden');
                }
            });

            async function fetchVacantRooms() {
                const building = document.getElementById('buildingSelect').value;
                const timeMode = document.getElementById('timeMode').value;
                const theatresOnly = document.getElementById('theatresOnly').checked;
                
                let dtParam = '';
                if (timeMode === 'custom') {
                    dtParam = document.getElementById('customDatetime').value;
                }

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
                        grid.innerHTML = `
                            <div class="col-span-2 text-center py-12 bg-slate-800/30 rounded-2xl border border-slate-800">
                                <p class="text-slate-400 text-base font-medium">No vacant halls found for this time slot.</p>
                                <p class="text-slate-600 text-xs mt-1">Try selecting a different building or checking another time.</p>
                            </div>
                        `;
                        return;
                    }

                    data.vacant.forEach(room => {
                        const card = document.createElement('div');
                        card.className = 'bg-slate-800/40 border border-slate-700/50 hover:border-slate-600 transition rounded-2xl p-5 flex items-center justify-between group shadow-sm';
                        card.innerHTML = `
                            <div>
                                <h3 class="text-lg font-bold text-white group-hover:text-blue-400 transition">${room.name}</h3>
                                <p class="text-xs text-emerald-400 font-medium mt-1 flex items-center gap-1.5">
                                    <span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                                    ${room.until}
                                </p>
                            </div>
                            <span class="bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-xs font-semibold px-3 py-1.5 rounded-xl">
                                Available
                            </span>
                        `;
                        grid.appendChild(card);
                    });

                } catch (err) {
                    grid.innerHTML = '<div class="col-span-2 text-center py-12 text-rose-400">Error fetching schedule data. Make sure rooms.db is updated.</div>';
                }
            }

            document.getElementById('searchBtn').addEventListener('click', fetchVacantRooms);
            document.getElementById('buildingSelect').addEventListener('change', fetchVacantRooms);

            // Initial load
            fetchVacantRooms();
        </script>
    </body>
    </html>
    """
    return render_template_string(html_code, buildings=BUILDINGS)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
