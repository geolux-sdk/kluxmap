nuitka KMagHunters.py ^
--standalone ^
--mingw64 --jobs=8 ^
--plugin-enable=pyside6 ^
--file-reference-choice=runtime ^
--deployment ^
--include-data-files=./img/*.png=./img/ ^
--windows-console-mode=disable ^
--windows-icon-from-ico=./img/viewer.ico

