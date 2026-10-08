"""Unit tests for QueryOrchestrator.

This module tests the orchestrator's coordination of the query pipeline,
including retry logic, error handling, and integration with all components.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import REGISTRY

from pg_mcp.config.settings import ResilienceConfig, ValidationConfig
from pg_mcp.models.errors import (
    DatabaseError,
    LLMError,
    LLMTimeoutError,
    LLMUnavailableError,
    SecurityViolationError,
    SQLParseError,
)
from pg_mcp.models.query import (
    QueryRequest,
    ResultValidationResult,
    ReturnType,
)
from pg_mcp.models.schema import ColumnInfo, DatabaseSchema, TableInfo
from pg_mcp.resilience.circuit_breaker import CircuitState
from pg_mcp.services.orchestrator import QueryOrchestrator


def get_sample_value(name: str, labels: dict[str, str] | None = None) -> float | None:
    """Read a current metric sample value from the default Prometheus registry."""
    return REGISTRY.get_sample_value(name, labels)


class TestDatabaseResolution:
    """Test database name resolution logic."""

    @pytest.fixture
    def mock_pools(self) -> dict[str, MagicMock]:
        """Create mock connection pools."""
        return {
            "db1": MagicMock(),
            "db2": MagicMock(),
        }

    @pytest.fixture
    def orchestrator(self, mock_pools: dict[str, MagicMock]) -> QueryOrchestrator:
        """Create orchestrator with mocked components."""
        return QueryOrchestrator(
            sql_generator=MagicMock(),
            sql_validator=MagicMock(),
            sql_executors={"test_db": MagicMock()},
            result_validator=MagicMock(),
            schema_cache=MagicMock(),
            pools=mock_pools,
            resilience_config=ResilienceConfig(),
            validation_config=ValidationConfig(),
        )

    def test_resolve_database_specified_valid(self, orchestrator: QueryOrchestrator) -> None:
        """Test resolving a specified valid database."""
        result = orchestrator._resolve_database("db1")
        assert result == "db1"

    def test_resolve_database_specified_invalid(self, orchestrator: QueryOrchestrator) -> None:
        """Test resolving a specified but invalid database."""
        with pytest.raises(DatabaseError) as exc_info:
            orchestrator._resolve_database("nonexistent")

        assert "not found" in str(exc_info.value).lower()
        assert "db1" in exc_info.value.details["available_databases"]
        assert "db2" in exc_info.value.details["available_databases"]

    def test_resolve_database_auto_select_single(self) -> None:
        """Test auto-selecting when only one database available."""
        orchestrator = QueryOrchestrator(
            sql_generator=MagicMock(),
            sql_validator=MagicMock(),
            sql_executors={"test_db": MagicMock()},
            result_validator=MagicMock(),
            schema_cache=MagicMock(),
            pools={"only_db": MagicMock()},
            resilience_config=ResilienceConfig(),
            validation_config=ValidationConfig(),
        )

        result = orchestrator._resolve_database(None)
        assert result == "only_db"

    def test_resolve_database_auto_select_multiple_fails(
        self, orchestrator: QueryOrchestrator
    ) -> None:
        """Test that auto-select fails when multiple databases available."""
        with pytest.raises(DatabaseError) as exc_info:
            orchestrator._resolve_database(None)

        assert "multiple databases" in str(exc_info.value).lower()
        assert "db1" in exc_info.value.details["available_databases"]

    def test_resolve_database_no_databases(self) -> None:
        """Test error when no databases configured."""
        orchestrator = QueryOrchestrator(
            sql_generator=MagicMock(),
            sql_validator=MagicMock(),
            sql_executors={"test_db": MagicMock()},
            result_validator=MagicMock(),
            schema_cache=MagicMock(),
            pools={},
            resilience_config=ResilienceConfig(),
            validation_config=ValidationConfig(),
        )

        with pytest.raises(DatabaseError) as exc_info:
            orchestrator._resolve_database(None)

        assert "no databases configured" in str(exc_info.value).lower()


class TestSQLGenerationWithRetry:
    """Test SQL generation with retry logic."""

    @pytest.fixture
    def mock_schema(self) -> DatabaseSchema:
        """Create mock database schema."""
        return DatabaseSchema(
            database_name="test_db",
            tables=[
                TableInfo(
                    schema_name="public",
                    table_name="users",
                    columns=[
                        ColumnInfo(
                            name="id",
                            data_type="integer",
                            is_nullable=False,
                            is_primary_key=True,
                        ),
                        ColumnInfo(
                            name="name",
                            data_type="varchar(255)",
                            is_nullable=False,
                        ),
                    ],
                )
            ],
            version="15.0",
        )

    @pytest.mark.asyncio
    async def test_generate_sql_success_first_attempt(self, mock_schema: DatabaseSchema) -> None:
        """Test successful SQL generation on first attempt."""
        # Setup mocks
        mock_generator = AsyncMock()
        mock_generator.generate.return_value = "SELECT * FROM users;"

        mock_validator = MagicMock()
        mock_validator.validate_or_raise.return_value = None  # No exception = valid

        orchestrator = QueryOrchestrator(
            sql_generator=mock_generator,
            sql_validator=mock_validator,
            sql_executors={"test_db": MagicMock()},
            result_validator=MagicMock(),
            schema_cache=MagicMock(),
            pools={"test_db": MagicMock()},
            resilience_config=ResilienceConfig(max_retries=3, retry_delay=0.1, backoff_factor=1.0),
            validation_config=ValidationConfig(),
        )

        # Execute
        sql, validation_result, _tokens = await orchestrator._generate_sql_with_retry(
            question="Get all users",
            schema=mock_schema,
        )

        # Verify
        assert sql == "SELECT * FROM users;"
        assert validation_result.is_valid is True
        assert validation_result.is_select is True
        mock_generator.generate.assert_called_once()
        mock_validator.validate_or_raise.assert_called_once_with("SELECT * FROM users;")

    @pytest.mark.asyncio
    async def test_generate_sql_retry_on_validation_failure(
        self, mock_schema: DatabaseSchema
    ) -> None:
        """Test retry logic when validation fails."""
        # Setup mocks - first attempt fails validation, second succeeds
        mock_generator = AsyncMock()
        mock_generator.generate.side_effect = [
            "SELECT * FROM user;",  # First attempt (wrong table name)
            "SELECT * FROM users;",  # Second attempt (correct)
        ]

        mock_validator = MagicMock()
        # First call raises error, second call succeeds
        mock_validator.validate_or_raise.side_effect = [
            SQLParseError('relation "user" does not exist'),
            None,  # Success on second attempt
        ]

        orchestrator = QueryOrchestrator(
            sql_generator=mock_generator,
            sql_validator=mock_validator,
            sql_executors={"test_db": MagicMock()},
            result_validator=MagicMock(),
            schema_cache=MagicMock(),
            pools={"test_db": MagicMock()},
            resilience_config=ResilienceConfig(max_retries=3, retry_delay=0.1, backoff_factor=1.0),
            validation_config=ValidationConfig(),
        )

        # Execute
        sql, validation_result, _tokens = await orchestrator._generate_sql_with_retry(
            question="Get all users",
            schema=mock_schema,
        )

        # Verify
        assert sql == "SELECT * FROM users;"
        assert validation_result.is_valid is True
        assert mock_generator.generate.call_count == 2
        assert mock_validator.validate_or_raise.call_count == 2

        # Verify retry included error feedback
        second_call = mock_generator.generate.call_args_list[1]
        assert second_call.kwargs["previous_attempt"] == "SELECT * FROM user;"
        assert 'relation "user" does not exist' in second_call.kwargs["error_feedback"]

    @pytest.mark.asyncio
    async def test_generate_sql_fails_after_max_retries(self, mock_schema: DatabaseSchema) -> None:
        """Test failure after exhausting all retries."""
        # Setup mocks - all attempts fail validation
        mock_generator = AsyncMock()
        mock_generator.generate.return_value = "DELETE FROM users;"

        mock_validator = MagicMock()
        mock_validator.validate_or_raise.side_effect = SecurityViolationError(
            "DELETE statements are not allowed"
        )

        orchestrator = QueryOrchestrator(
            sql_generator=mock_generator,
            sql_validator=mock_validator,
            sql_executors={"test_db": MagicMock()},
            result_validator=MagicMock(),
            schema_cache=MagicMock(),
            pools={"test_db": MagicMock()},
            resilience_config=ResilienceConfig(max_retries=2, retry_delay=0.1, backoff_factor=1.0),
            validation_config=ValidationConfig(),
        )

        # Execute and verify exception
        with pytest.raises(SecurityViolationError) as exc_info:
            await orchestrator._generate_sql_with_retry(
                question="Delete all users",
                schema=mock_schema,
                request_id="test-123",
            )

        assert "DELETE statements are not allowed" in str(exc_info.value)
        # Should attempt max_retries + 1 times (initial + retries)
        assert mock_generator.generate.call_count == 3
        assert orchestrator.circuit_breaker.failure_count == 1

    @pytest.mark.asyncio
    async def test_generate_sql_circuit_breaker_open(self, mock_schema: DatabaseSchema) -> None:
        """Test that open circuit breaker prevents SQL generation."""
        orchestrator = QueryOrchestrator(
            sql_generator=AsyncMock(),
            sql_validator=MagicMock(),
            sql_executors={"test_db": MagicMock()},
            result_validator=MagicMock(),
            schema_cache=MagicMock(),
            pools={"test_db": MagicMock()},
            resilience_config=ResilienceConfig(circuit_breaker_threshold=1),
            validation_config=ValidationConfig(),
        )

        # Manually open the circuit breaker
        orchestrator.circuit_breaker._state = CircuitState.OPEN
        orchestrator.circuit_breaker._failure_count = 5

        # Attempt should fail immediately
        with pytest.raises(LLMError) as exc_info:
            await orchestrator._generate_sql_with_retry(
                question="Get all users",
                schema=mock_schema,
                request_id="test-123",
            )

        assert "temporarily unavailable" in str(exc_info.value).lower()
        assert "circuit breaker" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_generate_sql_unexpected_error(self, mock_schema: DatabaseSchema) -> None:
        """Test handling of unexpected errors during generation."""
        mock_generator = AsyncMock()
        mock_generator.generate.side_effect = RuntimeError("Unexpected error")

        orchestrator = QueryOrchestrator(
            sql_generator=mock_generator,
            sql_validator=MagicMock(),
            sql_executors={"test_db": MagicMock()},
            result_validator=MagicMock(),
            schema_cache=MagicMock(),
            pools={"test_db": MagicMock()},
            resilience_config=ResilienceConfig(max_retries=1, retry_delay=0.1, backoff_factor=1.0),
            validation_config=ValidationConfig(),
        )

        with pytest.raises(LLMError) as exc_info:
            await orchestrator._generate_sql_with_retry(
                question="Get all users",
                schema=mock_schema,
                request_id="test-123",
            )

        assert "unexpectedly" in str(exc_info.value).lower()
        assert orchestrator.circuit_breaker.failure_count == 1


class TestResultValidation:
    """Test result validation logic."""

    @pytest.mark.asyncio
    async def test_validate_results_success(self) -> None:
        """Test successful result validation."""
        mock_validator = AsyncMock()
        mock_validator.validate.return_value = ResultValidationResult(
            confidence=85,
            explanation="Results match the question well",
            suggestion=None,
            is_acceptable=True,
        )

        orchestrator = QueryOrchestrator(
            sql_generator=MagicMock(),
            sql_validator=MagicMock(),
            sql_executors={"test_db": MagicMock()},
            result_validator=mock_validator,
            schema_cache=MagicMock(),
            pools={"test_db": MagicMock()},
            resilience_config=ResilienceConfig(),
            validation_config=ValidationConfig(enabled=True),
        )

        confidence = await orchestrator._validate_results_safely(
            question="Count users",
            sql="SELECT COUNT(*) FROM users",
            results=[{"count": 42}],
            row_count=1,
        )

        assert confidence == 85
        mock_validator.validate.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_results_disabled(self) -> None:
        """Test that validation is skipped when disabled."""
        mock_validator = AsyncMock()

        orchestrator = QueryOrchestrator(
            sql_generator=MagicMock(),
            sql_validator=MagicMock(),
            sql_executors={"test_db": MagicMock()},
            result_validator=mock_validator,
            schema_cache=MagicMock(),
            pools={"test_db": MagicMock()},
            resilience_config=ResilienceConfig(),
            validation_config=ValidationConfig(enabled=False),
        )

        confidence = await orchestrator._validate_results_safely(
            question="Count users",
            sql="SELECT COUNT(*) FROM users",
            results=[{"count": 42}],
            row_count=1,
        )

        assert confidence == 100
        mock_validator.validate.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_results_failure_does_not_raise(self) -> None:
        """Test that validation failures don't raise exceptions."""
        mock_validator = AsyncMock()
        mock_validator.validate.side_effect = Exception("Validation failed")

        orchestrator = QueryOrchestrator(
            sql_generator=MagicMock(),
            sql_validator=MagicMock(),
            sql_executors={"test_db": MagicMock()},
            result_validator=mock_validator,
            schema_cache=MagicMock(),
            pools={"test_db": MagicMock()},
            resilience_config=ResilienceConfig(),
            validation_config=ValidationConfig(enabled=True),
        )

        # Should not raise, returns default confidence
        confidence = await orchestrator._validate_results_safely(
            question="Count users",
            sql="SELECT COUNT(*) FROM users",
            results=[{"count": 42}],
            row_count=1,
        )

        assert confidence == 100


