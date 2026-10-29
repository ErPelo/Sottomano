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
    print("\nTutto quello che avevi gia' prima di installare Sottomano NON viene toccato.")
    if not input("\nProcedo? [s/N] ").strip().lower().startswith(("s", "y")):
        print("Annullato: non ho rimosso niente.")
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
