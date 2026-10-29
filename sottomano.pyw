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

VERSIONE = "0.1"
BASE = Path(__file__).resolve().parent
TESSDATA = BASE / "tessdata"
LOG = BASE / "errori.log"

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic", ".heif", ".ico"}
ARC_EXT = {".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".xz"}
VID_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".m4v", ".mpg", ".mpeg", ".flv", ".3gp", ".ts"}
AUD_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}

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


def _tk():
    import tkinter as tk
    root = tk.Tk()
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


def mostra_testo(titolo, testo):
    """Finestra con il testo estratto, già copiato negli appunti."""
    import tkinter as tk
    from tkinter import scrolledtext
    root = tk.Tk()
    _logo(root)
    root.title(titolo)
    root.geometry("720x520")
    root.attributes("-topmost", True)
    root.after(800, lambda: root.attributes("-topmost", False))
    root.clipboard_clear(); root.clipboard_append(testo); root.update()
    tk.Label(root, text="Testo copiato negli appunti (e salvato in un .txt accanto al file).",
             anchor="w").pack(fill="x", padx=8, pady=(8, 2))
    box = scrolledtext.ScrolledText(root, wrap="word", font=("Segoe UI", 10))
    box.pack(fill="both", expand=True, padx=8, pady=8)
    box.insert("1.0", testo)
    tk.Button(root, text="Chiudi", command=root.destroy, width=12).pack(pady=(0, 8))
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
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW)
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


def testo_pdf(f, forza_ocr=False):
    fitz = _fitz()
    doc = fitz.open(f)
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
        with fitz.open(f) as d:
            out_doc.insert_pdf(d)
    out = libero(Path(files[0]).with_name("PDF_uniti.pdf"))
    with in_corso(out):
        out_doc.save(out, garbage=3, deflate=True)
    return f"Uniti {len(files)} PDF ({out_doc.page_count} pagine) in:\n{out.name}"


def pdf_in_immagini(files):
    fitz = _fitz()
    tot = 0
    for f in files:
        f = Path(f)
        cartella = libero(f.with_name(f.stem + "_pagine"))
        cartella.mkdir()
        with fitz.open(f) as d:
            for i, pag in enumerate(d, 1):
                pag.get_pixmap(dpi=200).save(cartella / f"pagina_{i:03d}.png")
                tot += 1
    return f"Esportate {tot} pagine come PNG (cartella *_pagine)."


def pdf_comprimi(files):
    fitz = _fitz()
    righe = []
    for f in files:
        f = Path(f)
        out = libero(f.with_name(f.stem + "_compresso.pdf"))
        with in_corso(out), fitz.open(f) as d:
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
}


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


def _selezione_esplora(hwnd, cartelle_out):
    import win32com.client
    candidati = []
    for w in win32com.client.Dispatch("Shell.Application").Windows():
        try:
            if int(w.HWND) == hwnd:
                candidati.append(w)
        except Exception:
            pass
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
    sw = win32com.client.Dispatch("Shell.Application").Windows()
    loc = win32com.client.VARIANT(pythoncom.VT_I4, shellcon.CSIDL_DESKTOP)
    empty = win32com.client.VARIANT(pythoncom.VT_EMPTY, None)
    disp = sw.FindWindowSW(loc, empty, 8, 0, 1)  # SWC_DESKTOP=8, SWFO_NEEDDISPATCH=1
    sp = disp._oleobj_.QueryInterface(pythoncom.IID_IServiceProvider)
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


