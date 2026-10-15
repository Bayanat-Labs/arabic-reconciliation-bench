# Reproducing the controlled visual subset

The renderer reads existing `cases` Parquet rows and canonical specs, selects
one complete test family and one complete challenge family per mechanism, and
renders three worlds in the two Arabic numeral views. The selection is the
minimum SHA256 of `arb-visual-v1:` plus the family ID within each group. The
release contains 28 families, 168 packets, and 1,120 document pages. These pages
repeat the text cases; they are not additional independent transactions.

## Recorded production environment

The production render used macOS on arm64, Node.js 24.19.0, Playwright 1.62.1
(and its `playwright-core` 1.62.1 dependency), pdf-lib 1.17.1, and Google Chrome
155.0.8059.40 in a fresh headless browser instance. The Python environment used
Python 3.13, pyarrow 26.0.0, and datasets 5.1.0. The Python requirements and
direct npm dependencies are pinned in `requirements.txt` and `package.json`.
The npm transitive dependency tree is not locked by a supplied lockfile.

The actual browser version, renderer source hashes, font hashes, page hashes,
and counts are recorded in `visual_subset/render_manifest.json`. Selection and
source-job hashes are recorded in `visual_subset/selection_manifest.json`.
The expected selection and document text are deterministic. Exact PDF or image
byte identity across browser versions, operating systems, or rasterizers is
not asserted.

## Required files

Keep `render_packets.py`, `render_packets.cjs`, `audit_visual_subset.py`,
`package.json`, `requirements.txt`, and the entire `fonts/` directory together.
The four bundled TTF files cover Arabic and Latin text in regular and bold:
Noto Sans Arabic 2.010 and Noto Sans 2.015. Each font's source metadata and
SHA256 appear in `fonts/manifest.json`; the copyright notices and SIL Open Font
License 1.1 appear in `fonts/OFL-1.1.txt`. The fonts were obtained from an
existing local LibreOffice distribution, and the TTF name tables independently
declare the same license. No system font installation or font network request
is needed.

The input release must retain `data/cases/{test,challenge}-*.parquet` and
`specs/{test,challenge}.jsonl.gz`. The Python orchestrator uses canonical field
IDs and row-group IDs to check coverage. The browser receives only the already
visible document text, title, ID, and these expected field markers. Canonical
fact values, internal document roles, mechanisms, worlds, and gold answers are
never used in page HTML.

## Run from a downloaded dataset repository

These commands assume the scripts are packaged in `code/` and the dataset
repository is the current directory. In the original development repository,
the equivalent source directory is `research/arabic-reconciliation-bench/`.
Use a fresh copy of the dataset if retaining the shipped files matters: the
render command rewrites `visual_subset/` and `data/pages/`.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r code/requirements.txt
npm install --prefix code
```

Provide a compatible existing Chromium or Chrome executable explicitly:

```sh
python code/render_packets.py \
  --release-dir . \
  --work-dir ../arabic-reconciliation-render-work \
  --node-modules-dir code/node_modules \
  --chrome-executable /path/to/chrome
```

Alternatively install Playwright's Chromium, then omit `--chrome-executable`:

```sh
cd code
npx playwright install chromium
cd ..
python code/render_packets.py \
  --release-dir . \
  --work-dir ../arabic-reconciliation-render-work \
  --node-modules-dir code/node_modules
```

The Chromium download in the latter command is external to this dataset. A
Linux host may additionally need Playwright's documented browser system
dependencies. The renderer launches a separate headless instance and never
attaches to a user's active browser profile or tabs. Only one rendering
instance is needed; no web access is used to lay out the documents.

Audit the entire rendered subset after completion:

```sh
python code/audit_visual_subset.py --release-dir .
```

The report is written to `visual_subset/validation_report.json`. Review image
samples as well as this report. Structural validation is not an expert review
of Arabic language or procurement accounting.

## Outputs and coordinates

Each packet has a multipage `packet.pdf`, `visible_text.json`, and
`field_boxes.json`. Every visible source document occupies exactly one page.
PNGs are 794 by 1,123 pixels and are embedded once in the Hugging Face `pages`
configuration under `data/pages/`. By default, individual PNG copies are kept
only in the supplied work directory for inspection. `--keep-pngs` additionally
retains duplicate public PNGs; the released dataset uses the default.

The `image` feature contains PNG bytes and a null path; `datasets` can decode
it with Pillow, which is included in the Python requirements. Each page row
also carries its case/family/document IDs, question, original document text,
PDF path, and serialized field boxes. The field boxes describe DOM field
containers, not individual glyphs or human-annotated OCR regions. One CSS pixel
equals one PNG pixel. PDF boxes are the corresponding page-coordinate scaling.

The renderer checks missing or repeated fields, content overflow, one PDF page
per document, and literal character order inside numeric/date/identifier
tokens. Directional isolation with an LTR override preserves the original
order of Arabic-Indic ISO dates. The audit checks source-text equality, image
CRC and hashes, associations, field coverage and bounds, font character
coverage, and the one-changed-document contrastive image property.

All source files and font assets required for this render are included. Node,
the Python dependencies, and a Chromium executable are runtime prerequisites
rather than bundled executables.
