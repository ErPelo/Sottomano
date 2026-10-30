# -*- coding: utf-8 -*-
"""
Sottomano - azioni rapide sui file di Esplora file (Windows 10/11).

Uso:  pythonw sottomano.pyw ascolta                   servizio in background: Ctrl+Alt+S apre il menu
      pythonw sottomano.pyw menu                      menu sui file della finestra in primo piano
      pythonw sottomano.pyw <azione> "file1" [...]   esegue direttamente un'azione

Copyright (C) 2026 Tommaso Pelosin

This program is free software: you can redistribute it and/or modify it under the
terms of the GNU Affero General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later version.
This program is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""
import os
import sys
import json
import shutil
import hashlib
import tempfile
import subprocess
import traceback
from contextlib import contextmanager
from pathlib import Path

# Con pythonw.exe non esiste una console: sys.stdout/stderr valgono None e qualsiasi
# libreria che stampa (es. la barra di avanzamento di un download) andrebbe in errore.
for _flusso in ("stdout", "stderr"):
    if getattr(sys, _flusso) is None:
        setattr(sys, _flusso, open(os.devnull, "w", encoding="utf-8"))

VERSIONE = "0.2"
BASE = Path(__file__).resolve().parent
TESSDATA = BASE / "tessdata"
LOG = BASE / "errori.log"

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic", ".heif", ".ico"}
ARC_EXT = {".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".xz"}
VID_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".m4v", ".mpg", ".mpeg", ".flv", ".3gp", ".ts"}
AUD_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}
TXT_EXT = {".txt", ".md", ".log", ".csv", ".json", ".xml", ".yml", ".yaml", ".ini", ".cfg", ".py", ".js",
           ".html", ".htm", ".css", ".bat", ".ps1", ".sql", ".srt", ".vtt"}
OFFICE_EXT = {".doc", ".docx", ".rtf", ".odt", ".xls", ".xlsx", ".ods", ".ppt", ".pptx", ".odp"}

NO_WINDOW = 0x08000000 if os.name == "nt" else 0


# ----------------------------------------------------------------- utilità GUI
LOGO = BASE / "logo.ico"


def _logo(root):
    """Logo di Sottomano nella barra del titolo delle finestre."""
    if LOGO.exists():
        try:
            root.iconbitmap(default=str(LOGO))
        except Exception:
            pass


def nitido():
    """Finestre e menu disegnati alla risoluzione vera dello schermo (nitidi anche al 125/150%)."""
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _tk():
    from ritaglia import radice
    root = radice()
    _logo(root)
    root.withdraw()
    root.attributes("-topmost", True)
    return root


def info(msg, title="Sottomano"):
    from tkinter import messagebox
    r = _tk(); messagebox.showinfo(title, msg, parent=r); r.destroy()


def errore(msg, title="Sottomano - errore"):
    from tkinter import messagebox
    r = _tk(); messagebox.showerror(title, msg, parent=r); r.destroy()


def mostra_testo(titolo, testo, nota="Testo copiato negli appunti (e salvato in un .txt accanto al file).",
                 link=None):
    """Finestra con il testo estratto, già copiato negli appunti."""
    import tkinter as tk
    from tkinter import scrolledtext
    from ritaglia import radice
    root = radice()
    _logo(root)
    root.title(titolo)
    k = max(root.winfo_fpixels("1i") / 96.0, 1.0)
    w, h = int(720 * k), int(520 * k)
    root.geometry(f"{w}x{h}+{(root.winfo_screenwidth() - w) // 2}+{max((root.winfo_screenheight() - h) // 3, 0)}")
    root.attributes("-topmost", True)
    root.after(800, lambda: root.attributes("-topmost", False))
    root.clipboard_clear(); root.clipboard_append(testo); root.update()
    tk.Label(root, text=nota, anchor="w").pack(fill="x", padx=8, pady=(8, 2))
    box = scrolledtext.ScrolledText(root, wrap="word", font=("Segoe UI", 10))
    box.pack(fill="both", expand=True, padx=8, pady=8)
    box.insert("1.0", testo)
    giu = tk.Frame(root)
    giu.pack(pady=(0, 8))
    if link:
        tk.Button(giu, text="Apri il link", command=lambda: os.startfile(link), width=14).pack(side="left", padx=4)
    tk.Button(giu, text="Chiudi", command=root.destroy, width=12).pack(side="left", padx=4)
    root.deiconify()
    root.after(50, lambda: (root.focus_force(), root.lift()))
    root.mainloop()


# --------------------------------------------------------------- utilità file
def libero(p: Path) -> Path:
    """Restituisce un percorso che non sovrascrive file esistenti."""
    def occupato(x):
        return x.exists() or Path(str(x) + ".in-corso").exists()
    if not occupato(p):
        return p
    i = 1
    while True:
        q = p.with_name(f"{p.stem} ({i}){p.suffix}")
        if not occupato(q):
            return q
        i += 1


@contextmanager
def in_corso(*uscite):
    """Come i download di Chrome: finche' il lavoro non e' finito, accanto all'originale
    c'e' un file segnaposto 'nome.ext.in-corso' (0 KB), poi compare il file vero."""
    segni = []
    for u in uscite:
        m = Path(str(u) + ".in-corso")
        try:
            m.write_bytes(b"")
            segni.append(m)
        except OSError:
            pass
    try:
        yield
    finally:
        for m in segni:
            try:
                m.unlink()
            except OSError:
                pass


def apri_immagine(path, massimo=None):
    """Apre un'immagine gia' raddrizzata secondo l'EXIF.
    massimo=(larghezza, altezza): se basta una versione piu' piccola, i JPEG vengono decodificati
    direttamente ridotti (draft): molta meno RAM e molto piu' veloce, stesso risultato a schermo."""
    from PIL import Image, ImageOps
    import math
    if Path(path).suffix.lower() in (".heic", ".heif"):
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            raise RuntimeError("Per i file HEIC serve il pacchetto pillow-heif.")
    im = Image.open(path)
    if massimo and im.format == "JPEG":
        w, h = im.size
        bw, bh = massimo
        s = max(min(bw / w, bh / h), min(bw / h, bh / w))   # va bene anche se la foto e' ruotata
        if s < 1:
            im.draft(im.mode, (max(math.ceil(w * s), 1), max(math.ceil(h * s), 1)))
    try:
        im = ImageOps.exif_transpose(im)  # rispetta la rotazione delle foto da telefono
    except Exception:
        pass
    return im


def dimensioni_immagine(path):
    """Larghezza e altezza come si vedono (rotazione EXIF compresa), senza decodificare i pixel."""
    from PIL import Image
    with Image.open(path) as im:
        w, h = im.size
        try:
            if im.getexif().get(0x0112) in (5, 6, 7, 8):
                w, h = h, w
        except Exception:
            pass
    return w, h


def rgb(im):
    """Converte in RGB appiattendo la trasparenza su sfondo bianco."""
    from PIL import Image
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        return bg
    return im.convert("RGB")


def trova_exe(*candidati):
    for c in candidati:
        c = os.path.expandvars(c)
        if os.path.isfile(c):
            return c
        w = shutil.which(c)
        if w:
            return w
    return None


def sette_zip():
    exe = trova_exe(r"%ProgramFiles%\7-Zip\7z.exe", r"%ProgramFiles(x86)%\7-Zip\7z.exe", "7z")
    if not exe:
        raise RuntimeError("7-Zip non trovato. Installalo con: winget install 7zip.7zip")
    return exe


def tesseract():
    import pytesseract
    exe = trova_exe(r"%ProgramFiles%\Tesseract-OCR\tesseract.exe",
                    r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe", "tesseract")
    if not exe:
        raise RuntimeError("Tesseract OCR non trovato. Rilancia installa.bat.")
    pytesseract.pytesseract.tesseract_cmd = exe
    return pytesseract


def ocr_immagine(im):
    pt = tesseract()
    # Le lingue scaricate dall'installer stanno in %LOCALAPPDATA%\Sottomano\tessdata.
    # Le indico con TESSDATA_PREFIX: passare il percorso tra virgolette in "config"
    # su Windows lascia le virgolette dentro il percorso e Tesseract non lo trova.
    if (TESSDATA / "ita.traineddata").exists() and (TESSDATA / "eng.traineddata").exists():
        os.environ["TESSDATA_PREFIX"] = str(TESSDATA)
        lang = "ita+eng"
    else:
        os.environ.pop("TESSDATA_PREFIX", None)  # uso le lingue incluse in Tesseract
        lang = "eng"
    return pt.image_to_string(rgb(im), lang=lang)


def run(cmd):
    # stdin chiuso: se un archivio chiede la password, 7-Zip si ferma subito invece di aspettare per sempre
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL,
                       encoding="utf-8", errors="replace")
    if r.returncode not in (0, 1):  # 1 = avvisi non bloccanti per 7z/rar
        raise RuntimeError((r.stderr or r.stdout or "comando fallito").strip()[-800:])


