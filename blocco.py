# -*- coding: utf-8 -*-
# Sottomano - blocco con password di file e cartelle.
# Copyright (C) 2026 Tommaso Pelosin - Licenza AGPL-3.0 (vedi LICENSE)
#
# L'elemento vero va in una cartella di Sottomano ("bloccati") e al suo posto resta un collegamento
# con lo stesso nome e la stessa icona: il doppio clic chiede la password e poi apre l'elemento vero.
# In piu', l'elemento vero ha nei permessi (NTFS) una regola "Nega" per tutti: Windows non lo lascia
# aprire, leggere, modificare, spostare ne' eliminare. Con la password giusta Sottomano toglie la regola.
#
# Le password NON vengono salvate: in bloccati.json c'e' solo un'impronta (PBKDF2-SHA256,
# 200.000 passaggi) che serve a controllare se la password scritta e' giusta.
#
# Importante: e' un blocco, non una cifratura. Ferma chi usa il PC normalmente (doppio clic,
# anteprime, copia), ma chi e' amministratore del PC ed esperto di permessi puo' toglierlo.

import os
import json
import time
import hashlib
import secrets
from pathlib import Path

BASE = Path(__file__).resolve().parent
REGISTRO = BASE / "bloccati.json"
ITERAZIONI = 200_000
# leggere / elencare (0x1), scrivere / aggiungere file (0x2), aggiungere dati / sottocartelle (0x4),
# eseguire / attraversare (0x20), eliminare il contenuto (0x40), eliminare / rinominare / spostare (0x10000)
MASCHERA = 0x10067
TUTTI = "S-1-1-0"          # il gruppo "Everyone" (Tutti), in qualsiasi lingua di Windows


class Errore(Exception):
    pass


# ------------------------------------------------------------------ registro
def chiave(p):
    return os.path.normcase(os.path.abspath(str(p)))


def leggi():
    for f in (REGISTRO, REGISTRO.with_suffix(".bak")):
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except ValueError:
            continue           # file rovinato: provo la copia di sicurezza
    return {}


def scrivi(reg):
    tmp = REGISTRO.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    if REGISTRO.exists():
        try:
            os.replace(REGISTRO, REGISTRO.with_suffix(".bak"))     # copia di sicurezza
        except OSError:
            pass
    os.replace(tmp, REGISTRO)


def _impronta(password, sale):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(sale), ITERAZIONI).hex()


def stato(p, reg=None):
    """'bloccato', 'aperto' (sblocco parziale: si richiude da solo quando lo chiudi) oppure None."""
    reg = reg if reg is not None else leggi()
    k = _trova(reg, p)
    return reg[k]["stato"] if k else None


def password_giusta(p, password, reg=None):
    reg = reg if reg is not None else leggi()
    k = _trova(reg, p)
    v = reg[k] if k else None
    return bool(v) and secrets.compare_digest(_impronta(password, v["sale"]), v["impronta"])


def elementi(reg=None):
    """[(percorso, stato)] di tutto cio' che Sottomano sta proteggendo."""
    reg = reg if reg is not None else leggi()
    return [(v["percorso"], v["stato"]) for v in reg.values()]


