# TeamTalk VoiceOver Client – macOS Installationsanleitung
# TeamTalk VoiceOver Client – macOS Installation Guide
# TeamTalk VoiceOver Client – Guide d'installation macOS
# TeamTalk VoiceOver Client – Guía de instalación macOS

Version 6.1.6 · Florian Lichteblau (Flarion)

---

## 🇩🇪 Deutsch

### Systemvoraussetzungen

- macOS 11 Big Sur oder neuer
- VoiceOver (eingebaut in macOS, keine zusätzliche Software nötig)
- Optional: Braillezeile (wird von VoiceOver automatisch erkannt)

### Schritt 1 – TeamTalk VoiceOver Client installieren

1. Die Datei `TeamTalk VO Client 6.1.6.dmg` öffnen (Doppelklick).
2. Das App-Symbol `TeamTalk VO Client.app` in den Ordner **Programme** ziehen.
3. Das DMG-Fenster schließen und das Laufwerk auswerfen.
4. Die App zum ersten Mal starten:
   - Im Finder zum Ordner **Programme** navigieren.
   - Auf `TeamTalk VO Client.app` **Rechtsklick → Öffnen** wählen.
   - Den Dialog mit **Öffnen** bestätigen (einmalig nötig wegen Gatekeeper).
5. Wenn macOS nach der **Mikrofon-Berechtigung** fragt: **OK** klicken.

> **Hinweis:** Das einmalige Rechtsklick → Öffnen ist nur beim allerersten Start nötig.
> Danach startet die App normal per Doppelklick oder mit VoiceOver.

### Schritt 2 – Systemton übertragen (BlackHole, optional)

BlackHole ist ein kostenloses virtuelles Audiogerät. Damit kann der Systemton des Mac
(Musik, Sprache aus anderen Apps usw.) über TeamTalk an andere übertragen werden.

**Ist BlackHole im Bundle enthalten?**
Ja – die PKG-Datei liegt bereits in der App unter
`TeamTalk VO Client.app/Contents/MacOS/third_party/blackhole/BlackHole2ch.pkg`.

**Installation:**

1. In der App: **Einstellungen → Audio** öffnen.
2. Im Bereich **Systemton** auf **"BlackHole installieren"** klicken.
   - Die App startet den Installer automatisch.
3. Den macOS-Installer durchlaufen (Passwort eingeben wenn gefragt).
4. Nach Abschluss: in der App auf **"Geräte aktualisieren"** klicken.
5. Als Eingabegerät **"[Systemton] BlackHole 2ch"** auswählen.
6. **Audio anwenden** klicken – fertig.

Alternativ über Homebrew (falls installiert):
```
brew install blackhole-2ch
```

**BlackHole manuell installieren (ohne App-Hilfe):**
1. Im Finder: Rechtsklick auf `TeamTalk VO Client.app → Paketinhalt zeigen`.
2. Navigieren zu `Contents/MacOS/third_party/blackhole/`.
3. `BlackHole2ch.pkg` doppelklicken und Installer folgen.

### Schritt 3 – Ersten Server einrichten

1. App starten.
2. Im Bereich **Verbindung**: Serveradresse, Port, Benutzername und Passwort eintragen.
3. **Verbinden** klicken (Alt+V / Enter).
4. Kanal aus der Liste auswählen und **Kanal beitreten** klicken.

### Deinstallation

1. `TeamTalk VO Client.app` aus dem Programme-Ordner in den Papierkorb ziehen.
2. Einstellungen entfernen (optional):
   ```
   ~/Library/Application Support/TeamTalkVOClient/
   ~/Library/Preferences/com.flarion.teamtalk-vo-client.plist
   ```
3. BlackHole entfernen (optional): `System → Erweiterungen → BlackHole 2ch → Entfernen`
   oder `brew uninstall blackhole-2ch`.

---

## 🇬🇧 English

### System Requirements

- macOS 11 Big Sur or later
- VoiceOver (built into macOS, no additional software required)
- Optional: Braille display (automatically recognised by VoiceOver)

### Step 1 – Install TeamTalk VoiceOver Client

1. Open the file `TeamTalk VO Client 6.1.6.dmg` (double-click).
2. Drag the app icon `TeamTalk VO Client.app` into the **Applications** folder.
3. Close the DMG window and eject the volume.
4. Launch the app for the first time:
   - In Finder, navigate to the **Applications** folder.
   - **Right-click → Open** on `TeamTalk VO Client.app`.
   - Confirm the dialog by clicking **Open** (required once due to Gatekeeper).
5. When macOS asks for **Microphone permission**: click **OK**.

