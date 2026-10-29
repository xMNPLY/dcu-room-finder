import sqlite3
from datetime import datetime
import typer
from InquirerPy import inquirer
from rich.console import Console
from rich.table import Table

app = typer.Typer()
console = Console()

LECTURE_THEATRE_UUID = "289a88ea-eaf1-e5be-9044-807575b4286a"

# Blacklist specialized non-lecture spaces that share the parent tag
EXCLUDED_ROOMS = {
    "GLA.HG00",
    "GLA.HG0017",
    "GLA.HG0018",
    "GLA.HG0019",
    "GLA.HG0020",
}

BUILDINGS = {
    "All Glasnevin Buildings": "ALL",
    "Polaris Building (FT)": "GLA.FT",
    "Stokes Building (S)": "GLA.S",
    "Stokes Extension (SA)": "GLA.SA",
    "McNulty / Computing (L)": "GLA.L",
    "Henry Grattan (C)": "GLA.C",
    "Henry Grattan Extension (CA)": "GLA.CA",
    "DCU Business School (Q)": "GLA.Q",
    "Lonsdale / Science (X)": "GLA.X",
    "Alice Reeves / Nursing (H)": "GLA.H",
    "Marconi / Engineering (N)": "GLA.N",
    "Albert College (A)": "GLA.A",
    "Bea Orpen (D)": "GLA.D",
    "Terence Larkin Theatre (T)": "GLA.T",
    "Mathematical Sciences (F)": "GLA.F",
    "Pavilion / Invent (P)": "GLA.P",
    "Library / O'Reilly (Y)": "GLA.Y",
}

def get_vacant_rooms(building_code: str, theatres_only: bool = False):
    conn = sqlite3.connect("rooms.db")
    cursor = conn.cursor()

    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    cursor.execute("""
        SELECT DISTINCT room_id 
        FROM bookings 
        WHERE substr(start_iso, 1, 19) <= ? 
          AND substr(end_iso, 1, 19) > ?
    """, (now_iso, now_iso))
    
    occupied_ids = {row[0] for row in cursor.fetchall()}

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
    conn.close()

    # Filter out occupied rooms and explicitly blacklisted pods
    vacant = [
        r for r in all_rooms 
        if r[0] not in occupied_ids and r[1] not in EXCLUDED_ROOMS
    ]
    
    total_valid = len([r for r in all_rooms if r[1] not in EXCLUDED_ROOMS])
    return vacant, total_valid

@app.command()
def interactive(
    theatres_only: bool = typer.Option(False, "--theatres-only", "-t", help="Show official lecture theatres only")
):
    """Launch interactive building dropdown menu."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    selected_label = inquirer.select(
        message="Select a Building on Glasnevin Campus:",
        choices=list(BUILDINGS.keys()),
        default="All Glasnevin Buildings"
    ).execute()

    building_code = BUILDINGS[selected_label]
    vacant_list, total_building_rooms = get_vacant_rooms(building_code, theatres_only=theatres_only)

    title = f"Vacant Rooms — {selected_label} ({now_str})"
    if theatres_only:
        title += " [OFFICIAL LECTURE THEATRES ONLY]"

    table = Table(title=title)
    table.add_column("Room Code", style="bold cyan", no_wrap=True)
    table.add_column("Status", style="bold green")

    for room_id, room_name, _ in vacant_list:
        table.add_row(room_name, "Free Right Now")

    console.print()
    console.print(table)
    console.print(f"\n[bold green]Free Rooms Found:[/bold green] {len(vacant_list)} / {total_building_rooms}")

if __name__ == "__main__":
    app()