# ------------------------------------------------------------------ immagini
def converti_immagine(files, fmt):
    fatti = []
    for f in files:
        f = Path(f)
        im = apri_immagine(f)
        out = libero(f.with_suffix("." + fmt))
        with in_corso(out):
            if fmt in ("jpg", "jpeg"):
                rgb(im).save(out, "JPEG", quality=92, optimize=True)
            elif fmt == "png":
                im.save(out, "PNG", optimize=True)
            elif fmt == "webp":
                im.save(out, "WEBP", quality=90, method=6)
            elif fmt == "ico":
                im.convert("RGBA").save(out, "ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        fatti.append(out.name)
    return f"Creati {len(fatti)} file:\n" + "\n".join(fatti)


def immagini_in_pdf(files):
    """Una pagina per immagine, aggiunte una alla volta: la RAM resta costante anche con 100 foto.
    I JPEG gia' dritti finiscono nel PDF cosi' come sono (nessuna ricompressione);
    PNG, screenshot e simili restano senza perdita; le altre foto diventano JPEG di alta qualita'."""
    import io
    from PIL import Image
    fitz = _fitz()
    files = sorted(files, key=lambda p: Path(p).name.lower())
    primo = Path(files[0])
    nome = primo.stem if len(files) == 1 else primo.parent.name or "immagini"
    out = libero(primo.with_name(nome + ".pdf"))
    doc = fitz.open()
    with in_corso(out):
        for f in files:
            f = Path(f)
            ext = f.suffix.lower()
            dati = None
            if ext in (".jpg", ".jpeg") and _orientamento(f) == 1:
                with Image.open(f) as im:
                    w, h = im.size
                    if im.mode in ("RGB", "L"):        # i JPEG CMYK li converto: nei PDF i colori sbaglierebbero
                        dati = f.read_bytes()
            if dati is None:
                im = rgb(apri_immagine(f))
                w, h = im.size
                buf = io.BytesIO()
                if ext in (".png", ".bmp", ".gif", ".tif", ".tiff"):
                    im.save(buf, "PNG")                    # senza perdita (testo nitido)
                else:
                    im.save(buf, "JPEG", quality=92)
                del im
                dati = buf.getvalue()
            pagina = doc.new_page(width=w * 72 / 150, height=h * 72 / 150)   # 150 dpi, come prima
            pagina.insert_image(pagina.rect, stream=dati)
            del dati
        doc.save(out, garbage=3, deflate=True)
        n = doc.page_count
        doc.close()
    return f"PDF creato ({n} pagine):\n{out.name}"


def ocr(files):
    blocchi = []
    for f in files:
        f = Path(f)
        if f.suffix.lower() == ".pdf":
            testo = testo_pdf(f, forza_ocr=True)
        else:
            testo = ocr_immagine(apri_immagine(f))
        f.with_name(f.stem + "_testo.txt").write_text(testo, encoding="utf-8")
        blocchi.append(testo if len(files) == 1 else f"===== {f.name} =====\n{testo}")
    mostra_testo("Testo estratto", "\n\n".join(blocchi).strip() or "(nessun testo riconosciuto)")
    return None


def _salva_immagine(im, out, qualita=90):
    ext = out.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        rgb(im).save(out, "JPEG", quality=qualita, optimize=True, progressive=True)
    elif ext == ".webp":
        im.save(out, "WEBP", quality=qualita, method=6)
    elif ext == ".png":
        im.save(out, "PNG", optimize=True)
    else:
        im.save(out)


def ritaglia_immagine(files):
    """Editor grafico: ritaglia, ruota e ridimensiona (una immagine)."""
    import ritaglia
    f = Path(files[0])
    risultato = ritaglia.ritaglia(apri_immagine(f), f.name)
    if risultato is None:
        return None                      # annullato
    ext = f.suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"):
        ext = ".jpg"                     # HEIC e simili: salvo in JPG
    out = libero(f.with_name(f.stem + "_ritagliata" + ext))
    with in_corso(out):
        _salva_immagine(risultato, out)
    return f"Salvata: {out.name}  ({risultato.width} × {risultato.height} px)"


def comprimi_immagini(files):
    """Piu' immagini insieme: dimensione e qualita' scelte con i pulsanti."""
    import ritaglia
    try:
        esempio = dimensioni_immagine(files[0])
    except Exception:
        esempio = None
    scelta = ritaglia.scegli_dimensione(len(files), esempio)
    if not scelta:
        return None
    lato, qualita = scelta
    risparmio = 0
    for f in files:
        f = Path(f)
        im = rgb(apri_immagine(f, (lato, lato) if lato else None))
        if lato:
            im.thumbnail((lato, lato))
        out = libero(f.with_name(f.stem + "_compressa.jpg"))
        with in_corso(out):
            _salva_immagine(im, out, qualita)
        risparmio += f.stat().st_size - out.stat().st_size
    return f"Fatto: {len(files)} immagini.\nSpazio risparmiato: {risparmio / 1048576:.1f} MB"


def _orientamento(path):
    from PIL import Image
    try:
        with Image.open(path) as im:
            return int(im.getexif().get(0x0112, 1) or 1)
    except Exception:
        return 1


def _jpeg_senza_metadati(src, dst):
    """Copia il JPEG togliendo i blocchi di metadati, SENZA ricomprimere l'immagine.
    Via: EXIF/XMP (APP1), IPTC/Photoshop (APP13), commenti, APP3-APP12/APP15 dei produttori,
    APP2 che non sono profili colore, e le immagini secondarie accodate dai telefoni.
    Restano: JFIF (APP0), profilo colore ICC (APP2), Adobe (APP14, serve ai colori CMYK)
    e, se la foto e' ruotata, un EXIF minimo con la sola rotazione."""
    from PIL import Image
    dati = Path(src).read_bytes()
    if dati[:2] != b"\xff\xd8":
        raise ValueError("JPEG non valido")
    out = bytearray(b"\xff\xd8")
    rot = _orientamento(src)
    if rot != 1:
        ex = Image.Exif()
        ex[0x0112] = rot
        corpo = ex.tobytes()                       # b"Exif\0\0" + TIFF con il solo orientamento
        out += b"\xff\xe1" + (len(corpo) + 2).to_bytes(2, "big") + corpo
    i, n = 2, len(dati)
    while i < n - 1:
        if dati[i] != 0xFF:
            raise ValueError("struttura JPEG inattesa")
        while i < n - 1 and dati[i + 1] == 0xFF:   # byte di riempimento
            i += 1
        m = dati[i + 1]
        if m == 0xD9:                              # fine immagine: stop (via eventuali immagini accodate)
            out += b"\xff\xd9"
            break
        if m == 0x01 or 0xD0 <= m <= 0xD7:         # marcatori senza lunghezza
            out += dati[i:i + 2]
            i += 2
            continue
        lung = int.from_bytes(dati[i + 2:i + 4], "big")
        seg = dati[i:i + 2 + lung]
        tieni = True
        if m in (0xE1, 0xED, 0xFE) or 0xE3 <= m <= 0xEC or m == 0xEF:
            tieni = False
        elif m == 0xE2 and not seg[4:16].startswith(b"ICC_PROFILE"):
            tieni = False
        if tieni:
            out += seg
        i += 2 + lung
        if m == 0xDA:                              # dati compressi: li copio fino al prossimo marcatore
            j = i
            while True:
                j = dati.find(b"\xff", j)
                if j < 0 or j >= n - 1:
                    j = n
                    break
                nxt = dati[j + 1]
                if nxt == 0x00 or 0xD0 <= nxt <= 0xD7:
                    j += 2
                    continue
                break
            out += dati[i:j]
            i = j
    Path(dst).write_bytes(bytes(out))


def _png_senza_metadati(src, dst):
    """Copia il PNG togliendo testi, data, EXIF e simili. Restano i dati e i blocchi che servono
    a mostrarlo uguale (palette, trasparenza, colori, densita')."""
    import struct
    dati = Path(src).read_bytes()
    if dati[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("PNG non valido")
    utili = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP",
             b"sBIT", b"pHYs", b"bKGD", b"acTL", b"fcTL", b"fdAT"}
    out = bytearray(dati[:8])
    i = 8
    while i + 8 <= len(dati):
        lung, tipo = struct.unpack(">I4s", dati[i:i + 8])
        fine = i + 12 + lung
        if tipo in utili:
            out += dati[i:fine]
        i = fine
        if tipo == b"IEND":
            break
    Path(dst).write_bytes(bytes(out))


def _webp_senza_metadati(src, dst):
    """Copia il WEBP togliendo i blocchi EXIF e XMP (e aggiorna l'intestazione)."""
    import struct
    dati = Path(src).read_bytes()
    if dati[:4] != b"RIFF" or dati[8:12] != b"WEBP":
        raise ValueError("WEBP non valido")
    blocchi = bytearray()
    i = 12
    while i + 8 <= len(dati):
        tipo, lung = dati[i:i + 4], struct.unpack("<I", dati[i + 4:i + 8])[0]
        fine = i + 8 + lung + (lung & 1)
        blocco = bytearray(dati[i:fine])
        if tipo == b"VP8X":
            blocco[8] &= ~(0x08 | 0x04) & 0xFF     # tolgo i flag "contiene EXIF" e "contiene XMP"
        if tipo not in (b"EXIF", b"XMP "):
            blocchi += blocco
        i = fine
    Path(dst).write_bytes(b"RIFF" + struct.pack("<I", 4 + len(blocchi)) + b"WEBP" + bytes(blocchi))


def rimuovi_metadati(files):
    """Toglie GPS, data, modello di fotocamera e simili.
    JPEG, PNG e WEBP: senza ricomprimere (nessuna perdita di qualita', quasi niente RAM).
    Altri formati: copio solo i pixel in un'immagine nuova."""
    from PIL import Image
    for f in files:
        f = Path(f)
        ext = f.suffix.lower()
        out = libero(f.with_name(f.stem + "_pulita" + f.suffix))
        with in_corso(out):
            try:
                if ext in (".jpg", ".jpeg"):
                    _jpeg_senza_metadati(f, out)
                    continue
                if ext == ".png" and _orientamento(f) == 1:
                    _png_senza_metadati(f, out)
                    continue
                if ext == ".webp" and _orientamento(f) == 1:
                    _webp_senza_metadati(f, out)
                    continue
            except Exception:
                log(f"--- metadati, metodo veloce non riuscito su {f}: uso la copia dei pixel\n"
                    f"{traceback.format_exc()}")
            im = apri_immagine(f)                       # gia' raddrizzata secondo l'EXIF
            if im.mode not in ("1", "L", "LA", "P", "RGB", "RGBA", "CMYK", "I", "F"):
                im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
            pulita = Image.new(im.mode, im.size)
            pulita.paste(im)                            # solo i pixel: i metadati restano fuori
            if im.mode == "P":
                pulita.putpalette(im.getpalette())
                if "transparency" in im.info:
                    pulita.info["transparency"] = im.info["transparency"]
            del im
            _salva_immagine(pulita, out, qualita=95)
    return f"Metadati (GPS, fotocamera, data) rimossi da {len(files)} immagini.\nCreate copie con suffisso _pulita."


MODELLO_SFONDO = "isnet-general-use"


def rimuovi_sfondo(files):
    try:
        from rembg import remove, new_session
    except ImportError:
        raise RuntimeError("Funzione opzionale non installata.\nRilancia installa.bat e scegli S alla domanda sulla rimozione sfondo.")
    # Modello leggero (~170 MB, poca RAM). Il predefinito di rembg (bria-rmbg-2.0) pesa 1 GB
    # e su molti PC esaurisce la memoria fino a bloccare il computer.
    files = [Path(f) for f in files]
    uscite = [libero(f.with_name(f.stem + "_senza_sfondo.png")) for f in files]
    with in_corso(*uscite):  # i segnaposto compaiono subito, anche durante il caricamento del modello
        sessione = new_session(MODELLO_SFONDO)
        for f, out in zip(files, uscite):
            remove(apri_immagine(f), session=sessione).save(out)
    return f"Sfondo rimosso da {len(files)} immagini (salvate in PNG)."


# ----------------------------------------------------------------------- PDF
def _fitz():
    try:
        import pymupdf
        return pymupdf
    except ImportError:
        import fitz
        return fitz


def _tipo_vero(dati):
    """Che file e' davvero, guardando i primi byte (per i 'PDF' che PDF non sono)."""
    t = dati[:600].lstrip().lower()
    for inizio, nome in ((b"<?xml", "XML (per esempio una fattura elettronica)"), (b"<!doctype html", "HTML (una pagina web)"),
                         (b"<html", "HTML (una pagina web)"), (b"pk\x03\x04", "ZIP"), (b"\xff\xd8", "JPEG (una foto)"),
                         (b"\x89png", "PNG (un'immagine)"), (b"{\\rtf", "RTF (un documento di testo)"),
                         (b"\xd0\xcf\x11\xe0", "Office (Word o Excel vecchio formato)"), (b"%!ps", "PostScript")):
        if t.startswith(inizio):
            return nome
    return None


def apri_pdf(f):
    """Apre un PDF con PyMuPDF. Se non ci riesce: lo ripara con PDFium (piu' tollerante) oppure
    spiega cosa c'e' che non va (file vuoto, file non PDF, PDF danneggiato)."""
    fitz = _fitz()
    f = Path(f)
    try:
        return fitz.open(f)
    except Exception as e:
        primo = e
    try:
        dati = f.read_bytes()[:2048]
    except OSError:
        dati = b""
    if not dati:
        raise RuntimeError(f"«{f.name}» è vuoto (0 KB): forse il download non è finito, "
                           "oppure il file è solo nel cloud (OneDrive) e non sul PC.")
    if b"%PDF" not in dati[:1024]:
        tipo = _tipo_vero(dati)
        raise RuntimeError(f"«{f.name}» non è un vero PDF" +
                           (f": è un file {tipo} a cui è stata data l'estensione .pdf." if tipo
                            else ", anche se ha l'estensione .pdf.") +
                           "\nSe ti serve il PDF, chiedi di nuovo il file a chi te l'ha mandato.")
    try:
        import io
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(f))
        buf = io.BytesIO()
        pdf.save(buf)
        pdf.close()
        log(f"--- {f.name}: PDF danneggiato, riparato con PDFium")
        return fitz.open(stream=buf.getvalue(), filetype="pdf")
    except Exception:
        pass
    raise RuntimeError(f"«{f.name}» è un PDF danneggiato e non riesco a ripararlo.") from primo


