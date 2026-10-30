# -*- coding: utf-8 -*-
# Sottomano - avviato dal doppio clic sul collegamento di un elemento bloccato.
# Copyright (C) 2026 Tommaso Pelosin - Licenza AGPL-3.0 (vedi LICENSE)
#
# E' volutamente minuscolo (niente librerie da caricare): passa il codice dell'elemento a Sottomano,
# che e' gia' acceso e mostra subito la finestra della password. Se Sottomano non e' acceso,
# la mostra avviandolo per questa volta.
import os
import sys
import json
import ctypes
import subprocess
from ctypes import wintypes


class COPYDATA(ctypes.Structure):
    _fields_ = [("dwData", ctypes.c_size_t), ("cbData", wintypes.DWORD), ("lpData", ctypes.c_void_p)]


def main():
    if len(sys.argv) < 2:
        return
    ident = sys.argv[1]
    u = ctypes.windll.user32
    u.AllowSetForegroundWindow(wintypes.DWORD(-1 & 0xFFFFFFFF))   # ASFW_ANY: la finestra della password va davanti
    u.FindWindowW.restype = wintypes.HWND
    hwnd = u.FindWindowW("SottomanoServizio", None)
    if hwnd:
        dati = json.dumps(["apri_bloccato", ident]).encode("utf-8")
        buf = ctypes.create_string_buffer(dati)
        cd = COPYDATA(0x534D, len(dati), ctypes.addressof(buf))
        u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_void_p]
        u.SendMessageW.restype = ctypes.c_ssize_t
        if u.SendMessageW(hwnd, 0x004A, 0, ctypes.byref(cd)) == 1:        # WM_COPYDATA
            return
    qui = os.path.dirname(os.path.abspath(__file__))
    subprocess.Popen([sys.executable, os.path.join(qui, "sottomano.pyw"), "apri_bloccato", ident], cwd=qui)


if __name__ == "__main__":
    main()
