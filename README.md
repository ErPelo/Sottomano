<p align="center"><img src="logo.png" width="128" alt="Logo di Sottomano"></p>

<h1 align="center">Sottomano</h1>

<p align="center"><b>Gli strumenti che ti servono sui file, a portata di mano.</b><br>
Per Windows 10 e 11 · gratis e open source · versione 0.1 (beta)</p>

---

Sottomano aggiunge due cose a Esplora file e al desktop:

- **Ctrl+Alt+S → menu Strumenti.** Selezioni uno o più file, premi la combinazione e accanto al file si apre un menu, come quello del tasto destro, con le azioni adatte a quei file: conversioni di immagini, video e audio, testo dalle immagini (OCR), strumenti PDF, ritaglio, conversione di archivi.
- **Spazio → anteprima al volo**, come QuickLook su Mac. Immagini, video con audio, PDF, testo e contenuto degli archivi si aprono all'istante; con le frecce scorri i file della cartella.

Inoltre:

- non modifica il registro di Windows;
- non tocca mai i tuoi file: i risultati vengono salvati accanto all'originale, con un nome nuovo;
- funziona tutto sul tuo PC: i file non vengono mai caricati da nessuna parte (vedi [Privacy](#privacy)).

> **Versione beta**: funziona, ma è giovane. Se trovi un problema apri una *Issue* allegando `errori.log` (vedi [Problemi](#problemi)).

## Cosa fa

Il menu mostra solo le voci adatte ai file selezionati.

| File selezionati | Azioni |
|---|---|
| **Immagini** (jpg, png, webp, bmp, gif, tiff, heic) | Converti in PNG / JPG / WEBP / ICO / PDF (più immagini = un solo PDF) · Estrai testo (OCR) · **Ritaglia e ridimensiona** con editor grafico · Ridimensiona e comprimi più foto insieme · Rimuovi metadati (GPS, fotocamera, data) · Rimuovi sfondo con AI *(opzionale)* |
| **PDF** | Copia testo · Estrai testo con OCR (per i PDF scansionati) · Unisci PDF · PDF in immagini · Comprimi PDF |
| **Video** (mp4, mkv, mov, avi, webm, wmv…) | Converti in MP4 / MKV / MOV / WEBM / GIF animata · Comprimi video · Estrai audio (MP3) |
| **Audio** (mp3, wav, m4a, flac, ogg…) | Converti in MP3 / WAV / M4A / FLAC |
| **Archivi** (zip, 7z, rar, tar, gz…) | Converti in 7z / ZIP / RAR |
| **Qualsiasi file** | Calcola SHA-256 |

- Il testo estratto viene copiato negli appunti e salvato in un `.txt` accanto all'originale. L'OCR riconosce italiano e inglese.
- Mentre un'azione lavora, accanto all'originale compare un file `nome.estensione.in-corso` (come i download di Chrome): quando sparisce, il risultato è pronto.
- **Editor di ritaglio**: trascini il riquadro con le maniglie e, quando lo rilasci, la vista si ingrandisce sulla zona scelta. Proporzioni fisse (1:1, 4:3, 16:9…), rotazione e dimensione finale con una barra.

## Scorciatoie

| Dove | Tasto | Cosa fa |
|---|---|---|
| Esplora file o desktop | **Ctrl+Alt+S** | apre il menu sui file selezionati |
| Esplora file o desktop | **Spazio** | anteprima del file selezionato (mentre rinomini o scrivi, lo Spazio resta uno spazio normale) |
| Anteprima | **← → ↑ ↓** | file precedente / successivo |
| Anteprima | **Invio** o doppio clic | apre il file nel programma predefinito |
| Anteprima | **Spazio**, **Esc** o clic fuori | chiude |
| Anteprima video | clic sul video · barra in basso | pausa · avanti e indietro |
| Editor di ritaglio | **rotellina** · **Invio** · **Esc** | zoom · salva · annulla |

## Installazione

Requisiti: Windows 10 o 11 con **winget** (già incluso nelle versioni recenti; altrimenti aggiorna "Programma di installazione app" dal Microsoft Store). Spazio su disco: circa 500 MB, più circa 600 MB se scegli anche la rimozione sfondo con AI.

1. Scarica il progetto: **Code → Download ZIP**, oppure dalla sezione *Releases*.
2. Estrai la cartella e fai doppio clic su **`installa.bat`**.
3. Fatto: seleziona un file e premi **Ctrl+Alt+S**, oppure **Spazio** per l'anteprima.

`installa.bat` fa due cose, e mostra ogni passaggio a schermo:

1. con **winget** (l'installer ufficiale di Windows) installa, solo se mancano, Python 3.12, 7-Zip e Tesseract OCR;
2. con `installa.py` installa le librerie Python (compreso FFmpeg per i video), scarica le lingue OCR italiano e inglese, crea il collegamento **Sottomano** nel menu Start e, **solo se lo scegli**, l'icona sul desktop e l'avvio automatico.

Sottomano resta attivo con un'icona vicino all'orologio (a volte tra le icone nascoste, sotto la freccia **^**). Per chiuderlo: tasto destro sull'icona → *Esci*. Per riaprirlo: menu Start → **Sottomano**.

## Disinstallazione

Doppio clic su `disinstalla.bat` (si trova anche in `%LOCALAPPDATA%\Sottomano`).

Durante l'installazione Sottomano tiene un registro (`installato.txt`) di **ciò che ha installato lui e che prima non c'era**: Python, 7-Zip, Tesseract, le librerie Python, il modello AI, l'icona sul desktop. La disinstallazione mostra l'elenco, chiede conferma e rimuove **solo quelle cose**. Se avevi già Python, 7-Zip o una libreria prima di installare Sottomano, restano dove sono.

## Privacy

Tutte le operazioni avvengono sul tuo PC: Sottomano non carica i tuoi file su internet e non raccoglie dati. Si collega a internet solo durante l'installazione (per scaricare i programmi e le librerie dalle fonti ufficiali) e, se la usi, la prima volta che rimuovi uno sfondo (per scaricare il modello AI).

## Problemi

**L'antivirus lo blocca?** Sottomano è composto da script leggibili: puoi aprire ogni file con il Blocco note e controllare cosa fa. Alcuni antivirus segnalano per prudenza i programmi che restano attivi in background o ascoltano una combinazione di tasti. Se succede, puoi segnalare il falso positivo al produttore dell'antivirus (ad esempio [Kaspersky](https://opentip.kaspersky.com/)).

**Ctrl+Alt+S non fa niente?** Controlla che l'icona di Sottomano sia vicino all'orologio; se non c'è, avvialo dal menu Start. Se un altro programma usa già Ctrl+Alt+S, Sottomano te lo dice all'avvio.

Gli errori vengono salvati in `%LOCALAPPDATA%\Sottomano\errori.log`: apri una *Issue* allegando il log.

## Dipendenze

Sottomano non include software di terzi: l'installer li scarica dalle fonti ufficiali.

| Progetto | Uso | Licenza |
|---|---|---|
| [Python](https://www.python.org/) | esecuzione | PSF |
| [Pillow](https://python-pillow.org/) | immagini | MIT-CMU |
| [pillow-heif](https://github.com/bigcat88/pillow_heif) | foto HEIC | BSD-3-Clause |
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | PDF | AGPL-3.0 |
| [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) + [tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast) | OCR | Apache-2.0 |
| [pytesseract](https://github.com/madmaze/pytesseract) | OCR | Apache-2.0 |
| [pywin32](https://github.com/mhammond/pywin32) | menu, Esplora file, icona vicino all'orologio | PSF |
| [comtypes](https://github.com/enthought/comtypes) | icone dei file e posizione del menu | MIT |
| [ffpyplayer](https://github.com/matham/ffpyplayer) | anteprima video | LGPL-2.1 |
| [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) (include [FFmpeg](https://ffmpeg.org/)) | conversione video e audio | BSD-2-Clause (FFmpeg: GPL) |
| [7-Zip](https://www.7-zip.org/) | archivi | LGPL-2.1 |
| [rembg](https://github.com/danielgatis/rembg) *(opzionale)* | rimozione sfondo | MIT |
| [WinRAR](https://www.win-rar.com/) *(opzionale, se già installato)* | creazione file .rar | proprietaria |

## Licenza

Copyright (C) 2026 Tommaso Pelosin

Distribuito con licenza **GNU AGPL-3.0**: vedi [LICENSE](LICENSE). Puoi usarlo, modificarlo e ridistribuirlo liberamente; le versioni modificate che distribuisci devono restare open source con la stessa licenza.

Il software è fornito **"così com'è", senza alcuna garanzia**. L'autore non è responsabile di eventuali danni o perdite di dati derivanti dal suo uso.