# ---------------------------------------------------------------- permessi
if os.name == "nt":
    def _cambia(path, blocca):
        """Aggiunge (o toglie) la regola 'Nega a Tutti' in cima ai permessi dell'elemento."""
        import win32security as ws
        sd = ws.GetFileSecurity(path, ws.DACL_SECURITY_INFORMATION)
        vecchia = sd.GetSecurityDescriptorDacl()
        tutti = ws.ConvertStringSidToSid(TUTTI)
        nuova = ws.ACL()
        if blocca:
            nuova.AddAccessDeniedAceEx(ws.ACL_REVISION, 0, MASCHERA, tutti)   # i "Nega" vanno per primi
        if vecchia is None:            # nessuna lista = accesso libero: lo rendo esplicito
            nuova.AddAccessAllowedAceEx(ws.ACL_REVISION, 0, 0x1F01FF, tutti)
        else:
            for i in range(vecchia.GetAceCount()):
                ace = vecchia.GetAce(i)
                (tipo, flag), maschera, sid = ace[0], ace[1], ace[2]
                if tipo == 1 and maschera == MASCHERA and sid == tutti and not flag & 0x10:
                    continue           # la nostra regola (gia' presente): non la duplico / la tolgo
                if tipo == 0:
                    nuova.AddAccessAllowedAceEx(ws.ACL_REVISION, flag, maschera, sid)
                elif tipo == 1:
                    nuova.AddAccessDeniedAceEx(ws.ACL_REVISION, flag, maschera, sid)
                else:
                    raise Errore(f"«{Path(path).name}» ha permessi speciali che Sottomano non sa gestire.")
        sd.SetSecurityDescriptorDacl(1, nuova, 0)
        ws.SetFileSecurity(path, ws.DACL_SECURITY_INFORMATION, sd)

    def supporta_permessi(path):
        """Il blocco funziona solo sui dischi NTFS (non sulle chiavette FAT32/exFAT)."""
        import win32api
        radice = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
        try:
            return bool(win32api.GetVolumeInformation(radice)[3] & 0x8)   # FILE_PERSISTENT_ACLS
        except Exception:
            return False
else:                                  # solo per provare la logica fuori da Windows
    def _cambia(path, blocca):
        os.chmod(path, 0 if blocca else (0o700 if os.path.isdir(path) else 0o600))

    def supporta_permessi(path):
        return True


def avvisa_esplora(path):
    """Dico a Esplora file e al desktop che l'elemento e' cambiato. Senza questo, il desktop puo'
    ricordarsi che 'non si apriva' e continuare a non aprirlo anche dopo lo sblocco."""
    if os.name != "nt":
        return
    try:
        import ctypes
        sh = ctypes.windll.shell32
        sh.SHChangeNotify.argtypes = [ctypes.c_long, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_wchar_p]
        SHCNF_PATHW_NOWAIT = 0x0005 | 0x2000
        p = os.path.abspath(str(path))
        if os.path.isdir(p):
            sh.SHChangeNotify(0x00001000, SHCNF_PATHW_NOWAIT, p, None)       # SHCNE_UPDATEDIR
        sh.SHChangeNotify(0x00002000, SHCNF_PATHW_NOWAIT, p, None)           # SHCNE_UPDATEITEM
        sh.SHChangeNotify(0x00000800, SHCNF_PATHW_NOWAIT, p, None)           # SHCNE_ATTRIBUTES
        sh.SHChangeNotify(0x00001000, SHCNF_PATHW_NOWAIT, os.path.dirname(p), None)
    except Exception:
        pass
    _aggiorna_viste(os.path.dirname(os.path.abspath(str(path))))


def _aggiorna_viste(cartella):
    """Come premere F5 sul desktop e nelle finestre che mostrano quella cartella. Il desktop a volte
    ignora gli avvisi e tiene in memoria che l'elemento 'non si apriva': cosi' lo rilegge davvero."""
    import ctypes
    u = ctypes.windll.user32
    AGGIORNA = 0x7103                     # il comando "Aggiorna" (F5) delle viste di Esplora file
    c = os.path.normcase(cartella)
    try:
        desktop = {os.path.normcase(os.path.join(os.path.expanduser("~"), "Desktop"))}
        try:
            from win32com.shell import shell, shellcon
            for csidl in (shellcon.CSIDL_DESKTOPDIRECTORY, shellcon.CSIDL_COMMON_DESKTOPDIRECTORY):
                desktop.add(os.path.normcase(shell.SHGetFolderPath(0, csidl, None, 0)))
        except Exception:
            pass
        if c in desktop:
            u.FindWindowW.restype = ctypes.c_void_p
            u.FindWindowExW.restype = ctypes.c_void_p
            u.FindWindowExW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p]
            viste = []
            progman = u.FindWindowW("Progman", None)
            v = u.FindWindowExW(progman, None, "SHELLDLL_DefView", None)
            if v:
                viste.append(v)
            w = u.FindWindowExW(None, None, "WorkerW", None)
            while w:                          # con alcuni sfondi il desktop sta dentro una WorkerW
                v = u.FindWindowExW(w, None, "SHELLDLL_DefView", None)
                if v:
                    viste.append(v)
                w = u.FindWindowExW(None, w, "WorkerW", None)
            for v in viste:
                u.PostMessageW(ctypes.c_void_p(v), 0x0111, AGGIORNA, 0)     # WM_COMMAND
    except Exception:
        pass
    try:
        import win32com.client
        for fin in win32com.client.Dispatch("Shell.Application").Windows():
            try:
                if os.path.normcase(fin.Document.Folder.Self.Path) != c:
                    continue
                fin.Refresh()                 # come F5 in quella finestra
            except Exception:
                pass
    except Exception:
        pass


