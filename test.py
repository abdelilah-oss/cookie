import subprocess
import requests
import websocket
import json
import time
import os

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
DEBUG_PORT = 9222
PROFILE    = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data")


def launch_edge_debug():
    """Lance Edge en mode remote debugging (Edge doit être fermé avant)."""
    subprocess.Popen([
        EDGE_PATH,
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
    ])
    # Attendre qu'Edge soit prêt
    for _ in range(10):
        try:
            requests.get(f"http://localhost:{DEBUG_PORT}/json", timeout=1)
            return True
        except Exception:
            time.sleep(1)
    raise RuntimeError("Edge n'a pas démarré en mode debug dans les temps")


def get_all_cookies():
    """Récupère tous les cookies via le protocole CDP."""
    # Trouver un target actif
    targets = requests.get(f"http://localhost:{DEBUG_PORT}/json").json()

    # Prendre le premier onglet disponible
    ws_url = None
    for t in targets:
        if t.get("type") == "page":
            ws_url = t["webSocketUrl"]
            break

    if not ws_url:
        raise RuntimeError("Aucun onglet Edge trouvé")

    ws = websocket.create_connection(ws_url, timeout=10)

    # Activer le domaine Network (nécessaire pour getAllCookies)
    ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
    ws.recv()

    # Récupérer tous les cookies
    ws.send(json.dumps({"id": 2, "method": "Network.getAllCookies"}))
    result = json.loads(ws.recv())
    ws.close()

    return result.get("result", {}).get("cookies", [])


if __name__ == "__main__":
    print("Ferme Edge s'il est ouvert, puis appuie sur Entrée...")
    input()

    launch_edge_debug()
    print("Edge lancé en mode debug, récupération des cookies...")

    cookies = get_all_cookies()
    print(f"{len(cookies)} cookies récupérés\n")

    for c in cookies:
        print(f"[{c['domain']}] {c['name']} = {c['value']!r}")
