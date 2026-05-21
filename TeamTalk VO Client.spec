# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src/app.py'],
    pathex=['src', 'third_party/teamtalk/tt5sdk_v5.19a_macos_universal/Library/TeamTalkPy'],
    binaries=[],
    datas=[('src/teamtalk_client', 'teamtalk_client'), ('src/platform_paths.py', '.'), ('src/ui', 'ui'), ('src/ui_wx', 'ui_wx'), ('src/chat_history.py', '.'), ('src/global_hotkeys.py', '.'), ('licenses', 'licenses'), ('CHANGELOG.txt', '.'), ('INSTALL_macOS.md', '.'), ('src/manual.html', '.'), ('third_party/teamtalk/tt5sdk_v5.19a_macos_universal/Library/TeamTalkPy', 'TeamTalkPy'), ('third_party/teamtalk/tt5sdk_v5.19a_macos_universal/Library/TeamTalk_DLL', 'TeamTalk_DLL'), ('third_party/yt-dlp', 'yt-dlp'), ('third_party/espeak-ng', 'espeak-ng'), ('third_party/blackhole', 'third_party/blackhole'), ('src/sounds', 'sounds')],
    hiddenimports=['app_wx', 'teamtalk_client', 'teamtalk_client.tt', 'teamtalk_client.client', 'ui.tabs.system', 'ui_wx.tabs.system', 'platform_paths', 'sound_manager', 'objc', 'AppKit', 'Quartz', 'chat_history', 'global_hotkeys', 'pyaudio', 'i18n', 'mss', 'mss.tools', 'screen_capture', 'system_audio'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['whisper', 'torch', 'numba', 'numba.core', 'llvmlite', 'tiktoken', 'tiktoken_ext', 'tiktoken_ext.openai_public'],
    noarchive=False,
    optimize=2,
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
        'CFBundleShortVersionString': '7.1.0',
        'CFBundleVersion': '7.1.0',
        'NSMicrophoneUsageDescription': 'Der TeamTalk VO Client benötigt Zugriff auf das Mikrofon, um Sprache übertragen zu können.',
    },
)