> **Note:** The right-click → Open step is only needed on the very first launch.
> After that, the app opens normally with a double-click or via VoiceOver.

### Step 2 – Transmit System Audio (BlackHole, optional)

BlackHole is a free virtual audio device. It lets you transmit your Mac's system audio
(music, speech from other apps, etc.) through TeamTalk to other participants.

**Is BlackHole included in the bundle?**
Yes – the PKG installer is already inside the app at
`TeamTalk VO Client.app/Contents/MacOS/third_party/blackhole/BlackHole2ch.pkg`.

**Installation:**

1. In the app: open **Settings → Audio**.
2. In the **System Audio** section, click **"Install BlackHole"**.
   - The app will launch the installer automatically.
3. Follow the macOS installer (enter your password if prompted).
4. Once done: click **"Refresh Devices"** in the app.
5. Select **"[System Audio] BlackHole 2ch"** as the input device.
6. Click **Apply Audio** – done.

Alternatively via Homebrew (if installed):
```
brew install blackhole-2ch
```

**Installing BlackHole manually (without the app helper):**
1. In Finder: right-click `TeamTalk VO Client.app → Show Package Contents`.
2. Navigate to `Contents/MacOS/third_party/blackhole/`.
3. Double-click `BlackHole2ch.pkg` and follow the installer.

### Step 3 – Set Up Your First Server

1. Launch the app.
2. In the **Connection** panel: enter the server address, port, username and password.
3. Click **Connect** (Alt+V / Enter).
4. Select a channel from the list and click **Join Channel**.

### Uninstalling

1. Drag `TeamTalk VO Client.app` from the Applications folder to the Trash.
2. Remove preferences (optional):
   ```
   ~/Library/Application Support/TeamTalkVOClient/
   ~/Library/Preferences/com.flarion.teamtalk-vo-client.plist
   ```
3. Remove BlackHole (optional): `System → Extensions → BlackHole 2ch → Remove`
   or `brew uninstall blackhole-2ch`.

---

## 🇫🇷 Français

### Configuration requise

- macOS 11 Big Sur ou version ultérieure
- VoiceOver (intégré à macOS, aucun logiciel supplémentaire requis)
- Optionnel : plage braille (reconnue automatiquement par VoiceOver)

### Étape 1 – Installer TeamTalk VoiceOver Client

1. Ouvrir le fichier `TeamTalk VO Client 6.1.6.dmg` (double-clic).
2. Faire glisser l'icône `TeamTalk VO Client.app` dans le dossier **Applications**.
3. Fermer la fenêtre DMG et éjecter le volume.
4. Lancer l'application pour la première fois :
   - Dans le Finder, naviguer jusqu'au dossier **Applications**.
   - Faire un **Clic droit → Ouvrir** sur `TeamTalk VO Client.app`.
   - Confirmer en cliquant sur **Ouvrir** (nécessaire une seule fois à cause de Gatekeeper).
5. Lorsque macOS demande la **permission d'accès au microphone** : cliquer sur **OK**.

> **Remarque :** Le clic droit → Ouvrir n'est nécessaire qu'au tout premier lancement.
> Ensuite, l'application s'ouvre normalement par double-clic ou via VoiceOver.

### Étape 2 – Transmettre le son système (BlackHole, optionnel)

