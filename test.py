import os, sqlite3, shutil, tempfile

base = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data")
cookie_path = os.path.join(base, "Default", "Network", "Cookies")

tmp = tempfile.mktemp(suffix=".db")
shutil.copy2(cookie_path, tmp)

conn = sqlite3.connect(tmp)
rows = conn.execute("SELECT host_key, name, encrypted_value FROM cookies LIMIT 20").fetchall()
conn.close()
os.remove(tmp)

for host, name, enc in rows:
    prefix = bytes(enc[:3]) if enc else b""
    print(f"[{host}] {name} → préfixe: {prefix}")
