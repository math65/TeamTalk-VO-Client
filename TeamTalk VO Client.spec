# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src/app.py'],
    pathex=['src', 'third_party/teamtalk/tt5sdk_v5.19a_macos_universal/Library/TeamTalkPy'],
    binaries=[],
    datas=[('src/teamtalk_client', 'teamtalk_client'), ('src/platform_paths.py', '.'), ('src/ui', 'ui'), ('third_party/teamtalk/tt5sdk_v5.19a_macos_universal/Library/TeamTalkPy', 'TeamTalkPy'), ('third_party/teamtalk/tt5sdk_v5.19a_macos_universal/Library/TeamTalk_DLL', 'TeamTalk_DLL'), ('third_party/yt-dlp', 'yt-dlp'), ('third_party/espeak-ng', 'espeak-ng')],
    hiddenimports=['teamtalk_client', 'teamtalk_client.tt', 'teamtalk_client.client', 'ui.tabs.system', 'platform_paths'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TeamTalk VO Client',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TeamTalk VO Client',
)
app = BUNDLE(
    coll,
    name='TeamTalk VO Client.app',
    icon=None,
    bundle_identifier=None,
    info_plist={
        'NSMicrophoneUsageDescription': 'Dieses TeamTalk-Client braucht Mikrofonzugriff, um Audio zu senden.',
    },
)
