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
    "ALL": "All Buildings",
    "GLA.FT": "Polaris (FT)",
    "GLA.S": "Stokes (S)",
    "GLA.SA": "Stokes Ext (SA)",
    "GLA.L": "McNulty (L)",
    "GLA.C": "Henry Grattan (C)",
    "GLA.CA": "Grattan Ext (CA)",
    "GLA.Q": "Business School (Q)",
    "GLA.X": "Lonsdale (X)",
    "GLA.H": "Nursing (H)",
    "GLA.N": "Engineering (N)",
    "GLA.A": "Albert College (A)",
    "GLA.T": "Larkin Theatre (T)",
    "GLA.F": "Maths (F)",
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
                free_until_str = "Free for the rest of the day"

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
        "query_time": target_dt.strftime("%a, %b %d • %H:%M")
    })

@app.route("/")
def index():
    html_code = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>DCU Room Finder</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
        <style>
            body { 
                font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif; 
                -webkit-tap-highlight-color: transparent;
            }
            .hide-scrollbar::-webkit-scrollbar { display: none; }
            .hide-scrollbar { -ms-overflow-style: none; scrollbar-width: none; }
        </style>
    </head>
    <body class="bg-[#F8FAFC] text-slate-800 min-h-screen pb-12 antialiased">
        
        <!-- Sticky Header -->
        <header class="sticky top-0 z-30 bg-[#1A3C66] text-white px-5 py-4 shadow-md">
            <div class="max-w-xl mx-auto flex items-center justify-between">
                <div>
                    <h1 class="text-xl font-bold tracking-tight">DCU Room Finder</h1>
                    <p class="text-xs text-blue-200 mt-0.5">Glasnevin Campus Vacancies</p>
                </div>
                <div id="liveBadge" class="flex items-center gap-1.5 bg-white/10 px-3 py-1 rounded-full text-xs font-medium text-blue-100 backdrop-blur-sm">
                    <span class="w-2 h-2 rounded-full bg-emerald-400"></span>
                    Live
                </div>
            </div>
        </header>

        <main class="max-w-xl mx-auto px-4 pt-5 space-y-5">
            
            <!-- Controls Card -->
            <div class="bg-white rounded-2xl p-4 shadow-sm border border-slate-200/80 space-y-4">
                
                <!-- Horizontal Scrollable Building Selector -->
                <div>
                    <label class="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Building</label>
                    <div class="flex gap-2 overflow-x-auto hide-scrollbar -mx-1 px-1 py-1" id="buildingChips">
                        {% for code, label in buildings.items() %}
                        <button 
                            data-code="{{ code }}"
                            class="building-chip whitespace-nowrap px-3.5 py-2 rounded-xl text-xs font-semibold transition border border-slate-200 text-slate-600 bg-slate-50 active:scale-95 flex-shrink-0 first:ml-0"
                        >
                            {{ label }}
                        </button>
                        {% endfor %}
                    </div>
                </div>

                <hr class="border-slate-100">

                <!-- Time Filter Bar -->
                <div class="space-y-3">
                    <div class="flex items-center justify-between">
                        <span class="text-xs font-semibold text-slate-500 uppercase tracking-wider">When</span>
                        
                        <!-- Toggle Buttons -->
                        <div class="bg-slate-100 p-1 rounded-xl flex gap-1">
                            <button id="btnTimeNow" class="px-3 py-1 rounded-lg text-xs font-semibold bg-white text-slate-900 shadow-sm transition">
                                Now
                            </button>
                            <button id="btnTimeCustom" class="px-3 py-1 rounded-lg text-xs font-semibold text-slate-600 hover:text-slate-900 transition">
                                Later
                            </button>
                        </div>
                    </div>

                    <!-- Custom Picker Box -->
                    <div id="customTimeBox" class="hidden pt-1">
                        <input 
                            type="datetime-local" 
                            id="customDatetime" 
                            class="w-full bg-slate-50 border border-slate-200 text-slate-800 text-sm font-medium rounded-xl px-3.5 py-2.5 focus:outline-none focus:ring-2 focus:ring-[#1A3C66] focus:border-transparent"
                        >
                    </div>
                </div>

                <!-- Lecture Theatre Checkbox -->
                <div class="pt-2 flex items-center justify-between text-xs text-slate-600 border-t border-slate-100">
                    <label for="theatresOnly" class="flex items-center gap-2 cursor-pointer py-1 font-medium select-none">
                        <input type="checkbox" id="theatresOnly" checked class="w-4 h-4 rounded text-[#1A3C66] focus:ring-[#1A3C66] border-slate-300">
                        Lecture halls only
                    </label>
                    <button id="refreshBtn" class="text-xs font-bold text-[#1A3C66] hover:underline px-1 py-1">
                        Update
                    </button>
                </div>

            </div>

            <!-- Results Section Header -->
            <div class="flex items-center justify-between px-1">
                <div>
                    <h2 class="text-base font-bold text-slate-900" id="statusHeading">Available Rooms</h2>
                    <p class="text-xs text-slate-500 font-medium mt-0.5" id="querySummary">Loading...</p>
                </div>
                <span id="roomCountBadge" class="bg-blue-50 text-[#1A3C66] text-xs font-bold px-3 py-1 rounded-full border border-blue-100">
                    -- Free
                </span>
            </div>

            <!-- Results List -->
            <div id="resultsGrid" class="space-y-3">
                <!-- Room items rendered dynamically -->
            </div>

        </main>

        <script>
            let currentBuilding = 'ALL';
            let timeMode = 'now';

            // Initialize building chips
            const chips = document.querySelectorAll('.building-chip');
            chips.forEach(chip => {
                if (chip.dataset.code === currentBuilding) {
                    chip.classList.remove('bg-slate-50', 'text-slate-600', 'border-slate-200');
                    chip.classList.add('bg-[#1A3C66]', 'text-white', 'border-[#1A3C66]');
                }

                chip.addEventListener('click', () => {
                    chips.forEach(c => {
                        c.classList.remove('bg-[#1A3C66]', 'text-white', 'border-[#1A3C66]');
                        c.classList.add('bg-slate-50', 'text-slate-600', 'border-slate-200');
                    });
                    chip.classList.remove('bg-slate-50', 'text-slate-600', 'border-slate-200');
                    chip.classList.add('bg-[#1A3C66]', 'text-white', 'border-[#1A3C66]');
                    currentBuilding = chip.dataset.code;
                    fetchVacantRooms();
                });
            });

            // Set local default time for datetime-local
            const now = new Date();
            now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
            document.getElementById('customDatetime').value = now.toISOString().slice(0, 16);

            // Time Mode Toggle
            const btnTimeNow = document.getElementById('btnTimeNow');
            const btnTimeCustom = document.getElementById('btnTimeCustom');
            const customTimeBox = document.getElementById('customTimeBox');

            btnTimeNow.addEventListener('click', () => {
                timeMode = 'now';
                btnTimeNow.className = 'px-3 py-1 rounded-lg text-xs font-semibold bg-white text-slate-900 shadow-sm transition';
                btnTimeCustom.className = 'px-3 py-1 rounded-lg text-xs font-semibold text-slate-600 hover:text-slate-900 transition';
                customTimeBox.classList.add('hidden');
                document.getElementById('liveBadge').classList.remove('opacity-40');
                fetchVacantRooms();
            });

            btnTimeCustom.addEventListener('click', () => {
                timeMode = 'custom';
                btnTimeCustom.className = 'px-3 py-1 rounded-lg text-xs font-semibold bg-white text-slate-900 shadow-sm transition';
                btnTimeNow.className = 'px-3 py-1 rounded-lg text-xs font-semibold text-slate-600 hover:text-slate-900 transition';
                customTimeBox.classList.remove('hidden');
                document.getElementById('liveBadge').classList.add('opacity-40');
                fetchVacantRooms();
            });

            document.getElementById('customDatetime').addEventListener('change', () => {
                if (timeMode === 'custom') fetchVacantRooms();
            });

            document.getElementById('theatresOnly').addEventListener('change', fetchVacantRooms);
            document.getElementById('refreshBtn').addEventListener('click', fetchVacantRooms);

            async function fetchVacantRooms() {
                const theatresOnly = document.getElementById('theatresOnly').checked;
                let dtParam = '';
                
                if (timeMode === 'custom') {
                    dtParam = document.getElementById('customDatetime').value;
                }

                const url = `/api/vacant?building=${currentBuilding}&datetime=${dtParam}&theatres_only=${theatresOnly}`;
                const container = document.getElementById('resultsGrid');
                
                container.innerHTML = `
                    <div class="bg-white rounded-2xl p-8 text-center text-slate-400 border border-slate-200/80">
                        <p class="text-sm font-medium">Checking schedules...</p>
                    </div>
                `;

                try {
                    const res = await fetch(url);
                    const data = await res.json();

                    document.getElementById('querySummary').textContent = data.query_time;
                    document.getElementById('roomCountBadge').textContent = `${data.vacant.length} of ${data.total} Free`;

                    container.innerHTML = '';

                    if (data.vacant.length === 0) {
                        container.innerHTML = `
                            <div class="bg-white rounded-2xl p-8 text-center border border-slate-200/80">
                                <p class="text-slate-700 font-semibold text-sm">No free rooms right now</p>
                                <p class="text-slate-400 text-xs mt-1">Try picking a different building or checking another time.</p>
                            </div>
                        `;
                        return;
                    }

                    data.vacant.forEach(room => {
                        const card = document.createElement('div');
                        card.className = 'bg-white rounded-2xl p-4 border border-slate-200/80 shadow-sm flex items-center justify-between gap-3';
                        card.innerHTML = `
                            <div>
                                <h3 class="text-base font-bold text-slate-900 tracking-tight">${room.name}</h3>
                                <p class="text-xs text-emerald-700 font-semibold mt-1 flex items-center gap-1.5">
                                    <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                                    ${room.until}
                                </p>
                            </div>
                            <span class="flex-shrink-0 bg-emerald-50 text-emerald-700 font-bold text-xs px-2.5 py-1.5 rounded-xl border border-emerald-200/60">
                                Free
                            </span>
                        `;
                        container.appendChild(card);
                    });

                } catch (err) {
                    container.innerHTML = `
                        <div class="bg-rose-50 text-rose-800 rounded-2xl p-4 border border-rose-200 text-xs font-medium text-center">
                            Failed to load room schedules. Check connection or database status.
                        </div>
                    `;
                }
            }

            // Initial fetch
            fetchVacantRooms();
        </script>
    </body>
    </html>
    """
    return render_template_string(html_code, buildings=BUILDINGS)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
