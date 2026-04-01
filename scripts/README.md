# TeamTalk VoiceOver Client – Build-Anleitung / Build Guide

> **Sprachen / Languages:** [🇩🇪 Deutsch](#-deutsch) · [🇬🇧 English](#-english)

---

## 🇩🇪 Deutsch

### Übersicht

Dieses Verzeichnis enthält Build-Skripte für alle unterstützten Plattformen:

| Skript | Plattform | Ausgabe |
|--------|-----------|---------|
| `build_macos.sh` | macOS 11+ (Intel + Apple Silicon) | `.app` + `.dmg` |
| `build_windows.ps1` | Windows 10/11 (64-Bit) | Portabler Ordner + `.zip` |
| `build_linux.sh` | Ubuntu 22.04 / Debian 12+ (x64) | Portabler Ordner + `.tar.gz` |

---

### Voraussetzungen

#### Alle Plattformen

- **Python 3.9–3.12** (nicht 3.13+, PyInstaller-Kompatibilität)
- **Git** (um das Repository zu klonen)
- Internetverbindung für `pip install`

#### macOS

```bash
# Xcode Command Line Tools
xcode-select --install

# Homebrew (falls nicht vorhanden)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# PortAudio (für pyaudio)
brew install portaudio

# Python (falls nicht vorhanden)
brew install python@3.12
```

#### Windows

- Python 3.9–3.12 von [python.org](https://python.org) – bei der Installation **„Add Python to PATH"** aktivieren
- [Microsoft Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe) (normalerweise bereits vorhanden)
- PowerShell-Ausführungsrichtlinie erlauben (einmalig als Administrator):
  ```powershell
  Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
  ```

#### Linux (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install python3-dev python3-pip python3-venv \
                 portaudio19-dev libgtk-3-dev \
                 libgstreamer1.0-dev gstreamer1.0-plugins-base \
                 xdotool   # für Fensterauswahl unter X11
# Für Wayland-Bildschirmaufnahme:
sudo apt install grim
```

---

### TeamTalk SDK einrichten

Das SDK ist **nicht im Repository enthalten** und muss separat heruntergeladen werden:

1. [https://bearware.dk/teamtalksdk](https://bearware.dk/teamtalksdk) öffnen
2. Passende Version herunterladen:
   - **macOS:** `tt5sdk_v5.19a_macos_universal.zip` → entpacken nach `third_party/teamtalk/tt5sdk_v5.19a_macos_universal/`
   - **Windows:** `tt5sdk_v5.19a_win64.zip` → entpacken nach `third_party/teamtalk/tt5sdk_v5.19a_win64/`
   - **Linux:** `tt5sdk_v5.19a_linux_x64.tar.gz` → entpacken nach `third_party/teamtalk/tt5sdk_v5.19a_linux_x64/`

Erwartete Struktur:
```
third_party/teamtalk/
  tt5sdk_v5.19a_macos_universal/
    Library/
      TeamTalkPy/    ← Python-Bindings
      TeamTalk_DLL/  ← Native Bibliothek (.dylib)
  tt5sdk_v5.19a_win64/
    Library/
      TeamTalkPy/
      TeamTalk_DLL/  ← (.dll)
  tt5sdk_v5.19a_linux_x64/
    Library/
      TeamTalkPy/
      TeamTalk_DLL/  ← (.so)
```

---

### BlackHole (macOS, optional)

Für Systemton-Übertragung wird BlackHole 2ch benötigt.
Das PKG ist bereits im Bundle enthalten: `third_party/blackhole/BlackHole2ch.pkg`

Falls die Datei fehlt:
```bash
# Manuell herunterladen
curl -L "https://github.com/ExistentialAudio/BlackHole/releases/download/v0.6.1/BlackHole2ch-0.6.1.pkg" \
     -o third_party/blackhole/BlackHole2ch.pkg
```

---

### Bauen

#### macOS

```bash
# Aus dem Projektverzeichnis:
chmod +x scripts/build_macos.sh
./scripts/build_macos.sh

# Mit optionalem Gitea-Release-Upload:
./scripts/build_macos.sh --release
```

Ausgabe: `dist/TeamTalk VO Client <VERSION>.dmg`

#### Windows

```powershell
# PowerShell aus dem Projektverzeichnis:
.\scripts\build_windows.ps1

# Mit ZIP-Archiv:
.\scripts\build_windows.ps1 -Release
```

Ausgabe: `dist\TeamTalk VO Client\` (Ordner) + optional `dist\TeamTalk VO Client <VERSION> Windows.zip`

#### Linux

```bash
chmod +x scripts/build_linux.sh
./scripts/build_linux.sh

# Mit tar.gz-Archiv:
./scripts/build_linux.sh --package
```

Ausgabe: `dist/TeamTalk VO Client/` (Ordner) + optional `dist/TeamTalk_VO_Client_<VERSION>_linux_x64.tar.gz`

---

### Requirements-Dateien

| Datei | Zweck |
|-------|-------|
| `requirements_base.txt` | Alle Plattformen (wx, pyaudio, mss, anthropic, …) |
| `requirements_macos.txt` | macOS: inkl. `pyobjc-framework-Quartz` |
| `requirements_windows.txt` | Windows: inkl. `pywin32` |
| `requirements_linux.txt` | Linux: nur base |

Die Skripte installieren automatisch die richtige Datei.

---

### Spec-Dateien (PyInstaller)

| Datei | Plattform |
|-------|-----------|
| `TeamTalk VO Client.spec` | macOS |
| `TeamTalk VO Client_win.spec` | Windows |
| `TeamTalk VO Client_linux.spec` | Linux |

---

### Version ändern

Die Versionsnummer steht an **einer einzigen Stelle**: `src/app.py`

```python
APP_VERSION = "6.2.0"
```

Alle anderen Dateien (Spec, version_info.txt, CHANGELOG.txt) werden beim nächsten Build automatisch gelesen. `version_info.txt` und `TeamTalk VO Client.spec` müssen manuell synchron gehalten werden.

---

### Gitea-Release (macOS)

Das Skript `release.sh` im Projektverzeichnis automatisiert Build + Release vollständig.
Es liest den Token aus `.release_token` (nicht commtten!):

```bash
echo 'DEIN_API_TOKEN' > .release_token
chmod 600 .release_token
./release.sh
```

---

---

## 🇬🇧 English

### Overview

This directory contains build scripts for all supported platforms:

| Script | Platform | Output |
|--------|----------|--------|
| `build_macos.sh` | macOS 11+ (Intel + Apple Silicon) | `.app` + `.dmg` |
| `build_windows.ps1` | Windows 10/11 (64-bit) | Portable folder + `.zip` |
| `build_linux.sh` | Ubuntu 22.04 / Debian 12+ (x64) | Portable folder + `.tar.gz` |

---

### Prerequisites

#### All Platforms

- **Python 3.9–3.12** (not 3.13+, PyInstaller compatibility)
- **Git**
- Internet access for `pip install`

#### macOS

```bash
# Xcode Command Line Tools
xcode-select --install

# Homebrew (if not installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# PortAudio (for pyaudio)
brew install portaudio

# Python (if not installed)
brew install python@3.12
```

#### Windows

- Python 3.9–3.12 from [python.org](https://python.org) – check **"Add Python to PATH"** during install
- [Microsoft Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe)
- Allow PowerShell scripts (once, as Administrator):
  ```powershell
  Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
  ```

#### Linux (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install python3-dev python3-pip python3-venv \
                 portaudio19-dev libgtk-3-dev \
                 libgstreamer1.0-dev gstreamer1.0-plugins-base \
                 xdotool   # for window list under X11
# For Wayland screen capture:
sudo apt install grim
```

---

### Setting Up the TeamTalk SDK

The SDK is **not included in the repository** and must be downloaded separately:

1. Open [https://bearware.dk/teamtalksdk](https://bearware.dk/teamtalksdk)
2. Download the matching version:
   - **macOS:** `tt5sdk_v5.19a_macos_universal.zip` → extract to `third_party/teamtalk/tt5sdk_v5.19a_macos_universal/`
   - **Windows:** `tt5sdk_v5.19a_win64.zip` → extract to `third_party/teamtalk/tt5sdk_v5.19a_win64/`
   - **Linux:** `tt5sdk_v5.19a_linux_x64.tar.gz` → extract to `third_party/teamtalk/tt5sdk_v5.19a_linux_x64/`

Expected structure:
```
third_party/teamtalk/
  tt5sdk_v5.19a_macos_universal/
    Library/
      TeamTalkPy/    ← Python bindings
      TeamTalk_DLL/  ← Native library (.dylib)
  tt5sdk_v5.19a_win64/
    Library/
      TeamTalkPy/
      TeamTalk_DLL/  ← (.dll)
  tt5sdk_v5.19a_linux_x64/
    Library/
      TeamTalkPy/
      TeamTalk_DLL/  ← (.so)
```

---

### BlackHole (macOS, optional)

BlackHole 2ch is required for system audio transmission.
The PKG is already included in the bundle: `third_party/blackhole/BlackHole2ch.pkg`

If the file is missing:
```bash
curl -L "https://github.com/ExistentialAudio/BlackHole/releases/download/v0.6.1/BlackHole2ch-0.6.1.pkg" \
     -o third_party/blackhole/BlackHole2ch.pkg
```

---

### Building

#### macOS

```bash
# From the project directory:
chmod +x scripts/build_macos.sh
./scripts/build_macos.sh

# With optional Gitea release upload:
./scripts/build_macos.sh --release
```

Output: `dist/TeamTalk VO Client <VERSION>.dmg`

#### Windows

```powershell
# PowerShell from the project directory:
.\scripts\build_windows.ps1

# With ZIP archive:
.\scripts\build_windows.ps1 -Release
```

Output: `dist\TeamTalk VO Client\` (folder) + optionally `dist\TeamTalk VO Client <VERSION> Windows.zip`

#### Linux

```bash
chmod +x scripts/build_linux.sh
./scripts/build_linux.sh

# With tar.gz archive:
./scripts/build_linux.sh --package
```

Output: `dist/TeamTalk VO Client/` (folder) + optionally `dist/TeamTalk_VO_Client_<VERSION>_linux_x64.tar.gz`

---

### Requirements Files

| File | Purpose |
|------|---------|
| `requirements_base.txt` | All platforms (wx, pyaudio, mss, anthropic, …) |
| `requirements_macos.txt` | macOS: includes `pyobjc-framework-Quartz` |
| `requirements_windows.txt` | Windows: includes `pywin32` |
| `requirements_linux.txt` | Linux: base only |

The scripts install the correct file automatically.

---

### Spec Files (PyInstaller)

| File | Platform |
|------|----------|
| `TeamTalk VO Client.spec` | macOS |
| `TeamTalk VO Client_win.spec` | Windows |
| `TeamTalk VO Client_linux.spec` | Linux |

---

### Changing the Version

The version number lives in **one place only**: `src/app.py`

```python
APP_VERSION = "6.2.0"
```

All other files (spec, version_info.txt, CHANGELOG.txt) read this value or must be manually kept in sync.

---

### Gitea Release (macOS)

The `release.sh` script in the project root automates build + release.
It reads the API token from `.release_token` (do not commit this file!):

```bash
echo 'YOUR_API_TOKEN' > .release_token
chmod 600 .release_token
./release.sh
```

---

*TeamTalk VoiceOver Client · Lead developer: Florian Lichteblau (Flarion)*
