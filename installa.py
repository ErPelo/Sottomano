# -*- coding: utf-8 -*-
# Sottomano - configurazione (avviata da installa.bat)
# Copyright (C) 2026 Tommaso Pelosin - Licenza AGPL-3.0 (vedi LICENSE)
#
# Cosa fa, e nient'altro:
#   1. installa le librerie Python necessarie (pip)
#   2. scarica i file di lingua OCR italiano/inglese da github.com/tesseract-ocr
#   3. copia i file in %LOCALAPPDATA%\Sottomano
#   4. crea il collegamento "Sottomano" nel menu Start (e, solo se lo chiedi, in Esecuzione automatica)
#   5. avvia Sottomano (icona vicino all'orologio, tasto destro -> Esci per chiuderlo)
#
# Tiene un registro (installato.txt) di cio' che installa e che prima NON c'era:
# disinstalla.bat rimuove solo quello, mai programmi o librerie che avevi gia'.

import os
import sys
import json
import shutil
import subprocess
import urllib.request
from pathlib import Path

SRC = Path(__file__).resolve().parent
DEST = Path(os.environ["LOCALAPPDATA"]) / "Sottomano"
PYTHON = Path(sys.executable)
PYTHONW = PYTHON.with_name("pythonw.exe")
LIBRERIE = ["pillow", "pillow-heif", "pymupdf", "pypdfium2", "pytesseract", "pywin32", "comtypes", "ffpyplayer",
            "imageio-ffmpeg", "qrcode", "zxing-cpp"]
APPDATA = Path(os.environ["APPDATA"])
MENU_START = APPDATA / r"Microsoft\Windows\Start Menu\Programs"
ESEC_AUTO = MENU_START / "Startup"
REGISTRO = DEST / "installato.txt"
INTESTAZIONE = "# Registro di Sottomano: cosa ha installato lui (usato da disinstalla.bat)"
MODELLI_AI = Path(os.environ.get("U2NET_HOME", Path.home() / ".rembg"))


def leggi_registro():
    if not REGISTRO.exists():
        return []
    return [r.strip() for r in REGISTRO.read_text(encoding="utf-8", errors="replace").splitlines() if r.strip()]


def registra(riga):
    if riga not in leggi_registro():
        DEST.mkdir(parents=True, exist_ok=True)
        with open(REGISTRO, "a", encoding="utf-8") as fh:
            fh.write(riga + "\n")


def librerie_presenti():
    r = subprocess.run([str(PYTHON), "-m", "pip", "list", "--format=json", "--disable-pip-version-check"],
                       capture_output=True, text=True)
    try:
        return {p["name"].lower().replace("_", "-") for p in json.loads(r.stdout)}
    except Exception:
        return set()


def winget_presente(id_):
    try:
        return subprocess.run(["winget", "list", "--id", id_, "-e", "--accept-source-agreements"],
                              capture_output=True).returncode == 0
    except Exception:
        return False


def versione_precedente():
    """Le versioni vecchie non tenevano il registro: chiedo una volta cosa aveva installato Sottomano."""
    righe = leggi_registro()
    if INTESTAZIONE in righe or not (DEST / "sottomano.pyw").exists():
        return
    passo("Ho trovato una versione precedente di Sottomano")
    print("    Le versioni precedenti non segnavano cosa installavano. Rispondi, cosi' la")
    print("    disinstallazione sapra' cosa puo' togliere. Nel dubbio rispondi N (non verra' toccato).")
    for id_, nome in (("Python.Python.3.12", "Python 3.12"), ("7zip.7zip", "7-Zip"),
                      ("UB-Mannheim.TesseractOCR", "Tesseract OCR")):
        if f"winget {id_}" not in righe and winget_presente(id_):
            if chiedi(f"{nome} l'ha installato Sottomano?"):
                registra(f"winget {id_}")
    presenti = librerie_presenti()
    nostre = [l for l in LIBRERIE + ["rembg", "faster-whisper"] if l in presenti and f"pip {l}" not in righe]
    if nostre and chiedi("Queste librerie Python le hai installate solo per Sottomano?\n      "
                         + ", ".join(nostre) + "\n   "):
        for l in nostre:
            registra(f"pip {l}")
    if MODELLI_AI.exists() and chiedi(f"La cartella dei modelli AI ({MODELLI_AI}) l'ha creata Sottomano?"):
        registra(f"cartella {MODELLI_AI}")


SCELTE = DEST / "scelte.txt"