def voci_per(files):
    """Restituisce [(etichetta, azione) | (etichetta, [sottovoci]) | None per separatore]."""
    est = {Path(f).suffix.lower() for f in files}
    if not files or any(os.path.isdir(f) for f in files):
        return []
    tutte_img = est <= IMG_EXT
    tutte_pdf = est == {".pdf"}
    tutte_arc = est <= ARC_EXT
    tutti_vid = est <= VID_EXT
    tutti_aud = est <= AUD_EXT

    def formati(opzioni):
        """Tolgo il formato che i file hanno gia' (inutile convertire MP4 in MP4)."""
        return [o for o in opzioni if o is None or {"." + o[1].split("_")[-1]} != est]
    v = []
    if tutte_img:
        v.append(("Converti in", [("PNG", "png"), ("JPG", "jpg"), ("WEBP", "webp"),
                                  ("ICO (icona)", "ico"), None, ("PDF", "img2pdf")]))
        v.append(("Estrai testo (OCR)", "ocr"))
        if len(files) == 1:
            v.append(("Ritaglia e ridimensiona…", "ritaglia"))
        else:
            v.append(("Ridimensiona e comprimi…", "comprimi"))
        v.append(("Rimuovi metadati (GPS, EXIF)", "metadati"))
        try:
            import importlib.util
            if importlib.util.find_spec("rembg"):
                v.append(("Rimuovi sfondo (AI)", "sfondo"))
        except Exception:
            pass
    elif tutte_pdf:
        v += [("Copia testo dal PDF", "pdf_testo"), ("Estrai testo con OCR", "ocr")]
        if len(files) > 1:
            v.append(("Unisci PDF", "pdf_unisci"))
        v += [("PDF in immagini (PNG)", "pdf_immagini"), ("Comprimi PDF", "pdf_comprimi")]
    elif tutte_arc:
        v.append(("Converti in", [("7z", "to7z"), ("ZIP", "tozip"), ("RAR", "torar")]))
    elif tutti_vid:
        v.append(("Converti in", formati([("MP4", "v_mp4"), ("MKV", "v_mkv"), ("MOV", "v_mov"),
                                          ("WEBM", "v_webm"), None, ("GIF animata", "v_gif")])))
        v += [("Comprimi video", "v_comprimi"), ("Estrai audio (MP3)", "a_mp3")]
    elif tutti_aud:
        v.append(("Converti in", formati([("MP3", "a_mp3"), ("WAV", "a_wav"),
                                          ("M4A", "a_m4a"), ("FLAC", "a_flac")])))
    if v:
        v.append(None)
    v.append(("Calcola SHA-256", "hash"))
    return v


def mostra_menu(files):
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

    titolo = Path(files[0]).name if len(files) == 1 else f"{len(files)} file selezionati"
    if len(titolo) > 40:
        titolo = titolo[:37] + "..."
    menu = win32gui.CreatePopupMenu()
    win32gui.AppendMenu(menu, win32con.MF_STRING | win32con.MF_GRAYED, 0, "Sottomano  -  " + titolo)
    win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
    riempi(menu, voci_per(files))

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


def _su_hotkey():
    import win32gui
    hwnd = win32gui.GetForegroundWindow()
    if win32gui.GetClassName(hwnd) not in ("CabinetWClass", "ExploreWClass", "Progman", "WorkerW"):
        return  # Ctrl+Alt+S premuto in un altro programma: lo ignoro
    files = file_selezionati(hwnd)
    if not files:
        messaggio("Seleziona prima uno o più file, poi premi Ctrl+Alt+S.")
        return
    _attendi_tasti_rilasciati()
    azione = mostra_menu(files)
    if azione:
        # l'azione gira in un processo separato: il servizio resta sempre pronto
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), azione] + files)


def alleggerisci():
    """Restituisce a Windows la memoria che il servizio non sta usando (come fa Windows con i
    programmi ridotti a icona). Il servizio resta pronto: se serve, la memoria torna subito."""
    import gc
    import ctypes
    from ctypes import wintypes
    gc.collect()
    try:
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = wintypes.HANDLE
        k.SetProcessWorkingSetSize.argtypes = [wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t]
        k.SetProcessWorkingSetSize(k.GetCurrentProcess(), ctypes.c_size_t(-1), ctypes.c_size_t(-1))
    except Exception:
        pass


TIMER_RIPOSO = 78          # dopo 30 secondi senza usare Sottomano libero la memoria
RIPOSO_MS = 30_000