BlackHole est un périphérique audio virtuel gratuit. Il permet de transmettre le son
système du Mac (musique, voix d'autres applications, etc.) via TeamTalk aux autres
participants.

**BlackHole est-il inclus dans le bundle ?**
Oui – le fichier PKG se trouve déjà dans l'application à l'emplacement
`TeamTalk VO Client.app/Contents/MacOS/third_party/blackhole/BlackHole2ch.pkg`.

**Installation :**

1. Dans l'application : ouvrir **Réglages → Audio**.
2. Dans la section **Son système**, cliquer sur **"Installer BlackHole"**.
   - L'application lance l'installeur automatiquement.
3. Suivre l'installeur macOS (saisir le mot de passe si demandé).
4. Une fois terminé : cliquer sur **"Actualiser les périphériques"** dans l'application.
5. Sélectionner **"[Son système] BlackHole 2ch"** comme périphérique d'entrée.
6. Cliquer sur **Appliquer l'audio** – terminé.

Alternativement via Homebrew (si installé) :
```
brew install blackhole-2ch
```

**Installer BlackHole manuellement (sans l'aide de l'application) :**
1. Dans le Finder : clic droit sur `TeamTalk VO Client.app → Afficher le contenu du paquet`.
2. Naviguer vers `Contents/MacOS/third_party/blackhole/`.
3. Double-cliquer sur `BlackHole2ch.pkg` et suivre l'installeur.

### Étape 3 – Configurer votre premier serveur

1. Lancer l'application.
2. Dans le panneau **Connexion** : saisir l'adresse du serveur, le port, le nom d'utilisateur
   et le mot de passe.
3. Cliquer sur **Connecter** (Alt+V / Entrée).
4. Sélectionner un salon dans la liste et cliquer sur **Rejoindre le salon**.

### Désinstallation

1. Faire glisser `TeamTalk VO Client.app` du dossier Applications vers la Corbeille.
2. Supprimer les préférences (optionnel) :
   ```
   ~/Library/Application Support/TeamTalkVOClient/
   ~/Library/Preferences/com.flarion.teamtalk-vo-client.plist
   ```
3. Supprimer BlackHole (optionnel) : `Système → Extensions → BlackHole 2ch → Supprimer`
   ou `brew uninstall blackhole-2ch`.

---

## 🇪🇸 Español

### Requisitos del sistema

- macOS 11 Big Sur o posterior
- VoiceOver (integrado en macOS, sin software adicional)
- Opcional: pantalla Braille (reconocida automáticamente por VoiceOver)

### Paso 1 – Instalar TeamTalk VoiceOver Client

1. Abrir el archivo `TeamTalk VO Client 6.1.6.dmg` (doble clic).
2. Arrastrar el icono `TeamTalk VO Client.app` a la carpeta **Aplicaciones**.
3. Cerrar la ventana del DMG y expulsar el volumen.
4. Iniciar la aplicación por primera vez:
   - En el Finder, navegar a la carpeta **Aplicaciones**.
   - Hacer **clic derecho → Abrir** sobre `TeamTalk VO Client.app`.
   - Confirmar haciendo clic en **Abrir** (necesario una sola vez por Gatekeeper).
5. Cuando macOS solicite el **permiso de micrófono**: hacer clic en **OK**.

> **Nota:** El paso clic derecho → Abrir solo es necesario en el primer inicio.
> Después, la aplicación se abre normalmente con doble clic o mediante VoiceOver.

### Paso 2 – Transmitir audio del sistema (BlackHole, opcional)

BlackHole es un dispositivo de audio virtual gratuito. Permite transmitir el audio del
sistema Mac (música, voz de otras aplicaciones, etc.) a través de TeamTalk a otros
participantes.

**¿BlackHole está incluido en el bundle?**
Sí – el instalador PKG ya está dentro de la aplicación en
`TeamTalk VO Client.app/Contents/MacOS/third_party/blackhole/BlackHole2ch.pkg`.

**Instalación:**

1. En la aplicación: abrir **Ajustes → Audio**.
2. En la sección **Audio del sistema**, hacer clic en **"Instalar BlackHole"**.
   - La aplicación lanza el instalador automáticamente.
3. Seguir el instalador de macOS (introducir la contraseña si se solicita).
4. Una vez completado: hacer clic en **"Actualizar dispositivos"** en la aplicación.
5. Seleccionar **"[Audio del sistema] BlackHole 2ch"** como dispositivo de entrada.
6. Hacer clic en **Aplicar audio** – listo.

Alternativamente mediante Homebrew (si está instalado):
```
brew install blackhole-2ch
```

**Instalar BlackHole manualmente (sin la ayuda de la aplicación):**
1. En el Finder: clic derecho en `TeamTalk VO Client.app → Mostrar contenido del paquete`.
2. Navegar a `Contents/MacOS/third_party/blackhole/`.
3. Hacer doble clic en `BlackHole2ch.pkg` y seguir el instalador.

### Paso 3 – Configurar el primer servidor

1. Iniciar la aplicación.
2. En el panel **Conexión**: introducir la dirección del servidor, el puerto, el nombre de
   usuario y la contraseña.
3. Hacer clic en **Conectar** (Alt+V / Intro).
4. Seleccionar un canal de la lista y hacer clic en **Unirse al canal**.

### Desinstalación

1. Arrastrar `TeamTalk VO Client.app` desde la carpeta Aplicaciones a la Papelera.
2. Eliminar preferencias (opcional):
   ```
   ~/Library/Application Support/TeamTalkVOClient/
   ~/Library/Preferences/com.flarion.teamtalk-vo-client.plist
   ```
3. Eliminar BlackHole (opcional): `Sistema → Extensiones → BlackHole 2ch → Eliminar`
   o `brew uninstall blackhole-2ch`.

---

*TeamTalk VoiceOver Client v6.1.6 · Hauptentwickler / Lead developer: Florian Lichteblau (Flarion)*
*BlackHole 2ch v0.6.1 · © ExistentialAudio · MIT License · existential.audio/BlackHole*