def _blocca_albero(path):
    _blocca_albero_dentro(path)
    avvisa_esplora(path)


def _blocca_albero_dentro(path):
    """Cartella: blocco prima tutto il contenuto (dal fondo) e per ultima la cartella,
    finche' posso ancora leggerla. Se qualcosa va storto rimetto tutto com'era."""
    fatti = []
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            for radice, cartelle, nomi in os.walk(path, topdown=False):
                for n in nomi:
                    p = os.path.join(radice, n)
                    _cambia(p, True)
                    fatti.append(p)
                for d in cartelle:
                    p = os.path.join(radice, d)
                    _cambia(p, True)
                    fatti.append(p)
        _cambia(path, True)
    except Exception:
        for p in reversed(fatti):
            try:
                _cambia(p, False)
            except Exception:
                pass
        raise


def _sblocca_albero(path):
    _sblocca_albero_dentro(path)
    avvisa_esplora(path)


def _sblocca_albero_dentro(path):
    """Al contrario: prima la cartella (cosi' posso vederne il contenuto), poi dentro."""
    _cambia(path, False)
    if os.path.isdir(path) and not os.path.islink(path):
        with os.scandir(path) as it:
            voci = list(it)
        for e in voci:
            if e.is_dir(follow_symlinks=False):
                _sblocca_albero_dentro(e.path)
            else:
                _cambia(e.path, False)


# --------------------------------------------------------------- cassaforte
# L'elemento vero viene spostato in una cartella di Sottomano ("bloccati") e al suo posto resta un
# collegamento con lo stesso nome e la stessa icona. Il doppio clic sul collegamento apre la finestra
# della password (non Esplora file): con la password giusta si apre l'elemento vero.
# Spostare sullo stesso disco e' istantaneo (cambia solo l'indirizzo, non si copia niente).
def cassaforte(path):
    """Cartella dove tenere gli elementi bloccati: su C: quella di Sottomano, sugli altri dischi
    una cartella nascosta sullo stesso disco (cosi' lo spostamento resta istantaneo)."""
    disco = os.path.splitdrive(os.path.abspath(str(path)))[0].lower()
    if os.name != "nt" or disco == os.path.splitdrive(str(BASE))[0].lower():
        return BASE / "bloccati"
    c = Path(disco + "\\") / ".sottomano-bloccati"
    if not c.exists():
        c.mkdir()
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(str(c), 0x2)      # nascosta
        except Exception:
            pass
    return c


def _pythonw():
    import sys
    p = Path(sys.executable)
    return str(p.with_name("pythonw.exe")) if p.with_name("pythonw.exe").exists() else str(p)


def _icona_per(path, cartella):
    """Icona del collegamento: quella delle cartelle, o quella del tipo di file (presa dal registro
    di Windows, solo in lettura)."""
    if cartella:
        return os.path.expandvars(r"%SystemRoot%\System32\imageres.dll") + ",3"
    ext = os.path.splitext(str(path))[1].lower()
    if ext and os.name == "nt":
        try:
            import winreg
            prog = winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, ext)
            for chiave_icona in (prog + r"\DefaultIcon", ext + r"\DefaultIcon"):
                try:
                    v = winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, chiave_icona)
                    if v and v.strip() != "%1":
                        return os.path.expandvars(v.strip().strip('"'))
                except OSError:
                    continue
        except OSError:
            pass
    return os.path.expandvars(r"%SystemRoot%\System32\imageres.dll") + ",2"     # documento generico


