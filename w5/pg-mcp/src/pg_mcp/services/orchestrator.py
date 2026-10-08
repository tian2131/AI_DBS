"""Query orchestrator for coordinating the complete query flow.

This module provides the QueryOrchestrator class that coordinates all components
of the query processing pipeline: SQL generation, validation, execution, and result
validation. It implements retry logic with exponential backoff, concurrency rate
limiting, a circuit breaker, metrics collection, and request tracing.
"""

import asyncio
import logging
import time
from typing import Any

from asyncpg import Pool

from pg_mcp.cache.schema_cache import SchemaCache
from pg_mcp.config.settings import ResilienceConfig, ValidationConfig
from pg_mcp.models.errors import (
    DatabaseError,
    ErrorCode,
    LLMError,
    LLMTimeoutError,
    LLMUnavailableError,
    PgMcpError,
    RateLimitExceededError,
    SchemaLoadError,
    SecurityViolationError,
    SQLParseError,
)
from pg_mcp.models.query import (
    ErrorDetail,
    QueryRequest,
    QueryResponse,
    QueryResult,
    ReturnType,
    ValidationResult,
)
from pg_mcp.observability.metrics import metrics
from pg_mcp.observability.tracing import generate_request_id, request_context
from pg_mcp.resilience.circuit_breaker import CircuitBreaker
from pg_mcp.resilience.rate_limiter import MultiRateLimiter
from pg_mcp.services.result_validator import ResultValidator
from pg_mcp.services.sql_executor import SQLExecutor
from pg_mcp.services.sql_generator import SQLGenerator
from pg_mcp.services.sql_validator import SQLValidator

logger = logging.getLogger(__name__)


