"""Tests for global variables SQLite storage."""

import pytest

from deerflow.global_variables.storage import (
    GlobalVariablesStorage,
    get_storage,
    reset_storage,
    utc_now_iso_z,
)


class TestUtcNowIsoZ:
    def test_returns_iso_string_with_z(self):
        result = utc_now_iso_z()
        assert isinstance(result, str)
        assert result.endswith("Z")


class TestGlobalVariablesStorageSQLite:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.tmp_path = tmp_path
        self.db_path = tmp_path / "test_global_variables.db"
        reset_storage()

    def _create_storage(self) -> GlobalVariablesStorage:
        storage = GlobalVariablesStorage()
        storage._get_db_path = lambda: self.db_path
        return storage

    def test_project_save_and_load(self):
        storage = self._create_storage()
        data = {"variables": {"mode": {"value": "writing", "description": "Work mode", "llm_editable": True}}}
        assert storage.save(data, scope="project")

        loaded = storage.load("project")
        assert "variables" in loaded
        assert "mode" in loaded["variables"]
        assert loaded["variables"]["mode"]["value"] == "writing"
        assert loaded["variables"]["mode"]["description"] == "Work mode"

    def test_thread_save_and_load(self):
        storage = self._create_storage()
        thread_id = "test-thread-1"
        data = {"variables": {"chapter": {"value": "5", "description": "Current chapter", "llm_editable": True}}}
        assert storage.save(data, scope="thread", thread_id=thread_id)

        loaded = storage.load("thread", thread_id=thread_id)
        assert "chapter" in loaded["variables"]
        assert loaded["variables"]["chapter"]["value"] == "5"

    def test_load_nonexistent_returns_system_variables(self):
        storage = self._create_storage()
        data = storage.load("project")
        assert "workdir" in data["variables"]
        assert data["variables"]["workdir"]["is_system"] is True
        assert data["is_custom"] is False

    def test_system_variables_synced_to_db(self):
        storage = self._create_storage()
        storage.load("project")
        import sqlite3

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM global_variables WHERE key = 'workdir' AND thread_id IS NULL")
        row = cursor.fetchone()
        conn.close()
        assert row is not None
        assert row["value"] == "/mnt/shared-data"
        assert row["is_system"] == 1

    def test_delete_variable(self):
        storage = self._create_storage()
        data = {"variables": {"key1": {"value": "v1", "llm_editable": True}, "key2": {"value": "v2", "llm_editable": True}}}
        storage.save(data, scope="project")

        assert storage.delete("key1", scope="project")

        loaded = storage.load("project")
        assert "key1" not in loaded["variables"]
        assert "key2" in loaded["variables"]

    def test_isolation_between_scopes(self):
        storage = self._create_storage()
        project_data = {"variables": {"shared": {"value": "project_val", "llm_editable": True}}}
        thread_data = {"variables": {"shared": {"value": "thread_val", "llm_editable": True}}}
        storage.save(project_data, scope="project")
        storage.save(thread_data, scope="thread", thread_id="t1")

        p = storage.load("project")
        t = storage.load("thread", thread_id="t1")
        assert p["variables"]["shared"]["value"] == "project_val"
        assert t["variables"]["shared"]["value"] == "thread_val"

    def test_system_variables_merged(self):
        storage = self._create_storage()
        custom_data = {"variables": {"custom_var": {"value": "custom", "llm_editable": True}}}
        storage.save(custom_data, scope="project")

        loaded = storage.load("project")
        assert "workdir" in loaded["variables"]  # System variable
        assert "custom_var" in loaded["variables"]  # Custom variable
        assert loaded["variables"]["workdir"]["is_system"] is True
        assert loaded["variables"]["custom_var"]["is_system"] is False

    def test_system_variables_not_saved(self):
        storage = self._create_storage()
        data_with_system = {
            "variables": {
                "workdir": {"value": "/hacked", "is_system": True},  # Should be ignored
                "custom": {"value": "custom", "is_system": False},
            }
        }
        storage.save(data_with_system, scope="project")

        loaded = storage.load("project")
        assert loaded["variables"]["workdir"]["value"] == "/mnt/shared-data"  # Original system value
        assert loaded["variables"]["custom"]["value"] == "custom"

    def test_thread_overrides_project(self):
        storage = self._create_storage()
        project_data = {"variables": {"mode": {"value": "writing", "llm_editable": True}}}
        thread_data = {"variables": {"mode": {"value": "reviewing", "llm_editable": True}}}
        storage.save(project_data, scope="project")
        storage.save(thread_data, scope="thread", thread_id="t1")

        p = storage.load("project")
        t = storage.load("thread", thread_id="t1")
        assert p["variables"]["mode"]["value"] == "writing"
        assert t["variables"]["mode"]["value"] == "reviewing"


class TestGetStorage:
    def test_returns_singleton(self):
        reset_storage()
        s1 = get_storage()
        s2 = get_storage()
        assert s1 is s2

    def test_reset_clears_singleton(self):
        reset_storage()
        s1 = get_storage()
        reset_storage()
        s2 = get_storage()
        assert s1 is not s2
