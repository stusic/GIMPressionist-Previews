# GIMPressionist Preview

Explore GIMP’s GIMPressionist filter with adjustable controls and a large side-by-side preview. Change brush size and shape, stroke density and orientation, paper texture, or color, then render with GIMP’s native filter. The utility opens in your browser and processes images locally.

## Requirements

- [GIMP 3.x](https://www.gimp.org/downloads/) with the GIMPressionist plug-in and GIMP’s Python batch interpreter.
- [Python 3.8 or newer](https://www.python.org/downloads/) on your command line. The script uses Python’s standard library.
- A web browser and a copy of [gimpressionist_preview.py](gimpressionist_preview.py).

## Run the utility

Open a terminal in the folder containing `gimpressionist_preview.py`.

**Windows (PowerShell)**

```powershell
py .\gimpressionist_preview.py
```

**macOS or Linux**

```sh
python3 ./gimpressionist_preview.py
```

The script opens the preview page in your default browser. If the page does not open automatically, copy the local address printed in the terminal into your browser. Keep the terminal open while using the utility. Press **Ctrl+C** in the terminal to stop it.

## Generate a preview

1. Click **Open image** and choose a file. The utility renders an initial preview.
2. Adjust the controls under **Brush & size**, **Orientation & placement**, **Paper**, or **Color & finish**.
3. Click **Generate preview** to apply your changes. Use **Reset** to restore the starting settings.
4. Click either image to inspect it at its rendered size. Click **Save PNG** to download the displayed result.

**Preview size** sets the maximum length of the image’s longest side. Choose 480 px for quick experiments, 800 px for the default, or 1,200 px to inspect finer detail. Smaller source images stay at their original dimensions. **Save PNG** exports the rendered preview at that size, and brush size is measured in pixels at the render resolution. GIMPressionist uses randomness, so repeated renders with identical settings can look slightly different.

The file picker accepts JPG, PNG, WebP, AVIF, TIFF, BMP, GIF, and XCF files up to 100 MB. For a layered XCF, the preview uses the merged visible layers.

## Compatibility and troubleshooting

The full workflow was tested with **GIMP 3.0.4 on Linux**. The launcher searches common Windows and macOS install locations and checks the system PATH. Those Windows and macOS launch paths are unverified. Flatpak and Snap packages may require a launcher adjustment because GIMP and the script need access to the same temporary files.

- **GIMP was not found.** Re-run the launch command with `--gimp` followed by the quoted path to your GIMP executable. For example, if your Windows installation has the console executable at this location:

  ```powershell
  py .\gimpressionist_preview.py --gimp "C:\Program Files\GIMP 3\bin\gimp-console-3.0.exe"
  ```

- **GIMP did not render the preview.** Check the message in the browser and any details printed in the terminal. Confirm that the selected GIMP installation includes GIMPressionist and supports the `python-fu-eval` batch interpreter.
- **The image is too small for the chosen brush.** Reduce **Maximum size** or choose a higher **Preview size** if the source has enough pixels.
