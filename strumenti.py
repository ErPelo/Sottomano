# -*- coding: utf-8 -*-
# Sottomano - finestre degli strumenti: rinomina, QR code, pagine PDF, taglio video,
# unione immagini, zona dello schermo, duplicati. Stesso stile dell'editor di ritaglio.
# Copyright (C) 2026 Tommaso Pelosin - Licenza AGPL-3.0 (vedi LICENSE)

import os
import re
import threading
import tkinter as tk
from pathlib import Path

from ritaglia import BG, BARRA, FG, SUB, ACCENTO, CHIP, Chip, applica_logo, radice, pallino

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic", ".heif", ".ico"}
CAMPO = "#2b2b2b"
BORDO = "#3a3a3a"
ERRORE = "#ff99a4"


# ============================================================ mattoncini comuni
def finestra(titolo):
    root = radice()
    root.withdraw()
    root.title(titolo)
    root.configure(bg=BG)
    applica_logo(root)
    k = max(root.winfo_fpixels("1i") / 96.0, 1.0)
    return root, k


def mostra(root, w=None, h=None, ridimensionabile=False):
    """Centra la finestra (un po' piu' in alto del centro, come le finestre di Windows) e la mostra."""
    root.update_idletasks()
    w = w or root.winfo_reqwidth()
    h = h or root.winfo_reqheight()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    w, h = min(w, sw - 40), min(h, sh - 80)
    root.geometry(f"{w}x{h}+{(sw - w) // 2}+{max((sh - h) // 3, 0)}")
    root.resizable(ridimensionabile, ridimensionabile)
    root.deiconify()
    root.after(50, lambda: (root.focus_force(), root.lift()))


def etichetta(master, testo, k, colore=SUB, dim=9, grassetto=False, **kw):
    return tk.Label(master, text=testo, bg=master["bg"], fg=colore,
                    font=("Segoe UI", dim, "bold" if grassetto else "normal"), **kw)


def campo(master, k, larghezza=30, testo="", **kw):
    e = tk.Entry(master, width=larghezza, bg=CAMPO, fg=FG, insertbackground=FG, relief="flat",
                 font=("Segoe UI", 10), highlightthickness=max(int(k), 1), highlightbackground=BORDO,
                 highlightcolor=ACCENTO, disabledbackground=BARRA, disabledforeground=SUB, **kw)
    if testo:
        e.insert(0, testo)
    return e


class Scelta:
    """Gruppo di pulsanti di cui uno solo e' selezionato (come i 'chip' delle proporzioni)."""

    def __init__(self, master, k, opzioni, valore, al_cambio=None):
        self.valore, self.al_cambio = valore, al_cambio
        self.frame = tk.Frame(master, bg=master["bg"])
        self.chips = []
        for testo, v in opzioni:
            c = Chip(self.frame, testo, lambda v=v: self.imposta(v), k)
            c.pack(side="left", padx=(0, int(4 * k)))
            self.chips.append((v, c))
        self._colora()

    def imposta(self, v):
        self.valore = v
        self._colora()
        if self.al_cambio:
            self.al_cambio(v)

    def _colora(self):
        for v, c in self.chips:
            c.seleziona(v == self.valore)

    def pack(self, **kw):
        self.frame.pack(**kw)
        return self


def riquadro(master, w, h, colore=BARRA):
    """Label di dimensione fissa in PIXEL (una Label senza immagine misurerebbe in caratteri)."""
    box = tk.Frame(master, bg=colore, width=w, height=h)
    box.pack_propagate(False)
    lab = tk.Label(box, bg=colore, bd=0)
    lab.pack(fill="both", expand=True)
    return box, lab


def pulsanti(master, k, testo_ok, ok, annulla, testo_annulla="Annulla"):
    giu = tk.Frame(master, bg=master["bg"])
    b_ok = Chip(giu, testo_ok, ok, k, primario=True)
    b_ok.pack(side="right", padx=int(2 * k))
    Chip(giu, testo_annulla, annulla, k).pack(side="right", padx=int(6 * k))
    return giu, b_ok


class Scorrevole(tk.Frame):
    """Contenitore con barra di scorrimento verticale e rotellina del mouse."""

    def __init__(self, master, k, **kw):
        super().__init__(master, bg=master["bg"], **kw)
        self.canvas = tk.Canvas(self, bg=self["bg"], highlightthickness=0, bd=0)
        self.barra = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.dentro = tk.Frame(self.canvas, bg=self["bg"])
        self._id = self.canvas.create_window(0, 0, anchor="nw", window=self.dentro)
        self.canvas.configure(yscrollcommand=self.barra.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.barra.pack(side="right", fill="y")
        self.dentro.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._id, width=e.width))
        self.bind_all("<MouseWheel>", self._rotella, add="+")

    def _rotella(self, e):
        try:
            if self.canvas.winfo_exists():
                self.canvas.yview_scroll(int(-e.delta / 120) * 3, "units")
        except tk.TclError:
            pass


def _miniatura(path, lato):
    """Miniatura veloce (i JPEG vengono decodificati gia' piccoli)."""
    from PIL import Image, ImageOps
    if Path(path).suffix.lower() in (".heic", ".heif"):
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            pass
    im = Image.open(path)
    if im.format == "JPEG":
        im.draft("RGB", (lato * 2, lato * 2))
    try:
        im = ImageOps.exif_transpose(im)
    except Exception:
        pass
    im.thumbnail((lato, lato))
    return im.convert("RGBA") if im.mode in ("RGBA", "LA", "P") else im.convert("RGB")


# ============================================================ rinomina in blocco
VIETATI = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def data_di(path):
    """Data di scatto (EXIF) per le foto, altrimenti data di ultima modifica."""
    import datetime
    p = Path(path)
    if p.suffix.lower() in IMG_EXT:
        try:
            from PIL import Image
            with Image.open(p) as im:
                ex = im.getexif()
                v = ex.get_ifd(0x8769).get(0x9003) or ex.get(0x0132)
            if v:
                return datetime.datetime.strptime(str(v).strip("\x00 ")[:19], "%Y:%m:%d %H:%M:%S")
        except Exception:
            pass
    return datetime.datetime.fromtimestamp(p.stat().st_mtime)


def nuovi_nomi(files, modo, nome="", inizio=1, trova="", sostituisci="", ordine="nome", _date=None):
    """[(vecchio, nuovo)] nell'ordine scelto. L'estensione resta sempre quella originale."""
    files = [Path(f) for f in files]
    date = _date if _date is not None else ({f: data_di(f) for f in files} if modo == "data" or ordine == "data" else {})
    if ordine == "data" or modo == "data":
        files.sort(key=lambda f: (date[f], f.name.lower()))
    else:
        files.sort(key=lambda f: _naturale(f.name))
    nome = VIETATI.sub("_", nome).strip()
    out = []
    if modo == "numero":
        cifre = max(3, len(str(inizio + len(files) - 1)))
        for i, f in enumerate(files):
            n = f"{inizio + i:0{cifre}d}"
            out.append((f, f.with_name(f"{nome} {n}{f.suffix}" if nome else f"{n}{f.suffix}")))
    elif modo == "data":
        visti = {}
        for f in files:
            base = date[f].strftime("%Y-%m-%d %H.%M.%S")
            if nome:
                base = f"{nome} {base}"
            visti[base] = visti.get(base, 0) + 1
            out.append((f, base))
        contati = {}
        finale = []
        for f, base in out:
            if visti[base] > 1:
                contati[base] = contati.get(base, 0) + 1
                base = f"{base} ({contati[base]})"
            finale.append((f, f.with_name(base + f.suffix)))
        out = finale
    else:  # sostituisci
        for f in files:
            stem = f.stem.replace(trova, VIETATI.sub("_", sostituisci)) if trova else f.stem
            out.append((f, f.with_name(stem.rstrip(" .") + f.suffix) if stem.strip(" .") else f))
    return out


