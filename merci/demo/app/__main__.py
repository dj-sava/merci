import asyncio
import functools
import sys
import zlib
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from merci import IdentifierMapper

from .config import AlembicCommandLine, async_sessionmaker_factory
from .models import IdentifierMapping, IdentifierMappingMigration, Role
from .shapes import User


def load(keys: tuple[str, ...]) -> dict[int, dict[str, Any]]:
    data = {}
    for input_schema in (False, True):
        head = [input_schema, input_schema and 'POST' or 'GET', '/user', User.__module__, User.__name__]
        for name in User.__annotations__.keys():
            body = head + [name]

            # calculate integer index of identifier
            sign = zlib.crc32(''.join(map(str, body)).encode())
            data[sign] = dict(zip(keys, body))
    return data


async def init(session: AsyncSession) -> int | None:
    if not await session.scalar(select(Role.id).limit(1)):
        roles = {}
        for title in ('admin', 'user'):
            roles[title] = Role(title=title)
            session.add(roles[title])
        await session.commit()
        return int(roles['admin'].id)
    return None


async def bind(session: AsyncSession, pk: int) -> None:
    await session.execute(
        update(IdentifierMapping) \
        .where(IdentifierMapping.field_name == 'birthday') \
        .values(reference_id=pk))
    await session.commit()


async def show(session: AsyncSession, keys: tuple[str, ...]) -> None:
    pack = await session.scalars(
        select(IdentifierMapping) \
        .where(IdentifierMapping.reference_id.is_not(None)) \
        .options(joinedload(IdentifierMapping.reference)))

    for item in pack:
        print(': '.join((
            item.reference.title, ' '.join((
                item.route_method,
                item.route_path,
                '.'.join(map(functools.partial(getattr, item), keys[-3:])))))))


async def main() -> None:
    async with async_sessionmaker_factory() as session:
        keys = ('input_schema', 'route_method', 'route_path', 'module_name', 'schema_name', 'field_name')

        # fill roles table if records does not exists
        pk = await init(session)

        # gather identifiers data
        data = load(keys)

        # call mappings migrations
        mapper: IdentifierMapper[IdentifierMapping, IdentifierMappingMigration] = IdentifierMapper(
            session,
            mapping_model=IdentifierMapping,
            mapping_migration_model=IdentifierMappingMigration)
        await mapper.migrate(data)

        # fill initial reference if does not exists
        if pk:
            await bind(session, pk)

        # check result
        await show(session, keys)


if len(sys.argv) > 1:
    AlembicCommandLine().main()
else:
    asyncio.run(main())
