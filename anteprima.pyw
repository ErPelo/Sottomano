# -*- coding: utf-8 -*-
# Sottomano - anteprima rapida (barra spaziatrice), stile QuickLook.
# Copyright (C) 2026 Tommaso Pelosin - Licenza AGPL-3.0 (vedi LICENSE)
#
# Avviato come:  pythonw anteprima.pyw "percorso\del\file"
# Non modifica nulla: legge soltanto il file per mostrarlo.
#   Spazio / Esc / clic fuori = chiudi
#   Frecce sinistra-destra o su-giu = file precedente / successivo nella cartella

import os
import sys
import tkinter as tk
from tkinter import font as tkfont
from pathlib import Path

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic", ".heif", ".ico"}
ARC_EXT = {".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".xz"}
VID_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".m4v", ".mpg", ".mpeg", ".flv", ".3gp", ".ts"}
TXT_EXT = {".txt", ".md", ".log", ".csv", ".json", ".xml", ".yml", ".yaml", ".ini", ".cfg", ".conf",
           ".py", ".pyw", ".js", ".ts", ".jsx", ".tsx", ".html", ".htm", ".css", ".scss", ".php",
           ".java", ".c", ".h", ".cpp", ".cs", ".go", ".rs", ".sh", ".bat", ".cmd", ".ps1", ".sql",
           ".toml", ".env", ".srt", ".vtt"}

BG = "#1e1e1e"
FG = "#e6e6e6"
SUB = "#9a9a9a"



# ------------------------------------------------------------------ utilità
def dimensione(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.2f} {u}".replace(".", ",")
        n /= 1024


def quando(ts):
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")


def mmss(sec):
    sec = int(max(sec, 0))
    return f"{sec // 60:02d}:{sec % 60:02d}"


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
            raise RuntimeError("Per le foto HEIC serve il pacchetto pillow-heif.")
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


def _bitmap_in_pil(hbmp, w, h):
    import ctypes
    from PIL import Image

    class BMIH(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", ctypes.c_ushort), ("biBitCount", ctypes.c_ushort),
                    ("biCompression", ctypes.c_uint32), ("biSizeImage", ctypes.c_uint32),
                    ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                    ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]
    gdi = ctypes.windll.gdi32
    bih = BMIH(biSize=ctypes.sizeof(BMIH), biWidth=w, biHeight=-h, biPlanes=1, biBitCount=32, biCompression=0)
    buf = ctypes.create_string_buffer(w * h * 4)
    hdc = ctypes.windll.user32.GetDC(0)
    gdi.GetDIBits(hdc, hbmp, 0, h, buf, ctypes.byref(bih), 0)
    ctypes.windll.user32.ReleaseDC(0, hdc)
    return Image.frombuffer("RGBA", (w, h), buf.raw, "raw", "BGRA", 0, 1)


def miniatura_shell(path, lato=640):
    """La miniatura che mostra Esplora file (video, Office, cartelle...), via Windows."""
    import ctypes
    from ctypes import wintypes
    import comtypes
    from comtypes import GUID, IUnknown, COMMETHOD, HRESULT

    class SIZE(ctypes.Structure):
        _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

    class IShellItemImageFactory(IUnknown):
        _iid_ = GUID("{bcc18b79-ba16-442f-80c4-8a59c30c463b}")
        _methods_ = [COMMETHOD([], HRESULT, "GetImage",
                               (["in"], SIZE, "size"), (["in"], ctypes.c_int, "flags"),
                               (["out"], ctypes.POINTER(wintypes.HBITMAP), "phbm"))]

    comtypes.CoInitialize()
    shell32 = ctypes.windll.shell32
    shell32.SHCreateItemFromParsingName.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p,
                                                    ctypes.c_void_p, ctypes.c_void_p]
    fab = ctypes.POINTER(IShellItemImageFactory)()
    iid = IShellItemImageFactory._iid_
    if shell32.SHCreateItemFromParsingName(str(path), None, ctypes.byref(iid), ctypes.byref(fab)) != 0:
        return None
    hbmp = fab.GetImage(SIZE(lato, lato), 0)  # SIIGBF_RESIZETOFIT

    class BITMAP(ctypes.Structure):
        _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long), ("bmHeight", ctypes.c_long),
                    ("bmWidthBytes", ctypes.c_long), ("bmPlanes", ctypes.c_ushort),
                    ("bmBitsPixel", ctypes.c_ushort), ("bmBits", ctypes.c_void_p)]
    gdi = ctypes.windll.gdi32
    bm = BITMAP()
    gdi.GetObjectW(hbmp, ctypes.sizeof(bm), ctypes.byref(bm))
    img = _bitmap_in_pil(hbmp, bm.bmWidth, bm.bmHeight)
    gdi.DeleteObject(hbmp)
    if img.getchannel("A").getextrema() == (0, 0):
        img = img.convert("RGB")
    return img