class QueryOrchestrator:
    """Orchestrates the complete query processing pipeline.

    This class coordinates SQL generation, validation, execution, and result
    validation. It implements retry logic with exponential backoff, concurrency
    rate limiting (query and LLM slots), a circuit breaker for fault tolerance,
    Prometheus metrics, and request-ID tracing via context variables.

    Example:
        >>> orchestrator = QueryOrchestrator(
        ...     sql_generator=generator,
        ...     sql_validator=validator,
        ...     sql_executors={"mydb": executor},
        ...     result_validator=result_validator,
        ...     schema_cache=cache,
        ...     pools={"mydb": pool},
        ...     resilience_config=resilience_config,
        ...     validation_config=validation_config,
        ... )
        >>> response = await orchestrator.execute_query(QueryRequest(
        ...     question="How many users?",
        ...     database="mydb"
        ... ))
    """

    def __init__(
        self,
        sql_generator: SQLGenerator,
        sql_validator: SQLValidator,
        sql_executors: dict[str, SQLExecutor],
        result_validator: ResultValidator,
        schema_cache: SchemaCache,
        pools: dict[str, Pool],
        resilience_config: ResilienceConfig,
        validation_config: ValidationConfig,
    ) -> None:
        """Initialize query orchestrator.

        Args:
            sql_generator: SQL generation service.
            sql_validator: SQL validation service.
            sql_executors: SQL execution services keyed by database name. The
                executor matching the resolved database is used per request.
            result_validator: Result validation service.
            schema_cache: Schema cache instance.
            pools: Dictionary mapping database names to connection pools.
            resilience_config: Resilience configuration for retries, backoff,
                circuit breaker, and concurrency limits.
            validation_config: Validation configuration including thresholds.
        """
        self.sql_generator = sql_generator
        self.sql_validator = sql_validator
        self.sql_executors = sql_executors
        self.result_validator = result_validator
        self.schema_cache = schema_cache
        self.pools = pools
        self.resilience_config = resilience_config
        self.validation_config = validation_config

        # Create circuit breaker for LLM calls
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=resilience_config.circuit_breaker_threshold,
            recovery_timeout=resilience_config.circuit_breaker_timeout,
        )

        # Concurrency limiters for query execution and LLM calls
        self.rate_limiter = MultiRateLimiter(
            query_limit=resilience_config.query_concurrency,
            llm_limit=resilience_config.llm_concurrency,
        )

    async def execute_query(self, request: QueryRequest) -> QueryResponse:
        """Execute complete query flow from question to results.

        This method orchestrates the entire pipeline:
        1. Generate request_id and enter the tracing context
        2. Acquire a query concurrency slot (rate limiting)
        3. Resolve and validate database name
        4. Load schema from cache
        5. Generate and validate SQL with retry + backoff
        6. Execute SQL on the resolved database (if return_type == RESULT)
        7. Validate results (optional)
        8. Return structured response

        Args:
            request: Query request containing question and parameters.

        Returns:
            QueryResponse: Complete response with SQL, results, or error information.

        Example:
            >>> response = await orchestrator.execute_query(
            ...     QueryRequest(question="Count all users", return_type="result")
            ... )
            >>> if response.success:
            ...     print(f"Found {response.data.row_count} rows")
        """
        request_id = generate_request_id()
        database_name: str | None = None
        start = time.monotonic()
        logger.info("Starting query execution", extra={"question": request.question[:100]})

        async with request_context(request_id):
            try:
                # Resolve the database up front so error metrics can be
                # labelled with it even when the pipeline fails early.
                database_name = self._resolve_database(request.database)
                logger.debug("Resolved database", extra={"database": database_name})
                async with self.rate_limiter.for_queries(
                    timeout=self.resilience_config.rate_limit_wait
                ):
                    return await self._process_query(
                        request, start, database_name=database_name, request_id=request_id
                    )
            except PgMcpError as e:
                # Handle known application errors
                logger.warning(
                    "Query execution failed with known error",
                    extra={"error_code": e.code, "error_message": str(e)},
                )
                self._record_query_metrics(e.code.value, database_name, start)
                return QueryResponse(
                    success=False,
                    generated_sql=None,
                    validation=None,
                    data=None,
                    error=ErrorDetail(
                        code=e.code.value,
                        message=e.message,
                        details=e.details,
                    ),
                    confidence=0,
                    tokens_used=None,
                )
            except TimeoutError as e:
                # Built-in TimeoutError here means the concurrency slot wait
                # timed out (service timeouts are converted to custom errors).
                logger.warning("Query rejected: concurrency limit", extra={"error": str(e)})
                self._record_query_metrics(
                    ErrorCode.RATE_LIMIT_EXCEEDED.value, database_name, start
                )
                return QueryResponse(
                    success=False,
                    generated_sql=None,
                    validation=None,
                    data=None,
                    error=ErrorDetail(
                        code=ErrorCode.RATE_LIMIT_EXCEEDED.value,
                        message=(
                            "Query concurrency limit reached; no slot acquired within "
                            f"{self.resilience_config.rate_limit_wait}s"
                        ),
                        details={"wait_seconds": self.resilience_config.rate_limit_wait},
                    ),
                    confidence=0,
                    tokens_used=None,
                )
            except Exception as e:
                # Handle unexpected errors
                logger.exception("Query execution failed with unexpected error")
                self._record_query_metrics(ErrorCode.INTERNAL_ERROR.value, database_name, start)
                return QueryResponse(
                    success=False,
                    generated_sql=None,
                    validation=None,
                    data=None,
                    error=ErrorDetail(
                        code=ErrorCode.INTERNAL_ERROR.value,
                        message=f"Internal server error: {e!s}",
                        details={"error_type": type(e).__name__},
                    ),
                    confidence=0,
                    tokens_used=None,
                )

    async def _process_query(
        self,
        request: QueryRequest,
        start: float,
        database_name: str,
        request_id: str | None = None,
    ) -> QueryResponse:
        """Run the query pipeline steps inside an acquired concurrency slot.

        Args:
            request: Query request containing question and parameters.
            start: ``time.monotonic()`` timestamp taken at request start, used
                for the end-to-end duration metric on success exits.
            database_name: Resolved target database name.
            request_id: Request ID generated by the caller for log correlation.

        Returns:
            QueryResponse: Complete response with SQL, results, or error information.

        Raises:
            DatabaseError: If the database or its executor cannot be resolved.
            SchemaLoadError: If schema introspection fails.
            LLMError: If SQL generation fails after all retries.
            SecurityViolationError: If SQL fails validation after all retries.
            SQLParseError: If SQL cannot be parsed.
        """
        # Step 1: Get schema from cache
        schema = self.schema_cache.get(database_name)
        if schema is None:
            # Schema not in cache, load it
            pool = self.pools.get(database_name)
            if pool is None:
                raise DatabaseError(
                    message=f"No connection pool available for database '{database_name}'",
                    details={"database": database_name},
                )
            try:
                schema = await self.schema_cache.load(database_name, pool)
            except Exception as e:
                raise SchemaLoadError(
                    message=f"Failed to load schema for database '{database_name}': {e!s}",
                    details={"database": database_name, "error": str(e)},
                ) from e

        logger.debug(
            "Schema loaded", extra={"database": database_name, "tables": len(schema.tables)}
        )

        # Step 2: Generate and validate SQL with retry logic
        generated_sql, validation_result, tokens_used = await self._generate_sql_with_retry(
            question=request.question,
            schema=schema,
            request_id=request_id,
        )

        # Step 3: If return_type is SQL, return early
        if request.return_type == ReturnType.SQL:
            logger.info("Returning SQL only", extra={"sql_length": len(generated_sql)})
            self._record_query_metrics(ErrorCode.SUCCESS.value, database_name, start)
            return QueryResponse(
                success=True,
                generated_sql=generated_sql,
                validation=validation_result,
                data=None,
                error=None,
                confidence=100,
                tokens_used=tokens_used,
            )

        # Step 4: Execute SQL on the resolved database's executor
        logger.debug("Executing SQL")
        executor = self.sql_executors.get(database_name)
        if executor is None:
            raise DatabaseError(
                message=f"No SQL executor configured for database '{database_name}'",
                details={
                    "database": database_name,
                    "available_databases": sorted(self.sql_executors),
                },
            )

        start_time = self._get_current_time_ms()
        results, total_count = await executor.execute(generated_sql)

        execution_time_ms = self._get_current_time_ms() - start_time
        logger.info(
            "SQL executed successfully",
            extra={"row_count": total_count, "execution_time_ms": execution_time_ms},
        )

        # Step 5: Validate results (non-blocking, failures don't fail the request)
        result_confidence = await self._validate_results_safely(
            question=request.question,
            sql=generated_sql,
            results=results,
            row_count=total_count,
        )

        # Step 6: Build successful response
        query_result = QueryResult(
            columns=list(results[0].keys()) if results else [],
            rows=results,
            row_count=len(results),  # Limited row count (after max_rows applied)
            execution_time_ms=execution_time_ms,
        )

        self._record_query_metrics(ErrorCode.SUCCESS.value, database_name, start)
        return QueryResponse(
            success=True,
            generated_sql=generated_sql,
            validation=validation_result,
            data=query_result,
            error=None,
            confidence=result_confidence,
            tokens_used=tokens_used,
        )

    def _resolve_database(self, database: str | None) -> str:
        """Resolve database name from request or auto-select.

        If database is specified, validate it exists.
        If not specified and only one database available, auto-select it.

        Args:
            database: Database name from request (optional).

        Returns:
            str: Resolved database name.

        Raises:
            DatabaseError: If database is invalid or cannot be auto-selected.

        Example:
            >>> name = orchestrator._resolve_database("mydb")  # Validates "mydb" exists
            >>> name = orchestrator._resolve_database(None)  # Auto-selects if only one DB
        """
        if database is not None:
            # Validate specified database exists
            if database not in self.pools:
                raise DatabaseError(
                    message=f"Database '{database}' not found",
                    details={
                        "requested_database": database,
                        "available_databases": list(self.pools.keys()),
                    },
                )
            return database

        # Auto-select if only one database available
        available_dbs = list(self.pools.keys())
        if len(available_dbs) == 0:
            raise DatabaseError(
                message="No databases configured",
                details={},
            )
        if len(available_dbs) == 1:
            return available_dbs[0]

        # Multiple databases, must specify
        raise DatabaseError(
            message="Multiple databases available, please specify which to query",
            details={"available_databases": available_dbs},
        )

    async def _generate_sql_with_retry(
        self,
        question: str,
        schema: Any,
        request_id: str | None = None,
    ) -> tuple[str, ValidationResult, int | None]:
        """Generate and validate SQL with retry, backoff, and circuit breaking.

        The retry loop handles two failure classes:
        - Validation failures (security/parse): retried with the error fed back
          to the LLM as corrective context.
        - Transient LLM errors (timeout, unavailability): retried as-is with
          exponential backoff, without error feedback.

        Args:
            question: User's natural language question.
            schema: Database schema for context.
            request_id: Request ID for log correlation when called outside the
                request tracing context (optional).

        Returns:
            tuple: (generated_sql, validation_result, tokens_used)

        Raises:
            LLMError: If circuit breaker is open or generation fails.
            SecurityViolationError: If SQL fails validation after all retries.
            SQLParseError: If SQL cannot be parsed.
            RateLimitExceededError: If no LLM concurrency slot is acquired.
        """
        # Check circuit breaker
        if not self.circuit_breaker.allow_request():
            raise LLMError(
                message="SQL generation service is temporarily unavailable (circuit breaker open)",
                details={
                    "circuit_state": self.circuit_breaker.state,
                    "failure_count": self.circuit_breaker.failure_count,
                },
            )

        previous_sql: str | None = None
        error_feedback: str | None = None
        max_retries = self.resilience_config.max_retries
        tokens_used: int | None = None

        for attempt in range(max_retries + 1):
            try:
                logger.debug(
                    "Generating SQL",
                    extra={"attempt": attempt + 1, "max_retries": max_retries + 1},
                )

                # Generate SQL inside the LLM concurrency slot
                async with self.rate_limiter.for_llm(
                    timeout=self.resilience_config.rate_limit_wait
                ):
                    generated_sql = await self.sql_generator.generate(
                        question=question,
                        schema=schema,
                        previous_attempt=previous_sql,
                        error_feedback=error_feedback,
                    )

                logger.debug("SQL generated", extra={"sql_length": len(generated_sql)})

                # Validate SQL
                try:
                    self.sql_validator.validate_or_raise(generated_sql)
                except (SecurityViolationError, SQLParseError) as validation_error:
                    if attempt < max_retries:
                        # Record as failure and retry with feedback
                        logger.warning(
                            "SQL validation failed, retrying with feedback",
                            extra={"attempt": attempt + 1, "error": str(validation_error)},
                        )
                        previous_sql = generated_sql
                        error_feedback = str(validation_error)
                        await self._backoff_sleep(attempt)
                        continue

                    # Out of retries, record failure and raise
                    self.circuit_breaker.record_failure()
                    metrics.increment_sql_rejected(
                        "security"
                        if isinstance(validation_error, SecurityViolationError)
                        else "parse"
                    )
                    logger.error(
                        "SQL validation failed after all retries",
                        extra={"attempts": attempt + 1, "error": str(validation_error)},
                    )
                    raise

                # Capture token usage from the generator. The isinstance guard
                # keeps mocked generators (non-int attributes in tests) from
                # breaking QueryResponse token validation.
                raw_tokens = getattr(self.sql_generator, "last_tokens_used", None)
                if isinstance(raw_tokens, int) and not isinstance(raw_tokens, bool):
                    tokens_used = raw_tokens

                # Validation successful
                self.circuit_breaker.record_success()
                logger.info(
                    "SQL generated and validated successfully",
                    extra={"attempts": attempt + 1},
                )

                # Build validation result
                validation_result = ValidationResult(
                    is_valid=True,
                    is_select=True,
                    allows_data_modification=False,
                    uses_blocked_functions=[],
                    error_message=None,
                )

                return generated_sql, validation_result, tokens_used

            except TimeoutError as e:
                # Built-in TimeoutError from the LLM concurrency slot wait
                raise RateLimitExceededError(
                    message=(
                        "LLM concurrency limit reached; no slot acquired within "
                        f"{self.resilience_config.rate_limit_wait}s"
                    ),
                    details={"wait_seconds": self.resilience_config.rate_limit_wait},
                ) from e
            except (LLMTimeoutError, LLMUnavailableError) as e:
                # Transient LLM errors: retry with backoff, no error feedback
                if attempt < max_retries:
                    logger.warning(
                        "Transient LLM error, retrying",
                        extra={"attempt": attempt + 1, "error": str(e)},
                    )
                    await self._backoff_sleep(attempt)
                    continue
                self.circuit_breaker.record_failure()
                raise
            except (LLMError, SecurityViolationError, SQLParseError):
                # Re-raise known non-transient errors
                raise
            except Exception as e:
                # Unexpected error during generation
                self.circuit_breaker.record_failure()
                logger.exception("Unexpected error during SQL generation")
                raise LLMError(
                    message=f"SQL generation failed unexpectedly: {e!s}",
                    details={"error_type": type(e).__name__},
                ) from e

        # Should not reach here, but just in case
        self.circuit_breaker.record_failure()
        raise LLMError(
            message="SQL generation failed after all retry attempts",
            details={"max_retries": max_retries},
        )

    async def _backoff_sleep(self, attempt: int) -> None:
        """Sleep for the exponential backoff delay before the next retry.

        Args:
            attempt: Zero-based index of the attempt that just failed.
        """
        delay = self.resilience_config.retry_delay * self.resilience_config.backoff_factor**attempt
        if delay > 0:
            await asyncio.sleep(delay)

    async def _validate_results_safely(
        self,
        question: str,
        sql: str,
        results: list[dict[str, Any]],
        row_count: int,
    ) -> int:
        """Validate query results with error handling (non-blocking).

        This method attempts to validate results using LLM, but failures
        don't cause the overall query to fail. Returns a confidence score.

        Args:
            question: User's original question.
            sql: Generated SQL query.
            results: Query results.
            row_count: Total row count.

        Returns:
            int: Confidence score (0-100). Returns 100 if validation disabled/fails.

        Example:
            >>> confidence = await orchestrator._validate_results_safely(
            ...     question="Count users",
            ...     sql="SELECT COUNT(*) FROM users",
            ...     results=[{"count": 42}],
            ...     row_count=1,
            ... )
        """
        if not self.validation_config.enabled:
            return 100

        try:
            logger.debug("Validating results")

            validation_result = await self.result_validator.validate(
                question=question,
                sql=sql,
                results=results,
                row_count=row_count,
            )

            logger.info(
                "Result validation completed",
                extra={
                    "confidence": validation_result.confidence,
                    "is_acceptable": validation_result.is_acceptable,
                },
            )

            return validation_result.confidence

        except Exception as e:
            # Log but don't fail the query
            logger.warning(
                "Result validation failed, continuing with default confidence",
                extra={"error": str(e)},
            )
            return 100  # Default to high confidence if validation fails

    def _record_query_metrics(self, status: str, database_name: str | None, start: float) -> None:
        """Record end-to-end query metrics.

        Args:
            status: Outcome label for the request counter.
            database_name: Resolved database name, or None if unresolved.
            start: ``time.monotonic()`` timestamp taken at request start.
        """
        metrics.increment_query_request(status, database_name or "unknown")
        metrics.observe_query_duration(time.monotonic() - start)

    @staticmethod
    def _get_current_time_ms() -> float:
        """Get current time in milliseconds.

        Returns:
            float: Current time in milliseconds since epoch.
        """
        return time.time() * 1000