def testo_pdf(f, forza_ocr=False):
    doc = apri_pdf(f)
    parti = []
    for pag in doc:
        t = "" if forza_ocr else pag.get_text()
        if len(t.strip()) < 20:  # pagina scannerizzata: OCR
            from PIL import Image
            pix = pag.get_pixmap(dpi=300)
            t = ocr_immagine(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
        parti.append(t)
    return "\n\n".join(parti)


def pdf_testo(files):
    blocchi = []
    for f in files:
        f = Path(f)
        t = testo_pdf(f)
        f.with_name(f.stem + "_testo.txt").write_text(t, encoding="utf-8")
        blocchi.append(t if len(files) == 1 else f"===== {f.name} =====\n{t}")
    mostra_testo("Testo del PDF", "\n\n".join(blocchi).strip() or "(nessun testo trovato)")


def pdf_unisci(files):
    fitz = _fitz()
    files = sorted(files, key=lambda p: Path(p).name.lower())
    out_doc = fitz.open()
    for f in files:
        with apri_pdf(f) as d:
            out_doc.insert_pdf(d)
    out = libero(Path(files[0]).with_name("PDF_uniti.pdf"))
    with in_corso(out):
        out_doc.save(out, garbage=3, deflate=True)
    return f"Uniti {len(files)} PDF ({out_doc.page_count} pagine) in:\n{out.name}"


def pdf_in_immagini(files):
    tot = 0
    for f in files:
        f = Path(f)
        cartella = libero(f.with_name(f.stem + "_pagine"))
        cartella.mkdir()
        with apri_pdf(f) as d:
            for i, pag in enumerate(d, 1):
                pag.get_pixmap(dpi=200).save(cartella / f"pagina_{i:03d}.png")
                tot += 1
    return f"Esportate {tot} pagine come PNG (cartella *_pagine)."


def pdf_comprimi(files):
    righe = []
    for f in files:
        f = Path(f)
        out = libero(f.with_name(f.stem + "_compresso.pdf"))
        with in_corso(out), apri_pdf(f) as d:
            try:
                d.rewrite_images(dpi_threshold=160, dpi_target=150, quality=75)
            except Exception:
                pass  # versioni vecchie di PyMuPDF: solo pulizia struttura
            d.save(out, garbage=4, deflate=True, clean=True)
        a, b = f.stat().st_size, out.stat().st_size
        righe.append(f"{f.name}: {a/1048576:.1f} MB -> {b/1048576:.1f} MB")
    return "\n".join(righe)


# ------------------------------------------------------------------- archivi
def converti_archivio(files, fmt):
    sz = sette_zip()
    rar = None
    if fmt == "rar":
        rar = trova_exe(r"%ProgramFiles%\WinRAR\Rar.exe", r"%ProgramFiles(x86)%\WinRAR\Rar.exe")
        if not rar:
            raise RuntimeError("Per creare file .rar serve WinRAR installato (Rar.exe non trovato).")
    fatti = []
    for f in files:
        f = Path(f)
        nome = f.name
        for e in (".tar.gz", ".tar.bz2", ".tar.xz"):
            if nome.lower().endswith(e):
                nome = nome[: -len(e)]
                break
        else:
            nome = f.stem
        out = libero(f.with_name(nome + "." + fmt))
        with in_corso(out), tempfile.TemporaryDirectory() as tmp:
            run([sz, "x", str(f), f"-o{tmp}", "-y"])
            # .tar.gz: dopo la prima estrazione resta un .tar da aprire
            interni = os.listdir(tmp)
            if len(interni) == 1 and interni[0].lower().endswith(".tar"):
                t = os.path.join(tmp, interni[0])
                run([sz, "x", t, f"-o{tmp}", "-y"])
                os.remove(t)
            if fmt == "rar":
                run([rar, "a", "-r", "-ep1", "-m5", "-y", str(out), os.path.join(tmp, "*")])
            else:
                livello = "-mx=9" if fmt == "7z" else "-mx=7"
                run([sz, "a", f"-t{fmt}", livello, str(out), os.path.join(tmp, "*")])
        a, b = f.stat().st_size, out.stat().st_size
        fatti.append(f"{out.name}  ({a/1048576:.1f} MB -> {b/1048576:.1f} MB)")
    return "Convertiti:\n" + "\n".join(fatti)


# --------------------------------------------------------------- video e audio
def ffmpeg_exe():
    """ffmpeg incluso nel pacchetto imageio-ffmpeg (installato da installa.bat)."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        e = shutil.which("ffmpeg")
        if e:
            return e
    raise RuntimeError("ffmpeg non trovato. Rilancia installa.bat per installarlo.")


H264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
AAC = ["-c:a", "aac", "-b:a", "192k"]


def _ffmpeg(args):
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-nostdin", "-y", *args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if r.returncode != 0:
        righe = [x for x in r.stderr.strip().splitlines() if x.strip()]
        raise RuntimeError("Conversione non riuscita:\n" + "\n".join(righe[-4:]))


def _riepilogo(coppie):
    righe = []
    for f, out in coppie:
        a, b = f.stat().st_size, out.stat().st_size
        righe.append(f"{out.name}  ({a / 1048576:.1f} MB -> {b / 1048576:.1f} MB)")
    return "\n".join(righe)


def converti_video(files, fmt):
    fatti = []
    for f in files:
        f = Path(f)
        out = libero(f.with_suffix("." + fmt))
        i = ["-i", str(f)]
        with in_corso(out):
            if fmt == "mkv":
                # MKV accetta qualsiasi formato: copio i flussi senza ricodificare (istantaneo)
                try:
                    _ffmpeg([*i, "-map", "0", "-c", "copy", str(out)])
                except RuntimeError:
                    _ffmpeg([*i, "-map", "0:v", "-map", "0:a?", "-map", "0:s?", "-c", "copy", str(out)])
            elif fmt in ("mp4", "mov"):
                # prima provo a copiare senza ricodificare; se i formati non sono compatibili ricodifico
                try:
                    _ffmpeg([*i, "-map", "0:v:0", "-map", "0:a?", "-c", "copy", "-movflags", "+faststart", str(out)])
                except RuntimeError:
                    _ffmpeg([*i, "-map", "0:v:0", "-map", "0:a?", *H264, *AAC, "-movflags", "+faststart", str(out)])
            elif fmt == "webm":
                _ffmpeg([*i, "-c:v", "libvpx-vp9", "-crf", "33", "-b:v", "0", "-deadline", "realtime",
                         "-cpu-used", "8", "-row-mt", "1", "-c:a", "libopus", "-b:a", "128k", str(out)])
            elif fmt == "gif":
                _ffmpeg(["-t", "30", *i, "-vf",
                         "fps=12,scale='min(480,iw)':-2:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse",
                         "-loop", "0", str(out)])
        fatti.append((f, out))
    nota = "\n\n(GIF: al massimo i primi 30 secondi)" if fmt == "gif" else ""
    return "Convertiti:\n" + _riepilogo(fatti) + nota


def comprimi_video(files):
    fatti = []
    for f in files:
        f = Path(f)
        out = libero(f.with_name(f.stem + "_compresso.mp4"))
        with in_corso(out):
            _ffmpeg(["-i", str(f), "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast",
                     "-crf", "28", "-vf", "scale='min(1280,iw)':-2", "-pix_fmt", "yuv420p",
                     "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)])
        fatti.append((f, out))
    return "Video compressi (max 1280 px di larghezza):\n" + _riepilogo(fatti)


AUDIO_OPZ = {
    "mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
    "wav": ["-c:a", "pcm_s16le"],
    "m4a": ["-c:a", "aac", "-b:a", "192k"],
    "flac": ["-c:a", "flac"],
}


def converti_audio(files, fmt):
    """Funziona sia su file audio sia per estrarre l'audio da un video."""
    fatti = []
    for f in files:
        f = Path(f)
        out = libero(f.with_suffix("." + fmt))
        with in_corso(out):
            _ffmpeg(["-i", str(f), "-vn", "-map", "0:a:0", *AUDIO_OPZ[fmt], str(out)])
        fatti.append((f, out))
    return "Fatto:\n" + _riepilogo(fatti)


# --------------------------------------------------------------------- vari
def hash_file(files):
    righe = []
    for f in files:
        h = hashlib.sha256()
        with open(f, "rb") as fh:
            for blocco in iter(lambda: fh.read(1 << 20), b""):
                h.update(blocco)
        righe.append(f"{Path(f).name}\n{h.hexdigest()}")
    testo = "\n\n".join(righe)
    mostra_testo("SHA-256", testo)


# ---------------------------------------------------------- appunti di Windows
def copia_testo_appunti(testo):
    import win32clipboard as cb
    cb.OpenClipboard()
    try:
        cb.EmptyClipboard()
        cb.SetClipboardText(testo, cb.CF_UNICODETEXT)
    finally:
        cb.CloseClipboard()


def copia_immagine_appunti(im):
    """Immagine negli appunti: formato classico (DIB) per tutti i programmi + PNG per chi
    lo capisce (cosi' la trasparenza non si perde)."""
    import io
    import win32clipboard as cb
    bmp = io.BytesIO()
    rgb(im).save(bmp, "BMP")
    png = io.BytesIO()
    im.save(png, "PNG")
    cb.OpenClipboard()
    try:
        cb.EmptyClipboard()
        cb.SetClipboardData(cb.CF_DIB, bmp.getvalue()[14:])
        cb.SetClipboardData(cb.RegisterClipboardFormat("PNG"), png.getvalue())
    finally:
        cb.CloseClipboard()


def copia_percorso(files):
    copia_testo_appunti("\r\n".join(str(f) for f in files))


def copia_immagine(files):
    copia_immagine_appunti(apri_immagine(files[0]))


def copia_contenuto(files):
    dati = Path(files[0]).read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            copia_testo_appunti(dati.decode(enc))
            return None
        except UnicodeDecodeError:
            continue


# ---------------------------------------------------------- rinomina in blocco
def rinomina_file(files):
    import strumenti
    coppie = strumenti.rinomina(files)
    if not coppie:
        return None
    selezione = {Path(a).resolve() for a, _ in coppie}
    usati, piano = set(), []
    for a, b in coppie:
        if a == b:
            usati.add(str(b).lower())
            continue
        n, base = 1, b
        # niente sovrascritture: ne' file esterni alla selezione, ne' due file con lo stesso nome
        while str(b).lower() in usati or (b.exists() and b.resolve() not in selezione):
            n += 1
            b = base.with_name(f"{base.stem} ({n}){base.suffix}")
        usati.add(str(b).lower())
        piano.append((a, b))
    # due passaggi (prima nomi temporanei): cosi' anche scambi come 1->2 e 2->1 funzionano
    temporanei, errori = [], []
    for i, (a, b) in enumerate(piano):
        t = a.with_name(f"~sottomano{os.getpid()}_{i}{a.suffix}")
        try:
            a.rename(t)
            temporanei.append((t, a, b))
        except OSError as e:
            errori.append(f"{a.name}: {e.strerror or e}")
    fatti = 0
    for t, a, b in temporanei:
        try:
            t.rename(b)
            fatti += 1
        except OSError as e:
            t.rename(a)
            errori.append(f"{a.name}: {e.strerror or e}")
    msg = f"Rinominati {fatti} file."
    if errori:
        msg += "\n\nNon rinominati (aperti in un altro programma?):\n" + "\n".join(errori[:10])
    return msg


# ---------------------------------------------------------------- ruota foto
# Rotazione EXIF: quale valore di "Orientamento" ottieni ruotando la foto come si vede
ROTAZIONI = {
    "dx":  {1: 6, 2: 7, 3: 8, 4: 5, 5: 2, 6: 3, 7: 4, 8: 1},
    "sx":  {1: 8, 2: 5, 3: 6, 4: 7, 5: 4, 6: 1, 7: 2, 8: 3},
    "180": {1: 3, 2: 4, 3: 1, 4: 2, 5: 7, 6: 8, 7: 5, 8: 6},
}


def _jpeg_ruota_senza_perdita(dati, verso):
    """Ruota un JPEG cambiando solo il campo 'Orientamento' dei metadati: nessuna ricompressione,
    istantaneo, qualita' identica (come fanno Windows e i telefoni). None se non si puo'."""
    from PIL import Image
    dati = bytearray(dati)
    if dati[:2] != b"\xff\xd8":
        return None
    i, n, app0 = 2, len(dati), None
    while i + 4 <= n:
        if dati[i] != 0xFF:
            return None
        m = dati[i + 1]
        if m == 0xFF:
            i += 1
            continue
        if m in (0xDA, 0xD9):
            break
        lung = int.from_bytes(dati[i + 2:i + 4], "big")
        if m == 0xE0 and app0 is None:
            app0 = i + 2 + lung
        if m == 0xE1 and dati[i + 4:i + 10] == b"Exif\0\0":
            t = i + 10
            e = {b"II": "little", b"MM": "big"}.get(bytes(dati[t:t + 2]))
            if not e:
                return None
            ifd = t + int.from_bytes(dati[t + 4:t + 8], e)
            for j in range(int.from_bytes(dati[ifd:ifd + 2], e)):
                voce = ifd + 2 + 12 * j
                if int.from_bytes(dati[voce:voce + 2], e) == 0x0112:
                    if int.from_bytes(dati[voce + 2:voce + 4], e) != 3:    # deve essere uno SHORT
                        return None
                    vecchio = int.from_bytes(dati[voce + 8:voce + 10], e)
                    dati[voce + 8:voce + 10] = ROTAZIONI[verso].get(vecchio, ROTAZIONI[verso][1]).to_bytes(2, e)
                    return bytes(dati)
            return None                       # EXIF senza orientamento: lo lascio a Pillow
        i += 2 + lung
    # nessun EXIF: ne aggiungo uno minimo con il solo orientamento
    ex = Image.Exif()
    ex[0x0112] = ROTAZIONI[verso][1]
    corpo = ex.tobytes()
    seg = b"\xff\xe1" + (len(corpo) + 2).to_bytes(2, "big") + corpo
    pos = app0 or 2
    return bytes(dati[:pos]) + seg + bytes(dati[pos:])


def ruota_immagini(files, verso):
    from PIL import Image, ImageOps, ImageSequence
    op = {"dx": Image.Transpose.ROTATE_270, "sx": Image.Transpose.ROTATE_90,
          "180": Image.Transpose.ROTATE_180}[verso]
    errori = []
    for f in files:
        f = Path(f)
        st = f.stat()
        tmp = f.with_name(f".{f.name}.sottomano-tmp")
        try:
            ext = f.suffix.lower()
            nuovi = _jpeg_ruota_senza_perdita(f.read_bytes(), verso) if ext in (".jpg", ".jpeg") else None
            if nuovi is not None:
                tmp.write_bytes(nuovi)
            elif ext in (".heic", ".heif"):
                im = apri_immagine(f).transpose(op)
                im.save(tmp, format="HEIF", quality=92)
            else:
                im = Image.open(f)
                fmt = im.format
                if getattr(im, "n_frames", 1) > 1 and fmt in ("GIF", "WEBP"):
                    fotogrammi = [fr.copy().transpose(op) for fr in ImageSequence.Iterator(im)]
                    fotogrammi[0].save(tmp, format=fmt, save_all=True, append_images=fotogrammi[1:],
                                       loop=im.info.get("loop", 0), duration=im.info.get("duration", 100))
                else:
                    opz = {}
                    if im.info.get("icc_profile"):
                        opz["icc_profile"] = im.info["icc_profile"]
                    if fmt == "JPEG":                        # stessa compressione dell'originale
                        from PIL import JpegImagePlugin
                        opz.update(qtables=im.quantization, subsampling=max(JpegImagePlugin.get_sampling(im), 0))
                        exif = im.getexif()
                        exif[0x0112] = 1
                        opz["exif"] = exif.tobytes()
                    elif fmt == "WEBP":
                        lossless = f.read_bytes()[12:16] == b"VP8L"
                        opz.update(lossless=lossless, quality=100 if lossless else 92)
                    elif fmt == "PNG":
                        opz["optimize"] = False
                    raddrizzata = ImageOps.exif_transpose(im).transpose(op)
                    raddrizzata.save(tmp, format=fmt, **opz)
            os.replace(tmp, f)
            os.utime(f, (st.st_atime, st.st_mtime))      # la data del file non cambia
        except Exception as e:
            tmp.unlink(missing_ok=True)
            errori.append(f"{f.name}: {e}")
            log(f"--- ruota {f}\n{traceback.format_exc()}")
    if errori:
        raise RuntimeError("Non sono riuscito a ruotare:\n" + "\n".join(errori[:10]))
    return None                                     # nessun messaggio: la miniatura si aggiorna da sola


# ------------------------------------------------------------------ QR code
def _testo_per_qr(files):
    """Testo iniziale del QR: link di un collegamento .url, contenuto di un .txt, o gli appunti."""
    if files:
        f = Path(files[0])
        try:
            if f.suffix.lower() == ".url":
                for riga in f.read_text(encoding="utf-8", errors="replace").splitlines():
                    if riga.upper().startswith("URL="):
                        return riga[4:].strip()
            if f.suffix.lower() in TXT_EXT and f.stat().st_size < 3000:
                return f.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            pass
    try:
        import tkinter as tk
        t = tk._default_root.clipboard_get() if tk._default_root else ""
        if t and len(t) < 1500:
            return t.strip()
    except Exception:
        pass
    return ""


def crea_qr(files):
    import strumenti
    from ritaglia import radice
    destinazione = Path(files[0]) if files else Path.home() / "Desktop"
    if not destinazione.is_dir():
        destinazione = destinazione.parent
    radice()                                          # serve per leggere gli appunti
    iniziale = _testo_per_qr(files)

    def salva(im, testo):
        import re
        nome = re.sub(r"^https?://(www\.)?", "", testo.splitlines()[0])
        nome = re.sub(r'[<>:"/\\|?*\s]+', "_", nome).strip("_.")[:40] or "testo"
        out = libero(destinazione / f"QR {nome}.png")
        im.save(out)
        return f"Salvato: {out.name}"

    def copia(im, testo):
        copia_immagine_appunti(im)
        return "Copiato: incollalo dove vuoi (Ctrl+V)"
    strumenti.crea_qr(iniziale, salva, copia)


def _leggi_codici(im):
    import zxingcpp
    risultati = zxingcpp.read_barcodes(rgb(im))
    if not risultati and min(im.size) < 400:      # codici piccoli: riprovo ingrandendo
        from PIL import Image
        risultati = zxingcpp.read_barcodes(rgb(im).resize((im.width * 3, im.height * 3), Image.LANCZOS))
    return [r.text for r in risultati if r.text]


def leggi_qr(files):
    trovati = []
    for f in files:
        for t in _leggi_codici(apri_immagine(f)):
            trovati.append(t if len(files) == 1 else f"{Path(f).name}:\n{t}")
    if not trovati:
        raise RuntimeError("Nessun QR code (o codice a barre) trovato nell'immagine.")
    testo = "\n\n".join(trovati)
    link = trovati[0] if len(trovati) == 1 and trovati[0].startswith(("http://", "https://")) else None
    mostra_testo("QR code", testo, nota="Contenuto del codice (già copiato negli appunti).", link=link)


# ------------------------------------------------- testo da una zona dello schermo
def zona_schermo(files=None):
    """Ctrl+Alt+T: scegli una zona dello schermo, Sottomano legge il testo (OCR) e i QR code."""
    import strumenti
    im = strumenti.scegli_zona()
    if im is None:
        return None
    parti = []
    try:
        codici = _leggi_codici(im)
    except Exception:
        codici = []
    for c in codici:
        parti.append(c)
    testo = ""
    try:
        testo = ocr_immagine(im.resize((im.width * 2, im.height * 2)) if im.height < 300 else im).strip()
    except Exception:
        if not codici:
            raise
    if testo and not codici:
        parti.append(testo)
    elif testo and codici:
        parti.append("Testo nella zona:\n" + testo)
    if not parti:
        raise RuntimeError("Non ho trovato testo né QR code nella zona scelta.")
    link = codici[0] if len(codici) == 1 and codici[0].startswith(("http://", "https://")) else None
    mostra_testo("Testo dallo schermo", "\n\n".join(parti), nota="Già copiato negli appunti: incollalo con Ctrl+V.",
                 link=link)


# ------------------------------------------------------------ unisci immagini
def unisci_immagini(files):
    import strumenti
    files = sorted(files, key=lambda p: strumenti._naturale(Path(p).name))
    scelta = strumenti.scegli_collage(files)
    if not scelta:
        return None
    modo, spazio, sfondo = scelta
    lato = 1600 if modo != "griglia" else 1000
    imgs = []
    for f in files:                       # gia' ridotte mentre le apro: poca RAM anche con 30 foto
        im = apri_immagine(f, (lato, lato))
        im.thumbnail((lato, lato))
        imgs.append(im)
    sp = spazio * max(lato // 100, 4)
    im = strumenti.collage(imgs, modo, sp, sfondo, lato)
    del imgs
    tutte_jpg = all(Path(f).suffix.lower() in (".jpg", ".jpeg") for f in files)
    out = libero(Path(files[0]).with_name(f"Immagini unite.{'jpg' if tutte_jpg else 'png'}"))
    with in_corso(out):
        _salva_immagine(im, out, 92)
    return f"Creata: {out.name}  ({im.width} × {im.height} px)"


# ---------------------------------------------------------- archivi: estrai e crea
def _nome_base(f):
    nome = f.name
    for e in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if nome.lower().endswith(e):
            return nome[: -len(e)]
    return f.stem


def _estrai(f, password=None, sciolto=False):
    """Estrae l'archivio accanto a se'. Se e' protetto chiede la password (finche' non e' giusta).
    sciolto=True: se dentro c'e' un solo elemento (file o cartella), lo rimette cosi' com'era.
    Restituisce il percorso creato, oppure None se annulli."""
    sz = sette_zip()
    out = libero(f.with_name(_nome_base(f)))
    tmp = Path(tempfile.mkdtemp(prefix="~sottomano_", dir=f.parent))
    try:
        with in_corso(out):
            sbagliata = False
            while True:
                try:
                    # senza password ne passo una finta: gli archivi normali la ignorano, quelli
                    # protetti danno subito "password sbagliata" (e allora te la chiedo)
                    run([sz, "x", str(f), f"-o{tmp}", "-y", "-p" + (password or "nessuna-password")])
                    break
                except RuntimeError as err:
                    if "password" not in str(err).lower():
                        raise
                    import strumenti
                    password = strumenti.chiedi_password(
                        "Protetto da password",
                        f"«{f.name}» è protetto." + (" Password sbagliata, riprova:" if sbagliata or password else
                                                    " Scrivi la password:"))
                    if password is None:
                        return None
                    sbagliata = True
                    shutil.rmtree(tmp, ignore_errors=True)
                    tmp.mkdir()
            interni = os.listdir(tmp)
            if len(interni) == 1 and interni[0].lower().endswith(".tar"):
                t = tmp / interni[0]
                run([sz, "x", str(t), f"-o{tmp}", "-y"])
                t.unlink()
                interni = os.listdir(tmp)
            # se dentro c'e' gia' una sola cartella, niente "cartella dentro la cartella"
            if len(interni) == 1 and ((tmp / interni[0]).is_dir() or sciolto):
                dest = libero(f.parent / interni[0])
                os.rename(tmp / interni[0], dest)
                tmp.rmdir()
            else:
                dest = out
                os.rename(tmp, dest)
        return dest
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)


def estrai_archivio(files):
    fatti = []
    for f in files:
        dest = _estrai(Path(f))
        if dest is None:
            break
        fatti.append(dest.name)
    return None if len(fatti) <= 1 else "Estratti in:\n" + "\n".join(fatti)


# ------------------------------------------------- blocco con password (file e cartelle)
def _chiedi_finche_giusta(p, titolo, verifica):
    """Chiede la password finche' e' giusta (verifica(pw) -> bool). False se annulli."""
    import strumenti
    testo = f"«{Path(p).name}» è bloccato. Scrivi la password:"
    while True:
        pw = strumenti.chiedi_password(titolo, testo)
        if pw is None:
            return False
        if verifica(pw):
            return True
        testo = f"Password sbagliata per «{Path(p).name}». Riprova:"


def blocca_file(files):
    import blocco
    import strumenti
    files = [str(Path(f)) for f in files]
    nome = Path(files[0]).name if len(files) == 1 else f"{len(files)} elementi"
    password = strumenti.chiedi_blocco(nome, cartella=any(os.path.isdir(f) for f in files))
    if not password:
        return None
    try:
        blocco.blocca(files, password)
    except blocco.Errore as e:
        raise RuntimeError(str(e))
    return None                                   # nessun messaggio: lo vedi provando ad aprirlo


def sblocca_e_apri(files, anteprima=False):
    """Password (se serve), poi apre l'elemento vero: nel suo programma o nell'anteprima."""
    import blocco
    p = files[0]
    v = blocco.voce(p)
    if v is None:
        reale = p
    elif v["stato"] == "bloccato":
        esito = {}

        def prova(pw):
            esito["p"] = blocco.apri(p, pw)
            return esito["p"] is not None
        if not _chiedi_finche_giusta(v.get("origine") or p, "Sblocca", prova):
            return None
        reale = esito["p"]
    else:
        reale = v["percorso"]
    if anteprima:
        apri_anteprima(reale)
    else:
        os.startfile(reale)
    return None


def apri_bloccato(files):
    """Doppio clic sul collegamento di un elemento bloccato (files[0] = il suo codice)."""
    import blocco
    v = blocco.per_id(files[0])
    if v is None:
        info("Questo collegamento non serve più: l'elemento non è più bloccato da Sottomano.\n"
             "Se l'hai sbloccato del tutto, lo trovi al suo posto originale.")
        return None
    return sblocca_e_apri([v["percorso"]])


def elenco_bloccati(files=None):
    """Finestra con tutti gli elementi bloccati (anche se ne hai cancellato il collegamento)."""
    import blocco
    import strumenti

    def apri(v):
        sblocca_e_apri([v["percorso"]])

    def completo(v):
        return togli_blocco([v["percorso"]])

    def ricrea(v):
        blocco.ricrea_collegamento(v["percorso"])
    strumenti.elenco_bloccati(lambda: list(blocco.leggi().values()), apri, completo, ricrea)


def richiudi_file(files):
    import blocco
    for f in files:
        blocco.richiudi(f)


def togli_blocco(files):
    """Sblocco completo: per sempre, e l'elemento torna al suo posto al posto del collegamento."""
    import blocco
    rimessi = []
    for f in files:
        v = blocco.voce(f)
        if v is None:
            continue
        esito = {}

        def prova(pw, f=f):
            esito["p"] = blocco.togli(f, pw)
            return esito["p"] is not False
        if v["stato"] == "bloccato":
            if not _chiedi_finche_giusta(v.get("origine") or f, "Sblocco completo", prova):
                return None
        else:
            esito["p"] = blocco.togli(f)
        if isinstance(esito.get("p"), str):
            rimessi.append(esito["p"])
    return None


def sblocca(files):
    """Rimette i file com'erano (chiede la password); l'archivio protetto va nel Cestino."""
    fatti = []
    for f in files:
        f = Path(f)
        dest = _estrai(f, sciolto=True)
        if dest is None:
            break
        try:
            al_cestino([f])
        except Exception:
            log(f"--- sblocca: cestino {f}\n{traceback.format_exc()}")
        fatti.append(dest.name)
    return None


def crea_archivio(files, fmt):
    sz = sette_zip()
    files = [Path(f) for f in files]
    base = files[0].stem if len(files) == 1 and files[0].is_file() else files[0].name if len(files) == 1 \
        else files[0].parent.name or "Archivio"
    out = libero(files[0].with_name(f"{base}.{fmt}"))
    with in_corso(out):
        run([sz, "a", f"-t{fmt}", "-mx=7" if fmt == "zip" else "-mx=9", str(out), *[str(f) for f in files]])
    return None


# ----------------------------------------------------------------- PDF in piu'
def conta_pagine(f):
    """Numero di pagine, in un attimo (PDFium). PyMuPDF lo carico solo per il lavoro vero."""
    def con_pymupdf():
        with apri_pdf(f) as d:
            if d.needs_pass:
                raise RuntimeError("Il PDF è protetto da password: prima usa «Aggiungi o togli password».")
            return d.page_count
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return con_pymupdf()
    try:
        pdf = pdfium.PdfDocument(str(f))
    except Exception as e:
        if "password" in str(e).lower():
            raise RuntimeError("Il PDF è protetto da password: prima usa «Aggiungi o togli password».")
        return con_pymupdf()          # ripara il PDF o spiega cosa c'e' che non va
    try:
        return len(pdf)
    finally:
        pdf.close()


def pdf_dividi(files):
    import strumenti
    f = Path(files[0])
    n = conta_pagine(f)
    scelta = strumenti.scegli_divisione(n, f.name)
    if not scelta:
        return None
    fitz = _fitz()
    with apri_pdf(f) as doc:

        def salva(pagine, out):
            nuovo = fitz.open()
            for a, b in _blocchi(pagine):
                nuovo.insert_pdf(doc, from_page=a, to_page=b)
            nuovo.save(out, garbage=3, deflate=True)
            nuovo.close()

        if scelta[0] == "pagine":
            etichetta = "".join(c for c in scelta[2] if c.isdigit() or c in "-,").strip(",")[:30]
            out = libero(f.with_name(f"{f.stem} (pagine {etichetta}).pdf"))
            with in_corso(out):
                salva(scelta[1], out)
            return f"Creato: {out.name}  ({len(scelta[1])} pagine)"
        cartella = libero(f.with_name(f"{f.stem} - diviso"))
        cartella.mkdir()
        passo = 1 if scelta[0] == "singole" else scelta[1]
        cifre = len(str(n))
        for i, inizio in enumerate(range(0, n, passo), 1):
            fine = min(inizio + passo, n) - 1
            nome = f"pagina {inizio + 1:0{cifre}d}.pdf" if passo == 1 else \
                f"parte {i:02d} (pagine {inizio + 1}-{fine + 1}).pdf"
            salva(list(range(inizio, fine + 1)), cartella / nome)
        return f"Creati {-(-n // passo)} PDF nella cartella:\n{cartella.name}"


def _blocchi(pagine):
    """[0,1,2,5,6] -> [(0,2),(5,6)]: inserire blocchi di pagine e' molto piu' veloce che una alla volta."""
    out = []
    for p in pagine:
        if out and p == out[-1][1] + 1:
            out[-1][1] = p
        else:
            out.append([p, p])
    return [tuple(x) for x in out]


def pdf_pagine(files):
    import strumenti
    f = Path(files[0])
    conta_pagine(f)                        # PDF protetto: lo dico subito, con un messaggio chiaro
    ed = strumenti.EditorPagine(f, _fitz)
    if not ed.risultato:
        return None
    out = libero(f.with_name(f.stem + " (modificato).pdf"))
    with in_corso(out), apri_pdf(f) as doc:
        rot_orig = [doc[i].rotation for i in range(doc.page_count)]
        doc.select([i for i, _ in ed.risultato])
        for j, (i, extra) in enumerate(ed.risultato):
            if extra:
                doc[j].set_rotation((rot_orig[i] + extra) % 360)
        doc.save(out, garbage=3, deflate=True)
    return f"Salvato: {out.name}  ({len(ed.risultato)} pagine)"


def pdf_password(files):
    import strumenti
    fitz = _fitz()
    righe = []
    nuova = None
    for f in files:
        f = Path(f)
        doc = apri_pdf(f)
        try:
            if doc.needs_pass:
                messaggio_pw = f"«{f.name}» è protetto. Scrivi la password per salvarne una copia senza password:"
                while True:
                    pw = strumenti.chiedi_password("Togli password", messaggio_pw)
                    if pw is None:
                        return "\n".join(righe) or None
                    if doc.authenticate(pw):
                        break
                    messaggio_pw = f"Password sbagliata per «{f.name}». Riprova:"
                out = libero(f.with_name(f.stem + " (senza password).pdf"))
                with in_corso(out):
                    doc.save(out, encryption=fitz.PDF_ENCRYPT_NONE, garbage=3, deflate=True)
                righe.append(f"Sbloccato: {out.name}")
            else:
                if nuova is None:
                    nuova = strumenti.chiedi_password(
                        "Proteggi con password",
                        "Scegli la password per aprire il PDF" + (" (vale per tutti i file selezionati)." if len(files) > 1 else "."),
                        conferma=True)
                    if nuova is None:
                        return "\n".join(righe) or None
                out = libero(f.with_name(f.stem + " (protetto).pdf"))
                with in_corso(out):
                    doc.save(out, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw=nuova, user_pw=nuova,
                             garbage=3, deflate=True)
                righe.append(f"Protetto: {out.name}")
        finally:
            doc.close()
    if nuova:
        righe.append("\nRicordati la password: senza, il PDF non si apre più.")
    return "\n".join(righe)


# --------------------------------------------------------- Word, Excel... in PDF
def office_pdf(files):
    """Usa Microsoft Office se c'e' (stesso risultato di 'Salva come PDF'), altrimenti LibreOffice."""
    righe = []
    for f in files:
        f = Path(f)
        out = libero(f.with_suffix(".pdf"))
        with in_corso(out):
            try:
                _office_com(f, out)
            except _NoOffice:
                _libreoffice(f, out)
        righe.append(out.name)
    return "Creati:\n" + "\n".join(righe)


class _NoOffice(Exception):
    pass


def _office_com(f, out):
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        raise _NoOffice()
    ext = f.suffix.lower()
    prog = "Word.Application" if ext in (".doc", ".docx", ".rtf", ".odt") else \
        "Excel.Application" if ext in (".xls", ".xlsx", ".ods") else "PowerPoint.Application"
    pythoncom.CoInitialize()
    try:
        app = win32com.client.DispatchEx(prog)          # istanza separata: non tocca i documenti che hai aperti
    except Exception:
        raise _NoOffice()
    try:
        if prog.startswith("Word"):
            app.Visible = False
            app.DisplayAlerts = 0
            doc = app.Documents.Open(str(f), ConfirmConversions=False, ReadOnly=True, AddToRecentFiles=False)
            try:
                doc.ExportAsFixedFormat(str(out), 17)    # wdExportFormatPDF
            finally:
                doc.Close(False)
        elif prog.startswith("Excel"):
            app.Visible = False
            app.DisplayAlerts = False
            wb = app.Workbooks.Open(str(f), ReadOnly=True, AddToMru=False)
            try:
                wb.ExportAsFixedFormat(0, str(out))       # xlTypePDF
            finally:
                wb.Close(False)
        else:
            pres = app.Presentations.Open(str(f), ReadOnly=True, Untitled=False, WithWindow=False)
            try:
                pres.SaveAs(str(out), 32)                 # ppSaveAsPDF
            finally:
                pres.Close()
    finally:
        try:
            app.Quit()
        except Exception:
            pass


def _libreoffice(f, out):
    exe = trova_exe(r"%ProgramFiles%\LibreOffice\program\soffice.exe",
                    r"%ProgramFiles(x86)%\LibreOffice\program\soffice.exe", "soffice")
    if not exe:
        raise RuntimeError("Per convertire in PDF serve Microsoft Office oppure LibreOffice (gratis).")
    with tempfile.TemporaryDirectory() as tmp:
        run([exe, "--headless", "--norestore", "--convert-to", "pdf", "--outdir", tmp, str(f)])
        prodotto = Path(tmp) / (f.stem + ".pdf")
        if not prodotto.exists():
            raise RuntimeError("LibreOffice non è riuscito a convertire il file.")
        shutil.move(str(prodotto), str(out))


# -------------------------------------------------------------- video: taglia
def durata_media(f):
    """Durata in secondi letta dall'intestazione (ffmpeg -i), senza decodificare nulla."""
    import re
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(f)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    if not m:
        raise RuntimeError("Non riesco a leggere la durata del file.")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)), r.stderr