class TestExecuteQueryFlow:
    """Test complete query execution flow."""

    @pytest.fixture
    def mock_schema(self) -> DatabaseSchema:
        """Create mock database schema."""
        return DatabaseSchema(
            database_name="test_db",
            tables=[
                TableInfo(
                    schema_name="public",
                    table_name="users",
                    columns=[
                        ColumnInfo(
                            name="id",
                            data_type="integer",
                            is_nullable=False,
                            is_primary_key=True,
                        ),
                        ColumnInfo(
                            name="name",
                            data_type="varchar(255)",
                            is_nullable=False,
                        ),
                    ],
                )
            ],
            version="15.0",
        )

    @pytest.mark.asyncio
    async def test_execute_query_sql_only(self, mock_schema: DatabaseSchema) -> None:
        """Test executing query with return_type=SQL."""
        # Setup mocks
        mock_generator = AsyncMock()
        mock_generator.generate.return_value = "SELECT * FROM users;"

        mock_validator = MagicMock()
        mock_validator.validate_or_raise.return_value = None

        mock_cache = MagicMock()
        mock_cache.get.return_value = mock_schema

        orchestrator = QueryOrchestrator(
            sql_generator=mock_generator,
            sql_validator=mock_validator,
            sql_executors={"test_db": MagicMock()},
            result_validator=MagicMock(),
            schema_cache=mock_cache,
            pools={"test_db": MagicMock()},
            resilience_config=ResilienceConfig(),
            validation_config=ValidationConfig(),
        )

        # Execute
        request = QueryRequest(
            question="Get all users",
            database="test_db",
            return_type=ReturnType.SQL,
        )
        response = await orchestrator.execute_query(request)

        # Verify
        assert response.success is True
        assert response.generated_sql == "SELECT * FROM users;"
        assert response.validation is not None
        assert response.validation.is_valid is True
        assert response.data is None  # No execution for SQL-only
        assert response.error is None

    @pytest.mark.asyncio
    async def test_execute_query_with_results(self, mock_schema: DatabaseSchema) -> None:
        """Test executing query with return_type=RESULT."""
        # Setup mocks
        mock_generator = AsyncMock()
        mock_generator.generate.return_value = "SELECT id, name FROM users;"

        mock_validator = MagicMock()
        mock_validator.validate_or_raise.return_value = None

        mock_executor = AsyncMock()
        mock_executor.execute.return_value = (
            [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
            ],
            2,  # total count
        )

        mock_result_validator = AsyncMock()
        mock_result_validator.validate.return_value = ResultValidationResult(
            confidence=90,
            explanation="Good results",
            suggestion=None,
            is_acceptable=True,
        )

        mock_cache = MagicMock()
        mock_cache.get.return_value = mock_schema

        orchestrator = QueryOrchestrator(
            sql_generator=mock_generator,
            sql_validator=mock_validator,
            sql_executors={"test_db": mock_executor},
            result_validator=mock_result_validator,
            schema_cache=mock_cache,
            pools={"test_db": MagicMock()},
            resilience_config=ResilienceConfig(),
            validation_config=ValidationConfig(enabled=True),
        )

        # Execute
        request = QueryRequest(
            question="Get all users",
            database="test_db",
            return_type=ReturnType.RESULT,
        )
        response = await orchestrator.execute_query(request)

        # Verify
        assert response.success is True
        assert response.generated_sql == "SELECT id, name FROM users;"
        assert response.data is not None
        assert response.data.row_count == 2
        assert len(response.data.rows) == 2
        assert response.data.columns == ["id", "name"]
        assert response.confidence == 90
        assert response.error is None

    @pytest.mark.asyncio
    async def test_execute_query_schema_not_cached(self) -> None:
        """Test loading schema when not in cache."""
        mock_schema = DatabaseSchema(
            database_name="test_db",
            tables=[],
            version="15.0",
        )

        # Setup mocks
        mock_cache = MagicMock()
        mock_cache.get.return_value = None  # Not in cache
        mock_cache.load = AsyncMock(return_value=mock_schema)

        mock_generator = AsyncMock()
        mock_generator.generate.return_value = "SELECT 1;"

        mock_validator = MagicMock()
        mock_validator.validate_or_raise.return_value = None

        mock_pool = MagicMock()

        orchestrator = QueryOrchestrator(
            sql_generator=mock_generator,
            sql_validator=mock_validator,
            sql_executors={"test_db": MagicMock()},
            result_validator=MagicMock(),
            schema_cache=mock_cache,
            pools={"test_db": mock_pool},
            resilience_config=ResilienceConfig(),
            validation_config=ValidationConfig(),
        )

        # Execute
        request = QueryRequest(
            question="Test query",
            database="test_db",
            return_type=ReturnType.SQL,
        )
        response = await orchestrator.execute_query(request)

        # Verify schema was loaded
        mock_cache.load.assert_called_once_with("test_db", mock_pool)
        assert response.success is True

    @pytest.mark.asyncio
    async def test_execute_query_schema_load_fails(self) -> None:
        """Test handling of schema load failure."""
        # Setup mocks
        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        mock_cache.load = AsyncMock(side_effect=Exception("DB connection failed"))

        orchestrator = QueryOrchestrator(
            sql_generator=MagicMock(),
            sql_validator=MagicMock(),
            sql_executors={"test_db": MagicMock()},
            result_validator=MagicMock(),
            schema_cache=mock_cache,
            pools={"test_db": MagicMock()},
            resilience_config=ResilienceConfig(),
            validation_config=ValidationConfig(),
        )

        # Execute
        request = QueryRequest(
            question="Test query",
            database="test_db",
            return_type=ReturnType.SQL,
        )
        response = await orchestrator.execute_query(request)

        # Verify error response
        assert response.success is False
        assert response.error is not None
        assert "schema" in response.error.message.lower()
        assert response.generated_sql is None

    @pytest.mark.asyncio
    async def test_execute_query_validation_error(self) -> None:
        """Test handling of SQL validation errors."""
        mock_schema = DatabaseSchema(
            database_name="test_db",
            tables=[],
            version="15.0",
        )

        # Setup mocks
        mock_cache = MagicMock()
        mock_cache.get.return_value = mock_schema

        mock_generator = AsyncMock()
        mock_generator.generate.return_value = "DELETE FROM users;"

        mock_validator = MagicMock()
        mock_validator.validate_or_raise.side_effect = SecurityViolationError("DELETE not allowed")

        orchestrator = QueryOrchestrator(
            sql_generator=mock_generator,
            sql_validator=mock_validator,
            sql_executors={"test_db": MagicMock()},
            result_validator=MagicMock(),
            schema_cache=mock_cache,
            pools={"test_db": MagicMock()},
            resilience_config=ResilienceConfig(max_retries=1, retry_delay=0.1, backoff_factor=1.0),
            validation_config=ValidationConfig(),
        )

        # Execute
        request = QueryRequest(
            question="Delete all users",
            database="test_db",
            return_type=ReturnType.SQL,
        )
        response = await orchestrator.execute_query(request)

        # Verify error response
        assert response.success is False
        assert response.error is not None
        assert "DELETE not allowed" in response.error.message
        assert response.error.code == "security_violation"

    @pytest.mark.asyncio
    async def test_execute_query_execution_error(self, mock_schema: DatabaseSchema) -> None:
        """Test handling of SQL execution errors."""
        # Setup mocks
        mock_cache = MagicMock()
        mock_cache.get.return_value = mock_schema

        mock_generator = AsyncMock()
        mock_generator.generate.return_value = "SELECT * FROM users;"

        mock_validator = MagicMock()
        mock_validator.validate_or_raise.return_value = None

        mock_executor = AsyncMock()
        mock_executor.execute.side_effect = DatabaseError("Query execution failed")

        orchestrator = QueryOrchestrator(
            sql_generator=mock_generator,
            sql_validator=mock_validator,
            sql_executors={"test_db": mock_executor},
            result_validator=MagicMock(),
            schema_cache=mock_cache,
            pools={"test_db": MagicMock()},
            resilience_config=ResilienceConfig(),
            validation_config=ValidationConfig(),
        )

        # Execute
        request = QueryRequest(
            question="Get all users",
            database="test_db",
            return_type=ReturnType.RESULT,
        )
        response = await orchestrator.execute_query(request)

        # Verify error response
        assert response.success is False
        assert response.error is not None
        assert "execution failed" in response.error.message.lower()
        assert response.error.code == "database_error"

    @pytest.mark.asyncio
    async def test_execute_query_unexpected_error(self, mock_schema: DatabaseSchema) -> None:
        """Test handling of unexpected errors."""
        # Setup mocks
        mock_cache = MagicMock()
        mock_cache.get.side_effect = RuntimeError("Unexpected error")

        orchestrator = QueryOrchestrator(
            sql_generator=MagicMock(),
            sql_validator=MagicMock(),
            sql_executors={"test_db": MagicMock()},
            result_validator=MagicMock(),
            schema_cache=mock_cache,
            pools={"test_db": MagicMock()},
            resilience_config=ResilienceConfig(),
            validation_config=ValidationConfig(),
        )

        # Execute
        request = QueryRequest(
            question="Get all users",
            database="test_db",
            return_type=ReturnType.SQL,
        )
        response = await orchestrator.execute_query(request)

        # Verify error response
        assert response.success is False
        assert response.error is not None
        assert response.error.code == "internal_error"
        assert "internal server error" in response.error.message.lower()

    @pytest.mark.asyncio
    async def test_execute_query_auto_select_database(self, mock_schema: DatabaseSchema) -> None:
        """Test auto-selecting database when only one available."""
        # Setup mocks
        mock_cache = MagicMock()
        mock_cache.get.return_value = mock_schema

        mock_generator = AsyncMock()
        mock_generator.generate.return_value = "SELECT 1;"

        mock_validator = MagicMock()
        mock_validator.validate_or_raise.return_value = None

        orchestrator = QueryOrchestrator(
            sql_generator=mock_generator,
            sql_validator=mock_validator,
            sql_executors={"test_db": MagicMock()},
            result_validator=MagicMock(),
            schema_cache=mock_cache,
            pools={"only_db": MagicMock()},  # Only one database
            resilience_config=ResilienceConfig(),
            validation_config=ValidationConfig(),
        )

        # Execute without specifying database
        request = QueryRequest(
            question="Test query",
            database=None,  # No database specified
            return_type=ReturnType.SQL,
        )
        response = await orchestrator.execute_query(request)

        # Verify
        assert response.success is True
        # Verify schema was fetched for auto-selected database
        mock_cache.get.assert_called_once_with("only_db")


