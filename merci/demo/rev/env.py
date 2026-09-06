import asyncio

from alembic import context
from sqlalchemy.engine import Connection


def run_migrations_offline() -> None:
    context.configure(
        url=context.config.attributes["url"],
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        **context.config.attributes['config'])

    with context.begin_transaction():
        context.run_migrations()


def run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        compare_type=True,
        compare_server_default=True,
        **context.config.attributes['config']
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = context.config.attributes["engine"]
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations)


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