def scelte_precedenti():
    try:
        return dict(r.split("=", 1) for r in SCELTE.read_text(encoding="utf-8").split() if "=" in r)
    except OSError:
        return {}


def salva_scelta(nome, si):
    sc = scelte_precedenti()
    sc[nome] = "si" if si else "no"
    DEST.mkdir(parents=True, exist_ok=True)
    SCELTE.write_text("\n".join(f"{k}={v}" for k, v in sc.items()) + "\n", encoding="utf-8")


def scelta(nome, domanda, gia_presente=False, descrizione=""):
    """Chiede solo la prima volta. Negli aggiornamenti tiene la scelta di prima, senza domande:
    se l'opzione e' gia' installata resta, se avevi detto di no non la richiede."""
    if gia_presente:
        print(f"    {descrizione}: gia' presente, la tengo")
        salva_scelta(nome, True)
        return True
    prima = scelte_precedenti().get(nome)
    if prima is not None:
        print(f"    {descrizione}: {'si' if prima == 'si' else 'no'} (scelto in precedenza)")
        return prima == "si"
    risposta = chiedi(domanda)
    salva_scelta(nome, risposta)
    return risposta


def passo(t):
    print(f"\n==> {t}")


def chiedi(domanda):
    return input(f"    {domanda} [s/N] ").strip().lower().startswith(("s", "y"))


def chiudi_versione_attiva():
    """Chiede gentilmente alla versione in esecuzione di chiudersi (come cliccare Esci)."""
    import ctypes
    u = ctypes.windll.user32
    hwnd = u.FindWindowW("SottomanoServizio", None)
    if hwnd:
        u.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        print("    Chiusa la versione gia' attiva")


def pip(*pacchetti):
    subprocess.check_call([str(PYTHON), "-m", "pip", "install", "--upgrade", "--disable-pip-version-check", *pacchetti])


def collegamento(percorso, descrizione):
    # pywin32 appena installato: lo uso in un processo nuovo, che lo vede gia' configurato
    codice = (
        "import sys, win32com.client as w;"
        "s = w.Dispatch('WScript.Shell').CreateShortcut(sys.argv[1]);"
        "s.TargetPath = sys.argv[2]; s.Arguments = sys.argv[3]; s.WorkingDirectory = sys.argv[4];"
        "s.Description = sys.argv[5]; s.IconLocation = sys.argv[6]; s.Hotkey = ''; s.Save()"
    )
    subprocess.check_call([str(PYTHON), "-c", codice, str(percorso), str(PYTHONW),
                           f'"{DEST / "sottomano.pyw"}" ascolta', str(DEST), descrizione,
                           f"{DEST / 'logo.ico'},0"])


def cartella_desktop():
    """Il vero desktop dell'utente (anche se e' sincronizzato con OneDrive)."""
    r = subprocess.run([str(PYTHON), "-c", "import win32com.client as w;"
                        "print(w.Dispatch('WScript.Shell').SpecialFolders('Desktop'))"],
                       capture_output=True, text=True)
    p = r.stdout.strip()
    return Path(p) if p and Path(p).exists() else None