def _crea_collegamento(lnk, ident, icona, nome):
    if os.name != "nt":
        Path(lnk).write_text(f"collegamento {ident}")                      # solo per i test
        return
    import win32com.client
    sc = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(lnk))
    sc.TargetPath = _pythonw()
    sc.Arguments = f'"{BASE / "apri_bloccato.pyw"}" {ident}'
    sc.WorkingDirectory = str(BASE)
    sc.IconLocation = icona
    sc.Description = f"«{nome}» è bloccato con Sottomano: doppio clic per sbloccarlo"
    sc.Save()


def _trova(reg, p):
    """Chiave del registro per: il percorso originale, il collegamento (.lnk) o l'elemento vero."""
    k = chiave(p)
    if k in reg:
        v = reg[k]
        # elemento in cassaforte: al suo posto originale ora c'e' il collegamento. Se li' c'e' un file
        # o una cartella vera, e' un elemento NUOVO con lo stesso nome: non e' quello bloccato.
        if not v.get("origine") or not os.path.exists(v["origine"]):
            return k
    elif k.endswith(".lnk") and k[:-4] in reg:
        return k[:-4]
    for kk, v in reg.items():
        if chiave(v["percorso"]) == k or v.get("id") == str(p):
            return kk
    return None


def voce(p, reg=None):
    reg = reg if reg is not None else leggi()
    k = _trova(reg, p)
    return reg[k] if k else None


def per_id(ident, reg=None):
    reg = reg if reg is not None else leggi()
    for v in reg.values():
        if v.get("id") == ident:
            return v
    return None


# -------------------------------------------------------------- operazioni
def blocca(percorsi, password):
    reg = leggi()
    sale = secrets.token_hex(16)
    impronta = _impronta(password, sale)
    nuovi = []
    for p in percorsi:
        p = os.path.abspath(str(p))
        k = _trova(reg, p)
        if k and reg[k]["stato"] == "bloccato":
            raise Errore(f"«{Path(p).name}» è già bloccato: per aprirlo fai doppio clic o premi Spazio.")
        if k:
            continue                     # era aperto: lo riblocco qui sotto con la password nuova
        if not supporta_permessi(p):
            raise Errore(f"«{Path(p).name}» è su un disco che non supporta i permessi (per esempio una "
                         "chiavetta FAT32/exFAT): il blocco funziona solo sui dischi NTFS.")
        if p.lower().endswith(".lnk"):
            raise Errore(f"«{Path(p).name}» è un collegamento: blocca l'elemento vero.")
        if os.path.exists(p + ".lnk"):
            raise Errore(f"Accanto a «{Path(p).name}» c'è già un collegamento con lo stesso nome.")
        nuovi.append(p)
    # 1) elementi gia' in cassaforte ma aperti: nuova password e di nuovo bloccati
    for p in percorsi:
        k = _trova(reg, p)
        if k:
            v = reg[k]
            v.update(sale=sale, impronta=impronta)
            _blocca_albero(v["percorso"])
            v["stato"] = "bloccato"
            scrivi(reg)
    # 2) elementi nuovi: in cassaforte, collegamento al loro posto, permessi tolti
    for p in nuovi:
        ident = secrets.token_hex(6)
        cartella = os.path.isdir(p)
        casa = cassaforte(p) / ident
        vero = casa / os.path.basename(p)
        icona = _icona_per(p, cartella)
        # prima lo segno nel registro: anche se il PC si spegnesse a meta', so dov'e' e cosa sbloccare
        reg[chiave(p)] = {"id": ident, "origine": p, "collegamento": p + ".lnk", "percorso": str(vero),
                          "stato": "bloccato", "sale": sale, "impronta": impronta, "cartella": cartella,
                          "dal": time.strftime("%Y-%m-%d %H:%M")}
        scrivi(reg)
        casa.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(p, vero)
        except OSError as e:
            del reg[chiave(p)]
            scrivi(reg)
            _rimuovi_vuota(casa)
            raise Errore(f"Non riesco a spostare «{Path(p).name}»: è aperto in un altro programma? "
                         f"Chiudilo e riprova. ({e.strerror or e})")
        try:
            _crea_collegamento(p + ".lnk", ident, icona, os.path.basename(p))
            _blocca_albero(str(vero))
        except Exception:
            # qualcosa e' andato storto: rimetto tutto com'era
            try:
                _sblocca_albero(str(vero))
            except Exception:
                pass
            os.rename(vero, p)
            Path(p + ".lnk").unlink(missing_ok=True)
            del reg[chiave(p)]
            scrivi(reg)
            _rimuovi_vuota(casa)
            raise
        avvisa_esplora(os.path.dirname(p))