class SpazioAnteprima:
    """Barra spaziatrice = anteprima, SOLO quando sei nell'elenco file di Esplora file o sul desktop.

    Non usa hook della tastiera: segue quale finestra e' in primo piano (SetWinEventHook) e
    registra il tasto Spazio con RegisterHotKey solo mentre Esplora file e' attivo.
    Se lo Spazio serve per scrivere (rinomina, barra di ricerca, indirizzo) lo "ripassa" a Windows.
    """
    CLASSI_ESPLORA = ("CabinetWClass", "ExploreWClass", "Progman", "WorkerW")

    def __init__(self, hwnd, id_tasto):
        import ctypes
        self.u = ctypes.windll.user32
        self.hwnd, self.id = hwnd, id_tasto
        self.attivo = False
        self._hook = None
        self._cb = None

    def avvia(self):
        import ctypes
        from ctypes import wintypes
        PROC = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
                                  wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
        self._cb = PROC(lambda *a: self.aggiorna())  # riferimento tenuto vivo
        EVENT_SYSTEM_FOREGROUND, WINEVENT_OUTOFCONTEXT = 0x0003, 0x0000
        self._hook = self.u.SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND,
                                            0, self._cb, 0, 0, WINEVENT_OUTOFCONTEXT)
        self.aggiorna()

    def _classe(self, h):
        import ctypes
        buf = ctypes.create_unicode_buffer(256)
        self.u.GetClassNameW(h, buf, 256)
        return buf.value

    def aggiorna(self):
        try:
            serve = self._classe(self.u.GetForegroundWindow()) in self.CLASSI_ESPLORA
            if serve and not self.attivo:
                self.attivo = bool(self.u.RegisterHotKey(self.hwnd, self.id, 0x4000, 0x20))  # MOD_NOREPEAT, VK_SPACE
            elif not serve and self.attivo:
                self.u.UnregisterHotKey(self.hwnd, self.id)
                self.attivo = False
        except Exception:
            log(f"--- spazio aggiorna\n{traceback.format_exc()}")

    def spegni(self):
        if self.attivo:
            self.u.UnregisterHotKey(self.hwnd, self.id)
            self.attivo = False
        if self._hook:
            self.u.UnhookWinEvent(self._hook)
            self._hook = None

    TIMER_RIATTIVA = 77

    def _ripassa_spazio(self):
        """Lo Spazio non era per noi: lo rimando alla finestra come se nulla fosse.
        Torno in ascolto solo dopo un attimo (timer): altrimenti intercetterei di nuovo
        proprio lo spazio che ho appena rimandato, all'infinito."""
        self.u.UnregisterHotKey(self.hwnd, self.id)
        self.attivo = False
        self.u.keybd_event(0x20, 0, 0, 0)
        self.u.keybd_event(0x20, 0, 2, 0)
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

    def premuto(self):
        fg = self.u.GetForegroundWindow()
        if not self._focus_su_elenco_file(fg):
            self._ripassa_spazio()
            return
        files = file_selezionati(fg)
        if not files:
            self._ripassa_spazio()
            return
        ant = Path(__file__).resolve().parent / "anteprima.pyw"
        subprocess.Popen([sys.executable, str(ant), files[0]])


