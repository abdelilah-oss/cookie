import os, json, struct, sqlite3, shutil, tempfile

# ════════════════════════════════════════════════════
#  DÉCOMPRESSEUR mozLz4 pur Python (zéro dépendance)
# ════════════════════════════════════════════════════

def lz4_block_decompress(data):
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
        if magic != b"mozLz40\0":
            raise ValueError(f"Header invalide : {magic}")
        f.read(4)  # taille décompressée (non utilisée)
        compressed = f.read()
    return lz4_block_decompress(compressed)

# ════════════════════════════════════════════════════
#  TROUVER LE PROFIL FIREFOX
# ════════════════════════════════════════════════════

def find_firefox_profile():
    firefox_base = os.path.expandvars(r"%APPDATA%\Mozilla\Firefox\Profiles")
    if not os.path.exists(firefox_base):
        raise FileNotFoundError(f"Dossier Firefox introuvable : {firefox_base}")
    
    profiles = [
        os.path.join(firefox_base, p)
        for p in os.listdir(firefox_base)
        if os.path.isdir(os.path.join(firefox_base, p))
    ]
    
    if not profiles:
        raise FileNotFoundError("Aucun profil Firefox trouvé")
    
    # Préférer le profil default-release, sinon le premier
    for p in profiles:
        if "default-release" in p:
            return p
    return profiles[0]

# ════════════════════════════════════════════════════
#  1. COOKIES PERSISTANTS → cookies.sqlite
# ════════════════════════════════════════════════════

def get_sqlite_cookies(profile_path):
    db_path = os.path.join(profile_path, "cookies.sqlite")
    if not os.path.exists(db_path):
        print("  [!] cookies.sqlite introuvable")
        return []
    
    # Copie temporaire car Firefox verrouille le fichier
    tmp = tempfile.mktemp(suffix=".db")
    shutil.copy2(db_path, tmp)
    
    try:
        conn = sqlite3.connect(tmp)
        rows = conn.execute(
            "SELECT host, name, value, path, isSecure, isHttpOnly, expiry FROM moz_cookies"
        ).fetchall()
        conn.close()
    finally:
        os.remove(tmp)
    
    cookies = []
    for host, name, value, path, secure, httponly, expiry in rows:
        cookies.append({
            "host": host, "name": name, "value": value,
            "path": path, "secure": bool(secure),
            "httpOnly": bool(httponly), "expiry": expiry,
            "session": False
        })
    return cookies

# ════════════════════════════════════════════════════
#  2. COOKIES DE SESSION → recovery.jsonlz4
# ════════════════════════════════════════════════════

def get_session_cookies(profile_path):
    # Ordre de priorité des fichiers
    candidates = [
        os.path.join(profile_path, "sessionstore-backups", "recovery.jsonlz4"),
        os.path.join(profile_path, "sessionstore-backups", "previous.jsonlz4"),
        os.path.join(profile_path, "sessionstore.jsonlz4"),
    ]
    
    session_file = None
    for c in candidates:
        if os.path.isfile(c):
            session_file = c
            break
    
    if not session_file:
        print("  [!] Aucun fichier de session trouvé (Firefox fermé ou pas de backup)")
        return []
    
    print(f"  [+] Fichier session : {session_file}")
    
    try:
        data = decompress_mozlz4(session_file)
        session = json.loads(data)
    except Exception as e:
        print(f"  [!] Erreur lecture session : {e}")
        return []
    
    cookies = []
    for c in session.get("cookies", []):
        cookies.append({
            "host": c.get("host", ""),
            "name": c.get("name", ""),
            "value": c.get("value", ""),
            "path": c.get("path", "/"),
            "secure": c.get("secure", False),
            "httpOnly": c.get("httpOnly", False),
            "expiry": None,
            "session": True
        })
    return cookies

# ════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════

def main():
    print("=" * 55)
    print("  Firefox Cookie Extractor")
    print("=" * 55)
    
    try:
        profile = find_firefox_profile()
        print(f"Profil : {profile}\n")
    except FileNotFoundError as e:
        print(f"Erreur : {e}")
        return
    
    print("── Cookies persistants (cookies.sqlite) ──")
    sqlite_cookies = get_sqlite_cookies(profile)
    print(f"  {len(sqlite_cookies)} cookies trouvés\n")
    
    print("── Cookies de session (recovery.jsonlz4) ──")
    session_cookies = get_session_cookies(profile)
    print(f"  {len(session_cookies)} cookies trouvés\n")
    
    all_cookies = sqlite_cookies + session_cookies
    print("=" * 55)
    print(f"  TOTAL : {len(all_cookies)} cookies")
    print("=" * 55)
    
    # Affichage
    print("\n── Tous les cookies ──\n")
    for c in all_cookies:
        tag = "[SESSION]" if c["session"] else "[PERSIST]"
        print(f"{tag} [{c['host']}] {c['name']} = {c['value']!r}")
    
    # Export JSON optionnel
    export_path = os.path.join(os.path.expanduser("~"), "Desktop", "firefox_cookies.json")
    with open(export_path, "w", encoding="utf-8") as f:
        json.dump(all_cookies, f, indent=2, ensure_ascii=False)
    print(f"\n[+] Exporté : {export_path}")

main()