def icona_file(path, size=32):
    """L'icona del tipo di file (quella che vedi in Esplora file), per la barra del titolo."""
    import ctypes
    from ctypes import wintypes

    class SHFILEINFO(ctypes.Structure):
        _fields_ = [("hIcon", wintypes.HICON), ("iIcon", ctypes.c_int),
                    ("dwAttributes", wintypes.DWORD), ("szDisplayName", ctypes.c_wchar * 260),
                    ("szTypeName", ctypes.c_wchar * 80)]

    SHGFI_ICON, SHGFI_LARGEICON, SHGFI_SMALLICON = 0x100, 0x0, 0x1
    sfi = SHFILEINFO()
    flag = SHGFI_ICON | (SHGFI_SMALLICON if size <= 16 else SHGFI_LARGEICON)
    if not ctypes.windll.shell32.SHGetFileInfoW(str(path), 0, ctypes.byref(sfi), ctypes.sizeof(sfi), flag):
        return None
    hicon = sfi.hIcon
    try:
        # disegno l'icona su un bitmap a 32 bit (con canale alfa)
        gdi, user = ctypes.windll.gdi32, ctypes.windll.user32
        dim = 32 if size > 16 else 16
        hdc = user.GetDC(0)
        memdc = gdi.CreateCompatibleDC(hdc)
        hbmp = gdi.CreateCompatibleBitmap(hdc, dim, dim)
        gdi.SelectObject(memdc, hbmp)
        user.DrawIconEx(memdc, 0, 0, hicon, dim, dim, 0, 0, 0x0003)  # DI_NORMAL
        img = _bitmap_in_pil(hbmp, dim, dim)
        gdi.DeleteDC(memdc)
        gdi.DeleteObject(hbmp)
        user.ReleaseDC(0, hdc)
        return img
    finally:
        ctypes.windll.user32.DestroyIcon(hicon)


# -------------------------------------------------- contenuti per tipo di file
def pagina_pdf(path, lato=1400):
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    from PIL import Image
    with fitz.open(path) as d:
        pag = d[0]
        n = d.page_count
        zoom = lato / max(pag.rect.width, pag.rect.height)
        pix = pag.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return img, n


def testo_file(path, max_righe=600):
    dati = Path(path).read_bytes()[:300_000]
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            testo = dati.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return None
    righe = testo.splitlines()
    out = "\n".join(righe[:max_righe])
    if len(righe) > max_righe:
        out += f"\n\n... (altre {len(righe) - max_righe} righe)"
    return out


