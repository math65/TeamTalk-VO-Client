# TeamTalk VoiceOver Client – Projektnotizen für Claude

## Build

```bash
# App bauen (aus Projektverzeichnis)
.venv/bin/pyinstaller -y "TeamTalk VO Client.spec"

# DMG erstellen (VERSION anpassen)
hdiutil create -volname "TeamTalk VO Client <VERSION>" \
  -srcfolder "dist/TeamTalk VO Client.app" \
  -ov -format UDZO "dist/TeamTalk VO Client <VERSION>.dmg"
```

Python-Umgebung liegt in `.venv/` (Python 3.9, PyInstaller).

## Versionierung

`APP_VERSION` in `src/app.py` (einzige Quelle).
Aktueller Stand: `6.4.6`
Schema: `6.x.y` – Patch-Releases bei Fehlerbehebungen und UI-/Dokumentationsanpassungen,
Minor-Releases bei neuen Feature-Blöcken.
`TeamTalk VO Client.spec` und `version_info.txt` müssen immer auf dieselbe Versionsnummer
wie `APP_VERSION` synchronisiert werden.
CHANGELOG in `CHANGELOG.txt` immer mitpflegen (neuester Eintrag oben).

## Projektstruktur

```
src/
  app.py                  # MainFrame, App, Event-Loop, Menüs
  tts.py                  # TTSManager (espeak-ng, afplay/winsound)
  sound_manager.py        # SoundManager (afplay / wx.adv.Sound)
  ui/
    a11y.py               # VoiceOver-Patches (macOS)
    server_tools.py       # OnlineUsersDialog, BanListDialog, …
    tabs/
      connection.py       # Tab 1: Verbindung / Serverliste
      channels.py         # Tab 2: Kanäle + Nutzerliste
      chat.py             # Tab 3: Chat
      audio.py            # Tab 4: Audio
      media.py            # Tab 5: Medien-Streaming
      files.py            # Tab 6: Dateien
      admin.py            # Tab 7: Administration
      speak.py            # Tab 8: ElevenLabs TTS → Kanal
      desktop.py          # Tab 9: Desktopfreigabe
      settings.py         # Tab 10: Einstellungen
      shortcuts.py        # Tab 11: Tastenkürzel
      system.py           # Tab 12: System-Log
      video.py            # Tab 13: Video
      channels_chat.py    # Hilfs-Panel Kanal+Chat
  models.py               # ServerProfile, ParsedTeamTalkFile, …
  tray.py                 # Tray-Icon
  tt_file_parser.py       # .tt-Datei / tt://-URL Parser
licenses/                 # Lizenztexte (ins Bundle kopiert)
third_party/espeak-ng/    # Gebündeltes espeak-ng
sounds/                   # Ereignis-Sounds (.wav)
```

## VoiceOver / Barrierefreiheit (macOS)

Alle Patches in `src/ui/a11y.py`, werden einmalig in `App.OnInit()` aufgerufen:

| Funktion | Was sie tut |
|---|---|
| `patch_button_accessibility()` | wxNSButton → "Taste"/"Schalter", wxNSPopUpButton → "Auswahlmenü", wxNSComboBox → "Kombinationsfeld" |
| `patch_list_row_accessibility()` | wxNSTableView → AXList ("Liste"), NSTableRow → Elementtext + kein "Zeile N" |
| `patch_control_accessibility()` | wxNSSlider → "Regler", wxNSTextField → "Textfeld", wxNSTextView → "Textbereich", wxNSOutlineView → "Baumansicht", NSProgressIndicator → "Fortschrittsanzeige" |
| `setup_list_accessible(lb)` | Setzt AXList-Rolle auf einzelner wx.ListBox-Instanz (Fallback) |

Patching-Technik: `objc.classAddMethod` (PyObjC) – ersetzt Klassen-Methode global,
kein Neustart nötig, wirkt auf alle Instanzen der Klasse.

## Wichtige Konventionen

- **Listen**: `wx.ListBox` statt `wx.ListCtrl` (VoiceOver-zuverlässiger auf macOS).
- **Trennzeichen in Listeinträgen**: Komma `, ` – kein Pipe `|` (VoiceOver liest `|` als "senkrechter Strich").
- **Parallele ID-Listen**: Neben jeder `wx.ListBox` gibt es eine parallele Python-Liste
  für IDs/Namen (z. B. `_file_ids`, `_file_names`, `_channel_list_ids`).
  Nie per String-Split auf Listeinhalte zugreifen.
- **Thread-Sicherheit**: SDK-Aufrufe und UI-Updates aus Threads immer via `wx.CallAfter`.
- **USER_UPDATE-Event**: Feuert bei jeder Sprachzustandsänderung – kein teures
  Channel-Refresh auslösen (nur bei strukturellen Events).
- **Sound**: macOS → `afplay`; Windows → `wx.adv.Sound` via
  `wx.CallAfter(lambda s=sound: s.Play(...))` (GC-Schutz!).

## Hauptentwickler & Plattformstrategie

Hauptentwickler: Florian Lichteblau (Flarion).
Primärplattform: **macOS** (VoiceOver + Braillezeile).
Windows/Linux: dank wxPython unterstützt, aber vereinzelte Einschränkungen möglich.

## Git / Remote

```
origin  https://git.garogaming.xyz/flarion/TeamTalk-VO-Client.git   (primär, Gitea)
github  https://github.com/fla-rion/TeamTalk-VO-Client.git           (Spiegel, GitHub)
branch  main
```

Releases immer auf **beiden** Remotes pushen und auf **beiden** als Release anlegen:
- Gitea: `git push origin main && git push origin vX.Y.Z`
- GitHub: `git push github main && git push github vX.Y.Z`

Token für Gitea-API steht in `git remote get-url origin` (URL enthält Credentials).
