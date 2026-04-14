"""
Integration tests simulating real user update scenarios.

Scenario A: Existing user downloads/overwrites RosterSU/ directory
- Old config at PROJECT_ROOT/rosterSU_config.json (survives overwrite since it's outside RosterSU/)
- New code in RosterSU/ reads from new location, migrates old config
- DB, aliases, aircraft, paths all survive

Scenario B: New user fresh install
- No config anywhere
- Defaults are used, config created at RosterSU/config/rosterSU_config.json

Scenario C: Existing user moves app to different directory
- Old config at old PROJECT_ROOT (now irrelevant)
- User copies old config to new PROJECT_ROOT manually
- App detects and migrates to new location inside RosterSU/config/
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest


class TestScenarioA_ExistingUserOverwrite(unittest.TestCase):
    """
    Simulate: User has been using the app, has customized config at PROJECT_ROOT/.
    They download new RosterSU/ and overwrite the old directory.
    The old config file at PROJECT_ROOT/ survives (it's outside RosterSU/).
    The new code should detect it, migrate it to RosterSU/config/, and load all settings.
    """

    def setUp(self):
        """Build a fake project structure mimicking a user's setup."""
        self.tmpdir = tempfile.mkdtemp()

        # Simulate PROJECT_ROOT structure
        # ├── rosterSU_config.json  (user's existing config with custom settings)
        # ├── roster_history.db     (user's database)
        # └── RosterSU/             (app directory — "newly overwritten")
        #     ├── config.py
        #     ├── config/           (empty, will be created by config.py)
        #     └── ...

        self.project_root = self.tmpdir
        self.app_dir = os.path.join(self.tmpdir, "RosterSU")
        self.config_dir = os.path.join(self.app_dir, "config")
        os.makedirs(self.app_dir)
        os.makedirs(self.config_dir)

        # Copy real source files into the temp app dir
        real_app_dir = os.path.join(os.path.dirname(__file__), "..", "RosterSU")
        for fname in ["config.py", "__init__.py"]:
            src = os.path.join(real_app_dir, fname)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(self.app_dir, fname))

        # User's OLD config (at legacy location — simulates existing user)
        self.old_config_path = os.path.join(self.project_root, "rosterSU_config.json")
        user_config = {
            "aliases": ["Nguyễn Văn A", "VAN A", "A.NV"],
            "aircraft": {
                "airbus": ["A320", "A321", "A350"],
                "boeing": ["B787", "B777"],
                "other": ["AT72"],
            },
            "port": 9999,
            "db_path": os.path.join(self.project_root, "my_roster.db"),
            "auto_ingest_dir": "/data/user/custom/Zalo",
            "export_dir": "/data/user/custom/exports",
            "static_html_output_dir": "/data/user/custom/viewer",
            "processed_archive_dir": "my_processed",
            "enable_flight_sync": True,
            "static_html_scope": "latest_n",
            "static_html_count": 10,
            "history_limit": 120,
            "page_size": 100,
        }
        with open(self.old_config_path, "w", encoding="utf-8") as f:
            json.dump(user_config, f, ensure_ascii=False, indent=2)

        # User's database (simulate with some data)
        self.user_db_path = os.path.join(self.project_root, "my_roster.db")
        conn = sqlite3.connect(self.user_db_path)
        conn.execute("""CREATE TABLE IF NOT EXISTS roster_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            name TEXT,
            shift TEXT,
            source_filename TEXT
        )""")
        conn.execute(
            "INSERT INTO roster_entries (date, name, shift) VALUES (?, ?, ?)",
            ("2026-04-14", "Nguyễn Văn A", "Sáng"),
        )
        conn.execute(
            "INSERT INTO roster_entries (date, name, shift) VALUES (?, ?, ?)",
            ("2026-04-15", "Nguyễn Văn A", "Tối"),
        )
        conn.commit()
        conn.close()

        # Save original sys.path and cwd
        self._orig_path = sys.path[:]
        self._orig_modules = {
            name: mod
            for name, mod in sys.modules.items()
            if name in ("config", "__init__")
        }

    def tearDown(self):
        # Restore sys.path
        sys.path[:] = self._orig_path
        # Clean up imported modules
        for name in list(sys.modules.keys()):
            if name in ("config",):
                del sys.modules[name]
        # Restore original modules if any
        for name, mod in self._orig_modules.items():
            sys.modules[name] = mod
        shutil.rmtree(self.tmpdir)

    def _import_config(self):
        """Import config module from the temp directory."""
        sys.path.insert(0, self.app_dir)
        # Remove cached module if any
        if "config" in sys.modules:
            del sys.modules["config"]
        import config
        return config

    def test_config_migrated_to_new_location(self):
        """Old config at PROJECT_ROOT should be copied to RosterSU/config/."""
        cfg = self._import_config()
        self.assertTrue(
            os.path.exists(cfg.CONFIG_FILE),
            f"Config not found at new location: {cfg.CONFIG_FILE}",
        )

    def test_migrated_config_has_all_user_settings(self):
        """After migration, all user customizations should be preserved."""
        cfg = self._import_config()

        # Read the migrated config
        with open(cfg.CONFIG_FILE, "r", encoding="utf-8") as f:
            migrated = json.load(f)

        # Check every user setting
        self.assertEqual(migrated["aliases"], ["Nguyễn Văn A", "VAN A", "A.NV"])
        self.assertEqual(migrated["aircraft"]["airbus"], ["A320", "A321", "A350"])
        self.assertEqual(migrated["aircraft"]["boeing"], ["B787", "B777"])
        self.assertEqual(migrated["aircraft"]["other"], ["AT72"])
        self.assertEqual(migrated["port"], 9999)
        self.assertEqual(migrated["db_path"], self.user_db_path)
        self.assertEqual(migrated["auto_ingest_dir"], "/data/user/custom/Zalo")
        self.assertEqual(migrated["export_dir"], "/data/user/custom/exports")
        self.assertEqual(
            migrated["static_html_output_dir"], "/data/user/custom/viewer"
        )
        self.assertEqual(migrated["processed_archive_dir"], "my_processed")
        self.assertTrue(migrated["enable_flight_sync"])
        self.assertEqual(migrated["static_html_scope"], "latest_n")
        self.assertEqual(migrated["static_html_count"], 10)
        self.assertEqual(migrated["history_limit"], 120)
        self.assertEqual(migrated["page_size"], 100)

    def test_merged_config_uses_user_values(self):
        """_MERGED config should reflect user overrides from the migrated file."""
        cfg = self._import_config()
        merged = cfg._MERGED
        self.assertEqual(merged["port"], 9999)
        self.assertEqual(merged["aliases"], ["Nguyễn Văn A", "VAN A", "A.NV"])
        self.assertEqual(merged["enable_flight_sync"], True)
        self.assertEqual(merged["static_html_scope"], "latest_n")

    def test_db_path_resolves_correctly(self):
        """DB_FILE should resolve to the user's custom DB path."""
        cfg = self._import_config()
        # DB_FILE should point to the user's database
        self.assertEqual(cfg.DB_FILE, self.user_db_path)
        self.assertTrue(os.path.exists(cfg.DB_FILE))

    def test_db_is_readable_after_migration(self):
        """User's database should still be readable with all entries."""
        cfg = self._import_config()
        conn = sqlite3.connect(cfg.DB_FILE)
        cursor = conn.execute("SELECT COUNT(*) FROM roster_entries")
        count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(count, 2, "Database entries should survive migration")

    def test_old_config_still_exists_not_deleted(self):
        """We copy (not move) the old config, so it still exists."""
        cfg = self._import_config()
        # Old config is not deleted (raw copy, not move)
        self.assertTrue(os.path.exists(self.old_config_path))

    def test_subsequent_loads_use_new_config(self):
        """Second import should read from new location (not re-copy)."""
        cfg1 = self._import_config()
        # Modify the new config
        with open(cfg1.CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["port"] = 7777
        with open(cfg1.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)

        # Re-import (simulates second launch)
        del sys.modules["config"]
        sys.path.insert(0, self.app_dir)
        cfg2 = __import__("config")

        # Should read the modified config, not re-copy from old location
        self.assertEqual(cfg2._MERGED["port"], 7777)

    def test_no_config_at_all_uses_defaults(self):
        """If no config files exist anywhere, defaults are used."""
        # Remove both old and new config
        os.remove(self.old_config_path)
        if os.path.exists(os.path.join(self.config_dir, "rosterSU_config.json")):
            os.remove(os.path.join(self.config_dir, "rosterSU_config.json"))

        cfg = self._import_config()
        merged = cfg._MERGED
        self.assertEqual(merged["port"], 8501)
        self.assertEqual(merged["history_limit"], 60)
        self.assertEqual(merged["enable_flight_sync"], False)


class TestScenarioB_FreshInstall(unittest.TestCase):
    """
    Simulate: Brand new user, no config files anywhere.
    App should start with defaults and create config at new location on first save.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.app_dir = os.path.join(self.tmpdir, "RosterSU")
        self.config_dir = os.path.join(self.app_dir, "config")
        os.makedirs(self.app_dir)
        # No config file anywhere

        # Copy config.py
        real_app_dir = os.path.join(os.path.dirname(__file__), "..", "RosterSU")
        shutil.copy2(
            os.path.join(real_app_dir, "config.py"),
            os.path.join(self.app_dir, "config.py"),
        )
        shutil.copy2(
            os.path.join(real_app_dir, "__init__.py"),
            os.path.join(self.app_dir, "__init__.py"),
        )

        self._orig_path = sys.path[:]

    def tearDown(self):
        sys.path[:] = self._orig_path
        if "config" in sys.modules:
            del sys.modules["config"]
        shutil.rmtree(self.tmpdir)

    def _import_config(self):
        sys.path.insert(0, self.app_dir)
        if "config" in sys.modules:
            del sys.modules["config"]
        import config
        return config

    def test_defaults_used_when_no_config(self):
        cfg = self._import_config()
        self.assertEqual(cfg._MERGED["port"], 8501)
        self.assertEqual(cfg._MERGED["history_limit"], 60)
        self.assertEqual(cfg._MERGED["enable_flight_sync"], False)
        self.assertEqual(cfg._MERGED["auto_ingest_dir"], "~/storage/downloads/Zalo")

    def test_config_dir_created_on_import(self):
        cfg = self._import_config()
        self.assertTrue(os.path.isdir(cfg.CONFIG_DIR))


class TestScenarioC_UserChangesInstallLocation(unittest.TestCase):
    """
    Simulate: User had app at /old/location/RosterSU/ with config at /old/location/rosterSU_config.json.
    User downloads to /new/location/RosterSU/ and copies old config to /new/location/.
    App should migrate from /new/location/rosterSU_config.json → /new/location/RosterSU/config/.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.new_project_root = self.tmpdir
        self.app_dir = os.path.join(self.tmpdir, "RosterSU")
        self.config_dir = os.path.join(self.app_dir, "config")
        os.makedirs(self.app_dir)
        os.makedirs(self.config_dir)

        # Copy config.py
        real_app_dir = os.path.join(os.path.dirname(__file__), "..", "RosterSU")
        shutil.copy2(
            os.path.join(real_app_dir, "config.py"),
            os.path.join(self.app_dir, "config.py"),
        )
        shutil.copy2(
            os.path.join(real_app_dir, "__init__.py"),
            os.path.join(self.app_dir, "__init__.py"),
        )

        # User copied their old config to the new project root
        old_config_path = os.path.join(self.new_project_root, "rosterSU_config.json")
        config_data = {
            "aliases": ["Test User"],
            "port": 5555,
            "db_path": os.path.join(self.tmpdir, "test.db"),
            "enable_flight_sync": True,
        }
        with open(old_config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)

        self._orig_path = sys.path[:]

    def tearDown(self):
        sys.path[:] = self._orig_path
        if "config" in sys.modules:
            del sys.modules["config"]
        shutil.rmtree(self.tmpdir)

    def _import_config(self):
        sys.path.insert(0, self.app_dir)
        if "config" in sys.modules:
            del sys.modules["config"]
        import config
        return config

    def test_config_migrated_to_app_dir_config(self):
        cfg = self._import_config()
        self.assertTrue(os.path.exists(cfg.CONFIG_FILE))

    def test_user_settings_preserved(self):
        cfg = self._import_config()
        with open(cfg.CONFIG_FILE, "r", encoding="utf-8") as f:
            migrated = json.load(f)
        self.assertEqual(migrated["aliases"], ["Test User"])
        self.assertEqual(migrated["port"], 5555)
        self.assertTrue(migrated["enable_flight_sync"])


if __name__ == "__main__":
    unittest.main()
