import os, json, struct

def decompress_mozlz4(path):
    with open(path, "rb") as f:
        magic = f.read(8)
        assert magic == b"mozLz40\0", "Pas un fichier mozLz4"
        
        # Lire la taille décompressée (4 bytes little-endian)
        uncompressed_size = struct.unpack("<I", f.read(4))[0]
        compressed_data = f.read()
    
    return lz4_block_decompress(compressed_data, uncompressed_size)

def lz4_block_decompress(data, max_size):
    result = bytearray()
    i = 0
    
    while i < len(data):
        token = data[i]
        i += 1
        
        # Longueur des literals
        lit_len = (token >> 4) & 0xF
        if lit_len == 15:
            while i < len(data):
                extra = data[i]; i += 1
                lit_len += extra
                if extra != 255:
                    break
        
        # Copier les literals
        result.extend(data[i:i + lit_len])
        i += lit_len
        
        # Fin de stream
        if i >= len(data):
            break
        
        # Offset de correspondance (2 bytes little-endian)
        offset = struct.unpack_from("<H", data, i)[0]
        i += 2
        if offset == 0:
            break
        
        # Longueur de la correspondance
        match_len = (token & 0xF) + 4
        if (token & 0xF) == 15:
            while i < len(data):
                extra = data[i]; i += 1
                match_len += extra
                if extra != 255:
                    break
        
        # Copier depuis le buffer (peut se chevaucher)
        match_pos = len(result) - offset
        for _ in range(match_len):
            result.append(result[match_pos])
            match_pos += 1
    
    return bytes(result)


# --- Lecture des cookies de session ---
firefox_base = os.path.expandvars(r"%APPDATA%\Mozilla\Firefox\Profiles")
session_path = None

for profile in os.listdir(firefox_base):
    candidate = os.path.join(firefox_base, profile, "sessionstore.jsonlz4")
    if os.path.exists(candidate):
        session_path = candidate
        break

if not session_path:
    print("sessionstore.jsonlz4 introuvable")
    exit()

data = decompress_mozlz4(session_path)
session = json.loads(data)

cookies = session.get("cookies", [])
print(f"{len(cookies)} cookies de session trouvés\n")
for c in cookies:
    print(f"[{c.get('host')}] {c.get('name')} = {c.get('value')!r}")
