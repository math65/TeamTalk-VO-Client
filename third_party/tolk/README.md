# Tolk – Windows Screen Reader DLLs

Lege folgende DLL-Dateien in dieses Verzeichnis, damit TeamTalk VO Client
Statusmeldungen an den laufenden Screen Reader (NVDA, JAWS, SAPI) sendet.

## Benötigte Dateien (64-Bit, empfohlen)

| Datei | Quelle | Pflicht? |
|---|---|---|
| `nvdaControllerClient64.dll` | NVDA-Installation: `C:\Program Files (x86)\NVDA\` | Für NVDA-Unterstützung |
| `tolk.dll` | https://github.com/dkager/tolk (Quellcode, selbst kompilieren) | Für JAWS + alle Reader |
| `SAAPI64.dll` | Mit tolk.dll mitgeliefert | Optional (SAPI-Fallback) |

## Minimal-Lösung (nur NVDA)

Kopiere `nvdaControllerClient64.dll` aus dem NVDA-Installationsordner hierher.
Das Modul `screen_reader.py` erkennt sie automatisch.

## Ohne DLLs

Das Programm läuft ohne diese DLLs normal; Statusmeldungen werden dann nicht
über den Screen Reader angekündigt.
