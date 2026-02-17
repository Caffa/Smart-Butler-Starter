# Menu bar icons

Optional PNGs for the Note Router menu bar app. Place them in this folder:

- **default.png** — Shown when no active workflows (menubar and Dock).
- **active.png** — Shown when one or more workflows are running (menubar and Dock).

If these files are missing, the app shows the text title "Note" in the menubar; the Dock will show the default Python icon when running with pythonw.

---

## Creating icons in Canva

### 1. Canvas size

Create a **custom size** design in Canva:

- **44 × 44 px** — recommended; works well on both standard and Retina displays.

Canva’s minimum is 40 × 40 px, so 44 × 44 fits and gives good quality. Use a **transparent background**.

### 2. Design tips

- Keep the icon **simple and recognizable** at small size.
- Use **dark shapes** on transparency — the menubar is usually light; macOS may invert colors in dark mode.
- Leave a few pixels of padding; avoid edge-to-edge art.
- For **active.png**, use a subtle visual difference (e.g. filled vs outline, different color, small indicator dot).

### 3. Export

1. **Share** → **Download**
2. Format: **PNG**
3. Enable **Transparent background**
4. Quality: **Best**
5. Download

### 4. Save files

Rename and place in this folder:

```
Note Sorting Scripts/menubar/icons/
├── default.png
└── active.png
```

### Optional: @2x for Retina

For crisper display on Retina Macs, you can add:

- `default@2x.png` (44 × 44 px)
- `active@2x.png` (44 × 44 px)

If `@2x` variants exist, macOS will use them on Retina displays automatically.
