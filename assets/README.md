# assets

`ThuggyEmuAutomation.png` is the application artwork, and `.ico` is built from
it. The one committed here is a plain placeholder - replace it with whatever you
want.

## Using your own picture

Drag a square PNG onto **`set-icon.bat`**, or run:

```
set-icon.bat "C:\path	o\picture.png"
```

It copies the picture here, crops it to the circle that fits inside the square,
makes everything outside that circle transparent - so a black or coloured
background disappears - writes a multi-size `.ico`, and rebuilds the Desktop
shortcut.

If the Desktop still shows the old icon afterwards, press F5 on the Desktop.
Windows caches shortcut icons.

## Requirements

A non-interlaced, 8-bit PNG. Any size; 256x256 or larger is ideal. Most tools
save this by default - if esdeck refuses the file, re-save it as PNG and retry.