def fotogramma(f, t, w, h):
    """Un solo fotogramma all'istante t, gia' rimpicciolito (ricerca veloce sui fotogrammi chiave)."""
    import io
    from PIL import Image
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(f),
                        "-frames:v", "1", "-vf", f"scale='min({w},iw)':'min({h},ih)':force_original_aspect_ratio=decrease",
                        "-f", "image2pipe", "-c:v", "bmp", "-"], capture_output=True, creationflags=NO_WINDOW,
                       stdin=subprocess.DEVNULL)
    if not r.stdout:
        return None
    return Image.open(io.BytesIO(r.stdout)).convert("RGB")


def taglia(files):
    import strumenti
    f = Path(files[0])
    durata, _ = durata_media(f)
    video = f.suffix.lower() in VID_EXT
    ed = strumenti.EditorTaglio(f.name, durata, (lambda t, w, h: fotogramma(f, t, w, h)) if video else None)
    if not ed.risultato:
        return None
    a, b, preciso = ed.risultato
    tempo = ["-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(f)]
    if not preciso:
        out = libero(f.with_name(f"{f.stem} (tagliato){f.suffix}"))
        with in_corso(out):
            _ffmpeg([*tempo, "-map", "0", "-c", "copy", "-avoid_negative_ts", "make_zero", str(out)])
    elif video:
        out = libero(f.with_name(f"{f.stem} (tagliato).mp4"))
        with in_corso(out):
            _ffmpeg([*tempo, "-map", "0:v:0", "-map", "0:a?", *H264, *AAC, "-movflags", "+faststart", str(out)])
    else:
        ext = f.suffix.lower().lstrip(".")
        fmt = ext if ext in AUDIO_OPZ else "mp3"
        out = libero(f.with_name(f"{f.stem} (tagliato).{fmt}"))
        with in_corso(out):
            _ffmpeg([*tempo, "-vn", "-map", "0:a:0", *AUDIO_OPZ[fmt], str(out)])
    return f"Salvato: {out.name}  ({strumenti._mmss(b - a)})"


ESTENSIONE_CODEC = {"aac": "m4a", "alac": "m4a", "mp3": "mp3", "opus": "opus", "vorbis": "ogg", "flac": "flac",
                    "ac3": "ac3", "eac3": "eac3", "pcm_s16le": "wav", "pcm_s24le": "wav"}


def audio_originale(files):
    """Estrae la traccia audio cosi' com'e' (nessuna ricodifica: istantaneo, qualita' identica)."""
    import re
    fatti = []
    for f in files:
        f = Path(f)
        _, info = durata_media(f)
        m = re.search(r"Audio:\s*([\w]+)", info)
        if not m:
            raise RuntimeError(f"«{f.name}» non ha una traccia audio.")
        ext = ESTENSIONE_CODEC.get(m.group(1), "mka")
        out = libero(f.with_suffix("." + ext))
        with in_corso(out):
            _ffmpeg(["-i", str(f), "-vn", "-map", "0:a:0", "-c:a", "copy", str(out)])
        fatti.append((f, out))
    return "Audio estratto senza ricodifica:\n" + _riepilogo(fatti)


# -------------------------------------------------- sottotitoli automatici (AI)
MODELLO_WHISPER = "base"     # leggero: ~145 MB, va bene anche sui PC lenti


def _srt_tempo(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def sottotitoli(files):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError("Funzione opzionale non installata.\nRilancia installa.bat e rispondi S alla domanda "
                           "sui sottotitoli automatici.")
    files = [Path(f) for f in files]
    uscite = [libero(f.with_suffix(".srt" if f.suffix.lower() in VID_EXT else ".txt")) for f in files]
    righe = []
    with in_corso(*uscite):
        modello = WhisperModel(MODELLO_WHISPER, device="cpu", compute_type="int8",
                               download_root=str(BASE / "modelli" / "whisper"),
                               cpu_threads=max((os.cpu_count() or 2) - 1, 1))
        for f, out in zip(files, uscite):
            segmenti, info = modello.transcribe(str(f), vad_filter=True)
            with open(out, "w", encoding="utf-8") as fh:
                for i, s in enumerate(segmenti, 1):
                    if out.suffix == ".srt":
                        fh.write(f"{i}\n{_srt_tempo(s.start)} --> {_srt_tempo(s.end)}\n{s.text.strip()}\n\n")
                    else:
                        fh.write(s.text.strip() + "\n")
            righe.append(f"{out.name}  (lingua: {info.language})")
    nota = "\n\nI lettori video (VLC, Film e TV...) caricano da soli il file .srt con lo stesso nome del video." \
        if any(o.suffix == ".srt" for o in uscite) else ""
    return "Creati:\n" + "\n".join(righe) + nota


# ------------------------------------------------------------------ duplicati
def al_cestino(percorsi):
    """Sposta nel Cestino (recuperabili), non cancella definitivamente."""
    from win32com.shell import shell, shellcon
    flag = shellcon.FOF_ALLOWUNDO | shellcon.FOF_NOCONFIRMATION | shellcon.FOF_SILENT | shellcon.FOF_NOERRORUI
    try:
        shell.SHFileOperation((0, shellcon.FO_DELETE, "\0".join(str(p) for p in percorsi), None, flag, None, None))
    except Exception:
        for p in percorsi:                    # ripiego: uno alla volta
            try:
                shell.SHFileOperation((0, shellcon.FO_DELETE, str(p), None, flag, None, None))
            except Exception:
                log(f"--- cestino {p}\n{traceback.format_exc()}")


def trova_duplicati(files):
    import strumenti
    cartella = Path(files[0]) if files else None
    if cartella is None or not cartella.is_dir():
        cartella = cartella.parent if cartella else Path.home()
    strumenti.duplicati(str(cartella), al_cestino)


AZIONI = {
    "png":            lambda fs: converti_immagine(fs, "png"),
    "jpg":            lambda fs: converti_immagine(fs, "jpg"),
    "webp":           lambda fs: converti_immagine(fs, "webp"),
    "ico":            lambda fs: converti_immagine(fs, "ico"),
    "img2pdf":        immagini_in_pdf,
    "ocr":            ocr,
    "comprimi":       comprimi_immagini,
    "ritaglia":       ritaglia_immagine,
    "metadati":       rimuovi_metadati,
    "sfondo":         rimuovi_sfondo,
    "pdf_testo":      pdf_testo,
    "pdf_unisci":     pdf_unisci,
    "pdf_immagini":   pdf_in_immagini,
    "pdf_comprimi":   pdf_comprimi,
    "to7z":           lambda fs: converti_archivio(fs, "7z"),
    "tozip":          lambda fs: converti_archivio(fs, "zip"),
    "torar":          lambda fs: converti_archivio(fs, "rar"),
    "v_mp4":          lambda fs: converti_video(fs, "mp4"),
    "v_mkv":          lambda fs: converti_video(fs, "mkv"),
    "v_mov":          lambda fs: converti_video(fs, "mov"),
    "v_webm":         lambda fs: converti_video(fs, "webm"),
    "v_gif":          lambda fs: converti_video(fs, "gif"),
    "v_comprimi":     comprimi_video,
    "a_mp3":          lambda fs: converti_audio(fs, "mp3"),
    "a_wav":          lambda fs: converti_audio(fs, "wav"),
    "a_m4a":          lambda fs: converti_audio(fs, "m4a"),
    "a_flac":         lambda fs: converti_audio(fs, "flac"),
    "hash":           hash_file,
    # nuove
    "rinomina":       rinomina_file,
    "ruota_dx":       lambda fs: ruota_immagini(fs, "dx"),
    "ruota_sx":       lambda fs: ruota_immagini(fs, "sx"),
    "ruota_180":      lambda fs: ruota_immagini(fs, "180"),
    "copia_percorso": copia_percorso,
    "copia_immagine": copia_immagine,
    "copia_testo":    copia_contenuto,
    "qr_crea":        crea_qr,
    "qr_leggi":       leggi_qr,
    "zona":           zona_schermo,
    "unisci_img":     unisci_immagini,
    "estrai":         estrai_archivio,
    "sblocca":        sblocca,
    "blocca":         blocca_file,
    "sblocca_apri":   sblocca_e_apri,
    "sblocca_vedi":   lambda fs: sblocca_e_apri(fs, anteprima=True),
    "richiudi":       richiudi_file,
    "togli_blocco":   togli_blocco,
    "apri_bloccato":  apri_bloccato,
    "bloccati_elenco": elenco_bloccati,
    "crea_zip":       lambda fs: crea_archivio(fs, "zip"),
    "crea_7z":        lambda fs: crea_archivio(fs, "7z"),
    "pdf_dividi":     pdf_dividi,
    "pdf_pagine":     pdf_pagine,
    "pdf_password":   pdf_password,
    "office_pdf":     office_pdf,
    "taglia":         taglia,
    "a_orig":         audio_originale,
    "sottotitoli":    sottotitoli,
    "duplicati":      trova_duplicati,
}
SENZA_FILE = {"zona", "qr_crea", "duplicati", "bloccati_elenco"}      # azioni che funzionano anche senza file selezionati


# ===================================================== menu rapido (Ctrl+Alt+S)
def log(testo):
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(testo.rstrip() + "\n")
    except Exception:
        pass


def file_selezionati(hwnd=None):
    """File selezionati in Esplora file o sul desktop. Prova piu' metodi, dal piu' preciso."""
    import win32gui
    hwnd = hwnd or win32gui.GetForegroundWindow()
    classe = win32gui.GetClassName(hwnd)
    desktop = classe in ("Progman", "WorkerW")
    cartelle = []
    metodi = [_selezione_desktop, _selezione_desktop_alt] if desktop else [lambda: _selezione_esplora(hwnd, cartelle)]
    metodi.append(lambda: _selezione_uia(_cartelle_desktop() if desktop else cartelle))
    for m in metodi:
        try:
            files = [f for f in m() if f and os.path.exists(f)]
            if files:
                return files
        except Exception:
            log(f"--- selezione ({classe})\n{traceback.format_exc()}")
    log(f"--- nessun file trovato, finestra in primo piano: {classe}")
    return []


_SHELL = None


def shell_app():
    """Oggetto Shell.Application di Windows: creato una volta e poi riusato (ogni volta costa)."""
    global _SHELL
    if _SHELL is None:
        import win32com.client
        _SHELL = win32com.client.Dispatch("Shell.Application")
    return _SHELL


def _finestre_esplora(hwnd):
    global _SHELL
    for tentativo in (1, 2):
        try:
            out = []
            for w in shell_app().Windows():
                try:
                    if int(w.HWND) == hwnd:
                        out.append(w)
                except Exception:
                    pass
            return out
        except Exception:
            _SHELL = None            # Esplora file riavviato: ricreo l'oggetto
            if tentativo == 2:
                raise


def cartella_attiva(hwnd):
    """Cartella aperta nella finestra di Esplora file (o il desktop)."""
    import win32gui
    if win32gui.GetClassName(hwnd) in ("Progman", "WorkerW"):
        d = _cartelle_desktop()
        return d[0] if d else None
    try:
        finestre = _finestre_esplora(hwnd)
        if len(finestre) > 1:
            finestre = [_scheda_attiva(hwnd, finestre) or finestre[0]]
        if finestre:
            p = finestre[0].Document.Folder.Self.Path
            return p if os.path.isdir(p) else None
    except Exception:
        log(f"--- cartella attiva\n{traceback.format_exc()}")
    return None


def _selezione_esplora(hwnd, cartelle_out):
    candidati = _finestre_esplora(hwnd)
    if not candidati:
        return []
    scelto = candidati[0]
    if len(candidati) > 1:  # piu' schede: prendo quella attiva
        scelto = _scheda_attiva(hwnd, candidati) or candidati[0]
    try:
        cartelle_out.append(scelto.Document.Folder.Self.Path)
    except Exception:
        pass
    return [it.Path for it in scelto.Document.SelectedItems()]


def _cartelle_desktop():
    from win32com.shell import shell as sh, shellcon
    out = []
    for csidl in (shellcon.CSIDL_DESKTOPDIRECTORY, shellcon.CSIDL_COMMON_DESKTOPDIRECTORY):
        try:
            out.append(sh.SHGetFolderPath(0, csidl, None, 0))
        except Exception:
            pass
    return out


def _selezione_desktop():
    """Metodo 'ufficiale': ShellWindows.FindWindowSW(SWC_DESKTOP) -> IShellBrowser -> vista attiva."""
    import pythoncom
    import win32com.client
    import win32com.shell.shell  # registra l'interfaccia IShellBrowser in pythoncom
    SID_STopLevelBrowser = pythoncom.MakeIID("{4C96BE40-915C-11CF-99D3-00AA004AE837}")
    IID_IShellBrowser = pythoncom.MakeIID("{000214E2-0000-0000-C000-000000000046}")
    sw = win32com.client.gencache.EnsureDispatch("{9BA05972-F6A8-11CF-A442-00A0C90A8F39}")  # ShellWindows
    loc = win32com.client.VARIANT(pythoncom.VT_I4, 0)          # CSIDL_DESKTOP
    root = win32com.client.VARIANT(pythoncom.VT_EMPTY, None)
    res = sw.FindWindowSW(loc, root, 8, 0, 1)                   # SWC_DESKTOP, SWFO_NEEDDISPATCH
    disp = None
    for x in (res if isinstance(res, tuple) else (res,)):
        if not isinstance(x, int):
            disp = x
    ole = getattr(disp, "_oleobj_", disp)
    sp = ole.QueryInterface(pythoncom.IID_IServiceProvider)
    sb = sp.QueryService(SID_STopLevelBrowser, IID_IShellBrowser)
    view = sb.QueryActiveShellView()
    doc = win32com.client.Dispatch(view.GetItemObject(0, pythoncom.IID_IDispatch))  # SVGIO_BACKGROUND
    return [it.Path for it in doc.SelectedItems()]


def _selezione_uia(cartelle):
    """Ripiego: legge i nomi selezionati con UI Automation e li cerca nelle cartelle note."""
    U, automazione = uia()
    fuoco = automazione.GetFocusedElement()
    nomi = []
    try:
        lista = automazione.ControlViewWalker.GetParentElement(fuoco)
        pat = lista.GetCurrentPattern(10001).QueryInterface(U.IUIAutomationSelectionPattern)
        sel = pat.GetCurrentSelection()
        nomi = [sel.GetElement(i).CurrentName for i in range(sel.Length)]
    except Exception:
        pass
    if not nomi and fuoco.CurrentName:
        nomi = [fuoco.CurrentName]
    out = []
    for nome in nomi:
        trovato = None
        for c in cartelle:
            p = os.path.join(c, nome)
            if os.path.exists(p):
                trovato = p
                break
            # estensioni nascoste: cerco per nome senza estensione
            try:
                simili = [f for f in os.listdir(c) if os.path.splitext(f)[0] == nome]
            except OSError:
                simili = []
            if len(simili) == 1:
                trovato = os.path.join(c, simili[0])
                break
        if trovato:
            out.append(trovato)
    return out


def _scheda_attiva(hwnd, finestre):
    import win32gui
    # 1) via IShellBrowser: la scheda attiva e' il primo ShellTabWindowClass figlio
    try:
        import pythoncom
        from win32com.shell import shell as sh
        attiva = win32gui.FindWindowEx(hwnd, 0, "ShellTabWindowClass", None)
        for w in finestre:
            sp = w._oleobj_.QueryInterface(pythoncom.IID_IServiceProvider)
            sb = sp.QueryService(sh.SID_STopLevelBrowser, sh.IID_IShellBrowser)
            if sb.GetWindow() == attiva:
                return w
    except Exception:
        pass
    # 2) ripiego: il titolo della finestra e' il nome della scheda attiva
    titolo = win32gui.GetWindowText(hwnd)
    for w in finestre:
        try:
            if w.LocationName and titolo.startswith(w.LocationName):
                return w
        except Exception:
            pass
    return None


def _selezione_desktop_alt():
    """Secondo tentativo per il desktop: stessa idea, tramite Shell.Application."""
    import win32com.client
    import pythoncom
    from win32com.shell import shell as sh, shellcon
    sw = shell_app().Windows()
    loc = win32com.client.VARIANT(pythoncom.VT_I4, shellcon.CSIDL_DESKTOP)
    empty = win32com.client.VARIANT(pythoncom.VT_EMPTY, None)
    res = sw.FindWindowSW(loc, empty, 8, 0, 1)  # SWC_DESKTOP=8, SWFO_NEEDDISPATCH=1
    # a seconda della versione di pywin32 torna l'oggetto da solo oppure (hwnd, oggetto)
    disp = next((x for x in (res if isinstance(res, tuple) else (res,)) if not isinstance(x, int)), None)
    if disp is None:
        return []
    sp = getattr(disp, "_oleobj_", disp).QueryInterface(pythoncom.IID_IServiceProvider)
    sb = sp.QueryService(sh.SID_STopLevelBrowser, sh.IID_IShellBrowser)
    view = sb.QueryActiveShellView()
    doc = win32com.client.Dispatch(view.GetItemObject(0, pythoncom.IID_IDispatch))
    return [it.Path for it in doc.SelectedItems()]


_UIA = None


def uia():
    """UI Automation di Windows: creata una volta sola e poi riusata (piu' veloce, meno memoria)."""
    global _UIA
    if _UIA is None:
        import comtypes.client
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as U
        _UIA = (U, comtypes.client.CreateObject(U.CUIAutomation, interface=U.IUIAutomation))
    return _UIA


def posizione_menu():
    """Angolo in alto a sinistra dell'elemento selezionato (UI Automation); altrimenti il mouse."""
    import win32api
    try:
        r = uia()[1].GetFocusedElement().CurrentBoundingRectangle
        if r.right > r.left and r.bottom > r.top:
            return r.left, r.top, True
    except Exception:
        pass
    x, y = win32api.GetCursorPos()
    return x, y, False


def _tema_scuro_menu():
    """Menu scuri se Windows e' in tema scuro (uxtheme SetPreferredAppMode, ordinale 135)."""
    try:
        import ctypes
        ux = ctypes.WinDLL("uxtheme")
        ux[135](1)  # AllowDark: segue il tema di sistema
        ux[136]()   # FlushMenuThemes
    except Exception:
        pass


_DISPONIBILE = {}


def disponibile(modulo):
    """La funzione opzionale e' installata? (controllato una volta sola)"""
    if modulo not in _DISPONIBILE:
        try:
            import importlib.util
            _DISPONIBILE[modulo] = importlib.util.find_spec(modulo) is not None
        except Exception:
            _DISPONIBILE[modulo] = False
    return _DISPONIBILE[modulo]


def voci_per(files):
    """Restituisce [(etichetta, azione) | (etichetta, [sottovoci]) | None per separatore]."""
    if not files:
        return []
    try:
        import blocco
        reg = blocco.leggi()
        stati = {blocco.stato(f, reg) for f in files} if reg else {None}
    except Exception:
        stati = {None}
    if "bloccato" in stati:            # bloccato: si puo' solo sbloccare
        return [("Sblocco completo…", "togli_blocco"), ("Sblocco parziale (apri)…", "sblocca_apri")]
    if stati == {"aperto"}:            # sblocco parziale in corso: si richiude da solo quando lo chiudi
        return [("Apri", "sblocca_apri"), None, ("Sblocco completo", "togli_blocco"),
                ("Blocca subito", "richiudi"), ("Cambia password…", "blocca")]
    return _voci_normali(files)


def _voci_normali(files):
    est = {Path(f).suffix.lower() for f in files}
    uno = len(files) == 1
    copia = [("Percorso", "copia_percorso")]
    archivio = ("Crea archivio", [("ZIP", "crea_zip"), ("7z", "crea_7z")])
    if any(os.path.isdir(f) for f in files):
        v = []
        if uno:
            v.append(("Trova duplicati qui dentro…", "duplicati"))
        v.append(archivio)
        v.append(("Blocca con password…", "blocca"))
        if len(files) > 1:
            v.append(("Rinomina in blocco…", "rinomina"))
        v += [None, ("Copia", copia)]
        return v
    tutte_img = est <= IMG_EXT
    tutte_pdf = est == {".pdf"}
    tutte_arc = est <= ARC_EXT
    tutti_vid = est <= VID_EXT
    tutti_aud = est <= AUD_EXT
    tutti_office = est <= OFFICE_EXT

    def formati(opzioni):
        """Tolgo il formato che i file hanno gia' (inutile convertire MP4 in MP4)."""
        return [o for o in opzioni if o is None or {"." + o[1].split("_")[-1]} != est]
    v = []
    if tutte_img:
        v.append(("Converti in", [("PNG", "png"), ("JPG", "jpg"), ("WEBP", "webp"),
                                  ("ICO (icona)", "ico"), None, ("PDF", "img2pdf")]))
        v.append(("Ruota", [("90° a destra", "ruota_dx"), ("90° a sinistra", "ruota_sx"), ("180°", "ruota_180")]))
        if uno:
            v.append(("Ritaglia e ridimensiona…", "ritaglia"))
        else:
            v.append(("Ridimensiona e comprimi…", "comprimi"))
            v.append(("Unisci in un'immagine…", "unisci_img"))
        v.append(None)
        v.append(("Estrai testo (OCR)", "ocr"))
        v.append(("Leggi QR code", "qr_leggi"))
        v.append(("Rimuovi metadati (GPS, EXIF)", "metadati"))
        if disponibile("rembg"):
            v.append(("Rimuovi sfondo (AI)", "sfondo"))
        if uno:
            copia.append(("Immagine", "copia_immagine"))
    elif tutte_pdf:
        v += [("Copia testo dal PDF", "pdf_testo"), ("Estrai testo con OCR", "ocr")]
        if len(files) > 1:
            v.append(("Unisci PDF", "pdf_unisci"))
        else:
            v.append(("Dividi o estrai pagine…", "pdf_dividi"))
            v.append(("Ruota, riordina, elimina pagine…", "pdf_pagine"))
        v += [("PDF in immagini (PNG)", "pdf_immagini"), ("Comprimi PDF", "pdf_comprimi"),
              ("Aggiungi o togli password…", "pdf_password")]
    elif tutti_office:
        v.append(("Converti in PDF", "office_pdf"))
    elif tutte_arc:
        if all("(protetto)" in Path(f).name for f in files):
            v.append(("Togli password", "sblocca"))
        v.append(("Estrai qui", "estrai"))
        v.append(("Converti in", [("7z", "to7z"), ("ZIP", "tozip"), ("RAR", "torar")]))
    elif tutti_vid:
        v.append(("Converti in", formati([("MP4", "v_mp4"), ("MKV", "v_mkv"), ("MOV", "v_mov"),
                                          ("WEBM", "v_webm"), None, ("GIF animata", "v_gif")])))
        if uno:
            v.append(("Taglia…", "taglia"))
        v.append(("Comprimi video", "v_comprimi"))
        v.append(("Estrai audio", [("MP3", "a_mp3"), ("WAV", "a_wav"), ("M4A", "a_m4a"), None,
                                   ("Originale (senza ricodifica)", "a_orig")]))
        if disponibile("faster_whisper"):
            v.append(("Crea sottotitoli (AI)", "sottotitoli"))
    elif tutti_aud:
        v.append(("Converti in", formati([("MP3", "a_mp3"), ("WAV", "a_wav"),
                                          ("M4A", "a_m4a"), ("FLAC", "a_flac")])))
        if uno:
            v.append(("Taglia…", "taglia"))
        if disponibile("faster_whisper"):
            v.append(("Trascrivi in testo (AI)", "sottotitoli"))
    elif uno and est <= TXT_EXT | {".url"}:
        v.append(("Crea QR code…", "qr_crea"))
    if uno and est <= TXT_EXT:
        copia.append(("Contenuto (testo)", "copia_testo"))
    if v:
        v.append(None)
    if len(files) > 1:
        v.append(("Rinomina in blocco…", "rinomina"))
    v.append(archivio)
    v.append(("Blocca con password…", "blocca"))
    v.append(("Copia", copia))
    v.append(("Calcola SHA-256", "hash"))
    return v


def voci_cartella():
    """Menu quando non c'e' niente di selezionato: strumenti che lavorano sulla cartella aperta."""
    return [("Crea QR code…", "qr_crea"),
            ("Trova duplicati in questa cartella…", "duplicati"),
            None,
            ("Testo da una zona dello schermo   Ctrl+Alt+T", "zona")]


def mostra_menu(files, cartella=None):
    import win32gui
    import win32con
    import win32api
    _tema_scuro_menu()

    wc = win32gui.WNDCLASS()
    wc.lpszClassName = "SottomanoMenu"
    wc.lpfnWndProc = {}
    wc.hInstance = win32api.GetModuleHandle(None)
    try:
        win32gui.RegisterClass(wc)
    except Exception:
        pass
    owner = win32gui.CreateWindow("SottomanoMenu", "Sottomano", win32con.WS_POPUP, 0, 0, 0, 0,
                                  0, 0, wc.hInstance, None)

    mappa, prossimo = {}, [1]

    def riempi(m, voci):
        for voce in voci:
            if voce is None:
                win32gui.AppendMenu(m, win32con.MF_SEPARATOR, 0, "")
            elif isinstance(voce[1], list):
                sub = win32gui.CreatePopupMenu()
                riempi(sub, voce[1])
                win32gui.AppendMenu(m, win32con.MF_POPUP, sub, voce[0])
            else:
                mappa[prossimo[0]] = voce[1]
                win32gui.AppendMenu(m, win32con.MF_STRING, prossimo[0], voce[0])
                prossimo[0] += 1

    if files:
        titolo = Path(files[0]).name if len(files) == 1 else f"{len(files)} elementi selezionati"
    else:
        titolo = Path(cartella).name or str(cartella)
    if len(titolo) > 40:
        titolo = titolo[:37] + "..."
    menu = win32gui.CreatePopupMenu()
    win32gui.AppendMenu(menu, win32con.MF_STRING | win32con.MF_GRAYED, 0, "Sottomano  -  " + titolo)
    win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
    riempi(menu, voci_per(files) if files else voci_cartella())

    x, y, _ = posizione_menu()
    # il menu si apre a SINISTRA del file, come un tasto destro "specchiato"
    flags = (win32con.TPM_RIGHTALIGN | win32con.TPM_TOPALIGN |
             win32con.TPM_RETURNCMD | win32con.TPM_RIGHTBUTTON)
    try:
        win32gui.SetForegroundWindow(owner)
    except Exception:
        pass
    scelta = win32gui.TrackPopupMenu(menu, flags, x, y, 0, owner, None)
    win32gui.PostMessage(owner, win32con.WM_NULL, 0, 0)
    win32gui.DestroyMenu(menu)
    win32gui.DestroyWindow(owner)
    return mappa.get(scelta)


# ============================================= servizio in background (hotkey)
TASTO = "S"  # Ctrl+Alt+S


def messaggio(testo):
    import ctypes
    ctypes.windll.user32.MessageBoxW(0, testo, "Sottomano", 0x40 | 0x40000)  # info + topmost


CLASSE_SERVIZIO = "SottomanoServizio"


def _attendi_tasti_rilasciati():
    """Rilasciare Alt con il menu aperto lo chiuderebbe: aspetto che Ctrl e Alt siano su."""
    import ctypes
    import time
    u = ctypes.windll.user32
    for _ in range(100):
        if not (u.GetAsyncKeyState(0x12) & 0x8000 or u.GetAsyncKeyState(0x11) & 0x8000):
            return
        time.sleep(0.02)


def _su_hotkey(lavoratore):
    import win32gui
    hwnd = win32gui.GetForegroundWindow()
    if win32gui.GetClassName(hwnd) not in ("CabinetWClass", "ExploreWClass", "Progman", "WorkerW"):
        return  # Ctrl+Alt+S premuto in un altro programma: lo ignoro
    files = file_selezionati(hwnd)
    cartella = None if files else cartella_attiva(hwnd)
    if not files and not cartella:
        messaggio("Seleziona prima uno o più file, poi premi Ctrl+Alt+S.")
        return
    _attendi_tasti_rilasciati()
    azione = mostra_menu(files, cartella)
    if not azione:
        return
    if azione == "copia_percorso":
        copia_percorso(files)                  # istantaneo: lo faccio qui, senza aprire niente
        return
    lavoratore.invia([azione] + (files or ([cartella] if azione != "zona" else [])))


def alleggerisci():
    """Pulizia leggera dopo un po' che non usi Sottomano. Non 'svuoto' piu' la memoria del processo
    (SetProcessWorkingSetSize): Windows doveva poi ricaricarla dal disco a ogni Ctrl+Alt+S o Spazio,
    e sui PC lenti si sentiva. Ci pensa gia' Windows, se la memoria serve ad altri programmi."""
    import gc
    gc.collect()


TIMER_RIPOSO = 78          # dopo 30 secondi senza usare Sottomano faccio pulizia
RIPOSO_MS = 30_000
TIMER_PRONTO = 79          # quando ripreparare il processo pronto
# sempre pythonw (senza finestra nera), anche se il servizio fosse stato avviato con python.exe
PYTHONW = str(Path(sys.executable).with_name("pythonw.exe")) \
    if Path(sys.executable).with_name("pythonw.exe").exists() else sys.executable


class Lavoratore:
    """Un processo Python gia' avviato che aspetta, fermo e senza usare CPU, il prossimo lavoro.

    Avviare Python, Tk, Pillow e PyMuPDF costa da mezzo secondo a qualche secondo sui PC lenti:
    lo faccio PRIMA che tu prema Spazio o scelga un'azione, cosi' quando serve la finestra si apre subito.
    Ogni processo pronto viene usato una volta sola (poi si chiude come prima); subito dopo ne preparo
    un altro. Se per qualche motivo non e' pronto, avvio un processo normale come facevo prima."""

    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.proc = None

    def prepara(self):
        import ctypes
        ctypes.windll.user32.KillTimer(self.hwnd, TIMER_PRONTO)
        if self.proc is not None and self.proc.poll() is None:
            return
        try:
            self.proc = subprocess.Popen([PYTHONW, str(SCRIPT), "pronto"], stdin=subprocess.PIPE,
                                         cwd=str(BASE), creationflags=0x00004000)   # priorita' bassa mentre carica
        except Exception:
            self.proc = None
            log(f"--- prepara\n{traceback.format_exc()}")

    def prepara_tra(self, ms):
        import ctypes
        ctypes.windll.user32.SetTimer(self.hwnd, TIMER_PRONTO, ms, None)

    def invia(self, comando):
        import ctypes
        p, self.proc = self.proc, None
        inviato = False
        if p is not None and p.poll() is None:
            try:
                ctypes.windll.user32.AllowSetForegroundWindow(p.pid)   # la sua finestra puo' venire in primo piano
                p.stdin.write((json.dumps(comando) + "\n").encode("utf-8"))
                p.stdin.close()
                inviato = True
            except OSError:
                pass
        if not inviato:
            subprocess.Popen([PYTHONW, str(SCRIPT), *comando], cwd=str(BASE))
        self.prepara_tra(800)    # il prossimo lo preparo dopo, per non rallentare quello che si sta aprendo

    def chiudi(self):
        p, self.proc = self.proc, None
        if p is not None:
            try:
                p.stdin.close()   # il processo pronto legge "fine" e si chiude da solo
            except OSError:
                pass


class SpazioAnteprima:
    """Tasti in Esplora file, SOLO quando sei nell'elenco dei file (o sul desktop):
      Spazio = anteprima (su un elemento bloccato: prima la password)
      Invio  = su un elemento bloccato chiede la password e lo apre (registrato solo se hai elementi bloccati)
    Inoltre, se hai elementi bloccati: quando Windows mostra "Accesso negato" perche' hai fatto doppio clic
    su uno di essi, al posto di quel messaggio compare la finestra della password.

    Non usa hook della tastiera ne' del mouse: segue quale finestra e' in primo piano (SetWinEventHook) e
    registra i tasti con RegisterHotKey solo mentre Esplora file e' attivo.
    Se il tasto serve per altro (rinomina, barra di ricerca, file non bloccato) lo "ripassa" a Windows.
    """
    CLASSI_ESPLORA = ("CabinetWClass", "ExploreWClass", "Progman", "WorkerW")
    VK_SPAZIO, VK_INVIO = 0x20, 0x0D

    def __init__(self, hwnd, id_spazio, id_invio):
        import ctypes
        self.u = ctypes.windll.user32
        self.hwnd = hwnd
        self.ids = {self.VK_SPAZIO: id_spazio, self.VK_INVIO: id_invio}
        self.attivi = set()                # tasti registrati in questo momento
        self._hook = None
        self._cb = None
        self.lavoratore = None
        self._reg_mtime = None
        self._bloccati = []
        self._ultimo_dialogo = (None, 0)

    # ---------------------------------------------------------- elementi bloccati
    def bloccati(self):
        """Elementi bloccati (letti dal registro solo quando cambia: costa quasi niente)."""
        try:
            import blocco
            m = blocco.REGISTRO.stat().st_mtime
        except OSError:
            m = None
        if m != self._reg_mtime:
            self._reg_mtime = m
            try:
                import blocco
                self._bloccati = blocco.bloccati() if m else []
            except Exception:
                self._bloccati = []
        return self._bloccati

    # ---------------------------------------------------------- finestra in primo piano
    def avvia(self):
        import ctypes
        from ctypes import wintypes
        PROC = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
                                  wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
        self._cb = PROC(lambda hook, ev, hwnd, *a: self._primo_piano(hwnd))  # riferimento tenuto vivo
        EVENT_SYSTEM_FOREGROUND, WINEVENT_OUTOFCONTEXT = 0x0003, 0x0000
        self._hook = self.u.SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND,
                                            0, self._cb, 0, 0, WINEVENT_OUTOFCONTEXT)
        self.aggiorna()

    def _primo_piano(self, hwnd):
        self.aggiorna()
        if hwnd and self.bloccati():
            try:
                self._forse_accesso_negato(hwnd)
            except Exception:
                log(f"--- accesso negato\n{traceback.format_exc()}")

    def _classe(self, h):
        import ctypes
        buf = ctypes.create_unicode_buffer(256)
        self.u.GetClassNameW(h, buf, 256)
        return buf.value

    def aggiorna(self):
        try:
            esplora = self._classe(self.u.GetForegroundWindow()) in self.CLASSI_ESPLORA
            vogliamo = set()
            if esplora:
                vogliamo.add(self.VK_SPAZIO)
                if self.bloccati():
                    vogliamo.add(self.VK_INVIO)
            for vk in vogliamo - self.attivi:
                if self.u.RegisterHotKey(self.hwnd, self.ids[vk], 0x4000, vk):   # MOD_NOREPEAT
                    self.attivi.add(vk)
            for vk in self.attivi - vogliamo:
                self.u.UnregisterHotKey(self.hwnd, self.ids[vk])
                self.attivi.discard(vk)
        except Exception:
            log(f"--- tasti aggiorna\n{traceback.format_exc()}")

    def spegni(self):
        for vk in list(self.attivi):
            self.u.UnregisterHotKey(self.hwnd, self.ids[vk])
        self.attivi.clear()
        if self._hook:
            self.u.UnhookWinEvent(self._hook)
            self._hook = None

    TIMER_RIATTIVA = 77

    def _ripassa(self, vk):
        """Il tasto non era per noi: lo rimando alla finestra come se nulla fosse.
        Torno in ascolto solo dopo un attimo (timer): altrimenti intercetterei di nuovo
        proprio il tasto che ho appena rimandato, all'infinito."""
        self.u.UnregisterHotKey(self.hwnd, self.ids[vk])
        self.attivi.discard(vk)
        self.u.keybd_event(vk, 0, 0, 0)
        self.u.keybd_event(vk, 0, 2, 0)
        self.u.SetTimer(self.hwnd, self.TIMER_RIATTIVA, 80, None)

    def riattiva(self):
        """Chiamata dal timer: torno in ascolto se Esplora file e' ancora in primo piano."""
        self.u.KillTimer(self.hwnd, self.TIMER_RIATTIVA)
        self.aggiorna()

    def _focus_su_elenco_file(self, fg):
        import ctypes
        from ctypes import wintypes

        class GUITHREADINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                        ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                        ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                        ("rcCaret", wintypes.RECT)]
        gi = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
        tid = self.u.GetWindowThreadProcessId(fg, None)
        if not self.u.GetGUIThreadInfo(tid, ctypes.byref(gi)) or not gi.hwndFocus:
            return False
        if gi.hwndCaret:  # c'e' un cursore di testo: stai scrivendo
            return False
        classe = self._classe(gi.hwndFocus)
        if classe == "SysListView32":  # desktop
            return True
        if classe == "DirectUIHWND":   # elenco file di Esplora file
            return self._classe(self.u.GetParent(gi.hwndFocus)) == "SHELLDLL_DefView"
        return False

    # ---------------------------------------------------------- tasti premuti
    def premuto(self, vk):
        lavoratore = self.lavoratore
        fg = self.u.GetForegroundWindow()
        if not self._focus_su_elenco_file(fg):
            self._ripassa(vk)
            return
        files = file_selezionati(fg)
        if not files:
            self._ripassa(vk)
            return
        bloccato = protetto = False
        try:
            import blocco
            v = blocco.voce(files[0])
            protetto = v is not None
            bloccato = protetto and v["stato"] == "bloccato"
        except Exception:
            log(f"--- tasto blocco\n{traceback.format_exc()}")
        if vk == self.VK_INVIO:
            if bloccato:
                lavoratore.invia(["sblocca_apri", files[0]])    # password, poi si apre nel suo programma
            else:
                self._ripassa(vk)                               # Invio normale di Esplora file
            return
        lavoratore.invia(["sblocca_vedi" if protetto else "anteprima", files[0]])

    # ---------------------------------------------------------- doppio clic
    def _forse_accesso_negato(self, hwnd):
        """Doppio clic su un elemento bloccato: Windows (o il programma) mostra un messaggio di errore
        che contiene il nome dell'elemento. Lo riconosco, lo chiudo e chiedo la password al suo posto."""
        import time
        import win32gui
        if self._classe(hwnd) != "#32770":                 # solo finestre di messaggio/errore
            return
        titolo = win32gui.GetWindowText(hwnd)
        if titolo.startswith("Sottomano"):                 # i messaggi di Sottomano stesso
            return
        testo = _testo_finestra(hwnd).lower()
        trovato = None
        for p in self.bloccati():
            if p.lower() in testo:
                trovato = p
                break
        if trovato is None:
            for p in self.bloccati():
                nome = os.path.basename(p).lower()
                if len(nome) >= 3 and nome in testo:
                    trovato = p
                    break
        if trovato is None:
            return
        ultimo, quando = self._ultimo_dialogo
        if ultimo == trovato and time.monotonic() - quando < 3:
            return
        self._ultimo_dialogo = (trovato, time.monotonic())
        win32gui.PostMessage(hwnd, 0x0010, 0, 0)           # WM_CLOSE: via il messaggio di errore
        self.lavoratore.invia(["sblocca_apri", trovato])


