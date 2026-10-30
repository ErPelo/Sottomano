# -*- coding: utf-8 -*-
# Sottomano - blocco con password di file e cartelle.
# Copyright (C) 2026 Tommaso Pelosin - Licenza AGPL-3.0 (vedi LICENSE)
#
# Il file (o la cartella) resta dov'e', con lo stesso nome e la stessa icona, ma Windows
# non lo lascia aprire, leggere, modificare, spostare ne' eliminare: Sottomano aggiunge ai suoi
# permessi (NTFS) una regola "Nega" per tutti. Con la password giusta Sottomano toglie la regola.
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
    """'bloccato', 'aperto' (sbloccato per ora, si richiude) oppure None."""
    v = (reg if reg is not None else leggi()).get(chiave(p))
    return v["stato"] if v else None


def password_giusta(p, password, reg=None):
    v = (reg if reg is not None else leggi()).get(chiave(p))
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


def _blocca_albero(path):
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
    """Al contrario: prima la cartella (cosi' posso vederne il contenuto), poi dentro."""
    _cambia(path, False)
    if os.path.isdir(path) and not os.path.islink(path):
        with os.scandir(path) as it:
            voci = list(it)
        for e in voci:
            if e.is_dir(follow_symlinks=False):
                _sblocca_albero(e.path)
            else:
                _cambia(e.path, False)


# -------------------------------------------------------------- operazioni
def blocca(percorsi, password):
    reg = leggi()
    sale = secrets.token_hex(16)
    impronta = _impronta(password, sale)
    for p in percorsi:
        p = os.path.abspath(str(p))
        if chiave(p) in reg:
            raise Errore(f"«{Path(p).name}» è già protetto da Sottomano.")
        if not supporta_permessi(p):
            raise Errore(f"«{Path(p).name}» è su un disco che non supporta i permessi (per esempio una "
                         "chiavetta FAT32/exFAT): il blocco funziona solo sui dischi NTFS.")
    for p in percorsi:
        p = os.path.abspath(str(p))
        # prima lo segno nel registro: anche se il PC si spegnesse a meta', so cosa sbloccare
        reg[chiave(p)] = {"percorso": p, "stato": "bloccato", "sale": sale, "impronta": impronta,
                          "cartella": os.path.isdir(p), "dal": time.strftime("%Y-%m-%d %H:%M")}
        scrivi(reg)
        try:
            _blocca_albero(p)
        except Exception:
            del reg[chiave(p)]
            scrivi(reg)
            raise


def apri(p, password):
    """Sblocca per ora (si richiude con 'Blocca di nuovo' o al prossimo avvio di Sottomano)."""
    reg = leggi()
    if not password_giusta(p, password, reg):
        return False
    _sblocca_albero(str(p))
    reg[chiave(p)]["stato"] = "aperto"
    scrivi(reg)
    return True


def richiudi(p):
    reg = leggi()
    v = reg.get(chiave(p))
    if not v or v["stato"] == "bloccato":
        return
    _blocca_albero(v["percorso"])
    v["stato"] = "bloccato"
    scrivi(reg)


def togli(p, password=None):
    """Toglie la protezione per sempre. Se e' bloccato serve la password."""
    reg = leggi()
    v = reg.get(chiave(p))
    if not v:
        return True
    if v["stato"] == "bloccato":
        if password is None or not password_giusta(p, password, reg):
            return False
        _sblocca_albero(v["percorso"])
    del reg[chiave(p)]
    scrivi(reg)
    return True


def dimentica(p):
    """Toglie dal registro un elemento che non esiste piu' (spostato o eliminato)."""
    reg = leggi()
    if reg.pop(chiave(p), None) is not None:
        scrivi(reg)


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
