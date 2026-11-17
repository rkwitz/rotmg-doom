@echo off
rem Starts the local RotMG server, UZDoom and the RotMG client. RotMG comes up full screen
rem with Doom hidden; ~ or RotMG's Doom button swaps to Doom (scripts\duo.py).
cd /d "%~dp0"
python scripts\setup.py play %*
