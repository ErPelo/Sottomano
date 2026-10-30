# -*- coding: utf-8 -*-
# Sottomano - disinstallazione (avviata da disinstalla.bat)
# Copyright (C) 2026 Tommaso Pelosin - Licenza AGPL-3.0 (vedi LICENSE)
#
# Rimuove Sottomano e SOLO cio' che Sottomano ha installato (elencato in installato.txt).
# Programmi e librerie che avevi gia' prima non vengono toccati.
# I programmi installati con winget (e la cartella di Python, se l'aveva installato Sottomano)
# vengono rimossi da disinstalla.bat DOPO che questo script e' terminato.

import os
import sys
import ctypes
import shutil
import subprocess
import time
from pathlib import Path

DEST = Path(os.environ["LOCALAPPDATA"]) / "Sottomano"
MENU_START = Path(os.environ["APPDATA"]) / r"Microsoft\Windows\Start Menu\Programs"
REGISTRO = DEST / "installato.txt"
DOPO = Path(os.environ["TEMP"]) / "sottomano_dopo.txt"
NOMI = {"Python.Python.3.12": "Python 3.12", "7zip.7zip": "7-Zip", "UB-Mannheim.TesseractOCR": "Tesseract OCR"}


def leggi_registro():
    if not REGISTRO.exists():
        return []
    righe = []
    for r in REGISTRO.read_text(encoding="utf-8", errors="replace").splitlines():
        r = r.strip()
        if r and not r.startswith("#") and r not in righe:
            righe.append(r)
    return righe


def sblocca_tutto():
    """Prima di disinstallare, tutto cio' che Sottomano ha bloccato con password va sbloccato:
    senza Sottomano non ci sarebbe piu' modo di aprirlo. Chiede la password elemento per elemento."""
    import getpass
    sys.path.insert(0, str(DEST))
    try:
        import blocco
    except ImportError:
        return True
    reg = blocco.leggi()
    if not reg:
        return True
    voci = list(reg.values())
    print(f"\nPrima di disinstallare sblocco gli elementi protetti con password ({len(voci)}).")
    print("Per ognuno scrivi la password (non si vede mentre scrivi). Invio a vuoto = annulla.\n")
    for i, v in enumerate(voci, 1):
        p = v["percorso"]
        tipo = "Cartella" if v.get("cartella") else "File"
        print(f"{tipo} {i} di {len(voci)}: {p}")
        if not os.path.exists(p):
            print("  Non trovato: forse è stato spostato insieme alla cartella che lo contiene.")
            if not input("  Lo salto e continuo? [s/N] ").strip().lower().startswith(("s", "y")):
                print("Disinstallazione annullata: rimetti l'elemento al suo posto e riprova.")
                return False
            blocco.dimentica(p)
            print()
            continue
        if v["stato"] != "bloccato":
            blocco.togli(p)
            print("  Era già aperto: protezione tolta.\n")
            continue
        while True:
            pw = getpass.getpass("Password: ")
            if not pw:
                print("\nDisinstallazione annullata: non ho rimosso niente "
                      "(gli elementi già sbloccati restano sbloccati).")
                return False
            if blocco.togli(p, pw):
                print("  Sbloccato.\n")
                break
            print("  Password sbagliata, riprova.")
    print("Tutto sbloccato.\n")
    return True


def main():
    voci = leggi_registro()
    winget = [r.split(" ", 1)[1] for r in voci if r.startswith("winget ")]
    pip = [r.split(" ", 1)[1] for r in voci if r.startswith("pip ")]
    cartelle = [r.split(" ", 1)[1] for r in voci if r.startswith("cartella ")]
    file = [r.split(" ", 1)[1] for r in voci if r.startswith("file ")]
    cartella_python = [r.split(" ", 1)[1] for r in voci if r.startswith("python ")]
    python_nostro = any(w.startswith("Python.") for w in winget)
    if python_nostro:
        pip = []   # le librerie se ne vanno insieme a Python

    print("Verranno rimossi:")
    print("  - Sottomano (la sua cartella, il collegamento nel menu Start e l'avvio automatico)")
    for w in winget:
        print(f"  - {NOMI.get(w, w)}  (installato da Sottomano)")
    if pip:
        print(f"  - librerie Python installate da Sottomano: {', '.join(pip)}")
    for c in cartelle + file:
        print(f"  - {c}")
    if not REGISTRO.exists():
        print("\n  (Nessun registro trovato: rimuovo solo Sottomano.)")
    try:
        sys.path.insert(0, str(DEST))
        import blocco
        n_bloccati = len(blocco.leggi())
    except Exception:
        n_bloccati = 0
    if n_bloccati:
        print(f"\n  Hai {n_bloccati} elementi bloccati con password: prima di disinstallare ti chiedo le password per sbloccarli.")
    print("\nTutto quello che avevi gia' prima di installare Sottomano NON viene toccato.")
    if not input("\nProcedo? [s/N] ").strip().lower().startswith(("s", "y")):
        print("Annullato: non ho rimosso niente.")
        return 1
    if not sblocca_tutto():
        return 1

    # 1. chiudo Sottomano (come cliccare Esci) e lascio che rilasci i file
    hwnd = ctypes.windll.user32.FindWindowW("SottomanoServizio", None)
    if hwnd:
        ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
        time.sleep(2)

    # 2. collegamenti
    for lnk in (MENU_START / "Sottomano.lnk", MENU_START / "Startup" / "Sottomano.lnk"):
        if lnk.exists():
            lnk.unlink()
    print("Collegamenti rimossi")

    # 3. librerie Python (solo se Python era gia' tuo: altrimenti se ne va tutto con Python)
    if pip:
        print("Rimuovo le librerie Python installate da Sottomano...")
        subprocess.call([sys.executable, "-m", "pip", "uninstall", "-y", "--disable-pip-version-check", *pip])

    # 4. modelli AI e altri file creati da Sottomano
    for c in cartelle:
        shutil.rmtree(c, ignore_errors=True)
    for f in file:
        Path(f).unlink(missing_ok=True)

    # 5. programmi winget e cartella di Python: li toglie disinstalla.bat dopo di me
    #    (non posso disinstallare Python mentre lo sto usando)
    with open(DOPO, "w", encoding="utf-8") as fh:
        for w in winget:
            fh.write(f"winget {w}\n")
        for c in cartella_python:
            fh.write(f"cartella {c}\n")

    # 6. cartella di Sottomano (il .bat che mi ha avviato la cancella per ultimo)
    qui = Path(__file__).resolve().parent
    if DEST.exists():
        for p in DEST.iterdir():
            if qui == DEST and p.name == "disinstalla.bat":
                continue
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    print("Sottomano rimosso")
    return 0


if __name__ == "__main__":
    sys.exit(main())
