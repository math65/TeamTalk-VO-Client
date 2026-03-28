# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src/app.py'],
    pathex=['src', 'third_party/teamtalk/tt5sdk_v5.19a_macos_universal/Library/TeamTalkPy'],
    binaries=[],
    datas=[('src/teamtalk_client', 'teamtalk_client'), ('src/platform_paths.py', '.'), ('src/ui', 'ui'), ('src/chat_history.py', '.'), ('src/global_hotkeys.py', '.'), ('licenses', 'licenses'), ('CHANGELOG.txt', '.'), ('src/manual.html', '.'), ('third_party/teamtalk/tt5sdk_v5.19a_macos_universal/Library/TeamTalkPy', 'TeamTalkPy'), ('third_party/teamtalk/tt5sdk_v5.19a_macos_universal/Library/TeamTalk_DLL', 'TeamTalk_DLL'), ('third_party/yt-dlp', 'yt-dlp'), ('third_party/espeak-ng', 'espeak-ng'), ('src/sounds', 'sounds'), ('.venv/lib/python3.9/site-packages/whisper/assets', 'whisper/assets')],
    hiddenimports=['teamtalk_client', 'teamtalk_client.tt', 'teamtalk_client.client', 'ui.tabs.system', 'platform_paths', 'sound_manager', 'objc', 'AppKit', 'chat_history', 'global_hotkeys', 'whisper', 'whisper.audio', 'whisper.decoding', 'whisper.model', 'whisper.tokenizer', 'whisper.transcribe', 'tiktoken', 'tiktoken_ext', 'tiktoken_ext.openai_public', 'pyaudio', 'numba', 'numba.core', 'llvmlite'],
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
        'CFBundleShortVersionString': '2.1.0',
        'CFBundleVersion': '2.1.0',
        'NSMicrophoneUsageDescription': 'Der TeamTalk VO Client benötigt Zugriff auf das Mikrofon, um Sprache übertragen zu können.',
    },
)
