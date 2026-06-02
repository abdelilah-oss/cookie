import os, sqlite3, shutil, tempfile

# Cherche le profil Firefox automatiquement
firefox_base = os.path.expandvars(r"%APPDATA%\Mozilla\Firefox\Profiles")
firefox_path = None

if os.path.exists(firefox_base):
    for profile in os.listdir(firefox_base):
        candidate = os.path.join(firefox_base, profile, "cookies.sqlite")
        if os.path.exists(candidate):
            firefox_path = candidate
            break

if not firefox_path:
    print("Firefox introuvable")
    exit()

tmp = tempfile.mktemp(suffix=".db")
shutil.copy2(firefox_path, tmp)

conn = sqlite3.connect(tmp)
rows = conn.execute("SELECT host, name, value, path, isSecure FROM moz_cookies").fetchall()
conn.close()
os.remove(tmp)

print(f"{len(rows)} cookies récupérés\n")
for host, name, value, path, secure in rows:
    print(f"[{host}] {name} = {value!r}")
