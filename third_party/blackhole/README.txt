BlackHole 2ch – Virtuelles CoreAudio-Gerät für macOS
=====================================================

Dieses Verzeichnis ist der Ablageort für das BlackHole-Installationspaket,
das in den App-Bundle eingebunden wird.

SCHRITT: PKG hier ablegen
--------------------------
1. BlackHole 2ch herunterladen: https://existingaudio.com/BlackHole
   Oder via Homebrew: brew install blackhole-2ch
   Direkt-Download (GitHub Releases):
   https://github.com/ExistingAudio/BlackHole/releases/latest

2. Die Datei "BlackHole2ch.pkg" in dieses Verzeichnis legen.

3. PyInstaller-Build ausführen – das PKG wird automatisch in den Bundle kopiert.

Lizenz: BlackHole ist MIT-lizenziert.
        https://github.com/ExistingAudio/BlackHole/blob/master/LICENSE

Warum BlackHole?
----------------
BlackHole ist ein kostenloser, quelloffener CoreAudio-Treiber der ein
virtuelles Loopback-Audiogerät bereitstellt. Damit kann der Systemton
des Mac (z.B. Musik, Sprache aus anderen Apps) über TeamTalk übertragen werden:

  System-Audioausgabe → BlackHole 2ch → TeamTalk-Eingabegerät → Kanal

Alternative: Rogue Amoeba "Loopback" (kostenpflichtig, mehr Funktionen).