def main():
    if not PYTHONW.exists():
        sys.exit(f"pythonw.exe non trovato accanto a {PYTHON}")

    versione_precedente()
    registra(INTESTAZIONE)
    if any(r.startswith("winget Python.") for r in leggi_registro()):
        registra(f"python {PYTHON.parent}")   # Python l'ha installato Sottomano: via anche la sua cartella

    passo("Librerie Python")
    prima = librerie_presenti()
    pip(*LIBRERIE)
    modello = MODELLI_AI / "isnet-general-use.onnx"
    sfondo_gia = "rembg" in prima and modello.exists()
    if scelta("sfondo", "Vuoi anche 'Rimuovi sfondo' con AI? (scarica circa 170 MB)", sfondo_gia,
              "Rimuovi sfondo con AI") and not sfondo_gia:
        pip("rembg[cpu]")
        if not MODELLI_AI.exists():
            registra(f"cartella {MODELLI_AI}")
        elif not modello.exists():
            registra(f"file {modello}")
        print("    Scarico il modello AI per la rimozione sfondo (solo la prima volta)...")
        subprocess.call([str(PYTHON), "-c", "from rembg import new_session; new_session('isnet-general-use')"])
    cartella_whisper = DEST / "modelli" / "whisper"
    whisper_gia = "faster-whisper" in prima and cartella_whisper.exists() and any(cartella_whisper.rglob("model.bin"))
    if scelta("sottotitoli", "Vuoi anche i sottotitoli automatici per video e audio, con AI? (scarica circa 300 MB)",
              whisper_gia, "Sottotitoli automatici con AI") and not whisper_gia:
        pip("faster-whisper")
        print("    Scarico il modello AI per i sottotitoli (solo la prima volta)...")
        cartella = DEST / "modelli" / "whisper"          # dentro Sottomano: se ne va con la disinstallazione
        cartella.mkdir(parents=True, exist_ok=True)
        subprocess.call([str(PYTHON), "-c", "import sys; from faster_whisper import WhisperModel; "
                         "WhisperModel('base', device='cpu', compute_type='int8', download_root=sys.argv[1])",
                         str(cartella)])
    for nuova in sorted(librerie_presenti() - prima):
        registra(f"pip {nuova}")   # solo quelle che prima non c'erano

    passo(f"Copio i file in {DEST}")
    chiudi_versione_attiva()
    DEST.mkdir(parents=True, exist_ok=True)
    for nome in ("sottomano.pyw", "nucleo.py", "anteprima.pyw", "ritaglia.py", "strumenti.py", "blocco.py", "apri_bloccato.pyw", "logo.ico", "logo.png", "disinstalla.bat", "disinstalla.py", "LICENSE", "README.md"):
        if (SRC / nome).exists():
            shutil.copy2(SRC / nome, DEST / nome)

    # versione gia' compilata dei moduli: la prima apertura di ogni finestra e' piu' rapida
    subprocess.call([str(PYTHON), "-m", "compileall", "-q", str(DEST / "nucleo.py"), str(DEST / "ritaglia.py"), str(DEST / "strumenti.py"),
                     str(DEST / "blocco.py")])

    passo("Lingue OCR (italiano + inglese)")
    tess = DEST / "tessdata"
    tess.mkdir(exist_ok=True)
    for lingua in ("ita", "eng"):
        f = tess / f"{lingua}.traineddata"
        if not f.exists():
            url = f"https://github.com/tesseract-ocr/tessdata_fast/raw/main/{lingua}.traineddata"
            print(f"    Scarico {lingua}...")
            urllib.request.urlretrieve(url, f)
    print("    Pronte")

    passo("Collegamenti")
    collegamento(MENU_START / "Sottomano.lnk", "Sottomano: Ctrl+Alt+S sui file selezionati")
    print("    Menu Start: Sottomano")
    desktop = cartella_desktop()
    if desktop:
        sul_desktop = desktop / "Sottomano.lnk"
        if scelta("icona_desktop", "Vuoi l'icona di Sottomano anche sul desktop?", sul_desktop.exists(),
                  "Icona sul desktop"):
            collegamento(sul_desktop, "Sottomano: Ctrl+Alt+S sui file selezionati")
            registra(f"file {sul_desktop}")
            print("    Icona sul desktop pronta")
        elif sul_desktop.exists():
            sul_desktop.unlink()
    auto = ESEC_AUTO / "Sottomano.lnk"
    if scelta("avvio_automatico", "Vuoi che Sottomano parta da solo quando accendi il PC?", auto.exists(),
              "Avvio automatico"):
        collegamento(auto, "Sottomano: Ctrl+Alt+S sui file selezionati")
        print("    Avvio automatico attivo (lo togli da Impostazioni > App > Avvio)")
    elif auto.exists():
        auto.unlink()
        print("    Avvio automatico disattivato")

    passo("Avvio Sottomano")
    subprocess.Popen([str(PYTHONW), str(DEST / "sottomano.pyw"), "ascolta"], cwd=str(DEST))
    print("""
Fatto! Trovi l'icona di Sottomano vicino all'orologio (anche tra le icone nascoste ^).
  1. Seleziona uno o piu' file in Esplora file o sul desktop
  2. Premi Ctrl+Alt+S (senza niente selezionato: strumenti per la cartella)
  3. Scegli l'azione dal menu
  Spazio = anteprima al volo   ·   Ctrl+Alt+T = testo da una zona dello schermo
Per chiuderlo: tasto destro sull'icona -> Esci.  Per riaprirlo: menu Start -> Sottomano.
(Per cambiare le scelte fatte qui: cancella %LOCALAPPDATA%\\Sottomano\\scelte.txt e rilancia installa.bat)""")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nERRORE: {e}\nMandami uno screenshot di questa finestra.")
