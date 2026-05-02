#!/usr/bin/env zsh
# zshrc-snippets.sh — Useful aliases to add to ~/.zshrc
#
# Source this file or copy the relevant sections into your ~/.zshrc.

# ─── Keep Awake (prevents Mac sleep) ────────────────────────────────────────
# Requires: keep_awake.sh to be placed at $HOME/keep_awake.sh
alias awake-start='zsh $HOME/keep_awake.sh start'
alias awake-stop='zsh $HOME/keep_awake.sh stop'
alias awake-status='zsh $HOME/keep_awake.sh status'

# ─── Android Tablet Mirroring via scrcpy ────────────────────────────────────
# Requires: scrcpy (brew install scrcpy)
# Device: Samsung S9+ Ultra

# High quality mode (100Mbps, H.265, 120fps, 2800px)
alias tablet='scrcpy --video-codec=h265 --video-encoder='"'"'c2.qti.hevc.encoder'"'"' --video-bit-rate=100M --max-size=2800 --max-fps=120 --audio-codec=flac --keyboard=uhid --mouse=uhid --mouse-bind=++++ --turn-screen-off --stay-awake --power-off-on-close --window-title="S9+ Ultra"'

# Stable mode (40Mbps, H.265, 120fps, 2560px, audio buffer for stability)
alias stable-tablet='scrcpy --video-codec=h265 --video-encoder='"'"'c2.qti.hevc.encoder'"'"' --video-bit-rate=40M --max-size=2560 --max-fps=120 --audio-codec=flac --audio-buffer=100 --keyboard=uhid --mouse=uhid --mouse-bind=++++ --turn-screen-off --stay-awake --window-title="S9+ 2K Stable"'