def ascolta():
    """Servizio con icona vicino all'orologio: Ctrl+Alt+S apre il menu, tasto destro sull'icona -> Esci.
    Usa RegisterHotKey (una sola combinazione), non legge la tastiera."""
    import win32gui
    import win32con
    import win32api

    spazio = None  # assegnato piu' sotto, usato dalle funzioni interne
    if win32gui.FindWindow(CLASSE_SERVIZIO, None):
        messaggio("Sottomano è già attivo: trovi l'icona vicino all'orologio.")
        return

    WM_TRAY = win32con.WM_USER + 20
    ID_HOTKEY, ID_SPAZIO, ID_ESCI = 1, 2, 1000

    def menu_icona(hwnd):
        m = win32gui.CreatePopupMenu()
        win32gui.AppendMenu(m, win32con.MF_STRING | win32con.MF_GRAYED, 0, f"Sottomano {VERSIONE}  ·  Ctrl+Alt+{TASTO} menu  ·  Spazio anteprima")
        win32gui.AppendMenu(m, win32con.MF_SEPARATOR, 0, "")
        win32gui.AppendMenu(m, win32con.MF_STRING, ID_ESCI, "Esci")
        x, y = win32gui.GetCursorPos()
        win32gui.SetForegroundWindow(hwnd)
        scelta = win32gui.TrackPopupMenu(m, win32con.TPM_RETURNCMD | win32con.TPM_RIGHTBUTTON, x, y, 0, hwnd, None)
        win32gui.PostMessage(hwnd, win32con.WM_NULL, 0, 0)
        win32gui.DestroyMenu(m)
        if scelta == ID_ESCI:
            win32gui.DestroyWindow(hwnd)

    def on_tray(hwnd, msg, wparam, lparam):
        if lparam in (win32con.WM_RBUTTONUP, win32con.WM_LBUTTONUP):
            menu_icona(hwnd)
        return 0

    def on_hotkey(hwnd, msg, wparam, lparam):
        try:
            if wparam == ID_SPAZIO:
                spazio.premuto()
            else:
                _su_hotkey()
        except Exception:
            log(f"--- hotkey {wparam}\n{traceback.format_exc()}")
        ctypes.windll.user32.SetTimer(hwnd, TIMER_RIPOSO, RIPOSO_MS, None)   # riparte il conto alla rovescia
        return 0

    def on_destroy(hwnd, msg, wparam, lparam):
        import ctypes
        ctypes.windll.user32.UnregisterHotKey(hwnd, ID_HOTKEY)
        spazio.spegni()
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (hwnd, 0))
        except Exception:
            pass
        win32gui.PostQuitMessage(0)
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
        return 0

    _tema_scuro_menu()
    wc = win32gui.WNDCLASS()
    wc.lpszClassName = CLASSE_SERVIZIO
    wc.hInstance = win32api.GetModuleHandle(None)
    wc.lpfnWndProc = {WM_TRAY: on_tray, win32con.WM_HOTKEY: on_hotkey, win32con.WM_TIMER: on_timer,
                      win32con.WM_DESTROY: on_destroy, win32con.WM_CLOSE: on_close}
    win32gui.RegisterClass(wc)
    hwnd = win32gui.CreateWindow(CLASSE_SERVIZIO, "Sottomano", 0, 0, 0, 0, 0, 0, 0, wc.hInstance, None)

    import ctypes
    MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x1, 0x2, 0x4000
    if not ctypes.windll.user32.RegisterHotKey(hwnd, ID_HOTKEY, MOD_ALT | MOD_CONTROL | MOD_NOREPEAT, ord(TASTO)):
        messaggio(f"La combinazione Ctrl+Alt+{TASTO} è già usata da un altro programma.")
        win32gui.DestroyWindow(hwnd)
        return

    icona = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
    try:
        lato = win32api.GetSystemMetrics(49)   # SM_CXSMICON: dimensione delle icone vicino all'orologio
        icona = win32gui.LoadImage(0, str(LOGO), win32con.IMAGE_ICON, lato, lato, win32con.LR_LOADFROMFILE)
    except Exception:
        pass
    win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, (hwnd, 0, win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
                                                 WM_TRAY, icona, f"Sottomano - Ctrl+Alt+{TASTO}, Spazio = anteprima"))
    spazio = SpazioAnteprima(hwnd, ID_SPAZIO)
    spazio.avvia()
    alleggerisci()            # all'avvio: via la memoria usata solo per partire
    win32gui.PumpMessages()


def main():
    try:
        import ctypes
        # barra delle applicazioni: icona di Sottomano invece di quella di Python
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Sottomano")
    except Exception:
        pass
    if len(sys.argv) >= 2 and sys.argv[1] == "ascolta":
        ascolta()
        return
    if len(sys.argv) >= 2 and sys.argv[1] == "menu":
        try:
            files = file_selezionati()
        except Exception:
            log(f"--- selezione\n{traceback.format_exc()}")
            files = []
        if not files:
            info("Non riesco a leggere i file selezionati.\nSeleziona uno o più file in Esplora file o sul desktop e premi Ctrl+Alt+S.\n\nSe succede ancora, mandami il file:\n" + str(LOG))
            return
        try:
            azione = mostra_menu(files)
        except Exception as e:
            with open(LOG, "a", encoding="utf-8") as fh:
                fh.write(f"\n--- menu {files}\n{traceback.format_exc()}")
            errore(f"{e}\n\nDettagli in: {LOG}")
            return
        if not azione:
            return
        sys.argv = [sys.argv[0], azione] + files

    if len(sys.argv) < 3 or sys.argv[1] not in AZIONI:
        errore("Uso: sottomano.pyw <azione> file...\nAzioni: " + ", ".join(AZIONI))
        return
    azione, files = sys.argv[1], [f for f in sys.argv[2:] if f.strip()]
    try:
        msg = AZIONI[azione](files)
        if msg:
            info(msg)
    except Exception as e:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(f"\n--- {azione} {files}\n{traceback.format_exc()}")
        errore(f"{e}\n\nDettagli in: {LOG}")


if __name__ == "__main__":
    main()