def _testo_finestra(hwnd):
    """Titolo e testi di una finestra di messaggio (anche quelle moderne, lette con UI Automation)."""
    import win32gui
    parti = [win32gui.GetWindowText(hwnd)]

    def figlio(h, _):
        t = win32gui.GetWindowText(h)
        if t:
            parti.append(t)
        return True
    try:
        win32gui.EnumChildWindows(hwnd, figlio, None)
    except Exception:
        pass
    try:
        U, a = uia()
        tutti = a.ElementFromHandle(hwnd).FindAll(4, a.CreateTrueCondition())    # TreeScope_Descendants
        for i in range(min(tutti.Length, 80)):
            n = tutti.GetElement(i).CurrentName
            if n:
                parti.append(n)
    except Exception:
        pass
    return "\n".join(parti)


class Guardiano:
    """Sblocco parziale: ogni 2 secondi controlla se gli elementi sbloccati sono ancora aperti
    (finestra di Esplora file, programma che li usa, titolo di una finestra). Quando li hai chiusi
    li blocca di nuovo. Se non c'e' niente di sbloccato, legge solo la data del registro."""
    TIMER = 80
    MARGINE = 20          # secondi dopo lo sblocco in cui non richiudo (i programmi lenti devono partire)

    def __init__(self, hwnd):
        import ctypes
        self.u = ctypes.windll.user32
        self.hwnd = hwnd
        self.liberi = {}

    def avvia(self):
        self.u.SetTimer(self.hwnd, self.TIMER, 2000, None)

    def controlla(self):
        import blocco
        if not blocco.REGISTRO.exists():
            return
        aperti = blocco.aperti()
        if not aperti:
            self.liberi.clear()
            return
        titoli = _titoli_finestre()
        cartelle = _cartelle_esplora()
        for p, da in aperti:
            if not os.path.exists(p) or da < self.MARGINE:
                self.liberi.pop(p, None)
                continue
            if blocco.in_uso(p, titoli, cartelle, blocco.file_occupati):
                self.liberi[p] = 0
                continue
            self.liberi[p] = self.liberi.get(p, 0) + 1
            if self.liberi[p] >= 2:                     # chiuso da almeno 2 controlli: lo blocco
                try:
                    blocco.richiudi(p)
                except Exception:
                    log(f"--- richiudi {p}\n{traceback.format_exc()}")
                self.liberi.pop(p, None)


