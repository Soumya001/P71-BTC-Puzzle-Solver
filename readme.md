# P71 Bitcoin Puzzle Solver

This project is a Python-based solver/checker for **Bitcoin Puzzle #71**.

## Features
- Brute-force private key search in defined range
- Puzzle #71 checker (RIPEMD160 target)
- Optional GUI/packaged EXE via PyInstaller

## Build EXE (Windows)
```bash
pip install -r requirements.txt
pyinstaller --onefile --icon=assets/icon.ico puzzle71_checker.py

## Downloads

- Latest Windows EXE: https://github.com/Soumya001/P71-BTC-Puzzle-Solver/releases/latest
- Verify checksum after download:

```powershell
Get-FileHash .\P-71-Solver.exe -Algorithm SHA256
# compare the hash with the value in P-71-Solver.exe.sha256.txt
