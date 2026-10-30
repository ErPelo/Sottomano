# -*- coding: utf-8 -*-
# Sottomano - editor grafico: ritaglia, ruota e ridimensiona un'immagine;
# finestra a pulsanti per ridimensionare piu' immagini insieme.
# Copyright (C) 2026 Tommaso Pelosin - Licenza AGPL-3.0 (vedi LICENSE)

import tkinter as tk

BG = "#1e1e1e"
BARRA = "#1b1b1b"
FG = "#e6e6e6"
SUB = "#9a9a9a"
ACCENTO = "#4cc2ff"
CHIP = "#2d2d2d"
CHIP_HOVER = "#3a3a3a"


def nitido():
    """Risoluzione nativa dello schermo (niente finestra 'stirata' con la scala al 125/150%)."""
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def applica_logo(root):
    """Logo di Sottomano nella barra del titolo e nella barra delle applicazioni."""
    import ctypes
    from pathlib import Path
    try:
        # cosi' Windows mostra l'icona della finestra e non quella di Python
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Sottomano")
    except Exception:
        pass
    ico = Path(__file__).resolve().parent / "logo.ico"
    if ico.exists():
        try:
            root.iconbitmap(default=str(ico))
        except Exception:
            pass


def radice():
    """Finestra principale di Tk. Se il processo e' stato pre-avviato da Sottomano ne esiste gia'
    una pronta (nascosta, vuota): la riuso e risparmio il tempo di avvio di Tk."""
    r = getattr(tk, "_default_root", None)
    if r is not None:
        try:
            if r.winfo_exists() and not r.winfo_children() and r.state() == "withdrawn":
                return r
        except tk.TclError:
            pass
    r = tk.Tk()
    r.withdraw()          # chi la usa la mostra quando e' pronta (niente finestra vuota che lampeggia)
    return r


_CACHE = {}


def pallino(diametro, colore="#ffffff"):
    """Cerchio smussato (disegnato 4x e ridotto)."""
    from PIL import Image, ImageDraw, ImageTk
    chiave = (diametro, colore)
    if chiave not in _CACHE:
        S = diametro * 4
        im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse([S * 0.06, S * 0.12, S * 0.94, S * 1.0], fill=(0, 0, 0, 90))
        d.ellipse([S * 0.06, S * 0.02, S * 0.94, S * 0.90], fill=colore)
        _CACHE[chiave] = ImageTk.PhotoImage(im.resize((diametro, diametro), Image.LANCZOS))
    return _CACHE[chiave]


class Chip(tk.Label):
    """Pulsante piatto con passaggio del mouse e stato 'selezionato'."""

    def __init__(self, master, testo, comando, k, primario=False):
        self.k, self.primario, self.sel = k, primario, False
        super().__init__(master, text=testo, font=("Segoe UI", 9, "bold" if primario else "normal"),
                         padx=int(12 * k), pady=int(5 * k), cursor="hand2")
        self.comando = comando
        self.bind("<Button-1>", lambda e: self.comando())
        self.bind("<Enter>", lambda e: self._colora(True))
        self.bind("<Leave>", lambda e: self._colora(False))
        self._colora(False)

    def seleziona(self, s):
        self.sel = s
        self._colora(False)

    def _colora(self, hover):
        if self.primario:
            self.config(bg="#6fd0ff" if hover else ACCENTO, fg="#000000")
        elif self.sel:
            self.config(bg=ACCENTO, fg="#000000")
        else:
            self.config(bg=CHIP_HOVER if hover else CHIP, fg=FG)