class TestMultiDatabaseRouting:
    """Test that queries route to the executor of the resolved database."""

    @pytest.fixture
    def mock_schema(self) -> DatabaseSchema:
        """Create mock database schema."""
        return DatabaseSchema(database_name="db_a", tables=[], version="15.0")

    def _make_orchestrator(
        self,
        mock_schema: DatabaseSchema,
    ) -> tuple[QueryOrchestrator, AsyncMock, AsyncMock]:
        """Build an orchestrator with executors for two databases."""
        mock_generator = AsyncMock()
        mock_generator.generate.return_value = "SELECT 1;"

        mock_validator = MagicMock()
        mock_validator.validate_or_raise.return_value = None

        executor_a = AsyncMock()
        executor_a.execute.return_value = ([{"id": 1}], 1)
        executor_b = AsyncMock()
        executor_b.execute.return_value = ([{"id": 2}], 1)

        mock_cache = MagicMock()
        mock_cache.get.return_value = mock_schema

        orchestrator = QueryOrchestrator(
            sql_generator=mock_generator,
            sql_validator=mock_validator,
            sql_executors={"db_a": executor_a, "db_b": executor_b},
            result_validator=AsyncMock(),
            schema_cache=mock_cache,
            pools={"db_a": MagicMock(), "db_b": MagicMock()},
            resilience_config=ResilienceConfig(),
            validation_config=ValidationConfig(enabled=False),
        )
        return orchestrator, executor_a, executor_b

    @pytest.mark.asyncio
    async def test_routes_to_matching_executor(self, mock_schema: DatabaseSchema) -> None:
        """Test the executor matching the requested database is used."""
        orchestrator, executor_a, executor_b = self._make_orchestrator(mock_schema)

        request = QueryRequest(
            question="Get users", database="db_a", return_type=ReturnType.RESULT
        )
        response = await orchestrator.execute_query(request)

        assert response.success is True
        executor_a.execute.assert_called_once()
        executor_b.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_executor_returns_database_error(
        self, mock_schema: DatabaseSchema
    ) -> None:
        """Test a missing executor for the resolved database yields database_error."""
        orchestrator, executor_a, executor_b = self._make_orchestrator(mock_schema)
        orchestrator.sql_executors = {}

        request = QueryRequest(
            question="Get users", database="db_a", return_type=ReturnType.RESULT
        )
        response = await orchestrator.execute_query(request)

        assert response.success is False
        assert response.error is not None
        assert response.error.code == "database_error"
        assert response.error.details["available_databases"] == []
        executor_a.execute.assert_not_called()
        executor_b.execute.assert_not_called()


