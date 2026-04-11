# RosterSU - Work Roster Management System

A single-user, offline-first work roster management application with Excel import, schedule parsing, and iCal/CSV export capabilities.

## Quick Start

### Option 1: Automatic Installation (Recommended)

Simply run the application - it will automatically detect and install missing dependencies:

```bash
python roster_single_user.py
```

On first run, you'll see:
```
============================================================
RosterSU - First Time Setup
============================================================

Missing dependencies: python-fasthtml, python-calamine, rapidfuzz

Installing required packages...
(This may take a few minutes)

✓ Dependencies installed successfully!
Restarting import process...
```

### Option 2: Manual Installation

Install dependencies yourself before running:

```bash
# Install all dependencies
pip install -r requirements.txt

# Run the application
python roster_single_user.py
```

### Option 3: Setup Script

Use the included setup script:

```bash
python setup.py
python roster_single_user.py
```

## Requirements

- **Python 3.9+** (earlier versions not tested)
- **pip** (Python package manager)

### Required Packages

These will be installed automatically on first run:

| Package | Purpose | Size |
|---------|---------|------|
| `python-fasthtml` | Web framework (includes Starlette) | ~500 KB |
| `python-calamine` | Fast Excel file parsing (Rust-based) | ~2 MB |
| `rapidfuzz` | Fuzzy string matching for schedule parsing | ~1 MB |

### System Requirements

- **Disk space**: ~5 MB for dependencies
- **RAM**: ~100 MB during operation
- **Network**: Required only for initial package installation

## Installation Troubleshooting

### pip not found

Install pip first:
```bash
# Debian/Ubuntu
sudo apt install python3-pip

# Termux (Android)
pkg install python
```

### Permission denied errors

```bash
# Install for current user only
pip install --user -r requirements.txt

# OR use virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
pip install -r requirements.txt
```

### Slow installation on Raspberry Pi

`python-calamine` and `rapidfuzz` compile from source on ARM. Consider:
```bash
# Install build tools first
sudo apt install build-essential python3-dev

# Then install dependencies
pip install -r requirements.txt
```

## Running the Application

```bash
cd RosterSU
python roster_single_user.py
```

The application will:
1. Check for missing dependencies
2. Install them automatically if needed
3. Start the web server
4. Open in your browser (usually http://localhost:8501)

## Keeping Your App Updated

RosterSU includes an automatic update system to keep you on the latest version.

### Quick Update (Recommended)

```bash
cd ~/RosterSU
./update.sh
```

The update script will:
- ✅ Check for new versions
- ✅ Show what's changed
- ✅ Create a backup
- ✅ Download and apply updates
- ✅ Install new dependencies automatically

### Web Interface Update

1. Open the app in your browser
2. Go to **Settings** (Cài đặt)
3. Click **"🔄 Kiểm tra cập nhật"**
4. Follow the instructions

### Version Information

Current version is tracked in the `VERSION` file.

For detailed update instructions, see [UPDATE_GUIDE.md](UPDATE_GUIDE.md).

## First-Time Setup Flow

```
User runs: python roster_single_user.py
                ↓
    Check if dependencies installed
                ↓
    ┌───────────┴───────────┐
    ↓                       ↓
All installed         Missing found
    ↓                       ↓
Start normally    Run pip install automatically
                          ↓
                    ┌─────┴─────┐
                    ↓           ↓
               Success       Failed
                    ↓           ↓
              Start app    Show error + 
                          manual instructions
```

## For Developers

### Viewing Dependencies

See `requirements.txt` for the full list of third-party packages.

All other imports are from Python's standard library (no installation needed).

### Dependency Architecture

```
roster_single_user.py (entry point)
    ├─ Auto-checks dependencies on import
    ├─ Installs missing packages via pip
    └─ Then proceeds with normal imports
```

The auto-installation code is at the top of `roster_single_user.py` (lines 72-120), before any third-party imports.

### Adding New Dependencies

If you add a new third-party package:

1. Add it to `requirements.txt`
2. Add an import check in `_ensure_dependencies()` function
3. Update this README

## File Structure

```
RosterSU/
├── roster_single_user.py    # Main application (auto-installs deps)
├── requirements.txt         # Python dependencies
├── setup.py                 # Manual dependency installer
├── README.md               # This file
├── config.py               # Configuration management
├── database.py             # SQLite database layer
├── routes.py               # Web routes
├── components.py           # UI components
├── export.py               # iCal/CSV export
├── state.py                # Application state
├── data_types.py           # Data structures
└── parser/                 # Schedule parsing
    ├── __init__.py
    ├── detection.py
    ├── engine.py
    └── utils.py
```

## Support

If automatic installation fails:

1. Check your Python version: `python --version`
2. Check pip is working: `pip --version`
3. Try manual install: `pip install -r requirements.txt`
4. Check error messages for clues

Common issues:
- **Network problems**: Check internet connection
- **Old pip version**: `pip install --upgrade pip`
- **Missing compiler**: Install build-essential (Linux) or Xcode tools (Mac)

## License

[Your license here]

## Version

Current version: **1.3.0** (see `VERSION` file)

See [UPDATE_GUIDE.md](UPDATE_GUIDE.md) for version numbering and update process.
