# Getting Started

Requirements, installation, troubleshooting and full command-line usage for
Pitwall. For what the app does, see the [main README](../README.md).

## Requirements

- Python 3.11+ (CI covers 3.10–3.12)
- [FastF1](https://github.com/theOehrly/Fast-F1) (Formula 1 data)
- [Arcade](https://api.arcade.academy/en/latest/) (rendering)
- [pdfplumber](https://github.com/jsvine/pdfplumber) (MotoGP timing sheets)
- numpy, pandas, requests, PySide6

Install dependencies:
```bash
pip install -r requirements.txt
```

The FastF1 cache folder is created automatically on first run. MotoGP data is
cached under `computed_data/motogp/`.

> **First-run notice:** Loading a session for the first time is slower because
> data must be downloaded, processed and cached locally. Later launches of the
> same session are much faster.

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Rm1n90/pitwall
   cd pitwall
   ```
2. **Create a virtual environment:**
   - macOS/Linux:
     ```bash
     python3 -m venv venv
     source venv/bin/activate
     ```
   - Windows:
     ```bash
     python -m venv venv
     .\venv\Scripts\activate
     ```
3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
4. **Run the application** using the Usage section below.

## Troubleshooting

If pulling F1 data fails, upgrade FastF1:
```bash
pip install --upgrade fastf1
```

**conda environments** may need an extra package if you hit
`arcade.application.NoOpenGLException: Unable to create an OpenGL 3.3+ context`:

```bash
conda install -c conda-forge libstdcxx-ng
```

Thanks to @el-mandaloriano for the fix (#12).

## Usage

**Default GUI menu.** Run with no arguments:
```bash
python main.py
```

![GUI Menu Preview](../resources/gui-menu.png)

Pick the **Series** (Formula 1 or MotoGP), then the year and event. For F1,
select a race weekend and session; for MotoGP, select an event and one of its
MotoGP / Moto2 / Moto3 race or sprint buttons.

**Optional CLI menu:**
```bash
python main.py --cli
```

![CLI Menu Preview](../resources/cli-menu.gif)

### Formula 1 from the command line

```bash
python main.py --viewer --year 2025 --round 12               # race
python main.py --viewer --year 2025 --round 12 --no-hud      # without HUD
python main.py --viewer --year 2025 --round 12 --sprint      # sprint
python main.py --viewer --year 2025 --round 12 --practice 1  # practice
python main.py --viewer --year 2025 --round 12 --qualifying  # qualifying
python main.py --viewer --year 2025 --round 12 --qualifying --sprint  # sprint qualifying
```

Practice has no grid and no finishing order, so the tower ranks on best lap and
the HUD counts the session down. A sprint weekend runs one practice session; a
normal weekend runs three. Add `--refresh-data` to force re-computation of a
cached session.

### MotoGP from the command line

```bash
python main.py --motogp --year 2025 --event THA --class MotoGP --session RAC
python main.py --motogp --year 2025 --event THA --class Moto2  --session RAC
python main.py --motogp --year 2025 --event THA --class MotoGP --session SPR
python main.py --motogp-live
```

`--event` takes the three-letter event code (`THA`, `NED`, `ITA`, …);
`--class` is `MotoGP`, `Moto2` or `Moto3`; `--session` is `RAC` or `SPR`.

MotoGP timing sheets are © Dorna and are not distributed with the project; the
tests fetch them locally with `../tests/fixtures/motogp/download_pdfs.py`. See
[MotoGPDataSources.md](./MotoGPDataSources.md) for details.

### Live mode

```bash
python main.py --live           # Formula 1
python main.py --motogp-live    # MotoGP
```

Full details, latency tuning and troubleshooting are in [LiveMode.md](./LiveMode.md).
