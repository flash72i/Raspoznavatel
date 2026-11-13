# -*- coding: utf-8 -*-
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHELL = ROOT / "installer_custom" / "SetupShell.exe"
BACKEND = ROOT / "dist" / "Raspoznavatel-2.7.0-Setup-Inno.exe"
OUT = ROOT / "dist" / "Raspoznavatel-2.7.0-Setup-WebUI.exe"

shell = SHELL.read_bytes()
backend = BACKEND.read_bytes()

footer = b"RSPINNO1" + struct.pack("<qq", len(shell), len(backend))
OUT.write_bytes(shell + backend + footer)

print("SHELL", len(shell))
print("BACKEND", len(backend))
print("OUT", OUT, OUT.stat().st_size)
