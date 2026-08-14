"""Integration tests for export workflow."""

import pytest
import asyncio
from sqlmodel import Session, select
from app.models.database import DatabaseConnection, DatabaseType
from app.models.schemas import QueryResult, QueryColumn, ExportResult
from app.workflows.export_workflow import AutomatedExportWorkflow, export_workflow


class TestAutomatedExportWorkflow:
    """Integration tests for AutomatedExportWorkflow class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.workflow = AutomatedExportWorkflow()

    def test_workflow_initialization(self):
        """Test workflow initialization."""
        assert self.workflow is not None
        assert hasattr(self.workflow, "export_history")
        assert len(self.workflow.export_history) == 0

    @pytest.mark.asyncio
    async def test_csv_generation(self):
        """Test CSV format generation."""
        query_result = QueryResult(
            columns=[
                QueryColumn(name="id", dataType="integer"),
                QueryColumn(name="name", dataType="varchar"),
            ],
            rows=[
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
                {"id": 3, "name": "Charlie"},
            ],
            rowCount=3,
            executionTimeMs=5,
            sql="SELECT * FROM users",
        )

        csv_data = self.workflow._generate_csv_data(query_result, "csv")

        assert csv_data is not None
        assert "id,name" in csv_data  # Header
        assert "1,Alice" in csv_data  # First row
        assert "2,Bob" in csv_data  # Second row
        assert "3,Charlie" in csv_data  # Third row

    @pytest.mark.asyncio
    async def test_csv_with_special_characters(self):
        """Test CSV generation with special characters."""
        query_result = QueryResult(
            columns=[
                QueryColumn(name="id", dataType="integer"),
                QueryColumn(name="description", dataType="varchar"),
            ],
            rows=[
                {"id": 1, "description": 'Hello, "world"'},
                {"id": 2, "description": "Line\nbreak"},
                {"id": 3, "description": "Normal text"},
            ],
            rowCount=3,
            executionTimeMs=5,
            sql="SELECT * FROM products",
        )

        csv_data = self.workflow._generate_csv_data(query_result, "csv")

        # Special characters should be properly escaped
        assert '"Hello, ""world"""' in csv_data  # Escaped quotes
        assert '"Line\nbreak"' in csv_data  # Escaped newline
        assert '"Line\nbreak"' in csv_data  # Newline should be in quotes

    @pytest.mark.asyncio
    async def test_csv_with_null_values(self):
        """Test CSV generation with NULL values."""
        query_result = QueryResult(
            columns=[
                QueryColumn(name="id", dataType="integer"),
                QueryColumn(name="name", dataType="varchar"),
                QueryColumn(name="email", dataType="varchar"),
            ],
            rows=[
                {"id": 1, "name": "Alice", "email": None},
                {"id": 2, "name": None, "email": "bob@test.com"},
                {"id": 3, "name": "Charlie", "email": "charlie@test.com"},
            ],
            rowCount=3,
            executionTimeMs=5,
            sql="SELECT * FROM users",
        )

        csv_data = self.workflow._generate_csv_data(query_result, "csv")

        # NULL values should be handled as empty strings
        assert "1,Alice," in csv_data  # NULL email
        assert "2,,bob@test.com" in csv_data  # NULL name

    @pytest.mark.asyncio
    async def test_json_generation(self):
        """Test JSON format generation."""
        query_result = QueryResult(
            columns=[
                QueryColumn(name="id", dataType="integer"),
                QueryColumn(name="name", dataType="varchar"),
            ],
            rows=[
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
            ],
            rowCount=2,
            executionTimeMs=5,
            sql="SELECT * FROM users",
        )

        json_data = self.workflow._generate_json_data(query_result, "json")

        assert json_data is not None
        assert '"id": 1' in json_data
        assert '"name": "Alice"' in json_data
        assert '"id": 2' in json_data
        assert '"name": "Bob"' in json_data

    @pytest.mark.asyncio
    async def test_json_with_null_values(self):
        """Test JSON generation preserves NULL values."""
        query_result = QueryResult(
            columns=[
                QueryColumn(name="id", dataType="integer"),
                QueryColumn(name="name", dataType="varchar"),
            ],
            rows=[
                {"id": 1, "name": None},
                {"id": 2, "name": "Bob"},
            ],
            rowCount=2,
            executionTimeMs=5,
            sql="SELECT * FROM users",
        )

        json_data = self.workflow._generate_json_data(query_result, "json")

        assert '"id": 1' in json_data
        assert '"name": null' in json_data  # NULL should be preserved
        assert '"id": 2' in json_data
        assert '"name": "Bob"' in json_data

    @pytest.mark.asyncio
    async def test_export_history_recording(self):
        """Test export history is recorded correctly."""
        # Simulate an export
        database_name = "test_db"
        sql = "SELECT * FROM users"
        export_format = "csv"
        row_count = 100
        export_time_ms = 250
        success = True

        self.workflow._record_export_history(
            database_name, sql, export_format, row_count, export_time_ms, success
        )

        assert len(self.workflow.export_history) == 1
        history_entry = self.workflow.export_history[0]

        assert history_entry["database_name"] == database_name
        assert history_entry["sql"] == sql
        assert history_entry["format"] == export_format
        assert history_entry["row_count"] == row_count
        assert history_entry["export_time_ms"] == export_time_ms
        assert history_entry["success"] is True

    @pytest.mark.asyncio
    async def test_export_history_limit(self):
        """Test export history is limited to 50 entries."""
        # Add more than 50 entries
        for i in range(60):
            self.workflow._record_export_history(
                f"db_{i}",
                f"SELECT * FROM table_{i}",
                "csv" if i % 2 == 0 else "json",
                100 * (i + 1),
                100 + i,
                True
            )

        # Should only keep the last 50 entries
        assert len(self.workflow.export_history) == 50

        # Should be the last 50 entries (from i=10 to i=59)
        assert self.workflow.export_history[0]["database_name"] == "db_10"
        assert self.workflow.export_history[-1]["database_name"] == "db_59"

    @pytest.mark.asyncio
    async def test_get_export_statistics_empty(self):
        """Test export statistics with no history."""
        stats = self.workflow.get_export_statistics()

        assert stats["total_exports"] == 0
        assert stats["csv_exports"] == 0
        assert stats["json_exports"] == 0
        assert stats["avg_export_time_ms"] == 0
        assert stats["total_rows_exported"] == 0

    @pytest.mark.asyncio
    async def test_get_export_statistics_with_data(self):
        """Test export statistics calculation."""
        # Add some export history
        self.workflow._record_export_history("db1", "SELECT * FROM users", "csv", 100, 200, True)
        self.workflow._record_export_history("db1", "SELECT * FROM products", "json", 50, 150, True)
        self.workflow._record_export_history("db2", "SELECT * FROM orders", "csv", 200, 300, True)

        stats = self.workflow.get_export_statistics()

        assert stats["total_exports"] == 3
        assert stats["csv_exports"] == 2
        assert stats["json_exports"] == 1
        assert stats["avg_export_time_ms"] == 216.67  # (200 + 150 + 300) / 3
        assert stats["total_rows_exported"] == 350  # 100 + 50 + 200

    @pytest.mark.asyncio
    async def test_determine_export_format_with_preference(self):
        """Test export format determination with user preference."""
        # Create a mock export suggestion
        class MockExportSuggestion:
            def __init__(self):
                self.recommended_format = "json"
                self.confidence_score = 0.8
                self.reasoning = "Data is complex"
                self.estimated_size_mb = 0.5
                self.export_time_estimate_ms = 150
                self.automation_suggestion = "ask"
                self.alternative_formats = ["csv"]

        suggestion = MockExportSuggestion()

        # User prefers CSV despite JSON recommendation
        format_with_preference = self.workflow._determine_export_format(
            suggestion, preferred_format="csv", auto_export=False
        )
        assert format_with_preference == "csv"

        # User has no preference, should use recommended
        format_without_preference = self.workflow._determine_export_format(
            suggestion, preferred_format=None, auto_export=False
        )
        assert format_without_preference == "json"

        # Auto export enabled, should use recommended format
        format_auto_export = self.workflow._determine_export_format(
            suggestion, preferred_format=None, auto_export=True
        )
        assert format_auto_export == "json"

    @pytest.mark.asyncio
    async def test_export_history_limit_param(self):
        """Test get_export_history with limit parameter."""
        # Add 20 entries
        for i in range(20):
            self.workflow._record_export_history(
                f"db_{i}",
                f"SELECT * FROM table_{i}",
                "csv" if i % 2 == 0 else "json",
                100 + i,
                100 + i * 10,
                True
            )

        # Get last 10 entries
        history = self.workflow.get_export_history(limit=10)

        assert len(history) == 10
        # Should be entries 10-19
        assert history[0]["database_name"] == "db_10"
        assert history[-1]["database_name"] == "db_19"

        # Get last 5 entries
        history_5 = self.workflow.get_export_history(limit=5)

        assert len(history_5) == 5
        # Should be entries 15-19
        assert history_5[0]["database_name"] == "db_15"
        assert history_5[-1]["database_name"] == "db_19"

    @pytest.mark.asyncio
    async def test_export_result_structure(self):
        """Test ExportResult structure for CSV format."""
        query_result = QueryResult(
            columns=[
                QueryColumn(name="id", dataType="integer"),
                QueryColumn(name="name", dataType="varchar"),
            ],
            rows=[
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
            ],
            rowCount=2,
            executionTimeMs=5,
            sql="SELECT * FROM users",
        )

        csv_data = self.workflow._generate_csv_data(query_result, "csv")

        # Verify ExportResult structure would be created correctly
        export_result = ExportResult(
            success=True,
            fileUrl=None,
            fileSize=len(csv_data),
            format="csv",
            row_count=query_result.row_count,
            exportTimeMs=50,
        )

        assert export_result.success is True
        assert export_result.format == "csv"
        assert export_result.row_count == 2
        assert export_result.file_size is not None and export_result.file_size > 0
        assert export_result.export_time_ms == 50
        assert export_result.error is None

    @pytest.mark.asyncio
    async def test_export_time_tracking(self):
        """Test that export time is tracked correctly in history."""
        import time

        start_time = time.time()

        # Simulate export operation
        time.sleep(0.1)  # Simulate 100ms export

        end_time = time.time()
        export_time_ms = int((end_time - start_time) * 1000)

        self.workflow._record_export_history(
            "test_db", "SELECT * FROM users", "csv", 100, export_time_ms, True
        )

        history_entry = self.workflow.export_history[0]

        # The recorded export time should be approximately 100ms
        assert 90 <= history_entry["export_time_ms"] <= 200  # Allow some tolerance

    @pytest.mark.asyncio
    async def test_format_alternatives_in_history(self):
        """Test that different formats are tracked separately in statistics."""
        # Add CSV exports
        for i in range(10):
            self.workflow._record_export_history(f"db_{i}", f"SELECT * FROM table_{i}", "csv", 100, 200, True)

        # Add JSON exports
        for i in range(10, 15):
            self.workflow._record_export_history(f"db_{i}", f"SELECT * FROM table_{i}", "json", 50, 150, True)

        stats = self.workflow.get_export_statistics()

        assert stats["csv_exports"] == 10
        assert stats["json_exports"] == 5
        assert stats["total_exports"] == 15