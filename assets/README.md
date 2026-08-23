# assets

Put the application artwork here as **`ThuggyEmuAutomation.png`** — a square PNG,
non-interlaced, 8-bit. Any size works; 256x256 or larger is ideal.

Setup crops it to the circle that fits inside the square, makes everything
outside that circle transparent (so a black or coloured background disappears),
writes `ThuggyEmuAutomation.ico`, and puts a Desktop shortcut on it.

To do it by hand at any time:

```
esdeck icon assets\ThuggyEmuAutomation.png --shortcut ThuggyEmuAutomation.bat
```
