"""Resolve explicitly configured workspace paths; no machine-specific defaults."""
from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CONFIG_PATH=ROOT/'workspace.local.json'
if not CONFIG_PATH.exists():
    raise FileNotFoundError(f'Configure {CONFIG_PATH} first; see scripts/bootstrap_workspace.py --help')
CONFIG=json.loads(CONFIG_PATH.read_text(encoding='utf-8-sig'))


def configured_path(key,default=None):
    value=CONFIG.get(key,default)
    if value is None:return None
    path=Path(value)
    return (path if path.is_absolute() else ROOT/path).resolve()


AUDIO_DIR=configured_path('audio_dir')
ORIGINAL_PACKAGE=configured_path('original_package_dir')
OUTPUT_DIR=configured_path('output_dir','releases')
REFERENCE_PROJECT=configured_path('reference_project_dir','work/fmod-reference')
RUNTIME_DIR=configured_path('runtime_dir','tools/runtime-2.02.14')
VGMSTREAM=configured_path('vgmstream_exe','tools/vgmstream/vgmstream-cli.exe')
FMOD_CLI=configured_path('fmod_cli')
GAME_ROOT=configured_path('game_root')
GAME_MOD_DIR=GAME_ROOT/'sound/mod' if GAME_ROOT else None
VERIFY_INSTALLED=bool(CONFIG.get('verify_installed',False))
REFERENCE_MASTER=configured_path('reference_master_dir')
REFERENCE_LEGACY=configured_path('reference_legacy_dir')
REFERENCE_WORK=configured_path('reference_work_dir')
