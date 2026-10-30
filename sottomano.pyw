# -*- coding: utf-8 -*-
"""
Sottomano - azioni rapide sui file di Esplora file (Windows 10/11).

Uso:  pythonw sottomano.pyw ascolta                   servizio in background: Ctrl+Alt+S apre il menu
      pythonw sottomano.pyw <azione> "file1" [...]   esegue direttamente un'azione

Il programma e' in nucleo.py. Questo file lo avvia soltanto: cosi' Python tiene la versione gia'
compilata di nucleo.py (in __pycache__) e non deve ricompilare quasi 3000 righe a ogni avvio.

Copyright (C) 2026 Tommaso Pelosin

This program is free software: you can redistribute it and/or modify it under the
terms of the GNU Affero General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later version.
This program is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nucleo  # noqa: E402

nucleo.main()
