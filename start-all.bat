@echo off
REM ==========================================================================
REM One-click launcher -- thin bootstrap. THIS FILE MUST STAY PURE ASCII.
REM
REM Reason (measured in v5.38): cmd.exe loses byte offsets when it parses a
REM UTF-8 batch file under "chcp 65001". Any multi-byte character (Chinese
REM text or box-drawing banners) can make cmd chop the FOLLOWING lines and
REM try to execute the fragments ("'xxx' is not recognized as an internal or
REM external command"), and a comment containing ">=" even becomes a
REM redirection that writes a junk file into the project root.
REM
REM All real logic and every Chinese message therefore live in start-all.ps1,
REM saved as UTF-8 with BOM and parsed by PowerShell, which has no such issue.
REM
REM Extra arguments are forwarded, e.g.:  start-all.bat -DryRun
REM ==========================================================================
title Exam System Launcher
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-all.ps1" %*
if errorlevel 1 echo [ERROR] start-all.ps1 failed. Check the messages above.
if errorlevel 1 pause
