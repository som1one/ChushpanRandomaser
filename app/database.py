"""Database layer: asyncpg connection pool management."""

import asyncpg
from asyncpg import Pool
from app.config import DatabaseConfig


class Database:
    """Manages asyncpg connection pool."""

    def __init__(self):
        self.pool: Pool | None = None

    async def connect(self, config: DatabaseConfig) -> None:
        """Create and initialize the connection pool."""
        self.pool = await asyncpg.create_pool(
            host=config.host,
            port=config.port,
            user=config.user,
            password=config.password,
            database=config.database,
            min_size=config.min_pool_size,
            max_size=config.max_pool_size,
        )

    async def close(self) -> None:
        """Close the connection pool."""
        if self.pool:
            await self.pool.close()
            self.pool = None

    def acquire(self):
        """Context manager for acquiring a connection from the pool."""
        if self.pool is None:
            raise RuntimeError("Database pool is not initialized. Call connect() first.")
        return self.pool.acquire()