def _titoli_finestre():
    import win32gui
    titoli = []

    def una(h, _):
        if win32gui.IsWindowVisible(h):
            t = win32gui.GetWindowText(h)
            if t:
                titoli.append(t.lower())
        return True
    win32gui.EnumWindows(una, None)
    return titoli


def _cartelle_esplora():
    out = []
    try:
        for w in shell_app().Windows():
            try:
                out.append(w.Document.Folder.Self.Path)
            except Exception:
                pass
    except Exception:
        global _SHELL
        _SHELL = None
    return out


def ascolta():
    """Servizio con icona vicino all'orologio: Ctrl+Alt+S apre il menu, tasto destro sull'icona -> Esci.
    Usa RegisterHotKey (una sola combinazione), non legge la tastiera."""
    import win32gui
    import win32con
    import win32api

    spazio = None  # assegnati piu' sotto, usati dalle funzioni interne
    guardiano = None
    if win32gui.FindWindow(CLASSE_SERVIZIO, None):
        messaggio("Sottomano è già attivo: trovi l'icona vicino all'orologio.")
        return

    WM_TRAY = win32con.WM_USER + 20
    ID_HOTKEY, ID_SPAZIO, ID_ZONA, ID_INVIO, ID_ESCI, ID_TESTO, ID_BLOCCATI = 1, 2, 3, 4, 1000, 1001, 1002
    lavoratore = None

    def menu_icona(hwnd):
        m = win32gui.CreatePopupMenu()
        win32gui.AppendMenu(m, win32con.MF_STRING | win32con.MF_GRAYED, 0, f"Sottomano {VERSIONE}  ·  Ctrl+Alt+{TASTO} menu  ·  Spazio anteprima")
        win32gui.AppendMenu(m, win32con.MF_SEPARATOR, 0, "")
        win32gui.AppendMenu(m, win32con.MF_STRING, ID_TESTO, "Testo da una zona dello schermo\tCtrl+Alt+T")
        win32gui.AppendMenu(m, win32con.MF_STRING, ID_BLOCCATI, "Elementi bloccati…")
        win32gui.AppendMenu(m, win32con.MF_SEPARATOR, 0, "")
        win32gui.AppendMenu(m, win32con.MF_STRING, ID_ESCI, "Esci")
        x, y = win32gui.GetCursorPos()
        win32gui.SetForegroundWindow(hwnd)
        scelta = win32gui.TrackPopupMenu(m, win32con.TPM_RETURNCMD | win32con.TPM_RIGHTBUTTON, x, y, 0, hwnd, None)
        win32gui.PostMessage(hwnd, win32con.WM_NULL, 0, 0)
        win32gui.DestroyMenu(m)
        if scelta == ID_ESCI:
            win32gui.DestroyWindow(hwnd)
        elif scelta == ID_TESTO:
            lavoratore.invia(["zona"])
        elif scelta == ID_BLOCCATI:
            lavoratore.invia(["bloccati_elenco"])

    def on_tray(hwnd, msg, wparam, lparam):
        if lparam in (win32con.WM_RBUTTONUP, win32con.WM_LBUTTONUP):
            menu_icona(hwnd)
        return 0

    def on_hotkey(hwnd, msg, wparam, lparam):
        try:
            if wparam == ID_SPAZIO:
                spazio.premuto(SpazioAnteprima.VK_SPAZIO)
            elif wparam == ID_INVIO:
                spazio.premuto(SpazioAnteprima.VK_INVIO)
            elif wparam == ID_ZONA:
                lavoratore.invia(["zona"])
            else:
                _su_hotkey(lavoratore)
        except Exception:
            log(f"--- hotkey {wparam}\n{traceback.format_exc()}")
        ctypes.windll.user32.SetTimer(hwnd, TIMER_RIPOSO, RIPOSO_MS, None)   # riparte il conto alla rovescia
        return 0

    def on_destroy(hwnd, msg, wparam, lparam):
        import ctypes
        ctypes.windll.user32.UnregisterHotKey(hwnd, ID_HOTKEY)
        ctypes.windll.user32.UnregisterHotKey(hwnd, ID_ZONA)
        if spazio is not None:
            spazio.spegni()
        if lavoratore is not None:
            lavoratore.chiudi()
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (hwnd, 0))
        except Exception:
            pass
        win32gui.PostQuitMessage(0)
        return 0

    def on_copydata(hwnd, msg, wparam, lparam):
        """Messaggio da apri_bloccato.pyw (doppio clic sul collegamento di un elemento bloccato):
        uso il processo gia' pronto, cosi' la finestra della password compare subito."""
        import ctypes
        import re

        class COPYDATA(ctypes.Structure):
            _fields_ = [("dwData", ctypes.c_size_t), ("cbData", ctypes.c_ulong), ("lpData", ctypes.c_void_p)]
        try:
            cd = COPYDATA.from_address(lparam)
            if cd.dwData != 0x534D or cd.cbData > 200:
                return 0
            comando = json.loads(ctypes.string_at(cd.lpData, cd.cbData).decode("utf-8"))
            # accetto solo questo comando, con un codice valido: nient'altro arriva da fuori
            if len(comando) == 2 and comando[0] == "apri_bloccato" and re.fullmatch(r"[0-9a-f]{12}", comando[1]):
                lavoratore.invia(comando)
                return 1
        except Exception:
            log(f"--- copydata\n{traceback.format_exc()}")
        return 0

    def on_close(hwnd, msg, wparam, lparam):  # usato da disinstalla.py
        win32gui.DestroyWindow(hwnd)
        return 0

    def on_timer(hwnd, msg, wparam, lparam):
        if wparam == SpazioAnteprima.TIMER_RIATTIVA and spazio is not None:
            spazio.riattiva()
        elif wparam == TIMER_RIPOSO:
            ctypes.windll.user32.KillTimer(hwnd, TIMER_RIPOSO)
            alleggerisci()
        elif wparam == TIMER_PRONTO:
            lavoratore.prepara()
        elif wparam == Guardiano.TIMER and guardiano is not None:
            try:
                guardiano.controlla()
            except Exception:
                log(f"--- guardiano\n{traceback.format_exc()}")
        return 0

    _tema_scuro_menu()
    wc = win32gui.WNDCLASS()
    wc.lpszClassName = CLASSE_SERVIZIO
    wc.hInstance = win32api.GetModuleHandle(None)
    wc.lpfnWndProc = {WM_TRAY: on_tray, win32con.WM_HOTKEY: on_hotkey, win32con.WM_TIMER: on_timer,
                      win32con.WM_DESTROY: on_destroy, win32con.WM_CLOSE: on_close, 0x004A: on_copydata}
    win32gui.RegisterClass(wc)
    hwnd = win32gui.CreateWindow(CLASSE_SERVIZIO, "Sottomano", 0, 0, 0, 0, 0, 0, 0, wc.hInstance, None)

    import ctypes
    MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x1, 0x2, 0x4000
    if not ctypes.windll.user32.RegisterHotKey(hwnd, ID_HOTKEY, MOD_ALT | MOD_CONTROL | MOD_NOREPEAT, ord(TASTO)):
        messaggio(f"La combinazione Ctrl+Alt+{TASTO} è già usata da un altro programma.")
        win32gui.DestroyWindow(hwnd)
        return
    if not ctypes.windll.user32.RegisterHotKey(hwnd, ID_ZONA, MOD_ALT | MOD_CONTROL | MOD_NOREPEAT, ord("T")):
        log("--- Ctrl+Alt+T gia' usata da un altro programma: la zona dello schermo resta nel menu dell'icona")

    icona = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
    try:
        lato = win32api.GetSystemMetrics(49)   # SM_CXSMICON: dimensione delle icone vicino all'orologio
        icona = win32gui.LoadImage(0, str(LOGO), win32con.IMAGE_ICON, lato, lato, win32con.LR_LOADFROMFILE)
    except Exception:
        pass
    win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, (hwnd, 0, win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
                                                 WM_TRAY, icona, f"Sottomano - Ctrl+Alt+{TASTO}, Spazio = anteprima"))
    try:
        import blocco
        blocco.richiudi_tutti()       # cio' che avevi sbloccato l'ultima volta torna bloccato
    except Exception:
        log(f"--- richiudi all'avvio\n{traceback.format_exc()}")
    lavoratore = Lavoratore(hwnd)
    spazio = SpazioAnteprima(hwnd, ID_SPAZIO, ID_INVIO)
    spazio.lavoratore = lavoratore
    spazio.avvia()
    guardiano = Guardiano(hwnd)
    guardiano.avvia()
    lavoratore.prepara_tra(2500)   # il primo processo pronto parte dopo qualche secondo (non rallenta l'avvio)
    win32gui.PumpMessages()