def _naturale(s):
    """Ordine 'naturale' come Esplora file: foto2 prima di foto10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def rinomina(files):
    """Finestra di rinomina. Restituisce [(vecchio, nuovo)] oppure None."""
    root, k = finestra(f"Rinomina {len(files)} file")
    pad = int(16 * k)
    esito = {"coppie": None}
    cartella = Path(files[0]).parent
    date_cache = {}

    etichetta(root, f"Rinomina {len(files)} file", k, FG, 11, True).pack(anchor="w", padx=pad, pady=(pad, int(8 * k)))
    modo = Scelta(root, k, [("Nome e numero", "numero"), ("Data di scatto", "data"), ("Sostituisci testo", "sostituisci")],
                  "numero", lambda v: aggiorna()).pack(anchor="w", padx=pad)

    campi = tk.Frame(root, bg=BG)
    campi.pack(fill="x", padx=pad, pady=(int(12 * k), 0))
    r1 = tk.Frame(campi, bg=BG)
    r1.pack(fill="x")
    l1 = etichetta(r1, "Nome", k, width=12, anchor="w")
    l1.pack(side="left")
    e1 = campo(r1, k, 32, cartella.name)
    e1.pack(side="left", ipady=int(3 * k))
    r2 = tk.Frame(campi, bg=BG)
    r2.pack(fill="x", pady=(int(8 * k), 0))
    l2 = etichetta(r2, "Inizia da", k, width=12, anchor="w")
    l2.pack(side="left")
    e2 = campo(r2, k, 8, "1")
    e2.pack(side="left", ipady=int(3 * k))
    r3 = tk.Frame(campi, bg=BG)
    r3.pack(fill="x", pady=(int(10 * k), 0))
    etichetta(r3, "Ordine", k, width=12, anchor="w").pack(side="left")
    ordine = Scelta(r3, k, [("Per nome", "nome"), ("Per data", "data")], "nome", lambda v: aggiorna()).pack(side="left")

    etichetta(root, "Anteprima", k).pack(anchor="w", padx=pad, pady=(int(14 * k), int(4 * k)))
    lista = tk.Text(root, height=9, width=70, bg=BARRA, fg=FG, relief="flat", font=("Segoe UI", 9),
                    padx=int(10 * k), pady=int(8 * k), wrap="none", highlightthickness=0, cursor="arrow")
    lista.tag_configure("vecchio", foreground=SUB)
    lista.tag_configure("freccia", foreground=ACCENTO)
    lista.pack(fill="x", padx=pad)
    avviso = etichetta(root, "", k, ERRORE)
    avviso.pack(anchor="w", padx=pad, pady=(int(6 * k), 0))

    def opzioni():
        m = modo.valore
        try:
            inizio = max(int(e2.get().strip() or 1), 0)
        except ValueError:
            inizio = 1
        if m == "sostituisci":
            return dict(modo=m, trova=e1.get(), sostituisci=e2.get(), ordine=ordine.valore)
        return dict(modo=m, nome=e1.get(), inizio=inizio, ordine=ordine.valore)

    def calcola():
        o = opzioni()
        if (o["modo"] == "data" or o["ordine"] == "data") and not date_cache:
            for f in files:
                try:
                    date_cache[Path(f)] = data_di(f)
                except OSError:
                    import datetime
                    date_cache[Path(f)] = datetime.datetime.now()
        return nuovi_nomi(files, _date=date_cache if date_cache else None, **o)

    ultimo_modo = [None]

    def aggiorna(*_):
        m = modo.valore
        if m != ultimo_modo[0]:
            ultimo_modo[0] = m
            if m == "sostituisci":
                l1.config(text="Trova")
                l2.config(text="Sostituisci con")
                e1.delete(0, "end")
                e2.config(width=32)
                e2.delete(0, "end")
                r2.pack(fill="x", pady=(int(8 * k), 0))
            else:
                l1.config(text="Nome" if m == "numero" else "Prima della data")
                l2.config(text="Inizia da")
                e2.config(width=8)
                if m == "numero":
                    if not e1.get():
                        e1.insert(0, cartella.name)
                    if not e2.get().strip().isdigit():
                        e2.delete(0, "end")
                        e2.insert(0, "1")
                    r2.pack(fill="x", pady=(int(8 * k), 0))
                else:
                    e1.delete(0, "end")
                    r2.pack_forget()
        coppie = calcola()
        lista.config(state="normal")
        lista.delete("1.0", "end")
        for a, b in coppie[:60]:
            lista.insert("end", a.name, "vecchio")
            lista.insert("end", "   →   ", "freccia")
            lista.insert("end", b.name + "\n")
        if len(coppie) > 60:
            lista.insert("end", f"... e altri {len(coppie) - 60}", "vecchio")
        lista.config(state="disabled")
        cambiano = sum(1 for a, b in coppie if a != b)
        nomi = [b.name.lower() for _, b in coppie]
        if len(set(nomi)) < len(nomi):
            avviso.config(text="Alcuni nomi risultano uguali: verrà aggiunto un numero tra parentesi.")
        elif cambiano == 0:
            avviso.config(text="Nessun nome cambia.", fg=SUB)
        else:
            avviso.config(text=f"Cambieranno {cambiano} nomi.", fg=SUB)
        return coppie

    def conferma():
        coppie = aggiorna()
        if any(a != b for a, b in coppie):
            esito["coppie"] = coppie
            root.destroy()

    for e in (e1, e2):
        e.bind("<KeyRelease>", lambda ev: root.after_idle(aggiorna))
    giu, _ = pulsanti(root, k, "Rinomina", conferma, root.destroy)
    giu.pack(fill="x", padx=pad, pady=pad)
    root.bind("<Return>", lambda e: conferma())
    root.bind("<Escape>", lambda e: root.destroy())
    aggiorna()
    mostra(root)
    e1.focus_set()
    e1.select_range(0, "end")
    root.mainloop()
    return esito["coppie"]


# ===================================================================== QR code
def immagine_qr(testo, lato=None):
    import qrcode
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=16, border=3)
    qr.add_data(testo)
    qr.make(fit=True)
    im = qr.make_image(fill_color="black", back_color="white").get_image().convert("RGB")
    if lato:
        from PIL import Image
        im = im.resize((lato, lato), Image.NEAREST)
    return im


def crea_qr(testo_iniziale, salva, copia):
    """Finestra: scrivi testo o link, vedi il QR in tempo reale, salva o copia."""
    from PIL import ImageTk
    root, k = finestra("Crea QR code")
    pad = int(16 * k)
    lato = int(240 * k)

    corpo = tk.Frame(root, bg=BG)
    corpo.pack(padx=pad, pady=(pad, 0))
    sx = tk.Frame(corpo, bg=BG)
    sx.pack(side="left", fill="y", padx=(0, pad))
    etichetta(sx, "Link o testo", k, FG, 11, True).pack(anchor="w")
    etichetta(sx, "Il QR code si aggiorna mentre scrivi.", k).pack(anchor="w", pady=(int(2 * k), int(8 * k)))
    box = tk.Text(sx, width=34, height=9, bg=CAMPO, fg=FG, insertbackground=FG, relief="flat", wrap="word",
                  font=("Segoe UI", 10), padx=int(8 * k), pady=int(6 * k), highlightthickness=max(int(k), 1),
                  highlightbackground=BORDO, highlightcolor=ACCENTO)
    box.pack(fill="both", expand=True)
    box.insert("1.0", testo_iniziale or "")
    stato = etichetta(sx, "", k)
    stato.pack(anchor="w", pady=(int(6 * k), 0))
    box_qr, tela = riquadro(corpo, lato, lato)
    box_qr.pack(side="left")

    rif = {"img": None, "foto": None, "job": None}

    def aggiorna():
        rif["job"] = None
        t = box.get("1.0", "end-1c").strip()
        if not t:
            rif["img"] = None
            tela.config(image="", text="Scrivi qualcosa", fg=SUB, font=("Segoe UI", 10))
            stato.config(text="")
            return
        try:
            rif["img"] = immagine_qr(t)
        except Exception:
            rif["img"] = None
            tela.config(image="", text="Testo troppo lungo\nper un QR code", fg=ERRORE)
            return
        rif["foto"] = ImageTk.PhotoImage(rif["img"].resize((lato, lato), 0))
        tela.config(image=rif["foto"], text="")
        stato.config(text=f"{len(t)} caratteri")

    def programma(_=None):
        if rif["job"]:
            root.after_cancel(rif["job"])
        rif["job"] = root.after(120, aggiorna)

    def fatto(azione):
        if rif["img"] is not None:
            msg = azione(rif["img"], box.get("1.0", "end-1c").strip())
            if msg:
                stato.config(text=msg, fg=ACCENTO)

    box.bind("<KeyRelease>", programma)
    giu = tk.Frame(root, bg=BG)
    giu.pack(fill="x", padx=pad, pady=pad)
    Chip(giu, "Salva PNG", lambda: fatto(salva), k, primario=True).pack(side="right", padx=int(2 * k))
    Chip(giu, "Copia immagine", lambda: fatto(copia), k).pack(side="right", padx=int(6 * k))
    Chip(giu, "Chiudi", root.destroy, k).pack(side="left")
    root.bind("<Escape>", lambda e: root.destroy())
    aggiorna()
    mostra(root)
    box.focus_set()
    box.tag_add("sel", "1.0", "end")
    root.mainloop()


# ============================================================ PDF: dividi
def leggi_intervalli(testo, n):
    """'1-3, 5, 8-' -> [0,1,2,4,7,...,n-1]. Numeri fuori dal documento -> ValueError."""
    pagine = []
    for parte in re.split(r"[,;\s]+", testo.strip()):
        if not parte:
            continue
        m = re.fullmatch(r"(\d*)\s*-\s*(\d*)", parte)
        if m:
            a = int(m.group(1)) if m.group(1) else 1
            b = int(m.group(2)) if m.group(2) else n
        elif parte.isdigit():
            a = b = int(parte)
        else:
            raise ValueError(f"Non capisco «{parte}»")
        if not (1 <= a <= n and 1 <= b <= n):
            raise ValueError(f"Il PDF ha {n} pagine")
        passo = 1 if b >= a else -1
        pagine += list(range(a - 1, b - 1 + passo, passo))
    if not pagine:
        raise ValueError("Scrivi quali pagine")
    return pagine


def scegli_divisione(n, nome):
    """('singole',) | ('pagine', [indici], testo) | ('ogni', N) | None"""
    root, k = finestra("Dividi PDF")
    pad = int(16 * k)
    esito = {"v": None}
    etichetta(root, nome, k, FG, 11, True).pack(anchor="w", padx=pad, pady=(pad, 0))
    etichetta(root, f"{n} pagine", k).pack(anchor="w", padx=pad, pady=(int(2 * k), int(12 * k)))
    modo = Scelta(root, k, [("Estrai pagine", "pagine"), ("Una pagina per file", "singole"),
                            ("Ogni N pagine", "ogni")], "pagine", lambda v: aggiorna()).pack(anchor="w", padx=pad)
    riga = tk.Frame(root, bg=BG)
    riga.pack(fill="x", padx=pad, pady=(int(14 * k), 0))
    lab = etichetta(riga, "Pagine", k, width=10, anchor="w")
    lab.pack(side="left")
    e = campo(riga, k, 24, f"1-{min(n, 3)}" if n > 1 else "1")
    e.pack(side="left", ipady=int(3 * k))
    aiuto = etichetta(root, "", k)
    aiuto.pack(anchor="w", padx=pad, pady=(int(8 * k), 0))

    def valuta():
        m = modo.valore
        if m == "singole":
            return ("singole",), f"Verranno creati {n} PDF, uno per pagina."
        if m == "ogni":
            try:
                x = int(e.get().strip())
                assert x >= 1
            except Exception:
                return None, "Scrivi ogni quante pagine dividere (es. 5)."
            parti = -(-n // x)
            return ("ogni", x), f"Verranno creati {parti} PDF da {x} pagine (l'ultimo può averne meno)."
        try:
            p = leggi_intervalli(e.get(), n)
        except ValueError as err:
            return None, f"{err}. Esempio: 1-3, 5, 8-10"
        return ("pagine", p, e.get().strip()), f"Nuovo PDF con {len(p)} pagine. Esempio: 1-3, 5, 8-10"

    ultimo = [None]

    def aggiorna(*_):
        m = modo.valore
        if m != ultimo[0]:
            ultimo[0] = m
            e.config(state="normal")
            e.delete(0, "end")
            if m == "ogni":
                lab.config(text="Ogni")
                e.insert(0, "5")
            elif m == "pagine":
                lab.config(text="Pagine")
                e.insert(0, f"1-{min(n, 3)}" if n > 1 else "1")
            else:
                lab.config(text="Pagine")
                e.config(state="disabled")
        v, msg = valuta()
        aiuto.config(text=msg, fg=SUB if v else ERRORE)

    def conferma():
        v, _ = valuta()
        if v:
            esito["v"] = v
            root.destroy()

    e.bind("<KeyRelease>", aggiorna)
    giu, _ = pulsanti(root, k, "Crea", conferma, root.destroy)
    giu.pack(fill="x", padx=pad, pady=pad)
    root.bind("<Return>", lambda ev: conferma())
    root.bind("<Escape>", lambda ev: root.destroy())
    aggiorna()
    mostra(root, w=int(460 * k))
    e.focus_set()
    root.mainloop()
    return esito["v"]


# ======================================================= PDF: editor delle pagine
def _pdf_per_miniature(path, fitz):
    """(numero pagine, disegna(i, lato) -> PIL, chiudi). PDFium se c'e' (veloce e leggero),
    altrimenti PyMuPDF. fitz: funzione che restituisce PyMuPDF (lo carico solo se serve)."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        pdfium = None
    if pdfium is not None:
        pdf = pdfium.PdfDocument(str(path))

        def disegna(i, lato):
            pag = pdf[i]
            w, h = pag.get_size()
            im = pag.render(scale=lato / max(w, h)).to_pil().convert("RGB")
            pag.close()
            return im
        return len(pdf), disegna, pdf.close
    fz = fitz() if callable(fitz) else fitz
    doc = fz.open(path)

    def disegna(i, lato):
        from PIL import Image
        pag = doc[i]
        z = lato / max(pag.rect.width, pag.rect.height)
        pix = pag.get_pixmap(matrix=fz.Matrix(z, z))
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return doc.page_count, disegna, doc.close