def _rimuovi_vuota(cartella):
    try:
        os.rmdir(cartella)
    except OSError:
        pass


def apri(p, password):
    """Sblocco parziale: aperto finche' lo usi, poi Sottomano lo richiude da solo.
    Restituisce il percorso dell'elemento vero, oppure None se la password e' sbagliata."""
    reg = leggi()
    k = _trova(reg, p)
    if not k or not secrets.compare_digest(_impronta(password, reg[k]["sale"]), reg[k]["impronta"]):
        return None
    v = reg[k]
    _sblocca_albero(v["percorso"])
    v["stato"] = "aperto"
    v["aperto_alle"] = time.time()
    scrivi(reg)
    return v["percorso"]


def richiudi(p):
    reg = leggi()
    k = _trova(reg, p)
    if not k or reg[k]["stato"] == "bloccato":
        return
    v = reg[k]
    _blocca_albero(v["percorso"])
    v["stato"] = "bloccato"
    scrivi(reg)


def togli(p, password=None):
    """Sblocco completo: toglie la protezione per sempre e rimette l'elemento al suo posto
    (al posto del collegamento). Se e' bloccato serve la password. Restituisce il percorso finale,
    True se non c'era niente da fare, False se la password e' sbagliata."""
    reg = leggi()
    k = _trova(reg, p)
    if not k:
        return True
    v = reg[k]
    if v["stato"] == "bloccato":
        if password is None or not secrets.compare_digest(_impronta(password, v["sale"]), v["impronta"]):
            return False
        _sblocca_albero(v["percorso"])
    finale = v["percorso"]
    if v.get("origine"):                 # era in cassaforte: torna dov'era
        Path(v["collegamento"]).unlink(missing_ok=True)
        origine = Path(v["origine"])
        if not origine.parent.exists():  # la cartella di partenza non c'e' piu': lo metto sul desktop
            origine = Path.home() / "Desktop" / origine.name
        dest, n = origine, 1
        while dest.exists():
            n += 1
            dest = origine.with_name(f"{origine.stem} ({n}){origine.suffix}")
        if os.path.exists(v["percorso"]):
            os.rename(v["percorso"], dest)
            _rimuovi_vuota(Path(v["percorso"]).parent)
        finale = str(dest)
        avvisa_esplora(str(dest.parent))
    del reg[k]
    scrivi(reg)
    return finale


def dimentica(p):
    """Toglie dal registro un elemento che non esiste piu' (spostato o eliminato)."""
    reg = leggi()
    k = _trova(reg, p)
    if k is not None:
        reg.pop(k)
        scrivi(reg)


def ricrea_collegamento(p):
    """Se hai cancellato il collegamento per sbaglio, lo rimetto al suo posto."""
    reg = leggi()
    k = _trova(reg, p)
    v = reg.get(k) if k else None
    if not v or not v.get("origine"):
        return None
    lnk = v["collegamento"]
    if not os.path.exists(lnk):
        Path(lnk).parent.mkdir(parents=True, exist_ok=True)
        _crea_collegamento(lnk, v["id"], _icona_per(v["origine"], v["cartella"]), Path(v["origine"]).name)
        avvisa_esplora(str(Path(lnk).parent))
    return lnk


