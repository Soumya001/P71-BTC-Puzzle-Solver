from PyInstaller.utils.hooks import collect_submodules, collect_dynamic_libs

hiddenimports = collect_submodules("coincurve")
binaries = collect_dynamic_libs("coincurve")
