# TeamTalk VoiceOver Client (macOS / Windows)

Minimaler Python/wxPython-Client auf Basis des TeamTalk SDK v5.19a (Standard Edition).
Das SDK liegt unter third_party/teamtalk/ und darf nur gemaess Lizenzbedingungen von BearWare verwendet werden.
Das Projekt bundelt espeak-ng (GPLv3) fuer TTS.

## Voraussetzungen

### macOS
- macOS 10.13+
- Python 3.10+
- TeamTalk SDK v5.19a (bereits in third_party/)
- wxPython (siehe requirements.txt)

### Windows
- Windows 10+
- Python 3.10+
- TeamTalk SDK v5.19a fuer Windows unter third_party/teamtalk/tt5sdk_v5.19a_win64/
- wxPython (siehe requirements.txt)
- espeak-ng fuer Windows (espeak-ng.exe + espeak-ng-data) unter third_party/espeak-ng/

## Start

### macOS
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src python src/app.py

### Windows
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
set PYTHONPATH=src
python src/app.py

## Build (macOS App)
source .venv/bin/activate
PYINSTALLER_CONFIG_DIR="$(pwd)/.pyinstaller" pyinstaller --noconfirm "TeamTalk VO Client.spec"

Die App liegt danach unter dist/TeamTalk VO Client.app.

## Build (Windows)
.venv\Scripts\activate
pyinstaller --noconfirm "TeamTalk VO Client_win.spec"

Die .exe liegt danach unter dist/TeamTalk VO Client/.

## Hinweise zu Accessibility (VoiceOver)
- Alle Felder besitzen explizite Labels und Names.
- Klare Tab-Reihenfolge durch MoveAfterInTabOrder.
- Statusmeldungen werden in ein Ereignisprotokoll geschrieben, damit VoiceOver Aenderungen ansagt.

## TTS (espeak-ng)
- espeak-ng wird im App-Bundle mitgeliefert.
- Beim ersten Aktivieren von TTS wird espeak-ng nach
  ~/Library/Application Support/TeamTalkVOClient/espeak-ng kopiert,
  um wiederholte macOS-Abfragen zu vermeiden.

## Features
- Serverliste mit Import/Export (JSON)
- Oeffnen von TeamTalk-Dateien (.tt, .ini, .json, .xml) und direktes Verbinden
- Kanalbaum + Doppelklick zum Beitreten
- Nutzerliste
- Textchat (Kanal/Benutzer)
- Audio-Geraetewahl, Gain/Volume, Voice Activation
- Push-to-Talk (Leertaste halten)
- Tray-Icon (Schliessen minimiert in Tray)

## Lizenz
- Der Quellcode dieses Projekts steht unter der GPLv3 (siehe LICENSE).
- Das TeamTalk SDK unterliegt der BearWare-Lizenz. Trial-Builds deaktivieren sich nach 30 Tagen. Fuer produktive Nutzung ist eine Lizenz erforderlich.
- espeak-ng ist GPLv3; diese Lizenz gilt fuer das gesamte Bundle.

## Hinweis zu Repos
dist/, build/, .venv/ und .pyinstaller/ werden nicht versioniert.