def richiudi_tutti():
    """All'avvio di Sottomano: tutto cio' che avevi aperto torna bloccato."""
    reg = leggi()
    cambiato = False
    for v in reg.values():
        if v["stato"] == "aperto" and os.path.exists(v["percorso"]):
            try:
                _blocca_albero(v["percorso"])
                v["stato"] = "bloccato"
                cambiato = True
            except Exception:
                pass
    if cambiato:
        scrivi(reg)


def aperti(reg=None):
    """Elementi in sblocco parziale: [(percorso vero, da quanti secondi)]."""
    reg = reg if reg is not None else leggi()
    adesso = time.time()
    return [(v["percorso"], adesso - v.get("aperto_alle", 0)) for v in reg.values() if v["stato"] == "aperto"]


def bloccati(reg=None):
    """Elementi bloccati 'sul posto' (versione precedente, senza cassaforte): per il doppio clic."""
    reg = reg if reg is not None else leggi()
    return [v["percorso"] for v in reg.values() if v["stato"] == "bloccato" and not v.get("origine")]


# ------------------------------------------------- e' ancora aperto?  (sblocco parziale)
def _nomi_da_cercare(nome):
    """Nome con e senza estensione (Esplora file e molti programmi nascondono l'estensione)."""
    nomi = {nome.lower()}
    radice_nome = os.path.splitext(nome)[0].lower()
    if len(radice_nome) >= 5:
        nomi.add(radice_nome)
    return nomi


def _nel_titolo(nome, titolo):
    """Il nome compare nel titolo come parola intera ("note.txt" si', "notepad" no)."""
    import re
    return re.search(r"(?<![\w.])" + re.escape(nome) + r"(?![\w])", titolo) is not None


def in_uso(percorso, titoli, cartelle_aperte, file_occupati):
    """Il file o la cartella si sta ancora usando?
    titoli: titoli delle finestre aperte (minuscolo); cartelle_aperte: cartelle mostrate in Esplora file;
    file_occupati(lista) -> True se un programma tiene aperto almeno uno di quei file."""
    p = chiave(percorso)
    if os.path.isdir(percorso):
        for c in cartelle_aperte:
            c = chiave(c)
            if c == p or c.startswith(p.rstrip("\\/") + os.sep):
                return True
        file_dentro = []
        for radice, _, nomi in os.walk(percorso):
            for n in nomi:
                file_dentro.append(os.path.join(radice, n))
                if len(file_dentro) >= 400:
                    break
            if len(file_dentro) >= 400:
                break
        cerca = set()
        for f in file_dentro:
            cerca |= {n for n in _nomi_da_cercare(os.path.basename(f)) if len(n) >= 5}
    else:
        file_dentro = [percorso]
        cerca = _nomi_da_cercare(os.path.basename(percorso))
    # programmi che mostrano il nome del file nel titolo (Blocco note, Foto, l'anteprima di Sottomano...)
    if any(n in t and _nel_titolo(n, t) for t in titoli for n in cerca):
        return True
    # programmi che tengono il file aperto (Word, Excel, lettori PDF, VLC...)
    try:
        return bool(file_dentro) and file_occupati(file_dentro)
    except Exception:
        return False


def file_occupati(percorsi):
    """Windows Restart Manager: c'e' un programma che sta usando questi file?"""
    import ctypes
    from ctypes import wintypes
    rm = ctypes.WinDLL("rstrtmgr")
    sessione = wintypes.DWORD()
    chiave_s = ctypes.create_unicode_buffer(64)
    if rm.RmStartSession(ctypes.byref(sessione), 0, chiave_s) != 0:
        return False
    try:
        arr = (wintypes.LPCWSTR * len(percorsi))(*[str(x) for x in percorsi])
        if rm.RmRegisterResources(sessione, len(percorsi), arr, 0, None, 0, None) != 0:
            return False
        servono, n, motivi = wintypes.UINT(0), wintypes.UINT(0), wintypes.DWORD(0)
        esito = rm.RmGetList(sessione, ctypes.byref(servono), ctypes.byref(n), None, ctypes.byref(motivi))
        return esito in (0, 234) and servono.value > 0          # 234 = ci sono programmi (ERROR_MORE_DATA)
    finally:
        rm.RmEndSession(sessione)