class Cursore(tk.Canvas):
    """Barra a scorrimento disegnata a mano, nello stile del lettore video."""

    def __init__(self, master, k, minimo, massimo, valore, al_cambio, larghezza=260):
        self.k, self.min, self.max, self.val, self.al_cambio = k, minimo, massimo, valore, al_cambio
        super().__init__(master, width=int(larghezza * k), height=int(28 * k), bg=BARRA,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.bind("<Configure>", lambda e: self.disegna())
        self.bind("<Button-1>", self._muovi)
        self.bind("<B1-Motion>", self._muovi)

    def _x(self):
        m = int(10 * self.k)
        return m, max(self.winfo_width() - m, m + 1)

    def _muovi(self, e):
        x0, x1 = self._x()
        f = min(max((e.x - x0) / (x1 - x0), 0), 1)
        self.val = round(self.min + f * (self.max - self.min))
        self.disegna()
        self.al_cambio(self.val)

    def disegna(self):
        self.delete("all")
        x0, x1 = self._x()
        cy, sp = self.winfo_height() // 2, max(int(4 * self.k), 2)
        f = (self.val - self.min) / (self.max - self.min)
        xf = int(x0 + (x1 - x0) * f)
        self.create_rectangle(x0, cy - sp // 2, x1, cy - sp // 2 + sp, fill="#3d3d3d", outline="")
        self.create_rectangle(x0, cy - sp // 2, xf, cy - sp // 2 + sp, fill=ACCENTO, outline="")
        self.create_image(xf, cy, image=pallino(int(14 * self.k)))


# ===================================================================== editor
PROPORZIONI = [("Libera", None), ("Originale", "orig"), ("1:1", 1.0), ("4:3", 4 / 3),
               ("3:2", 3 / 2), ("16:9", 16 / 9), ("9:16", 9 / 16)]


class Editor:
    """Ritaglio come Google Foto: quando rilasci il riquadro, la vista si ingrandisce su di esso."""

    def __init__(self, img, nome):
        self.orig = img
        self.risultato = None
        self.ratio = None
        self.ratio_scelto = None
        self.scala_out = 100
        self.trascino = None
        self.animando = False
        self._vista = None

        self.root = radice()
        self.root.withdraw()
        self.root.title(f"Ritaglia e ridimensiona - {nome}")
        self.root.configure(bg=BG)
        applica_logo(self.root)
        self.k = max(self.root.winfo_fpixels("1i") / 96.0, 1.0)
        self.sw, self.sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        k = self.k
        self.margine = int(36 * k)

        # barra comandi in basso (la creo prima, per misurarne l'altezza)
        barra = tk.Frame(self.root, bg=BARRA)
        barra.pack(fill="x", side="bottom")
        riga1 = tk.Frame(barra, bg=BARRA)
        riga1.pack(pady=(int(12 * k), int(6 * k)))              # centrata
        tk.Label(riga1, text="Proporzioni", bg=BARRA, fg=SUB, font=("Segoe UI", 9)).pack(side="left", padx=(0, int(8 * k)))
        self.chips = []
        for testo, r in PROPORZIONI:
            c = Chip(riga1, testo, lambda r=r: self.imposta_ratio(r), k)
            c.pack(side="left", padx=int(2 * k))
            self.chips.append((r, c))
        tk.Frame(riga1, bg="#3a3a3a", width=max(int(k), 1), height=int(22 * k)).pack(side="left", padx=int(14 * k))
        tk.Label(riga1, text="Ruota", bg=BARRA, fg=SUB, font=("Segoe UI", 9)).pack(side="left", padx=(0, int(6 * k)))
        Chip(riga1, "⟲", lambda: self.ruota(90), k).pack(side="left", padx=int(2 * k))
        Chip(riga1, "⟳", lambda: self.ruota(-90), k).pack(side="left", padx=int(2 * k))

        riga2 = tk.Frame(barra, bg=BARRA)
        riga2.pack(fill="x", padx=int(16 * k), pady=(int(6 * k), int(12 * k)))
        tk.Label(riga2, text="Dimensione", bg=BARRA, fg=SUB, font=("Segoe UI", 9)).pack(side="left", padx=(0, int(8 * k)))
        self.cursore = Cursore(riga2, k, 10, 100, 100, self._cambia_scala, larghezza=200)
        self.cursore.pack(side="left")
        self.info = tk.Label(riga2, bg=BARRA, fg=FG, font=("Segoe UI", 9), anchor="w", width=34)
        self.info.pack(side="left", padx=int(12 * k))
        Chip(riga2, "Salva", self.salva, k, primario=True).pack(side="right", padx=int(2 * k))
        Chip(riga2, "Annulla", self.root.destroy, k).pack(side="right", padx=int(6 * k))

        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._premi)
        self.canvas.bind("<B1-Motion>", self._trascina)
        self.canvas.bind("<ButtonRelease-1>", self._rilascia)
        self.canvas.bind("<Motion>", self._cursore)
        self.canvas.bind("<MouseWheel>", self._rotella)
        self.canvas.bind("<Configure>", lambda e: self._adatta_vista(animato=False))
        self.root.bind("<Return>", lambda e: self.salva())
        self.root.bind("<Escape>", lambda e: self.root.destroy())

        self._prepara()
        self.crop = [0.0, 0.0, float(self.iw), float(self.ih)]
        for rr, c in self.chips:
            c.seleziona(rr is None)

        # finestra: abbastanza larga per la barra, alta quanto serve per l'immagine
        self.root.update_idletasks()
        bw, bh = barra.winfo_reqwidth() + int(24 * k), barra.winfo_reqheight()
        max_w, max_h = int(self.sw * 0.85), int(self.sh * 0.85) - bh
        s = min((max_w - 2 * self.margine) / self.iw, (max_h - 2 * self.margine) / self.ih, 1)
        w = max(int(self.iw * s) + 2 * self.margine, bw)
        h = int(self.ih * s) + 2 * self.margine + bh
        self.root.minsize(bw, bh + int(200 * k))
        self.root.geometry(f"{w}x{h}+{(self.sw - w) // 2}+{max((self.sh - h) // 3, 0)}")
        self.root.deiconify()
        self.root.after(50, lambda: (self.root.focus_force(), self.root.lift()))
        self.root.mainloop()

    # ------------------------------------------------------------ immagine e vista
    def _prepara(self):
        self.iw, self.ih = self.orig.size        # una sola copia della foto in memoria: l'originale
        self.vs, self.vx, self.vy = 1.0, 0.0, 0.0

    def _area(self):
        return max(self.canvas.winfo_width(), 50), max(self.canvas.winfo_height(), 50)

    def _vista_per(self, x0, y0, x1, y1, max_zoom=None):
        """Scala e posizione per far stare il rettangolo (coord. immagine) al centro, con margine."""
        cw, ch = self._area()
        m = self.margine
        w, h = max(x1 - x0, 1), max(y1 - y0, 1)
        vs = min((cw - 2 * m) / w, (ch - 2 * m) / h)
        if max_zoom:
            vs = min(vs, max_zoom)
        vx = cw / 2 - (x0 + w / 2) * vs
        vy = ch / 2 - (y0 + h / 2) * vs
        return vs, vx, vy

    def _adatta_vista(self, animato=True):
        """Zoom sulla zona selezionata (al massimo 4 pixel dello schermo per pixel della foto)."""
        x0, y0, x1, y1 = self.crop
        intera = x1 - x0 >= self.iw - 0.5 and y1 - y0 >= self.ih - 0.5
        base = self._vista_per(0, 0, self.iw, self.ih, max_zoom=1)[0]
        dest = self._vista_per(x0, y0, x1, y1, max_zoom=max(4.0, base))
        if intera:
            dest = self._vista_per(0, 0, self.iw, self.ih, max_zoom=1)
        if animato:
            self._anima(dest)
        else:
            self.vs, self.vx, self.vy = dest
            self._componi(veloce=False)
            self.disegna()

    def _anima(self, dest, passi=10):
        partenza = (self.vs, self.vx, self.vy)
        self.animando = True

        def passo(i):
            t = i / passi
            t = 1 - (1 - t) ** 3                       # rallenta alla fine
            self.vs, self.vx, self.vy = (a + (b - a) * t for a, b in zip(partenza, dest))
            ultimo = i >= passi
            self._componi(veloce=not ultimo)
            self.disegna()
            if ultimo:
                self.animando = False
            else:
                self.root.after(15, lambda: passo(i + 1))
        passo(1)

    def _componi(self, veloce=False):
        """Prepara l'immagine visibile alla scala corrente (scura fuori dal ritaglio)."""
        from PIL import Image, ImageEnhance, ImageTk
        import math
        cw, ch = self._area()
        vs, vx, vy = self.vs, self.vx, self.vy
        ix0, iy0 = max(int((0 - vx) / vs), 0), max(int((0 - vy) / vs), 0)
        ix1 = min(int(math.ceil((cw - vx) / vs)) + 1, self.iw)
        iy1 = min(int(math.ceil((ch - vy) / vs)) + 1, self.ih)
        if ix1 <= ix0 or iy1 <= iy0:
            self._vista = None
            return
        dim = (max(int(round((ix1 - ix0) * vs)), 1), max(int(round((iy1 - iy0) * vs)), 1))
        filtro = Image.BILINEAR if veloce else (Image.LANCZOS if vs < 1 else Image.NEAREST if vs > 3 else Image.BICUBIC)
        # ridimensiono direttamente la zona visibile dell'originale (box): nessuna copia intermedia;
        # reducing_gap accelera molto le riduzioni forti con qualita' indistinguibile
        vista = self.orig.resize(dim, filtro, box=(ix0, iy0, ix1, iy1),
                                 reducing_gap=3.0 if vs < 1 else None)
        if vista.mode not in ("RGB", "RGBA"):
            vista = vista.convert("RGBA" if "A" in vista.getbands() or "transparency" in vista.info else "RGB")
        self._vista = vista
        self._vista_pos = (vx + ix0 * vs, vy + iy0 * vs)
        self._vista_scura = ImageTk.PhotoImage(ImageEnhance.Brightness(self._vista).enhance(0.35))

    def _rotella(self, e):
        if self.animando:
            return
        f = 1.15 if e.delta > 0 else 1 / 1.15
        base = self._vista_per(0, 0, self.iw, self.ih, max_zoom=1)[0]
        nuovo = min(max(self.vs * f, base * 0.9), 16)
        # zoom attorno al puntatore
        ix, iy = (e.x - self.vx) / self.vs, (e.y - self.vy) / self.vs
        self.vs = nuovo
        self.vx, self.vy = e.x - ix * nuovo, e.y - iy * nuovo
        self._componi()
        self.disegna()

    def ruota(self, gradi):
        from PIL import Image
        # rotazione esatta di 90 gradi (nessun ricampionamento, molto piu' veloce)
        self.orig = self.orig.transpose(Image.ROTATE_90 if gradi == 90 else Image.ROTATE_270)
        self._prepara()
        self.imposta_ratio(self.ratio_scelto)

    def imposta_ratio(self, r):
        self.ratio_scelto = r
        for rr, c in self.chips:
            c.seleziona(rr == r)
        self.ratio = (self.iw / self.ih) if r == "orig" else r
        if self.ratio:
            w, h = self.iw, self.iw / self.ratio
            if h > self.ih:
                h, w = self.ih, self.ih * self.ratio
            cx, cy = self.iw / 2, self.ih / 2
            self.crop = [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]
        else:
            self.crop = [0.0, 0.0, float(self.iw), float(self.ih)]
        self._adatta_vista()

    def _cambia_scala(self, v):
        self.scala_out = v
        self._aggiorna_info()

    def _aggiorna_info(self):
        x0, y0, x1, y1 = self.crop
        w, h = round(x1 - x0), round(y1 - y0)
        f = self.scala_out / 100
        self.info.config(text=f"{w} × {h} px  →  {self.scala_out}%  =  {max(round(w * f), 1)} × {max(round(h * f), 1)} px")

    # ------------------------------------------------------------ disegno
    def _a_schermo(self, x, y):
        return self.vx + x * self.vs, self.vy + y * self.vs

    def disegna(self):
        from PIL import ImageTk
        c, k = self.canvas, self.k
        c.delete("all")
        if self._vista is None:
            self._componi()
        if self._vista is None:
            return
        px, py = self._vista_pos
        c.create_image(px, py, image=self._vista_scura, anchor="nw")
        x0, y0, x1, y1 = self.crop
        X0, Y0 = self._a_schermo(x0, y0)
        X1, Y1 = self._a_schermo(x1, y1)
        # parte chiara = ritaglio (ritaglio della vista gia' pronta: veloce anche trascinando)
        a, b = int(round(X0 - px)), int(round(Y0 - py))
        cc, d = int(round(X1 - px)), int(round(Y1 - py))
        a, b = max(a, 0), max(b, 0)
        cc, d = min(cc, self._vista.width), min(d, self._vista.height)
        if cc > a and d > b:
            self._chiaro = ImageTk.PhotoImage(self._vista.crop((a, b, cc, d)))
            c.create_image(px + a, py + b, image=self._chiaro, anchor="nw")
        if self.trascino:
            for i in (1, 2):
                xx = X0 + (X1 - X0) * i / 3
                yy = Y0 + (Y1 - Y0) * i / 3
                c.create_line(xx, Y0, xx, Y1, fill="#d0d0d0", width=1)
                c.create_line(X0, yy, X1, yy, fill="#d0d0d0", width=1)
        c.create_rectangle(X0, Y0, X1, Y1, outline="#ffffff", width=max(int(k), 1))
        L, sp = int(20 * k), max(int(3 * k), 2)
        L = max(min(L, int((X1 - X0) / 3), int((Y1 - Y0) / 3)), 4)
        for (x, y, dx, dy) in ((X0, Y0, 1, 1), (X1, Y0, -1, 1), (X0, Y1, 1, -1), (X1, Y1, -1, -1)):
            c.create_line(x, y, x + dx * L, y, fill="#ffffff", width=sp, capstyle="projecting")
            c.create_line(x, y, x, y + dy * L, fill="#ffffff", width=sp, capstyle="projecting")
        mx, my = (X0 + X1) / 2, (Y0 + Y1) / 2
        for (x, y, oriz) in ((mx, Y0, True), (mx, Y1, True), (X0, my, False), (X1, my, False)):
            if oriz:
                c.create_line(x - L / 2, y, x + L / 2, y, fill="#ffffff", width=sp)
            else:
                c.create_line(x, y - L / 2, x, y + L / 2, fill="#ffffff", width=sp)
        self._aggiorna_info()

    # ------------------------------------------------------------ mouse
    def _zona(self, ex, ey):
        X0, Y0 = self._a_schermo(*self.crop[:2])
        X1, Y1 = self._a_schermo(*self.crop[2:])
        t = 14 * self.k
        vicino = lambda a, b: abs(a - b) <= t
        if vicino(ex, X0) and vicino(ey, Y0):
            return "nw"
        if vicino(ex, X1) and vicino(ey, Y0):
            return "ne"
        if vicino(ex, X0) and vicino(ey, Y1):
            return "sw"
        if vicino(ex, X1) and vicino(ey, Y1):
            return "se"
        if X0 < ex < X1 and vicino(ey, Y0):
            return "n"
        if X0 < ex < X1 and vicino(ey, Y1):
            return "s"
        if Y0 < ey < Y1 and vicino(ex, X0):
            return "w"
        if Y0 < ey < Y1 and vicino(ex, X1):
            return "e"
        if X0 < ex < X1 and Y0 < ey < Y1:
            return "move"
        return "nuovo"

    def _cursore(self, e):
        forme = {"nw": "size_nw_se", "se": "size_nw_se", "ne": "size_ne_sw", "sw": "size_ne_sw",
                 "n": "size_ns", "s": "size_ns", "e": "size_we", "w": "size_we", "move": "fleur",
                 "nuovo": "crosshair"}
        try:
            self.canvas.config(cursor=forme[self._zona(e.x, e.y)])
        except tk.TclError:
            pass

    def _a_immagine(self, ex, ey):
        x = (ex - self.vx) / self.vs
        y = (ey - self.vy) / self.vs
        return min(max(x, 0), self.iw), min(max(y, 0), self.ih)

    def _premi(self, e):
        if self.animando:
            return
        self.trascino = self._zona(e.x, e.y)
        self._inizio = self._a_immagine(e.x, e.y)
        self._crop0 = list(self.crop)
        self._mosso = False

    def _rilascia(self, _e):
        if not self.trascino:
            return
        self.trascino = None
        if self._mosso:
            self._adatta_vista()     # zoom sulla zona scelta
        else:
            self.disegna()

    def _trascina(self, e):
        if not self.trascino or self.animando:
            return
        self._mosso = True
        mx, my = self._a_immagine(e.x, e.y)
        x0, y0, x1, y1 = self._crop0
        iw, ih, z = self.iw, self.ih, self.trascino
        minimo = max(8.0, min(iw, ih) * 0.02)

        if z == "move":
            w, h = x1 - x0, y1 - y0
            nx = min(max(x0 + mx - self._inizio[0], 0), iw - w)
            ny = min(max(y0 + my - self._inizio[1], 0), ih - h)
            self.crop = [nx, ny, nx + w, ny + h]
            self.disegna()
            return
        if z == "nuovo":                       # riquadro nuovo: come trascinare un angolo
            x0, y0 = x1, y1 = self._inizio
            z = "se"

        r = self.ratio
        if z in ("nw", "ne", "sw", "se"):
            ax = x1 if "w" in z else x0          # angolo opposto: resta fermo
            ay = y1 if "n" in z else y0
            if z == "se" and self.trascino == "nuovo":
                ax, ay = self._inizio
            sx = -1 if mx < ax else 1
            sy = -1 if my < ay else 1
            w, h = abs(mx - ax), abs(my - ay)
            spazio_w = ax if sx < 0 else iw - ax
            spazio_h = ay if sy < 0 else ih - ay
            if r:
                w = max(w, h * r)                # lato dominante
                w = min(w, spazio_w, spazio_h * r)
                h = w / r
            nx0 = ax - w if sx < 0 else ax
            ny0 = ay - h if sy < 0 else ay
            nuovo = [nx0, ny0, nx0 + w, ny0 + h]
        elif z in ("n", "s"):
            ay = y1 if z == "n" else y0
            h = min(abs(my - ay), ay if z == "n" else ih - ay)
            if r:
                cx = (x0 + x1) / 2
                h = min(h, 2 * min(cx, iw - cx) / r)
                w = h * r
                nx0 = cx - w / 2
            else:
                nx0, w = x0, x1 - x0
            ny0 = ay - h if z == "n" else ay
            nuovo = [nx0, ny0, nx0 + w, ny0 + h]
        else:  # "e" / "w"
            ax = x1 if z == "w" else x0
            w = min(abs(mx - ax), ax if z == "w" else iw - ax)
            if r:
                cy = (y0 + y1) / 2
                w = min(w, 2 * min(cy, ih - cy) * r)
                h = w / r
                ny0 = cy - h / 2
            else:
                ny0, h = y0, y1 - y0
            nx0 = ax - w if z == "w" else ax
            nuovo = [nx0, ny0, nx0 + w, ny0 + h]

        if nuovo[2] - nuovo[0] < minimo or nuovo[3] - nuovo[1] < minimo:
            return
        self.crop = [min(max(nuovo[0], 0), iw), min(max(nuovo[1], 0), ih),
                     min(max(nuovo[2], 0), iw), min(max(nuovo[3], 0), ih)]
        self.disegna()

    # ------------------------------------------------------------ salva
    def salva(self):
        from PIL import Image
        x0, y0, x1, y1 = (int(round(v)) for v in self.crop)
        img = self.orig.crop((x0, y0, x1, y1))
        f = self.scala_out / 100
        if f < 1:
            img = img.resize((max(int(img.width * f), 1), max(int(img.height * f), 1)), Image.LANCZOS)
        self.risultato = img
        self.root.destroy()


def ritaglia(img, nome):
    """Apre l'editor. Restituisce l'immagine modificata, oppure None se annulli."""
    nitido()
    ed = Editor(img, nome)
    return ed.risultato


# =============================================== piu' immagini: solo pulsanti
LATI = [("Originale", None), ("3840 px", 3840), ("2560 px", 2560), ("1920 px", 1920),
        ("1280 px", 1280), ("800 px", 800), ("640 px", 640)]
QUALITA = [("Alta", 92), ("Media", 80), ("Bassa", 65)]


def scegli_dimensione(n_file, esempio=None):
    """Finestra a pulsanti per piu' immagini. Restituisce (lato_massimo|None, qualita) o None."""
    nitido()
    scelta = {"lato": 1920, "q": 80, "ok": False}
    root = radice()
    root.withdraw()
    root.title("Ridimensiona e comprimi")
    root.configure(bg=BG)
    applica_logo(root)
    k = max(root.winfo_fpixels("1i") / 96.0, 1.0)
    pad = int(16 * k)

    tk.Label(root, text=f"{n_file} immagini selezionate", bg=BG, fg=FG,
             font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=pad, pady=(pad, int(2 * k)))
    tk.Label(root, text="Il lato più lungo di ogni foto diventerà al massimo:", bg=BG, fg=SUB,
             font=("Segoe UI", 9)).pack(anchor="w", padx=pad, pady=(int(8 * k), int(4 * k)))
    r1 = tk.Frame(root, bg=BG)
    r1.pack(anchor="w", padx=pad)
    tk.Label(root, text="Qualità:", bg=BG, fg=SUB, font=("Segoe UI", 9)).pack(
        anchor="w", padx=pad, pady=(int(12 * k), int(4 * k)))
    r2 = tk.Frame(root, bg=BG)
    r2.pack(anchor="w", padx=pad)
    anteprima = tk.Label(root, bg=BG, fg=FG, font=("Segoe UI", 9))
    anteprima.pack(anchor="w", padx=pad, pady=(int(12 * k), 0))

    chips_l, chips_q = [], []

    def aggiorna():
        for v, c in chips_l:
            c.seleziona(v == scelta["lato"])
        for v, c in chips_q:
            c.seleziona(v == scelta["q"])
        if esempio:
            w, h = esempio
            lato = scelta["lato"]
            f = min(lato / max(w, h), 1) if lato else 1
            anteprima.config(text=f"Esempio: {w} × {h} px  →  {round(w * f)} × {round(h * f)} px")

    for testo, v in LATI:
        c = Chip(r1, testo, lambda v=v: (scelta.update(lato=v), aggiorna()), k)
        c.pack(side="left", padx=int(2 * k))
        chips_l.append((v, c))
    for testo, v in QUALITA:
        c = Chip(r2, testo, lambda v=v: (scelta.update(q=v), aggiorna()), k)
        c.pack(side="left", padx=int(2 * k))
        chips_q.append((v, c))

    giu = tk.Frame(root, bg=BG)
    giu.pack(fill="x", padx=pad, pady=pad)

    def conferma():
        scelta["ok"] = True
        root.destroy()
    Chip(giu, "Salva", conferma, k, primario=True).pack(side="right", padx=int(2 * k))
    Chip(giu, "Annulla", root.destroy, k).pack(side="right", padx=int(6 * k))
    root.bind("<Return>", lambda e: conferma())
    root.bind("<Escape>", lambda e: root.destroy())
    aggiorna()
    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    root.geometry(f"+{(root.winfo_screenwidth() - w) // 2}+{(root.winfo_screenheight() - h) // 3}")
    root.resizable(False, False)
    root.deiconify()
    root.after(50, lambda: (root.focus_force(), root.lift()))
    root.mainloop()
    return (scelta["lato"], scelta["q"]) if scelta["ok"] else None
