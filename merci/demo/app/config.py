import json
import pathlib

from alembic.config import CommandLine, Config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import merci

from .models import Base, IdentifierMappingMigration

path = pathlib.Path(__file__).resolve().parent.joinpath('..', 'cfg')
with open(path, 'r') as file:
    conf = json.loads(file.read())

engine = create_async_engine(conf['db'])
async_sessionmaker_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=True)


class AlembicCommandLine(CommandLine): # type: ignore[misc]
    def main(self, argv: list[str] | None = None) -> None:
        options = self.parser.parse_args(argv)
        config = Config()

        config.set_main_option('script_location', 'rev')
        config.set_main_option('version_locations', 'rev/migrations')

        config.attributes['url'] = conf['db']
        config.attributes['engine'] = engine
        config.attributes['mapping_migration_model'] = IdentifierMappingMigration

        config.attributes['config'] = {
            'target_metadata': Base.metadata,
            'process_revision_directives': merci.alembic.make_process_revision_directives()}

        self.run_cmd(config, options)
