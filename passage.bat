@echo off
rem A lancer par le Planificateur de taches Windows, toutes les 30 minutes.
cd /d "%~dp0"
python -m moteur passage --tous >> journal.txt 2>&1
