import os, json, struct

# ─── Décompresseur mozLz4 pur Python ───────────────────────────────────────

def lz4_block_decompress(data, max_size):
    result = bytearray()
    i = 0
    while i < len(data):
        token = data[i]; i += 1
        lit_len = (token >> 4) & 0xF
        if lit_len == 15:
            while i < len(data):
                extra = data[i]; i += 1
                lit_len += extra
                if extra != 255:
                    break
        result.extend(data[i:i + lit_len])
        i += lit_len
        if i >= len(data):
            break
        offset = struct.unpack_from("<H", data, i)[0]; i += 2
        if offset == 0:
            break
        match_len = (token & 0xF) + 4
        if (token & 0xF) == 15:
            while i < len(data):
                extra = data[i]; i += 1
                match_len += extra
                if extra != 255:
                    break
        match_pos = len(result) - offset
        for _ in range(match_len):
            result.append(result[match_pos])
            match_pos += 1
    return bytes(result)

def decompress_mozlz4(path):
    with open(path, "rb") as f:
        magic = f.read(8)
        assert magic == b"mozLz40\0", "Pas un fichier mozLz4"
        uncompressed_size = struct.unpack("<I", f.read(4))[0]
        compressed_data = f.read()
    return lz4_block_decompress(compressed_data, uncompressed_size)

# ─── Recherche dans profil + backup ────────────────────────────────────────

firefox_base = os.path.expandvars(r"%APPDATA%\Mozilla\Firefox\Profiles")

print("=== Fichiers session trouvés ===")
session_path = None

for profile in os.listdir(firefox_base):
    profile_path = os.path.join(firefox_base, profile)
    if not os.path.isdir(profile_path):
        continue
    print(f"\nProfil : {profile}")

    # Dossiers à scanner : racine du profil + sessionstore-backups
    scan_dirs = [profile_path]
    backup_dir = os.path.join(profile_path, "sessionstore-backups")
    if os.path.isdir(backup_dir):
        scan_dirs.append(backup_dir)

    for scan_dir in scan_dirs:
        for f in os.listdir(scan_dir):
            full_path = os.path.join(scan_dir, f)
            if not os.path.isfile(full_path):
                continue
            if "session" in f.lower() or "lz4" in f.lower():
                print(f"  -> {full_path}")
                if session_path is None and f.lower().endswith(".jsonlz4"):
                    session_path = full_path

# ─── Lecture et affichage des cookies ──────────────────────────────────────

if not session_path:
    print("\nAucun sessionstore trouvé.")
    exit()

print(f"\nUtilise : {session_path}")

data = decompress_mozlz4(session_path)
session = json.loads(data)

cookies = session.get("cookies", [])
print(f"\n{len(cookies)} cookies de session trouvés\n")
for c in cookies:
    print(f"[{c.get('host')}] {c.get('name')} = {c.get('value')!r}")
