# RosterSU Auto-Update System

## Overview

The auto-update system allows users to easily keep their RosterSU installation up to date with the latest features and bug fixes.

## Methods to Update

### Method 1: Command Line (Recommended)

Run the update script from the terminal:

```bash
cd ~/RosterSU
./update.sh
```

**Features:**
- ✅ Automatically checks for updates
- ✅ Shows what's new before updating
- ✅ Creates backup before updating
- ✅ Installs new dependencies automatically
- ✅ Rolls back if update fails
- ✅ Cleans up cache files

### Method 2: Web Interface

1. Open the app in your browser: `http://127.0.0.1:8501`
2. Go to **Settings** (Cài đặt)
3. Click **"🔄 Kiểm tra cập nhật"** button
4. If an update is available, follow the instructions to run `./update.sh`

## How It Works

### Version Tracking
- The app version is stored in the `VERSION` file
- Format: `MAJOR.MINOR.PATCH` (e.g., `1.3.0`)
- Version is compared with the remote repository

### Update Process
1. **Check**: Compares local version with remote version
2. **Fetch**: Downloads latest changes from GitHub
3. **Backup**: Creates a backup of your current code
4. **Pull**: Updates the code with latest changes
5. **Install**: Installs any new dependencies
6. **Cleanup**: Removes old cache files

### Safety Features
- **Automatic Backup**: Creates backup in `.update_backup/` directory
- **Rollback**: Automatically restores backup if update fails
- **Dependency Check**: Ensures all required packages are installed
- **Error Logging**: All operations are logged to `update.log`

## For Your Friend (User Instructions)

Share these instructions with your friend:

### Quick Start
```bash
# Navigate to the app directory
cd ~/RosterSU

# Run the update script
./update.sh

# Restart the app
python3 roster_single_user.py
```

### What to Expect
1. The script will check for new updates
2. Show you what's changed
3. Ask for confirmation
4. Create a backup
5. Download and apply updates
6. Install any new dependencies

### Troubleshooting

**Problem**: "Not a git repository"
```bash
# Clone the repository first
git clone https://github.com/dadenday/RosterSU.git
cd RosterSU
```

**Problem**: "Permission denied"
```bash
# Make the script executable
chmod +x update.sh
```

**Problem**: "No internet connection"
- Check your network connection
- Try again when connected

**Problem**: Update fails
- Check the log file: `cat update.log`
- Your code is safe - backup is in `.update_backup/`
- You can manually restore if needed

## For Developers

### Updating the Version

When releasing a new version:

1. Update the `VERSION` file:
   ```bash
   echo "1.4.0" > VERSION
   ```

2. Commit the change:
   ```bash
   git add VERSION
   git commit -m "bump version to 1.4.0"
   ```

3. Push to remote:
   ```bash
   git push
   ```

### Version Numbering

Follow [Semantic Versioning](https://semver.org/):

- **MAJOR**: Breaking changes
- **MINOR**: New features (backward compatible)
- **PATCH**: Bug fixes (backward compatible)

Examples:
- `1.3.0` → `1.3.1` (bug fix)
- `1.3.1` → `1.4.0` (new feature)
- `1.4.0` → `2.0.0` (breaking change)

### Adding New Dependencies

If you add new dependencies:

1. Add to `requirements.txt`
2. Update `roster_single_user.py` dependency checker
3. Bump the version number

The update script will automatically install new dependencies.

## Technical Details

### Files
- `VERSION` - Current version number
- `update.sh` - Update script
- `update.log` - Update operation log
- `.update_backup/` - Backup directory (created during update)

### API Endpoints
- `GET /api/version/check` - Check for updates (returns HTML)

### Dependencies
- `git` - Version control
- `rsync` - File synchronization (for backups)
- `pip3` - Python package manager

## Best Practices

1. **Always backup**: The script does this automatically, but you can also manually backup your database
2. **Test after update**: Run the app and verify everything works
3. **Keep backups**: Don't delete `.update_backup/` immediately after updating
4. **Read changelog**: Check what's new before updating
5. **Update regularly**: Stay up to date for security and features

## Support

If you encounter any issues:
1. Check the log file: `cat update.log`
2. Check the backup: `ls -la .update_backup/`
3. Report the issue on GitHub with the log output