class TestQueryRateLimiting:
    """Test query concurrency slot exhaustion."""

    @pytest.mark.asyncio
    async def test_slot_exhaustion_returns_rate_limit_exceeded(self) -> None:
        """Test a request that cannot acquire a query slot is rejected."""
        orchestrator = QueryOrchestrator(
            sql_generator=AsyncMock(),
            sql_validator=MagicMock(),
            sql_executors={"test_db": AsyncMock()},
            result_validator=AsyncMock(),
            schema_cache=MagicMock(),
            pools={"test_db": MagicMock()},
            resilience_config=ResilienceConfig(query_concurrency=1, rate_limit_wait=0.1),
            validation_config=ValidationConfig(),
        )

        # Occupy the only query slot so the request cannot acquire it
        await orchestrator.rate_limiter.query_limiter.acquire()
        try:
            request = QueryRequest(
                question="Get users", database="test_db", return_type=ReturnType.SQL
            )
            response = await orchestrator.execute_query(request)
        finally:
            orchestrator.rate_limiter.query_limiter.release()
            await asyncio.sleep(0)  # let the release bookkeeping task run

        assert response.success is False
        assert response.error is not None
        assert response.error.code == "rate_limit_exceeded"
        assert "concurrency" in response.error.message.lower()


class TestTransientLLMRetry:
    """Test retry of transient LLM errors with exponential backoff."""

    @pytest.fixture
    def mock_schema(self) -> DatabaseSchema:
        """Create mock database schema."""
        return DatabaseSchema(database_name="test_db", tables=[], version="15.0")

    def _make_orchestrator(
        self,
        mock_generator: AsyncMock,
        max_retries: int = 2,
    ) -> QueryOrchestrator:
        """Build an orchestrator with configurable retry settings."""
        mock_validator = MagicMock()
        mock_validator.validate_or_raise.return_value = None

        return QueryOrchestrator(
            sql_generator=mock_generator,
            sql_validator=mock_validator,
            sql_executors={"test_db": AsyncMock()},
            result_validator=AsyncMock(),
            schema_cache=MagicMock(),
            pools={"test_db": MagicMock()},
            resilience_config=ResilienceConfig(
                max_retries=max_retries,
                retry_delay=0.5,
                backoff_factor=2.0,
            ),
            validation_config=ValidationConfig(),
        )

    @pytest.mark.asyncio
    async def test_transient_error_retried_then_succeeds(
        self, mock_schema: DatabaseSchema, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test a transient LLM error is retried without error feedback."""
        delays: list[float] = []

        async def fake_sleep(delay: float) -> None:
            delays.append(delay)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        mock_generator = AsyncMock()
        mock_generator.generate.side_effect = [
            LLMTimeoutError("Request timed out"),
            "SELECT 1;",
        ]
        orchestrator = self._make_orchestrator(mock_generator)

        sql, validation, _tokens = await orchestrator._generate_sql_with_retry(
            question="Get users", schema=mock_schema
        )

        assert sql == "SELECT 1;"
        assert validation.is_valid is True
        assert mock_generator.generate.call_count == 2
        # Backoff delay: retry_delay * backoff_factor ** attempt(=0)
        assert delays == [0.5]
        # Transient retries carry no corrective context
        second_call = mock_generator.generate.call_args_list[1]
        assert second_call.kwargs["previous_attempt"] is None
        assert second_call.kwargs["error_feedback"] is None

    @pytest.mark.asyncio
    async def test_backoff_delays_grow_exponentially(
        self, mock_schema: DatabaseSchema, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test consecutive transient failures back off exponentially."""
        delays: list[float] = []

        async def fake_sleep(delay: float) -> None:
            delays.append(delay)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        mock_generator = AsyncMock()
        mock_generator.generate.side_effect = [
            LLMUnavailableError("api down"),
            LLMUnavailableError("api down"),
            "SELECT 1;",
        ]
        orchestrator = self._make_orchestrator(mock_generator, max_retries=2)

        sql, _validation, _tokens = await orchestrator._generate_sql_with_retry(
            question="Get users", schema=mock_schema
        )

        assert sql == "SELECT 1;"
        assert delays == [0.5, 1.0]  # 0.5 * 2^0, 0.5 * 2^1

    @pytest.mark.asyncio
    async def test_transient_error_exhausts_retries_and_records_failure(
        self, mock_schema: DatabaseSchema, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test final transient failure raises and records a breaker failure."""

        async def fake_sleep(_delay: float) -> None:
            return None

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        mock_generator = AsyncMock()
        mock_generator.generate.side_effect = LLMTimeoutError("Request timed out")
        orchestrator = self._make_orchestrator(mock_generator, max_retries=2)

        with pytest.raises(LLMTimeoutError):
            await orchestrator._generate_sql_with_retry(
                question="Get users", schema=mock_schema
            )

        assert mock_generator.generate.call_count == 3  # max_retries + 1
        assert orchestrator.circuit_breaker.failure_count == 1


class TestTokensUsedPropagation:
    """Test token usage flows from the generator to the response."""

    @pytest.fixture
    def mock_schema(self) -> DatabaseSchema:
        """Create mock database schema."""
        return DatabaseSchema(database_name="test_db", tables=[], version="15.0")

    def _make_orchestrator(self, mock_generator: AsyncMock) -> QueryOrchestrator:
        """Build an orchestrator around the given generator."""
        mock_validator = MagicMock()
        mock_validator.validate_or_raise.return_value = None

        mock_cache = MagicMock()
        mock_cache.get.return_value = DatabaseSchema(
            database_name="test_db", tables=[], version="15.0"
        )

        return QueryOrchestrator(
            sql_generator=mock_generator,
            sql_validator=mock_validator,
            sql_executors={"test_db": AsyncMock()},
            result_validator=AsyncMock(),
            schema_cache=mock_cache,
            pools={"test_db": MagicMock()},
            resilience_config=ResilienceConfig(),
            validation_config=ValidationConfig(),
        )

    @pytest.mark.asyncio
    async def test_tokens_used_reaches_response(self, mock_schema: DatabaseSchema) -> None:
        """Test integer token usage is forwarded to the response."""
        mock_generator = AsyncMock()
        mock_generator.generate.return_value = "SELECT 1;"
        mock_generator.last_tokens_used = 321
        orchestrator = self._make_orchestrator(mock_generator)

        request = QueryRequest(
            question="Get users", database="test_db", return_type=ReturnType.SQL
        )
        response = await orchestrator.execute_query(request)

        assert response.success is True
        assert response.tokens_used == 321

    @pytest.mark.asyncio
    async def test_non_int_tokens_ignored(self, mock_schema: DatabaseSchema) -> None:
        """Test non-integer token values (e.g. from mocks) are dropped."""
        mock_generator = AsyncMock()
        mock_generator.generate.return_value = "SELECT 1;"
        mock_generator.last_tokens_used = "not-an-int"
        orchestrator = self._make_orchestrator(mock_generator)

        request = QueryRequest(
            question="Get users", database="test_db", return_type=ReturnType.SQL
        )
        response = await orchestrator.execute_query(request)

        assert response.success is True
        assert response.tokens_used is None

    @pytest.mark.asyncio
    async def test_bool_tokens_ignored(self, mock_schema: DatabaseSchema) -> None:
        """Test boolean values are not mistaken for token counts."""
        mock_generator = AsyncMock()
        mock_generator.generate.return_value = "SELECT 1;"
        mock_generator.last_tokens_used = True
        orchestrator = self._make_orchestrator(mock_generator)

        request = QueryRequest(
            question="Get users", database="test_db", return_type=ReturnType.SQL
        )
        response = await orchestrator.execute_query(request)

        assert response.success is True
        assert response.tokens_used is None


class TestMetricsRecording:
    """Test Prometheus metrics deltas around query execution.

    Metrics are process-global singletons, so assertions always compare
    ``get_sample_value`` deltas instead of absolute values.
    """

    @pytest.fixture
    def mock_schema(self) -> DatabaseSchema:
        """Create mock database schema."""
        return DatabaseSchema(database_name="test_db", tables=[], version="15.0")

    @pytest.mark.asyncio
    async def test_success_increments_request_and_duration(
        self, mock_schema: DatabaseSchema
    ) -> None:
        """Test a successful query bumps the request counter and duration histogram."""
        mock_generator = AsyncMock()
        mock_generator.generate.return_value = "SELECT 1;"

        mock_validator = MagicMock()
        mock_validator.validate_or_raise.return_value = None

        mock_cache = MagicMock()
        mock_cache.get.return_value = mock_schema

        orchestrator = QueryOrchestrator(
            sql_generator=mock_generator,
            sql_validator=mock_validator,
            sql_executors={"test_db": AsyncMock()},
            result_validator=AsyncMock(),
            schema_cache=mock_cache,
            pools={"test_db": MagicMock()},
            resilience_config=ResilienceConfig(),
            validation_config=ValidationConfig(),
        )
        request = QueryRequest(
            question="Get users", database="test_db", return_type=ReturnType.SQL
        )

        before_requests = (
            get_sample_value(
                "pg_mcp_query_requests_total",
                {"status": "success", "database": "test_db"},
            )
            or 0.0
        )
        before_duration = (
            get_sample_value("pg_mcp_query_duration_seconds_count") or 0.0
        )

        response = await orchestrator.execute_query(request)

        after_requests = (
            get_sample_value(
                "pg_mcp_query_requests_total",
                {"status": "success", "database": "test_db"},
            )
            or 0.0
        )
        after_duration = (
            get_sample_value("pg_mcp_query_duration_seconds_count") or 0.0
        )

        assert response.success is True
        assert after_requests - before_requests == 1
        assert after_duration - before_duration == 1

    @pytest.mark.asyncio
    async def test_internal_error_increments_error_counter(
        self, mock_schema: DatabaseSchema
    ) -> None:
        """Test an unexpected error bumps the internal_error request counter."""
        mock_cache = MagicMock()
        mock_cache.get.side_effect = RuntimeError("boom")

        orchestrator = QueryOrchestrator(
            sql_generator=AsyncMock(),
            sql_validator=MagicMock(),
            sql_executors={"test_db": AsyncMock()},
            result_validator=AsyncMock(),
            schema_cache=mock_cache,
            pools={"test_db": MagicMock()},
            resilience_config=ResilienceConfig(),
            validation_config=ValidationConfig(),
        )
        request = QueryRequest(
            question="Get users", database="test_db", return_type=ReturnType.SQL
        )

        before = (
            get_sample_value(
                "pg_mcp_query_requests_total",
                {"status": "internal_error", "database": "test_db"},
            )
            or 0.0
        )

        response = await orchestrator.execute_query(request)

        after = (
            get_sample_value(
                "pg_mcp_query_requests_total",
                {"status": "internal_error", "database": "test_db"},
            )
            or 0.0
        )

        assert response.success is False
        assert response.error is not None
        assert response.error.code == "internal_error"
        assert after - before == 1

    @pytest.mark.asyncio
    async def test_final_validation_failure_increments_sql_rejected(
        self, mock_schema: DatabaseSchema, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test exhausting validation retries bumps the security rejection counter."""

        async def fake_sleep(_delay: float) -> None:
            return None

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        mock_generator = AsyncMock()
        mock_generator.generate.return_value = "DELETE FROM users;"

        mock_validator = MagicMock()
        mock_validator.validate_or_raise.side_effect = SecurityViolationError(
            "DELETE statements are not allowed"
        )

        orchestrator = QueryOrchestrator(
            sql_generator=mock_generator,
            sql_validator=mock_validator,
            sql_executors={"test_db": AsyncMock()},
            result_validator=AsyncMock(),
            schema_cache=MagicMock(),
            pools={"test_db": MagicMock()},
            resilience_config=ResilienceConfig(
                max_retries=1, retry_delay=0.1, backoff_factor=1.0
            ),
            validation_config=ValidationConfig(),
        )

        before = (
            get_sample_value("pg_mcp_sql_rejected_total", {"reason": "security"}) or 0.0
        )

        with pytest.raises(SecurityViolationError):
            await orchestrator._generate_sql_with_retry(
                question="Delete users", schema=mock_schema
            )

        after = (
            get_sample_value("pg_mcp_sql_rejected_total", {"reason": "security"}) or 0.0
        )

        assert after - before == 1