SCRIPT = Path(__file__).resolve()


def esegui(azione, files):
    if azione == "anteprima":
        apri_anteprima(files[0])
        return
    try:
        msg = AZIONI[azione](files)
        if msg:
            info(msg)
    except Exception as e:
        log(f"\n--- {azione} {files}\n{traceback.format_exc()}")
        errore(f"{e}\n\nDettagli in: {LOG}")


def _modulo_anteprima():
    """anteprima.pyw caricato come modulo (Python ne tiene la versione compilata: si apre prima)."""
    import importlib.util
    import importlib.machinery
    if "anteprima" in sys.modules:
        return sys.modules["anteprima"]
    loader = importlib.machinery.SourceFileLoader("anteprima", str(BASE / "anteprima.pyw"))
    spec = importlib.util.spec_from_loader("anteprima", loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["anteprima"] = mod
    loader.exec_module(mod)
    return mod


def apri_anteprima(path):
    mod = _modulo_anteprima()
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Sottomano.Anteprima")
    except Exception:
        pass
    try:
        if os.path.exists(path):
            mod.Anteprima(path)
    finally:
        os._exit(0)


def pronto():
    """Processo pre-avviato (vedi Lavoratore): carica tutto in anticipo, poi aspetta il comando."""
    nitido()
    import tkinter as tk
    from PIL import Image, ImageTk, ImageOps, ImageDraw   # noqa: F401  (caricati ora, usati dopo)
    # PyMuPDF NON lo precarico: da solo occupa ~100 MB. Per le anteprime basta PDFium (17 MB).
    for nome in ("pypdfium2", "comtypes.client", "win32com.client"):
        try:
            __import__(nome)
        except Exception:
            pass
    try:
        _modulo_anteprima()
        import ritaglia, strumenti   # noqa: F401
    except Exception:
        log(f"--- pronto\n{traceback.format_exc()}")
    root = tk.Tk()           # la finestra di Tk, nascosta: la usera' il prossimo lavoro
    root.withdraw()
    try:
        ingresso = sys.stdin.buffer
    except AttributeError:
        ingresso = os.fdopen(0, "rb")
    try:
        riga = ingresso.readline()
    except Exception:
        riga = b""
    if not riga.strip():
        os._exit(0)          # il servizio si e' chiuso: chiudo anche io
    try:
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x20)  # normale
    except Exception:
        pass
    comando = json.loads(riga.decode("utf-8"))
    try:
        esegui(comando[0], comando[1:])
    finally:
        os._exit(0)


