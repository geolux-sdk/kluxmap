nuitka KMagHunters.py ^
--mingw64 --jobs=8 ^
--plugin-enable=pyside6 ^
--onefile ^
--file-reference-choice=runtime ^
--deployment ^
--include-data-files=./img/*.png=./img/ ^
--windows-console-mode=disable ^
--windows-icon-from-ico=./img/viewer.ico

