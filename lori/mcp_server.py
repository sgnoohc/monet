#!/usr/bin/env python3
"""MCP server for lori — exposes driving time and location tools."""

import json
import sys
import pathlib

import requests
import yaml

LORI_DIR = pathlib.Path.home() / ".lori"
LOCATIONS_FILE = LORI_DIR / "locations.yaml"

OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def load_locations():
    if not LOCATIONS_FILE.exists():
        return {}
    with open(LOCATIONS_FILE) as f:
        data = yaml.safe_load(f)
    return data or {}


def save_locations(locs):
    LOCATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCATIONS_FILE, "w") as f:
        yaml.dump(locs, f, default_flow_style=False, sort_keys=False)


def geocode(address):
    resp = requests.get(NOMINATIM_URL, params={
        "q": address, "format": "json", "limit": 1
    }, headers={"User-Agent": "lori-mcp-server/1.0"}, timeout=10)
    resp.raise_for_status()
    results = resp.json()
    if not results:
        return None
    return (float(results[0]["lat"]), float(results[0]["lon"]))


def resolve_location(name_or_addr):
    locations = load_locations()
    if name_or_addr in locations:
        loc = locations[name_or_addr]
        if "coords" in loc and loc["coords"]:
            return tuple(loc["coords"]), locations
        if "address" in loc:
            coords = geocode(loc["address"])
            if coords:
                locations[name_or_addr]["coords"] = list(coords)
                save_locations(locations)
                return coords, locations
    # Try geocoding directly
    coords = geocode(name_or_addr)
    return coords, locations


def get_driving_time(from_coords, to_coords):
    coords_str = f"{from_coords[1]},{from_coords[0]};{to_coords[1]},{to_coords[0]}"
    url = f"{OSRM_URL}/{coords_str}"
    resp = requests.get(url, params={"overview": "false"}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        return None
    route = data["routes"][0]
    return {
        "duration_seconds": route["duration"],
        "duration_minutes": round(route["duration"] / 60, 1),
        "distance_km": round(route["distance"] / 1000, 1),
        "distance_miles": round(route["distance"] / 1609.34, 1),
    }


# ─── MCP Protocol ────────────────────────────────────────────────────────────

def send_response(response):
    line = json.dumps(response)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def handle_initialize(req):
    return {
        "jsonrpc": "2.0",
        "id": req["id"],
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "lori-mcp", "version": "1.0.0"},
        },
    }


def handle_tools_list(req):
    return {
        "jsonrpc": "2.0",
        "id": req["id"],
        "result": {
            "tools": [
                {
                    "name": "get_driving_time",
                    "description": "Get driving time and distance between two locations. Locations can be saved names (from ~/.lori/locations.yaml) or full addresses.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "from": {"type": "string", "description": "Origin location name or address"},
                            "to": {"type": "string", "description": "Destination location name or address"},
                        },
                        "required": ["from", "to"],
                    },
                },
                {
                    "name": "add_location",
                    "description": "Save a named location with address. Coordinates are geocoded automatically.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Short name for the location (e.g., 'lab', 'airport')"},
                            "address": {"type": "string", "description": "Full address to geocode"},
                        },
                        "required": ["name", "address"],
                    },
                },
            ]
        },
    }


def handle_tool_call(req):
    params = req.get("params", {})
    tool = params.get("name")
    args = params.get("arguments", {})

    if tool == "get_driving_time":
        from_loc = args.get("from", "")
        to_loc = args.get("to", "")
        try:
            from_coords, _ = resolve_location(from_loc)
            to_coords, _ = resolve_location(to_loc)
            if not from_coords:
                text = f"Could not resolve location: {from_loc}"
            elif not to_coords:
                text = f"Could not resolve location: {to_loc}"
            else:
                info = get_driving_time(from_coords, to_coords)
                if info:
                    text = (f"{from_loc} → {to_loc}\n"
                            f"Duration: {int(info['duration_minutes'])} min\n"
                            f"Distance: {info['distance_miles']:.1f} mi ({info['distance_km']:.1f} km)")
                else:
                    text = "Could not calculate route."
        except Exception as e:
            text = f"Error: {e}"

        return {
            "jsonrpc": "2.0",
            "id": req["id"],
            "result": {"content": [{"type": "text", "text": text}]},
        }

    elif tool == "add_location":
        name = args.get("name", "")
        address = args.get("address", "")
        try:
            coords = geocode(address)
            locations = load_locations()
            locations[name] = {"address": address}
            if coords:
                locations[name]["coords"] = list(coords)
            save_locations(locations)
            text = f"Saved location '{name}': {address}"
            if coords:
                text += f" ({coords[0]:.4f}, {coords[1]:.4f})"
        except Exception as e:
            text = f"Error: {e}"

        return {
            "jsonrpc": "2.0",
            "id": req["id"],
            "result": {"content": [{"type": "text", "text": text}]},
        }

    return {
        "jsonrpc": "2.0",
        "id": req["id"],
        "error": {"code": -32601, "message": f"Unknown tool: {tool}"},
    }


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = req.get("method", "")

        if method == "initialize":
            send_response(handle_initialize(req))
        elif method == "notifications/initialized":
            pass  # no response needed
        elif method == "tools/list":
            send_response(handle_tools_list(req))
        elif method == "tools/call":
            send_response(handle_tool_call(req))
        elif method == "ping":
            send_response({"jsonrpc": "2.0", "id": req["id"], "result": {}})
        else:
            if "id" in req:
                send_response({
                    "jsonrpc": "2.0",
                    "id": req["id"],
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                })


if __name__ == "__main__":
    main()