def main():
    try:
        import ctypes
        # barra delle applicazioni: icona di Sottomano invece di quella di Python
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Sottomano")
    except Exception:
        pass
    modo = sys.argv[1] if len(sys.argv) >= 2 else ""
    if modo == "ascolta":
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))   # menu nitidi (Per-Monitor v2)
        except Exception:
            nitido()
        ascolta()
        return
    if modo == "pronto":
        pronto()
        return
    nitido()
    if modo == "menu":
        try:
            files = file_selezionati()
        except Exception:
            log(f"--- selezione\n{traceback.format_exc()}")
            files = []
        if not files:
            info("Non riesco a leggere i file selezionati.\nSeleziona uno o più file in Esplora file o sul desktop e premi Ctrl+Alt+S.\n\nSe succede ancora, mandami il file:\n" + str(LOG))
            return
        try:
            modo = mostra_menu(files)
        except Exception as e:
            log(f"\n--- menu {files}\n{traceback.format_exc()}")
            errore(f"{e}\n\nDettagli in: {LOG}")
            return
        if not modo:
            return
        sys.argv = [sys.argv[0], modo] + files
    files = [f for f in sys.argv[2:] if f.strip()]
    if modo != "anteprima" and (modo not in AZIONI or (not files and modo not in SENZA_FILE)):
        errore("Uso: sottomano.pyw <azione> file...\nAzioni: " + ", ".join(AZIONI))
        return
    esegui(modo, files)


if __name__ == "__main__":
    main()