def contenuto_archivio(path):
    import zipfile
    import subprocess
    NO = 0x08000000
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            info = [i for i in z.infolist() if not i.is_dir()]
        tot = sum(i.file_size for i in info)
        voci = [(i.filename, dimensione(i.file_size)) for i in info[:600]]
        return voci, len(info), tot
    sz = None
    for c in (r"%ProgramFiles%\7-Zip\7z.exe", r"%ProgramFiles(x86)%\7-Zip\7z.exe"):
        c = os.path.expandvars(c)
        if os.path.isfile(c):
            sz = c
            break
    if not sz:
        return None, 0, 0
    r = subprocess.run([sz, "l", "-slt", "-ba", str(path)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=NO)
    voci, voce, tot = [], {}, 0
    for riga in (r.stdout + "\n").splitlines():
        if riga.strip() == "":
            if voce.get("Path") and "D" not in voce.get("Attributes", ""):
                s = int(voce.get("Size") or 0)
                tot += s
                voci.append((voce["Path"], dimensione(s)))
            voce = {}
        elif " = " in riga:
            k, _, v = riga.partition(" = ")
            voce[k.strip()] = v.strip()
    return voci[:600], len(voci), tot


def log_errore(dove):
    """Scrive l'errore in errori.log, accanto a sottomano.pyw."""
    import traceback
    try:
        with open(Path(__file__).resolve().parent / "errori.log", "a", encoding="utf-8") as fh:
            fh.write(f"\n--- anteprima {dove}\n{traceback.format_exc()}")
    except Exception:
        pass


# --------------------------------------------------------------- finestra
ACCENTO = "#4cc2ff"   # blu di Windows 11
BARRA_BG = "#1b1b1b"
MIN_W, MIN_H = 320, 60   # larghezza minima per i pulsanti della barra del titolo


_CACHE_ICONE = {}


def icona_aa(tipo, lato, colore="#e6e6e6", sup=4):
    """Icone disegnate a risoluzione 4x e poi ridotte: bordi smussati a qualsiasi dimensione."""
    from PIL import Image, ImageDraw, ImageTk
    import math
    chiave = (tipo, lato, colore)
    if chiave in _CACHE_ICONE:
        return _CACHE_ICONE[chiave]
    S = lato * sup
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if tipo == "play":
        d.polygon([(0.30 * S, 0.20 * S), (0.30 * S, 0.80 * S), (0.82 * S, 0.50 * S)], fill=colore)
    elif tipo == "pausa":
        r = 0.05 * S
        d.rounded_rectangle([0.27 * S, 0.20 * S, 0.42 * S, 0.80 * S], radius=r, fill=colore)
        d.rounded_rectangle([0.58 * S, 0.20 * S, 0.73 * S, 0.80 * S], radius=r, fill=colore)
    elif tipo == "ricomincia":
        c, r, sp = S / 2, 0.29 * S, max(int(0.085 * S), 1)
        d.arc([c - r, c - r, c + r, c + r], start=320, end=240, fill=colore, width=sp)
        a = math.radians(40)
        ex, ey = c + r * math.cos(a), c - r * math.sin(a)
        tx, ty = -math.sin(a), -math.cos(a)
        nx, ny = -ty, tx
        L, B = 0.20 * S, 0.15 * S
        d.polygon([(ex + tx * L, ey + ty * L), (ex + nx * B, ey + ny * B), (ex - nx * B, ey - ny * B)],
                  fill=colore)
    elif tipo == "cerchio":
        d.ellipse([0, 0, S - 1, S - 1], fill=colore)
    elif tipo == "pomello":
        # pallino bianco con un'ombra leggera
        d.ellipse([0.06 * S, 0.10 * S, 0.94 * S, 0.98 * S], fill=(0, 0, 0, 90))
        d.ellipse([0.06 * S, 0.02 * S, 0.94 * S, 0.90 * S], fill=colore)
    im = im.resize((lato, lato), Image.LANCZOS)
    foto = ImageTk.PhotoImage(im)
    _CACHE_ICONE[chiave] = foto
    return foto


class BarraVideo(tk.Canvas):
    """Barra del lettore: play/pausa, ricomincia, avanzamento, tempo. Nitida a ogni scala."""

    def __init__(self, master, k, on_play, on_restart, on_seek):
        self.k = k
        self.H = int(round(48 * k))
        super().__init__(master, height=self.H, bg=BARRA_BG, highlightthickness=0, bd=0, takefocus=0)
        self.on_play, self.on_restart, self.on_seek = on_play, on_restart, on_seek
        self.frazione = 0.0
        self.pausa = False
        self.testo = "00:00 / 00:00"
        self.hover = None
        self.trascino = False
        self.bind("<Configure>", lambda e: self.disegna())
        self.bind("<Motion>", self._muovi)
        self.bind("<Leave>", lambda e: self._set_hover(None))
        self.bind("<Button-1>", self._click)
        self.bind("<B1-Motion>", self._trascina)
        self.bind("<ButtonRelease-1>", self._rilascio)
        self.bind("<Double-Button-1>", lambda e: "break")

    def _p(self, v):
        return int(round(v * self.k))

    def _zone(self):
        w, cy = self.winfo_width(), self.H // 2
        x0 = self._p(92)
        x1 = max(w - self._p(112), x0 + 20)
        return (self._p(26), cy), (self._p(62), cy), (x0, x1, cy)

    def _cosa(self, x, y):
        (px, py), (rx, ry), (x0, x1, cy) = self._zone()
        r = self._p(17)
        if (x - px) ** 2 + (y - py) ** 2 <= r * r:
            return "play"
        if (x - rx) ** 2 + (y - ry) ** 2 <= r * r:
            return "restart"
        if x0 - self._p(8) <= x <= x1 + self._p(8) and abs(y - cy) <= self._p(14):
            return "barra"
        return None

    def _set_hover(self, h):
        if h != self.hover:
            self.hover = h
            self.disegna()
        self.config(cursor="hand2" if h else "")

    def _muovi(self, e):
        if not self.trascino:
            self._set_hover(self._cosa(e.x, e.y))

    def _frac(self, x):
        _, _, (x0, x1, _) = self._zone()
        return min(max((x - x0) / max(x1 - x0, 1), 0.0), 1.0)

    def _click(self, e):
        c = self._cosa(e.x, e.y)
        if c == "play":
            self.on_play()
        elif c == "restart":
            self.on_restart()
        elif c == "barra":
            self.trascino = True
            self.frazione = self._frac(e.x)
            self.disegna()

    def _trascina(self, e):
        if self.trascino:
            self.frazione = self._frac(e.x)
            self.disegna()

    def _rilascio(self, e):
        if self.trascino:
            self.trascino = False
            self.on_seek(self._frac(e.x))
            self._set_hover(self._cosa(e.x, e.y))

    def aggiorna(self, frazione, testo, pausa):
        if not self.trascino:
            self.frazione = frazione
        self.testo, self.pausa = testo, pausa
        # ridisegno solo se cambia qualcosa che si vede (non 30 volte al secondo per niente)
        _, _, (x0, x1, _) = self._zone()
        stato = (int((x1 - x0) * self.frazione), self.testo, self.pausa, self.hover, self.trascino,
                 self.winfo_width())
        if stato != getattr(self, "_ultimo", None):
            self._ultimo = stato
            self.disegna()

    def disegna(self):
        self.delete("all")
        w = self.winfo_width()
        (px, py), (rx, ry), (x0, x1, cy) = self._zone()
        ico, bg = self._p(22), self._p(34)

        # sfondo tondo al passaggio del mouse + icone smussate
        if self.hover == "play":
            self.create_image(px, py, image=icona_aa("cerchio", bg, "#333333"))
        self.create_image(px, py, image=icona_aa("play" if self.pausa else "pausa", ico))
        if self.hover == "restart":
            self.create_image(rx, ry, image=icona_aa("cerchio", bg, "#333333"))
        self.create_image(rx, ry, image=icona_aa("ricomincia", ico))

        # barra di avanzamento: rettangoli nitidi + estremita' tonde smussate
        attiva = self.hover == "barra" or self.trascino
        sp = self._p(6 if attiva else 4)
        y0, y1 = cy - sp // 2, cy - sp // 2 + sp
        xf = int(x0 + (x1 - x0) * self.frazione)
        self.create_rectangle(x0, y0, x1, y1, fill="#3d3d3d", outline="")
        self.create_image(x1, cy, image=icona_aa("cerchio", sp, "#3d3d3d"))
        self.create_image(x0, cy, image=icona_aa("cerchio", sp, ACCENTO if xf > x0 else "#3d3d3d"))
        if xf > x0:
            self.create_rectangle(x0, y0, xf, y1, fill=ACCENTO, outline="")
        self.create_image(xf, cy, image=icona_aa("pomello", self._p(16 if attiva else 12), "#ffffff"))

        # tempo
        self.create_text(w - self._p(16), cy, text=self.testo, fill="#cfcfcf",
                         font=("Segoe UI", 9), anchor="e")


class Anteprima:
    def __init__(self, path):
        self.path = Path(path)
        self.vicini = self._vicini(self.path)
        self.idx = self.vicini.index(self.path) if self.path in self.vicini else 0
        self._img_ref = None
        self.player = None
        self._video_after = None
        self.barra = None

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", True)
        self.sw, self.sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.k = max(self.root.winfo_fpixels("1i") / 96.0, 1.0)   # scala dello schermo (125%, 150%...)
        self.max_w, self.max_h = int(self.sw * 0.8), int(self.sh * 0.8)

        self.root.bind("<Escape>", lambda e: self.chiudi())
        self.root.bind("<space>", lambda e: self.chiudi())
        self.root.bind("<Left>", lambda e: self.vai(-1))
        self.root.bind("<Up>", lambda e: self.vai(-1))
        self.root.bind("<Right>", lambda e: self.vai(1))
        self.root.bind("<Down>", lambda e: self.vai(1))
        self.root.bind("<FocusOut>", self._focus_out)
        self.root.bind("<Return>", lambda e: self._apri())
        self.root.bind("<Double-Button-1>", lambda e: self._apri())

        # niente barra personale: nome e icona li mostra la barra del titolo di Windows
        self.corpo = tk.Frame(self.root, bg=BG)
        self.corpo.pack(fill="both", expand=True)

        self.carica(self.path)
        self.root.deiconify()
        self.root.after(50, lambda: (self.root.focus_force(), self.root.lift()))
        self.root.mainloop()

    # ------------------------------------------------------------ finestra
    def _adatta(self, cw, ch):
        """Finestra grande quanto il contenuto (centrata), entro i limiti dello schermo."""
        cw = int(min(max(cw, MIN_W * self.k), self.max_w))
        ch = int(min(max(ch, MIN_H * self.k), self.max_h))
        self.root.geometry(f"{cw}x{ch}+{(self.sw - cw) // 2}+{(self.sh - ch) // 3}")

    def _vicini(self, path):
        """File e cartelle nella stessa cartella, ordinati come in Esplora file (cartelle prima)."""
        try:
            voci = list(path.parent.iterdir())
        except OSError:
            return [path]
        cart = sorted((p for p in voci if p.is_dir()), key=lambda p: p.name.lower())
        file = sorted((p for p in voci if not p.is_dir()), key=lambda p: p.name.lower())
        return cart + file or [path]

    def vai(self, passo):
        if len(self.vicini) < 2:
            return
        self.idx = (self.idx + passo) % len(self.vicini)
        self.carica(self.vicini[self.idx])

    def _focus_out(self, _):
        self.root.after(120, self._forse_chiudi)

    def _forse_chiudi(self):
        """Chiudo solo se sei davvero passato a un'altra finestra (un altro programma).
        Il ridimensionamento o i clic dentro l'anteprima non la chiudono piu'."""
        import ctypes
        from ctypes import wintypes
        try:
            fg = ctypes.windll.user32.GetForegroundWindow()
            if not fg:
                return
            pid = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
            if pid.value != os.getpid():
                self.chiudi()
        except Exception:
            pass

    def ferma_video(self):
        if self._video_after is not None:
            try:
                self.root.after_cancel(self._video_after)
            except Exception:
                pass
            self._video_after = None
        if self.player is not None:
            p, self.player = self.player, None
            for fai in (lambda: p.set_volume(0.0), lambda: p.set_pause(True), p.close_player):
                try:
                    fai()          # prima zitto e in pausa, poi chiuso: l'audio non resta mai acceso
                except Exception:
                    pass
        self.barra = None

    def chiudi(self):
        if getattr(self, "_chiuso", False):
            return
        self._chiuso = True
        self.ferma_video()
        try:
            self.root.destroy()
        except Exception:
            pass
        os._exit(0)   # termina il processo: nessun thread audio puo' restare vivo

    def _apri(self):
        self.ferma_video()
        try:
            os.startfile(self.path)
        except Exception:
            pass
        self.chiudi()

    # ------------------------------------------------------------ rendering
    def carica(self, path):
        from PIL import ImageTk
        self.ferma_video()
        self.path = Path(path)
        pos = f"   ({self.idx + 1}/{len(self.vicini)})" if len(self.vicini) > 1 else ""
        self.root.title(self.path.name + pos)
        try:
            grande = icona_file(self.path, 32)
            if grande is not None:
                self._win_icon = ImageTk.PhotoImage(grande)
                self.root.iconphoto(False, self._win_icon)
        except Exception:
            pass
        for w in self.corpo.winfo_children():
            w.destroy()
        self._riempi()

    def _mostra_immagine(self, img):
        from PIL import ImageTk
        img.thumbnail((self.max_w, self.max_h))   # rimpicciolisce solo se serve, mai ingrandisce
        self._img_ref = ImageTk.PhotoImage(img)
        tk.Label(self.corpo, image=self._img_ref, bg=BG, bd=0).pack(fill="both", expand=True)
        self._adatta(*img.size)

    def _mostra_testo(self, testo, mono=True):
        from tkinter import scrolledtext
        f = ("Cascadia Mono", 10) if mono else ("Segoe UI", 11)
        try:
            tkfont.Font(family=f[0])
        except Exception:
            f = ("Consolas", 10)
        box = scrolledtext.ScrolledText(self.corpo, wrap="none" if mono else "word",
                                        bg="#141414", fg=FG, insertbackground=FG, font=f,
                                        relief="flat", padx=12, pady=10, takefocus=0, bd=0)
        box.insert("1.0", testo)
        box.configure(state="disabled")
        box.pack(fill="both", expand=True)
        # larghezza in base alla riga piu' lunga, altezza in base al numero di righe
        righe = testo.splitlines() or [""]
        cw = min(max(len(r) for r in righe[:300]), 120) * 8 + 60
        ch = min(len(righe), 40) * 18 + 40
        self._adatta(max(cw, 480) * self.k, max(ch, 200) * self.k)

    def _mostra_elenco(self, voci, n, tot):
        testo = f"{n} file · {dimensione(tot)}\n" + "─" * 54 + "\n"
        testo += "\n".join(nome + " " * max(1, 50 - len(nome)) + f"{sz:>10}" for nome, sz in voci)
        if n > len(voci):
            testo += f"\n... (e altri {n - len(voci)})"
        self._mostra_testo(testo)

    def _scheda_file(self, nota=None):
        wrap = tk.Frame(self.corpo, bg=BG)
        wrap.pack(expand=True, padx=40, pady=30)
        img = None
        try:
            img = miniatura_shell(self.path, 256)
        except Exception:
            pass
        if img is None:
            try:
                img = icona_file(self.path, 32)
            except Exception:
                img = None
        if img is not None:
            from PIL import ImageTk
            img = img.copy()
            img.thumbnail((256, 256))
            self._img_ref = ImageTk.PhotoImage(img)
            tk.Label(wrap, image=self._img_ref, bg=BG).pack(pady=(0, 14))
        tk.Label(wrap, text=self.path.name, bg=BG, fg=FG, font=("Segoe UI", 12, "bold"),
                 wraplength=420, justify="center").pack()
        try:
            st = self.path.stat()
            meta = f"{dimensione(st.st_size)}  ·  {quando(st.st_mtime)}"
        except OSError:
            meta = ""
        tipo = nota or ((self.path.suffix.upper().lstrip(".") or "File") + " · nessuna anteprima")
        tk.Label(wrap, text=f"{tipo}\n{meta}", bg=BG, fg=SUB, font=("Segoe UI", 9),
                 justify="center").pack(pady=(6, 0))
        self._adatta(480 * self.k, (400 if img is not None else 220) * self.k)

    # ------------------------------------------------------------ video
    def _mostra_video(self, path):
        """Riproduce il video (con audio). Clic sul video = pausa/riprendi."""
        try:
            from ffpyplayer.player import MediaPlayer
            self.player = MediaPlayer(str(path), ff_opts={"out_fmt": "rgb24"})
        except Exception:
            self.player = None
            self._scheda_file(nota="Premi Invio per riprodurre il video")
            return
        self.barra = BarraVideo(self.corpo, self.k, self._pausa_video, self._ricomincia_video, self._cerca)
        self.barra.pack(side="bottom", fill="x")
        self.vlabel = tk.Label(self.corpo, bg="#000000", bd=0)
        self.vlabel.pack(side="top", fill="both", expand=True)
        self.vlabel.bind("<Button-1>", lambda e: self._pausa_video())
        self._dim_video = None
        self._foto_video = None
        self._durata = None
        self._adatta(640 * self.k, 360 * self.k + self.barra.H)
        self.root.focus_set()
        self._video_after = self.root.after(40, self._tick_video)

    def _in_pausa(self):
        try:
            return bool(self.player.get_pause())
        except Exception:
            return False

    def _pausa_video(self):
        if self.player is not None:
            try:
                self.player.toggle_pause()
            except Exception:
                pass
            self._aggiorna_barra()

    def _ricomincia_video(self):
        if self.player is not None:
            try:
                self.player.seek(0, relative=False)
                if self._in_pausa():
                    self.player.set_pause(False)
            except Exception:
                pass
            self._aggiorna_barra()

    def _cerca(self, frazione):
        if self.player is not None and self._durata:
            try:
                self.player.seek(frazione * self._durata, relative=False)
            except Exception:
                pass
        self.root.focus_set()

    def _aggiorna_barra(self):
        if self.barra is None or self.player is None:
            return
        try:
            pos = float(self.player.get_pts() or 0)
        except Exception:
            pos = 0.0
        dur = self._durata or 0
        fr = pos / dur if dur else 0.0
        self.barra.aggiorna(fr, f"{mmss(pos)} / {mmss(dur)}", self._in_pausa())

    def _tick_video(self):
        if self.player is None:
            return
        from PIL import Image, ImageTk
        if self._durata is None:
            try:
                d = self.player.get_metadata().get("duration")
                if d:
                    self._durata = float(d)
            except Exception:
                pass
        try:
            frame, val = self.player.get_frame()
            self._errori_video = 0
        except Exception:
            self._errori_video = getattr(self, "_errori_video", 0) + 1
            log_errore("get_frame")
            if self._errori_video > 20:          # il video non si riesce a leggere: fermo tutto
                self.ferma_video()
                return
            self._video_after = self.root.after(50, self._tick_video)
            return
        if val == "eof":
            try:
                self.player.seek(0, relative=False)
            except Exception:
                pass
            self._video_after = self.root.after(40, self._tick_video)
            return
        if frame is not None:
            img, _pts = frame
            w, h = img.get_size()
            try:
                if self._dim_video is None:
                    # prima immagine: adatto la finestra al video e chiedo a ffmpeg di consegnarmi
                    # i fotogrammi gia' a quella dimensione (scalati in C, molto piu' leggero)
                    s = min(self.max_w / w, (self.max_h - self.barra.H) / h, 1)
                    self._dim_video = (max(int(w * s), 1), max(int(h * s), 1))
                    self._adatta(self._dim_video[0], self._dim_video[1] + self.barra.H)
                    if self._dim_video != (w, h):
                        try:
                            self.player.set_size(*self._dim_video)
                        except Exception:
                            pass
                ls = img.get_linesizes()[0]
                # leggo il fotogramma direttamente dalla memoria di ffmpeg, senza copiarlo
                pim = Image.frombuffer("RGB", (w, h), img.to_memoryview()[0], "raw", "RGB", ls, 1)
                if (w, h) != self._dim_video:
                    pim = pim.resize(self._dim_video, Image.BILINEAR)
                # una sola immagine per tutto il video: ad ogni fotogramma ne cambio solo i pixel
                if getattr(self, "_foto_video", None) is None or self._foto_video.width() != pim.width \
                        or self._foto_video.height() != pim.height:
                    self._foto_video = ImageTk.PhotoImage(pim)
                    self.vlabel.config(image=self._foto_video)
                else:
                    self._foto_video.paste(pim)
            except Exception:
                pass
        self._aggiorna_barra()
        attesa = int(max(val, 0) * 1000) if isinstance(val, (int, float)) else 33
        self._video_after = self.root.after(min(max(attesa, 1), 100), self._tick_video)

    # ------------------------------------------------------------ smistamento
    def _riempi(self):
        ext = self.path.suffix.lower()
        try:
            if self.path.is_dir():
                voci, tot, n = [], 0, 0
                for p in list(self.path.iterdir())[:600]:
                    n += 1
                    try:
                        s = p.stat().st_size if p.is_file() else 0
                    except OSError:
                        s = 0
                    tot += s
                    voci.append((p.name + ("/" if p.is_dir() else ""),
                                 dimensione(s) if p.is_file() else "cartella"))
                self._mostra_elenco(voci, n, tot)
            elif ext in IMG_EXT:
                self._mostra_immagine(apri_immagine(self.path, (self.max_w, self.max_h)))
            elif ext in VID_EXT:
                self._mostra_video(self.path)
            elif ext == ".pdf":
                img, _ = pagina_pdf(self.path)
                self._mostra_immagine(img)
            elif ext in ARC_EXT:
                voci, n, tot = contenuto_archivio(self.path)
                self._scheda_file() if voci is None else self._mostra_elenco(voci, n, tot)
            elif ext in TXT_EXT:
                t = testo_file(self.path)
                self._scheda_file() if t is None else self._mostra_testo(t)
            else:
                self._scheda_file()
        except Exception:
            import traceback
            for w in self.corpo.winfo_children():
                w.destroy()
            self._mostra_testo("Impossibile mostrare l'anteprima:\n\n" + traceback.format_exc())


def nitido():
    """Disegna a risoluzione nativa: senza questo, con la scala di Windows al 125/150%
    la finestra viene "stirata" e tutto appare sgranato."""
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main():
    if len(sys.argv) < 2:
        return
    nitido()
    try:
        import ctypes
        # barra delle applicazioni: icona della finestra (quella del file) invece di quella di Python
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Sottomano.Anteprima")
    except Exception:
        pass
    try:
        if os.path.exists(sys.argv[1]):
            Anteprima(sys.argv[1])
    finally:
        os._exit(0)   # qualunque cosa succeda, il processo dell'anteprima finisce qui


if __name__ == "__main__":
    main()