class EditorPagine:
    """Miniature delle pagine: clic per selezionare (Ctrl/Maiusc per piu' pagine),
    trascina per spostare, ruota ed elimina. Restituisce [(indice_originale, rotazione_extra)]."""

    def __init__(self, path, fitz):
        self.n, self._render, self._chiudi_doc = _pdf_per_miniature(path, fitz)
        n = self.n
        self.ordine = [[i, 0] for i in range(n)]       # [pagina originale, rotazione aggiunta]
        self.sel = set()                                # posizioni selezionate
        self.ancora = None
        self.risultato = None
        self.miniature = {}                             # pagina -> PIL
        self.foto = {}
        self.trascino = None

        self.root, k = finestra(f"Pagine - {Path(path).name}")
        self.k = k
        self.lato = int(150 * k)                        # altezza massima miniatura
        self.cella_w, self.cella_h = int(150 * k) + int(28 * k), self.lato + int(44 * k)

        barra = tk.Frame(self.root, bg=BARRA)
        barra.pack(side="bottom", fill="x")
        riga = tk.Frame(barra, bg=BARRA)
        riga.pack(fill="x", padx=int(16 * k), pady=int(12 * k))
        Chip(riga, "⟲  Ruota a sinistra", lambda: self.ruota(-90), k).pack(side="left", padx=(0, int(4 * k)))
        Chip(riga, "⟳  Ruota a destra", lambda: self.ruota(90), k).pack(side="left", padx=(0, int(4 * k)))
        Chip(riga, "Elimina", self.elimina, k).pack(side="left", padx=(0, int(4 * k)))
        self.info = tk.Label(riga, bg=BARRA, fg=SUB, font=("Segoe UI", 9))
        self.info.pack(side="left", padx=int(12 * k))
        Chip(riga, "Salva", self.salva, k, primario=True).pack(side="right", padx=int(2 * k))
        Chip(riga, "Annulla", self.root.destroy, k).pack(side="right", padx=int(6 * k))
        aiuto = tk.Label(barra, bg=BARRA, fg=SUB, font=("Segoe UI", 8),
                         text="Clic per selezionare  ·  Ctrl/Maiusc per più pagine  ·  trascina per spostare  ·  Canc per eliminare")
        aiuto.pack(pady=(0, int(10 * k)))

        wrap = tk.Frame(self.root, bg=BG)
        wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, bd=0)
        sb = tk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.disegna())
        self.canvas.bind("<Button-1>", self._premi)
        self.canvas.bind("<B1-Motion>", self._muovi)
        self.canvas.bind("<ButtonRelease-1>", self._rilascia)
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120) * 3, "units"))
        self.root.bind("<Delete>", lambda e: self.elimina())
        self.root.bind("<Control-a>", lambda e: self._tutte())
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.root.bind("<Control-s>", lambda e: self.salva())

        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        colonne = max(2, min(6, n))
        w = min(colonne * self.cella_w + int(60 * k), int(sw * 0.85))
        h = min(-(-n // colonne) * self.cella_h + int(150 * k), int(sh * 0.85))
        mostra(self.root, max(w, int(720 * k)), max(h, int(420 * k)), ridimensionabile=True)
        self.root.after(30, self._prossima_miniatura, 0)
        self.root.mainloop()
        self._chiudi_doc()

    # -- miniature create poco alla volta: la finestra e' subito usabile anche con 300 pagine
    def _prossima_miniatura(self, i):
        if i >= self.n:
            return
        try:
            self.miniature[i] = self._render(i, self.lato)
        except Exception:
            pass
        self.disegna()
        try:
            self.root.after(1, self._prossima_miniatura, i + 1)
        except tk.TclError:
            pass

    def _immagine(self, pag, rot):
        from PIL import ImageTk, Image
        chiave = (pag, rot % 360)
        if chiave not in self.foto and pag in self.miniature:
            im = self.miniature[pag]
            if rot % 360:
                im = im.rotate(-(rot % 360), expand=True)
                im.thumbnail((self.lato, self.lato), Image.BILINEAR)
            self.foto[chiave] = ImageTk.PhotoImage(im)
        return self.foto.get(chiave)

    def _colonne(self):
        return max(1, (self.canvas.winfo_width() - int(16 * self.k)) // self.cella_w)

    def _cella(self, pos):
        c = self._colonne()
        x0 = int(16 * self.k) + (pos % c) * self.cella_w
        y0 = int(16 * self.k) + (pos // c) * self.cella_h
        return x0, y0

    def disegna(self):
        cv, k = self.canvas, self.k
        try:
            cv.delete("all")
        except tk.TclError:
            return
        for pos, (pag, rot) in enumerate(self.ordine):
            x0, y0 = self._cella(pos)
            cx, cy = x0 + self.cella_w // 2, y0 + int(6 * k) + self.lato // 2
            sel = pos in self.sel
            if sel:
                cv.create_rectangle(x0 + int(4 * k), y0, x0 + self.cella_w - int(4 * k), y0 + self.cella_h - int(6 * k),
                                    fill="#1f3a4d", outline=ACCENTO, width=max(int(2 * k), 1))
            foto = self._immagine(pag, rot)
            if foto is not None:
                cv.create_image(cx, cy, image=foto)
            else:
                cv.create_rectangle(cx - self.lato // 3, y0 + int(6 * k), cx + self.lato // 3, y0 + int(6 * k) + self.lato,
                                    fill="#2a2a2a", outline="")
            cv.create_text(cx, y0 + self.lato + int(22 * k), text=str(pag + 1),
                           fill=FG if sel else SUB, font=("Segoe UI", 9, "bold" if sel else "normal"))
        if self.trascino and self.trascino.get("attivo"):
            dest = self.trascino["dest"]
            if dest is not None:
                if dest < len(self.ordine):
                    x, y = self._cella(dest)
                else:
                    x, y = self._cella(len(self.ordine) - 1)
                    x += self.cella_w
                cv.create_rectangle(x - max(int(2 * k), 1), y, x + max(int(2 * k), 1), y + self.cella_h - int(10 * k),
                                    fill=ACCENTO, outline="")
        righe = -(-len(self.ordine) // self._colonne())
        cv.configure(scrollregion=(0, 0, cv.winfo_width(), righe * self.cella_h + int(32 * k)))
        n = len(self.ordine)
        self.info.config(text=f"{n} pagine" + (f"  ·  {len(self.sel)} selezionate" if self.sel else ""))

    def _pos_a(self, ex, ey, inserimento=False):
        x, y = self.canvas.canvasx(ex), self.canvas.canvasy(ey)
        c = self._colonne()
        col = int((x - int(16 * self.k)) // self.cella_w)
        riga = int((y - int(16 * self.k)) // self.cella_h)
        if col < 0 or riga < 0:
            return 0 if inserimento else None
        if inserimento:
            frac = ((x - int(16 * self.k)) % self.cella_w) / self.cella_w
            col = min(col + (1 if frac > 0.5 else 0), c)
            return min(riga * c + col, len(self.ordine))
        if col >= c:
            return None
        pos = riga * c + col
        return pos if pos < len(self.ordine) else None

    def _premi(self, e):
        pos = self._pos_a(e.x, e.y)
        ctrl, shift = e.state & 0x4, e.state & 0x1
        if pos is None:
            if not ctrl:
                self.sel.clear()
        elif shift and self.ancora is not None:
            a, b = sorted((self.ancora, pos))
            self.sel = set(range(a, b + 1))
        elif ctrl:
            self.sel ^= {pos}
            self.ancora = pos
        else:
            if pos not in self.sel:
                self.sel = {pos}
            self.ancora = pos
        self.trascino = {"x": e.x, "y": e.y, "attivo": False, "dest": None, "pos": pos} if pos is not None else None
        self.disegna()

    def _muovi(self, e):
        t = self.trascino
        if not t or not self.sel:
            return
        if not t["attivo"] and abs(e.x - t["x"]) + abs(e.y - t["y"]) > 8 * self.k:
            t["attivo"] = True
            self.canvas.config(cursor="fleur")
        if t["attivo"]:
            t["dest"] = self._pos_a(e.x, e.y, inserimento=True)
            h = self.canvas.winfo_height()
            if e.y < 20 * self.k:
                self.canvas.yview_scroll(-1, "units")
            elif e.y > h - 20 * self.k:
                self.canvas.yview_scroll(1, "units")
            self.disegna()

    def _rilascia(self, e):
        t, self.trascino = self.trascino, None
        self.canvas.config(cursor="")
        if t and t["attivo"] and t["dest"] is not None:
            scelte = sorted(self.sel)
            pezzi = [self.ordine[i] for i in scelte]
            dest = t["dest"] - sum(1 for i in scelte if i < t["dest"])
            resto = [p for i, p in enumerate(self.ordine) if i not in self.sel]
            self.ordine = resto[:dest] + pezzi + resto[dest:]
            self.sel = set(range(dest, dest + len(pezzi)))
            self.ancora = dest
        elif t and not t["attivo"] and t["pos"] is not None and not (e.state & 0x5):
            self.sel = {t["pos"]}
        self.disegna()

    def _tutte(self):
        self.sel = set(range(len(self.ordine)))
        self.disegna()

    def ruota(self, gradi):
        bersaglio = self.sel or set(range(len(self.ordine)))
        for i in bersaglio:
            self.ordine[i][1] = (self.ordine[i][1] + gradi) % 360
        self.disegna()

    def elimina(self):
        if not self.sel or len(self.sel) >= len(self.ordine):
            return                                   # un PDF deve avere almeno una pagina
        self.ordine = [p for i, p in enumerate(self.ordine) if i not in self.sel]
        self.sel.clear()
        self.disegna()

    def salva(self):
        if [tuple(p) for p in self.ordine] != [(i, 0) for i in range(self.n)]:
            self.risultato = [tuple(p) for p in self.ordine]
        self.root.destroy()


# ===================================================================== password
def chiedi_password(titolo, testo, conferma=False):
    root, k = finestra(titolo)
    pad = int(16 * k)
    esito = {"pw": None}
    etichetta(root, testo, k, FG, 10, wraplength=int(380 * k), justify="left").pack(anchor="w", padx=pad, pady=(pad, int(10 * k)))
    e1 = campo(root, k, 34, show="•")
    e1.pack(anchor="w", padx=pad, ipady=int(3 * k))
    e2 = None
    if conferma:
        etichetta(root, "Ripeti la password", k).pack(anchor="w", padx=pad, pady=(int(10 * k), int(4 * k)))
        e2 = campo(root, k, 34, show="•")
        e2.pack(anchor="w", padx=pad, ipady=int(3 * k))
    avviso = etichetta(root, "", k, ERRORE)
    avviso.pack(anchor="w", padx=pad, pady=(int(6 * k), 0))

    def ok():
        p = e1.get()
        if not p:
            avviso.config(text="Scrivi una password.")
            return
        if e2 is not None and p != e2.get():
            avviso.config(text="Le due password non coincidono.")
            return
        esito["pw"] = p
        root.destroy()

    giu, _ = pulsanti(root, k, "OK", ok, root.destroy)
    giu.pack(fill="x", padx=pad, pady=pad)
    root.bind("<Return>", lambda e: ok())
    root.bind("<Escape>", lambda e: root.destroy())
    mostra(root)
    root.attributes("-topmost", True)
    e1.focus_set()
    root.mainloop()
    return esito["pw"]


def chiedi_blocco(nome, cartella=False):
    """Password per bloccare file o cartelle. Restituisce la password o None."""
    root, k = finestra("Blocca con password")
    pad = int(16 * k)
    L = int(400 * k)
    esito = {"v": None}
    etichetta(root, f"Blocca «{nome}»", k, FG, 11, True, wraplength=L, justify="left").pack(
        anchor="w", padx=pad, pady=(pad, int(4 * k)))
    cosa = "la cartella" if cartella else "il file"
    etichetta(root, f"Al suo posto resta un collegamento con lo stesso nome: il doppio clic chiede la password "
                    f"e poi apre {cosa}. Intanto Sottomano lo custodisce bloccato nella sua cartella.",
              k, wraplength=L, justify="left").pack(anchor="w", padx=pad, pady=(0, int(12 * k)))
    etichetta(root, "Password", k).pack(anchor="w", padx=pad, pady=(0, int(4 * k)))
    e1 = campo(root, k, 34, show="•")
    e1.pack(anchor="w", padx=pad, ipady=int(3 * k))
    etichetta(root, "Ripeti la password", k).pack(anchor="w", padx=pad, pady=(int(10 * k), int(4 * k)))
    e2 = campo(root, k, 34, show="•")
    e2.pack(anchor="w", padx=pad, ipady=int(3 * k))
    etichetta(root, "Quando lo chiudi si riblocca da solo.\n"
                    "Non dimenticare la password: senza, Sottomano non lo sblocca e non si può disinstallare.",
              k, "#ffd479", wraplength=L, justify="left").pack(anchor="w", padx=pad, pady=(int(12 * k), 0))
    avviso = etichetta(root, "", k, ERRORE)
    avviso.pack(anchor="w", padx=pad, pady=(int(4 * k), 0))

    def ok():
        p = e1.get()
        if len(p) < 4:
            avviso.config(text="Usa almeno 4 caratteri.")
            return
        if p != e2.get():
            avviso.config(text="Le due password non coincidono.")
            return
        esito["v"] = p
        root.destroy()

    giu, _ = pulsanti(root, k, "Blocca", ok, root.destroy)
    giu.pack(fill="x", padx=pad, pady=pad)
    root.bind("<Return>", lambda e: ok())
    root.bind("<Escape>", lambda e: root.destroy())
    mostra(root)
    root.attributes("-topmost", True)
    e1.focus_set()
    root.mainloop()
    return esito["v"]


# ============================================================ unisci immagini
def collage(immagini, modo, spazio, sfondo, lato):
    """immagini: lista di PIL gia' caricate (anche ridotte). lato: dimensione di riferimento."""
    from PIL import Image
    import math
    imgs = [im.convert("RGBA") if im.mode in ("RGBA", "LA", "P") else im.convert("RGB") for im in immagini]
    colore = (255, 255, 255) if sfondo == "bianco" else (0, 0, 0)
    n = len(imgs)
    if modo == "verticale":
        W = min(lato, sorted(im.width for im in imgs)[n // 2])
        parti = [im.resize((W, max(round(im.height * W / im.width), 1)), Image.LANCZOS) for im in imgs]
        H = sum(p.height for p in parti) + spazio * (n + 1 if spazio else 0)
        tela = Image.new("RGB", (W + 2 * spazio, H), colore)
        y = spazio
        for p in parti:
            tela.paste(p, (spazio, y), p if p.mode == "RGBA" else None)
            y += p.height + spazio
        return tela
    if modo == "orizzontale":
        Hh = min(lato, sorted(im.height for im in imgs)[n // 2])
        parti = [im.resize((max(round(im.width * Hh / im.height), 1), Hh), Image.LANCZOS) for im in imgs]
        W = sum(p.width for p in parti) + spazio * (n + 1 if spazio else 0)
        tela = Image.new("RGB", (W, Hh + 2 * spazio), colore)
        x = spazio
        for p in parti:
            tela.paste(p, (x, spazio), p if p.mode == "RGBA" else None)
            x += p.width + spazio
        return tela
    # griglia: celle uguali, ogni foto intera e centrata nella sua cella
    col = math.ceil(math.sqrt(n))
    righe = math.ceil(n / col)
    cw = min(lato, sorted(im.width for im in imgs)[n // 2])
    ch = round(cw * sorted(im.height / im.width for im in imgs)[n // 2])
    tela = Image.new("RGB", (col * cw + (col + 1) * spazio, righe * ch + (righe + 1) * spazio), colore)
    for i, im in enumerate(imgs):
        p = im.copy()
        p.thumbnail((cw, ch), Image.LANCZOS)
        if p.width < cw and p.height < ch:
            s = min(cw / p.width, ch / p.height)
            p = im.resize((max(int(im.width * s), 1), max(int(im.height * s), 1)), Image.LANCZOS)
        r, c = divmod(i, col)
        x = spazio + c * (cw + spazio) + (cw - p.width) // 2
        y = spazio + r * (ch + spazio) + (ch - p.height) // 2
        tela.paste(p, (x, y), p if p.mode == "RGBA" else None)
    return tela


def scegli_collage(files):
    """Finestra con anteprima. Restituisce (modo, spazio_relativo, sfondo) o None."""
    from PIL import ImageTk
    root, k = finestra("Unisci immagini")
    pad = int(16 * k)
    esito = {"v": None}
    piccole = []
    for f in files[:60]:
        try:
            piccole.append(_miniatura(f, 360))
        except Exception:
            pass

    corpo = tk.Frame(root, bg=BG)
    corpo.pack(padx=pad, pady=(pad, 0), fill="both", expand=True)
    sx = tk.Frame(corpo, bg=BG)
    sx.pack(side="left", fill="y", padx=(0, pad))
    etichetta(sx, f"{len(files)} immagini", k, FG, 11, True).pack(anchor="w")
    etichetta(sx, "Disposizione", k).pack(anchor="w", pady=(int(12 * k), int(4 * k)))
    modo = Scelta(sx, k, [("Verticale", "verticale"), ("Orizzontale", "orizzontale"), ("Griglia", "griglia")],
                  "verticale", lambda v: aggiorna()).pack(anchor="w")
    etichetta(sx, "Spazio tra le foto", k).pack(anchor="w", pady=(int(12 * k), int(4 * k)))
    spazio = Scelta(sx, k, [("Nessuno", 0), ("Sottile", 1), ("Largo", 3)], 0, lambda v: aggiorna()).pack(anchor="w")
    etichetta(sx, "Sfondo", k).pack(anchor="w", pady=(int(12 * k), int(4 * k)))
    sfondo = Scelta(sx, k, [("Bianco", "bianco"), ("Nero", "nero")], "bianco", lambda v: aggiorna()).pack(anchor="w")
    etichetta(sx, "L'ordine è quello dei nomi dei file.", k, dim=8).pack(anchor="w", pady=(int(16 * k), 0))
    lato_prev = int(360 * k)
    box_prev, tela = riquadro(corpo, lato_prev, lato_prev)
    box_prev.pack(side="left")
    rif = {}

    def aggiorna():
        if not piccole:
            return
        sp = spazio.valore * 6
        im = collage(piccole, modo.valore, sp, sfondo.valore, 360)
        im.thumbnail((lato_prev - int(16 * k), lato_prev - int(16 * k)))
        rif["foto"] = ImageTk.PhotoImage(im)
        tela.config(image=rif["foto"])

    def conferma():
        esito["v"] = (modo.valore, spazio.valore, sfondo.valore)
        root.destroy()

    giu, _ = pulsanti(root, k, "Crea immagine", conferma, root.destroy)
    giu.pack(fill="x", padx=pad, pady=pad)
    root.bind("<Return>", lambda e: conferma())
    root.bind("<Escape>", lambda e: root.destroy())
    aggiorna()
    mostra(root)
    root.mainloop()
    return esito["v"]


# ================================================================ taglia video
def _mmss(t, decimi=True):
    t = max(t, 0)
    m, s = divmod(t, 60)
    return f"{int(m):02d}:{s:04.1f}" if decimi else f"{int(m):02d}:{int(s):02d}"


class EditorTaglio:
    """Due maniglie sulla barra del tempo: inizio e fine. Trascinandole vedi il fotogramma."""

    def __init__(self, nome, durata, fotogramma=None):
        self.durata = max(durata, 0.1)
        self.inizio, self.fine = 0.0, self.durata
        self.fotogramma = fotogramma
        self.attiva = "inizio"
        self.risultato = None
        self._gen = 0
        self.root, k = finestra(f"Taglia - {nome}")
        self.k = k
        pad = int(16 * k)
        self.pw, self.ph = int(640 * k), int(360 * k)
        if fotogramma:
            box, self.schermo = riquadro(self.root, self.pw, self.ph, "#000000")
            box.pack(padx=pad, pady=(pad, 0))
        else:
            etichetta(self.root, nome, k, FG, 11, True).pack(anchor="w", padx=pad, pady=(pad, 0))
        self.tela = tk.Canvas(self.root, height=int(56 * k), bg=BG, highlightthickness=0, bd=0, cursor="hand2")
        self.tela.pack(fill="x", padx=pad, pady=(int(12 * k), 0))
        self.tela.bind("<Configure>", lambda e: self.disegna())
        self.tela.bind("<Button-1>", self._premi)
        self.tela.bind("<B1-Motion>", self._trascina)
        self.tela.bind("<ButtonRelease-1>", lambda e: self._carica())
        self.tempi = etichetta(self.root, "", k, FG, 10)
        self.tempi.pack(pady=(int(4 * k), 0))
        riga = tk.Frame(self.root, bg=BG)
        riga.pack(fill="x", padx=pad, pady=(int(12 * k), 0))
        etichetta(riga, "Taglio", k).pack(side="left", padx=(0, int(8 * k)))
        self.modo = Scelta(riga, k, [("Veloce, senza perdita", "veloce"), ("Preciso al decimo di secondo", "preciso")],
                           "veloce", lambda v: self._nota()).pack(side="left")
        self.nota = etichetta(self.root, "", k, dim=8, wraplength=int(620 * k), justify="left")
        self.nota.pack(anchor="w", padx=pad, pady=(int(6 * k), 0))
        giu, _ = pulsanti(self.root, k, "Taglia", self.conferma, self.root.destroy)
        giu.pack(fill="x", padx=pad, pady=pad)
        etichetta(giu, "←/→ sposta la maniglia di 0,1 s (Maiusc: 1 s)", k, dim=8).pack(side="left")
        self.root.bind("<Return>", lambda e: self.conferma())
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.root.bind("<Left>", lambda e: self._sposta(-1.0 if e.state & 1 else -0.1))
        self.root.bind("<Right>", lambda e: self._sposta(1.0 if e.state & 1 else 0.1))
        self._nota()
        mostra(self.root, w=self.pw + 2 * pad)
        self._carica()
        self.root.mainloop()

    def _nota(self):
        if self.modo.valore == "veloce":
            self.nota.config(text="Istantaneo e senza perdita di qualità. L'inizio può anticipare di qualche "
                                  "frazione di secondo (il video si può tagliare solo sui fotogrammi chiave).")
        else:
            self.nota.config(text="Taglia esattamente dove hai scelto. Ricodifica il video: più lento.")

    def _zone(self):
        w = self.tela.winfo_width()
        m = int(14 * self.k)
        return m, max(w - m, m + 1), int(28 * self.k)

    def _x(self, t):
        x0, x1, _ = self._zone()
        return x0 + (x1 - x0) * t / self.durata

    def _t(self, x):
        x0, x1, _ = self._zone()
        return min(max((x - x0) / (x1 - x0), 0), 1) * self.durata

    def disegna(self):
        c, k = self.tela, self.k
        c.delete("all")
        x0, x1, cy = self._zone()
        sp = int(8 * k)
        c.create_rectangle(x0, cy - sp // 2, x1, cy + sp // 2, fill="#3d3d3d", outline="")
        a, b = self._x(self.inizio), self._x(self.fine)
        c.create_rectangle(a, cy - sp // 2, b, cy + sp // 2, fill=ACCENTO, outline="")
        for t, nome in ((self.inizio, "inizio"), (self.fine, "fine")):
            x = self._x(t)
            col = "#ffffff" if nome == self.attiva else "#cfcfcf"
            hw, hh = int(5 * k), int(14 * k)
            c.create_rectangle(x - hw, cy - hh, x + hw, cy + hh, fill=col, outline="")
            c.create_image(x, cy - hh, image=pallino(hw * 2, col))
            c.create_image(x, cy + hh, image=pallino(hw * 2, col))
        c.create_text(x0, cy + int(24 * k), text="00:00", fill=SUB, anchor="w", font=("Segoe UI", 8))
        c.create_text(x1, cy + int(24 * k), text=_mmss(self.durata, False), fill=SUB, anchor="e", font=("Segoe UI", 8))
        self.tempi.config(text=f"Inizio {_mmss(self.inizio)}     ·     Fine {_mmss(self.fine)}     ·     "
                               f"Durata {_mmss(self.fine - self.inizio)}")

    def _premi(self, e):
        t = self._t(e.x)
        self.attiva = "inizio" if abs(t - self.inizio) <= abs(t - self.fine) else "fine"
        self._imposta(t)

    def _trascina(self, e):
        self._imposta(self._t(e.x), carica=False)

    def _imposta(self, t, carica=True):
        minimo = min(0.2, self.durata / 2)
        if self.attiva == "inizio":
            self.inizio = min(max(t, 0), self.fine - minimo)
        else:
            self.fine = max(min(t, self.durata), self.inizio + minimo)
        self.disegna()
        if carica:
            self._carica()
        else:
            self._programma()

    def _sposta(self, dt):
        self._imposta((self.inizio if self.attiva == "inizio" else self.fine) + dt)

    def _programma(self):
        if getattr(self, "_job", None):
            self.root.after_cancel(self._job)
        self._job = self.root.after(140, self._carica)

    def _carica(self):
        """Fotogramma della maniglia attiva, letto in un thread: la finestra non si blocca mai."""
        self._job = None
        if not self.fotogramma:
            return
        self._gen += 1
        gen = self._gen
        t = self.inizio if self.attiva == "inizio" else max(self.fine - 0.05, 0)

        def lavoro():
            try:
                im = self.fotogramma(t, self.pw, self.ph)
            except Exception:
                im = None
            try:
                self.root.after(0, self._mostra, gen, im)
            except Exception:
                pass
        threading.Thread(target=lavoro, daemon=True).start()

    def _mostra(self, gen, im):
        if gen != self._gen or im is None:
            return
        from PIL import ImageTk
        im.thumbnail((self.pw, self.ph))
        self._foto = ImageTk.PhotoImage(im)
        self.schermo.config(image=self._foto)

    def conferma(self):
        self.risultato = (round(self.inizio, 2), round(self.fine, 2), self.modo.valore == "preciso")
        self.root.destroy()


# ================================================== zona dello schermo (Ctrl+Alt+T)
def scegli_zona():
    """Schermo 'congelato' e scurito: trascini un rettangolo, restituisce l'immagine di quella zona."""
    from PIL import ImageGrab, ImageEnhance, ImageTk
    import ctypes
    try:
        u = ctypes.windll.user32
        vx, vy, vw, vh = u.GetSystemMetrics(76), u.GetSystemMetrics(77), u.GetSystemMetrics(78), u.GetSystemMetrics(79)
    except Exception:
        vx = vy = 0
        vw = vh = None
    schermo = ImageGrab.grab(all_screens=True).convert("RGB")
    if not vw:
        vw, vh = schermo.size
    scuro = ImageEnhance.Brightness(schermo).enhance(0.45)
    root = radice()
    root.withdraw()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.geometry(f"{vw}x{vh}+{vx}+{vy}")
    k = max(root.winfo_fpixels("1i") / 96.0, 1.0)
    c = tk.Canvas(root, width=vw, height=vh, highlightthickness=0, bd=0, cursor="crosshair", bg="#000000")
    c.pack()
    rif = {"sfondo": ImageTk.PhotoImage(scuro), "chiaro": None}
    c.create_image(0, 0, image=rif["sfondo"], anchor="nw")
    # istruzioni al centro dello schermo principale
    px = -vx + (root.winfo_screenwidth() // 2)
    py = -vy + int(60 * k)
    c.create_rectangle(px - int(260 * k), py - int(22 * k), px + int(260 * k), py + int(22 * k), fill="#1b1b1b", outline="#3a3a3a")
    c.create_text(px, py, text="Trascina per scegliere la zona da leggere  ·  Esc per annullare",
                  fill=FG, font=("Segoe UI", 11))
    stato = {"a": None, "b": None, "esito": None, "ultimo": 0}

    def disegna_sel():
        c.delete("sel")
        if not stato["a"] or not stato["b"]:
            return
        (x0, y0), (x1, y1) = stato["a"], stato["b"]
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        if x1 - x0 < 2 or y1 - y0 < 2:
            return
        rif["chiaro"] = ImageTk.PhotoImage(schermo.crop((x0, y0, x1, y1)))
        c.create_image(x0, y0, image=rif["chiaro"], anchor="nw", tags="sel")
        c.create_rectangle(x0, y0, x1, y1, outline=ACCENTO, width=max(int(2 * k), 1), tags="sel")

    def premi(e):
        stato["a"] = stato["b"] = (e.x, e.y)

    def muovi(e):
        import time
        stato["b"] = (e.x, e.y)
        if time.monotonic() - stato["ultimo"] > 0.025:   # max ~40 aggiornamenti al secondo
            stato["ultimo"] = time.monotonic()
            disegna_sel()

    def rilascia(e):
        stato["b"] = (e.x, e.y)
        (x0, y0), (x1, y1) = stato["a"], stato["b"]
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        if x1 - x0 >= 6 and y1 - y0 >= 6:
            stato["esito"] = schermo.crop((x0, y0, x1, y1))
            root.destroy()
        else:
            stato["a"] = stato["b"] = None
            disegna_sel()

    c.bind("<Button-1>", premi)
    c.bind("<B1-Motion>", muovi)
    c.bind("<ButtonRelease-1>", rilascia)
    root.bind("<Escape>", lambda e: root.destroy())
    c.bind("<Button-3>", lambda e: root.destroy())
    root.deiconify()
    root.after(30, lambda: (root.focus_force(), root.lift()))
    root.mainloop()
    return stato["esito"]


# ======================================================================= duplicati
def _dhash(path):
    """Impronta della foto (64 bit): foto uguali ma ridimensionate/ricompresse hanno impronte vicine."""
    from PIL import Image
    im = _miniatura(path, 64).convert("L").resize((9, 8), Image.LANCZOS)
    px = im.tobytes()
    h = 0
    for y in range(8):
        for x in range(8):
            h = (h << 1) | (px[y * 9 + x] > px[y * 9 + x + 1])
    return h


def cerca_duplicati(cartella, avanzamento=lambda testo: None, fermo=lambda: False):
    """Gruppi di file identici (stesso contenuto) e di foto simili.
    Restituisce [(tipo, [percorsi])], tipo = 'identici' | 'simili'."""
    import hashlib
    per_dim = {}
    n = 0
    for radice_, cartelle, nomi in os.walk(cartella):
        cartelle[:] = [d for d in cartelle if not d.startswith((".", "$")) and d not in ("node_modules", "__pycache__")]
        for nome in nomi:
            p = os.path.join(radice_, nome)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if st.st_size == 0 or nome.endswith(".in-corso"):
                continue
            per_dim.setdefault(st.st_size, []).append(p)
            n += 1
            if n % 500 == 0:
                avanzamento(f"Leggo i file... {n}")
            if fermo():
                return []

    def impronta(p, tutto):
        h = hashlib.blake2b(digest_size=20)
        with open(p, "rb") as fh:
            if tutto:
                for blocco in iter(lambda: fh.read(1 << 20), b""):
                    h.update(blocco)
            else:
                h.update(fh.read(65536))
        return h.digest()

    gruppi = []
    in_gruppo = set()
    candidati = [v for v in per_dim.values() if len(v) > 1]
    for i, stessi in enumerate(candidati):
        if fermo():
            return []
        if i % 50 == 0:
            avanzamento(f"Confronto i contenuti... {i}/{len(candidati)}")
        primo = {}
        for p in stessi:
            try:
                primo.setdefault(impronta(p, False), []).append(p)
            except OSError:
                pass
        for sotto in primo.values():
            if len(sotto) < 2:
                continue
            pieno = {}
            for p in sotto:
                try:
                    pieno.setdefault(impronta(p, True), []).append(p)
                except OSError:
                    pass
            for uguali in pieno.values():
                if len(uguali) > 1:
                    gruppi.append(("identici", sorted(uguali, key=lambda q: (os.path.getmtime(q), len(q)))))
                    in_gruppo.update(uguali)

    # foto simili (non identiche): confronto delle impronte visive
    foto = [p for v in per_dim.values() for p in v
            if Path(p).suffix.lower() in IMG_EXT and p not in in_gruppo]
    impronte = []
    for i, p in enumerate(foto):
        if fermo():
            return []
        if i % 25 == 0:
            avanzamento(f"Confronto le foto... {i}/{len(foto)}")
        try:
            impronte.append((p, _dhash(p)))
        except Exception:
            pass
    padre = list(range(len(impronte)))

    def trova(i):
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i
    for i in range(len(impronte)):
        hi = impronte[i][1]
        for j in range(i + 1, len(impronte)):
            if (hi ^ impronte[j][1]).bit_count() <= 5:
                padre[trova(j)] = trova(i)
    simili = {}
    for i, (p, _) in enumerate(impronte):
        simili.setdefault(trova(i), []).append(p)
    for g in simili.values():
        if len(g) > 1:
            gruppi.append(("simili", sorted(g, key=lambda q: -os.path.getsize(q))))
    return gruppi


def _mb(n):
    if n < 1024:
        return f"{n} byte"
    return f"{n / 1048576:.1f} MB".replace(".", ",") if n >= 104858 else f"{n / 1024:.0f} KB"


def duplicati(cartella, al_cestino):
    """Cerca (in un thread, con avanzamento) e mostra i gruppi. al_cestino(lista) sposta nel Cestino."""
    from PIL import ImageTk
    root, k = finestra(f"Duplicati - {Path(cartella).name}")
    pad = int(16 * k)
    stato = {"gruppi": None, "fermo": False, "testo": "Leggo i file..."}
    titolo = etichetta(root, f"Cerco duplicati in «{Path(cartella).name}»", k, FG, 11, True)
    titolo.pack(anchor="w", padx=pad, pady=(pad, int(4 * k)))
    sotto = etichetta(root, "Comprese le sottocartelle. Può volerci un po' con molti file.", k)
    sotto.pack(anchor="w", padx=pad)
    corpo = tk.Frame(root, bg=BG)
    corpo.pack(fill="both", expand=True, padx=pad, pady=(int(10 * k), 0))
    avanz = etichetta(corpo, stato["testo"], k, FG, 10)
    avanz.pack(pady=int(40 * k))
    giu = tk.Frame(root, bg=BG)
    giu.pack(fill="x", padx=pad, pady=pad)

    def chiudi():
        stato["fermo"] = True
        root.destroy()
    Chip(giu, "Chiudi", chiudi, k).pack(side="right")
    root.bind("<Escape>", lambda e: chiudi())
    root.protocol("WM_DELETE_WINDOW", chiudi)

    def lavoro():
        try:
            stato["gruppi"] = cerca_duplicati(cartella, lambda t: stato.update(testo=t), lambda: stato["fermo"])
        except Exception as e:
            stato["gruppi"] = e

    threading.Thread(target=lavoro, daemon=True).start()

    def controlla():
        if stato["fermo"]:
            return
        if stato["gruppi"] is None:
            avanz.config(text=stato["testo"])
            root.after(150, controlla)
        else:
            risultati(stato["gruppi"])

    scelte = {}
    foto_rif = []

    def risultati(gruppi):
        for w in corpo.winfo_children():
            w.destroy()
        if isinstance(gruppi, Exception):
            etichetta(corpo, f"Errore: {gruppi}", k, ERRORE).pack(pady=int(40 * k))
            return
        if not gruppi:
            titolo.config(text="Nessun duplicato trovato")
            sotto.config(text=f"In «{Path(cartella).name}» e nelle sue sottocartelle ogni file è unico.")
            return
        n_id = sum(1 for t, _ in gruppi if t == "identici")
        n_si = len(gruppi) - n_id
        parti = []
        if n_id:
            parti.append("1 gruppo di file identici" if n_id == 1 else f"{n_id} gruppi di file identici")
        if n_si:
            parti.append("1 gruppo di foto simili" if n_si == 1 else f"{n_si} gruppi di foto simili")
        titolo.config(text="Trovati: " + " e ".join(parti))
        sotto.config(text="Già spuntati: le copie in più dei file identici (resta il più vecchio). "
                          "Le foto simili decidi tu.")
        lista = Scorrevole(corpo, k)
        lista.pack(fill="both", expand=True)
        for gi, (tipo, percorsi) in enumerate(gruppi[:400]):
            box = tk.Frame(lista.dentro, bg=BARRA)
            box.pack(fill="x", pady=(0, int(8 * k)))
            try:
                dim = os.path.getsize(percorsi[0])
            except OSError:
                dim = 0
            intest = f"Identici · {len(percorsi)} file · {_mb(dim)} ciascuno" if tipo == "identici" \
                else f"Foto simili · {len(percorsi)} file"
            tk.Label(box, text=intest, bg=BARRA, fg=ACCENTO if tipo == "identici" else "#ffd479",
                     font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=int(10 * k), pady=(int(6 * k), int(2 * k)))
            for i, p in enumerate(percorsi):
                riga = tk.Frame(box, bg=BARRA)
                riga.pack(fill="x", padx=int(10 * k), pady=int(2 * k))
                v = tk.BooleanVar(value=(tipo == "identici" and i > 0))
                scelte[p] = v
                tk.Checkbutton(riga, variable=v, bg=BARRA, activebackground=BARRA, selectcolor=CHIP, fg=FG,
                               activeforeground=FG, bd=0, highlightthickness=0, command=riepilogo).pack(side="left")
                if Path(p).suffix.lower() in IMG_EXT:
                    try:
                        f = ImageTk.PhotoImage(_miniatura(p, int(44 * k)))
                        foto_rif.append(f)
                        tk.Label(riga, image=f, bg=BARRA).pack(side="left", padx=(0, int(8 * k)))
                    except Exception:
                        pass
                rel = os.path.relpath(p, cartella)
                try:
                    import datetime
                    info = f"{_mb(os.path.getsize(p))} · {datetime.datetime.fromtimestamp(os.path.getmtime(p)):%d/%m/%Y}"
                except OSError:
                    info = ""
                nome = tk.Label(riga, text=rel, bg=BARRA, fg=FG, font=("Segoe UI", 9), anchor="w", cursor="hand2")
                nome.pack(side="left", fill="x", expand=True)
                nome.bind("<Double-Button-1>", lambda e, p=p: _apri(p))
                tk.Label(riga, text=info, bg=BARRA, fg=SUB, font=("Segoe UI", 8)).pack(side="right")
            tk.Frame(box, bg=BARRA, height=int(6 * k)).pack()
        for w in giu.winfo_children():
            w.destroy()
        Chip(giu, "Chiudi", chiudi, k).pack(side="right")
        Chip(giu, "Sposta nel Cestino", cestina, k, primario=True).pack(side="right", padx=int(6 * k))
        rif["info"] = etichetta(giu, "", k, FG)
        rif["info"].pack(side="left")
        etichetta(giu, "   ·   doppio clic su un nome per aprirlo", k, dim=8).pack(side="left")
        riepilogo()

    rif = {}

    def riepilogo():
        if "info" not in rif:
            return
        sel = [p for p, v in scelte.items() if v.get()]
        tot = sum(os.path.getsize(p) for p in sel if os.path.exists(p))
        rif["info"].config(text=f"Selezionati {len(sel)} file · {_mb(tot)}" if sel else "Nessun file selezionato")

    def cestina():
        sel = [p for p, v in scelte.items() if v.get() and os.path.exists(p)]
        if not sel:
            return
        al_cestino(sel)
        for p in sel:
            scelte[p].set(False)
        titolo.config(text=f"Spostati nel Cestino {len(sel)} file")
        sotto.config(text="Se ti servono ancora, li recuperi dal Cestino.")
        root.after(1200, root.destroy)

    def _apri(p):
        try:
            os.startfile(p)
        except Exception:
            pass

    mostra(root, int(760 * k), int(620 * k), ridimensionabile=True)
    root.after(100, controlla)
    root.mainloop()


# ===================================================================== elementi bloccati
def elenco_bloccati(leggi_voci, apri, completo, ricrea):
    """Tutti gli elementi bloccati con Sottomano, anche se ne hai cancellato il collegamento."""
    import os as _os
    root, k = finestra("Elementi bloccati")
    pad = int(16 * k)
    etichetta(root, "Elementi bloccati con Sottomano", k, FG, 11, True).pack(anchor="w", padx=pad, pady=(pad, int(2 * k)))
    etichetta(root, "Anche se cancelli un collegamento per sbaglio, l'elemento resta qui al sicuro.", k).pack(
        anchor="w", padx=pad)
    corpo = tk.Frame(root, bg=BG)
    corpo.pack(fill="both", expand=True, padx=pad, pady=(int(10 * k), 0))
    giu = tk.Frame(root, bg=BG)
    giu.pack(fill="x", padx=pad, pady=pad)
    Chip(giu, "Chiudi", root.destroy, k).pack(side="right")
    root.bind("<Escape>", lambda e: root.destroy())

    def esegui(azione, v):
        try:
            azione(v)
        except Exception as e:
            etichetta(corpo, f"Errore: {e}", k, ERRORE).pack(anchor="w")
        try:
            disegna()
        except tk.TclError:
            pass

    def disegna():
        for w in corpo.winfo_children():
            w.destroy()
        voci = leggi_voci()
        if not voci:
            etichetta(corpo, "Nessun elemento bloccato.", k, FG, 10).pack(pady=int(30 * k))
            return
        lista = Scorrevole(corpo, k)
        lista.pack(fill="both", expand=True)
        for v in sorted(voci, key=lambda x: Path(x.get("origine") or x["percorso"]).name.lower()):
            dove = Path(v.get("origine") or v["percorso"])
            riga = tk.Frame(lista.dentro, bg=BARRA)
            riga.pack(fill="x", pady=(0, int(6 * k)))
            sx = tk.Frame(riga, bg=BARRA)
            sx.pack(side="left", fill="x", expand=True, padx=int(12 * k), pady=int(8 * k))
            stato = "Bloccato" if v["stato"] == "bloccato" else "Aperto (si richiude quando lo chiudi)"
            tk.Label(sx, text=dove.name, bg=BARRA, fg=FG,
                     font=("Segoe UI", 10, "bold"), anchor="w").pack(anchor="w")
            tipo = "Cartella" if v.get("cartella") else "File"
            tk.Label(sx, text=f"{tipo}  ·  {stato}  ·  in {dove.parent}", bg=BARRA, fg=SUB, font=("Segoe UI", 8),
                     anchor="w").pack(anchor="w")
            dx = tk.Frame(riga, bg=BARRA)
            dx.pack(side="right", padx=int(10 * k))
            Chip(dx, "Sblocco completo", lambda v=v: esegui(completo, v), k).pack(side="right", padx=int(3 * k))
            Chip(dx, "Apri", lambda v=v: esegui(apri, v), k, primario=True).pack(side="right", padx=int(3 * k))
            if v.get("origine") and not _os.path.exists(v.get("collegamento", "")):
                Chip(dx, "Rimetti il collegamento", lambda v=v: esegui(ricrea, v), k).pack(side="right", padx=int(3 * k))

    disegna()
    mostra(root, int(720 * k), int(460 * k), ridimensionabile=True)
    root.mainloop()
