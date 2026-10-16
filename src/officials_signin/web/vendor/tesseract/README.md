# Bundled OCR engine (Tesseract.js)

These files let the sign-in page read USA Swimming membership cards with the
camera **offline**: the app serves them from `localhost`, so there is no CDN and
nothing to install beyond Python 3 and Chrome (Android/Termux, ChromeOS, macOS, Linux).

| File | From npm package | License |
|---|---|---|
| `tesseract.min.js`, `worker.min.js` | `tesseract.js@7.0.0` (`dist/`) | Apache-2.0 (`LICENSE-tesseract.js.md`) |
| `tesseract-core-simd-lstm.wasm.js` | `tesseract.js-core@7.0.0` | Apache-2.0 (`LICENSE-tesseract.js-core`) |
| `eng.traineddata.gz` | `@tesseract.js-data/eng@1.0.0` (`4.0.0_best_int/`) | npm package MIT; the data is Tesseract's `tessdata_best` (integer build), Apache-2.0 |

Only the SIMD + LSTM core build is bundled (all current Chrome versions support
WebAssembly SIMD); the page points `corePath` straight at it.

To update: `npm install tesseract.js@<version> @tesseract.js-data/eng` in a scratch
folder, copy the same files here, update this table, and re-test card reading on
the tablet.
