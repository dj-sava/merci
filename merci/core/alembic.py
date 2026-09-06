from collections.abc import Callable
from typing import Any

from alembic.autogenerate import renderers
from alembic.autogenerate.api import AutogenContext
from alembic.operations import MigrateOperation, MigrationScript, Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import delete, exists, insert, select


def get_migration_model(context: MigrationContext) -> Any:
    return context.config.attributes['mapping_migration_model']


@Operations.register_operation('adjust_identifier_mappings')
class AdjustIdentifierMappingsOp(MigrateOperation): # type: ignore[misc]
    def __init__(self, revision: str, *values: tuple[int, int]):
        self.revision = revision
        self.values = values

    @classmethod
    def adjust_identifier_mappings(cls, operations: Operations, revision: str, *values: tuple[int, int]) -> Any:
        return operations.invoke(cls(revision, *values))


@Operations.register_operation('revert_identifier_mappings')
class RevertIdentifierMappingsOp(MigrateOperation): # type: ignore[misc]
    def __init__(self, revision: str):
        self.revision = revision

    @classmethod
    def revert_identifier_mappings(cls, operations: Operations, revision: str) -> Any:
        return operations.invoke(cls(revision))


@renderers.dispatch_for(AdjustIdentifierMappingsOp) # type: ignore[untyped-decorator]
def render_adjust_identifier_mappings(autogen_context: AutogenContext, op: AdjustIdentifierMappingsOp) -> str:
    data = ', '.join(map(str, op.values))
    return f'op.adjust_identifier_mappings(revision, {data})'


@renderers.dispatch_for(RevertIdentifierMappingsOp) # type: ignore[untyped-decorator]
def render_revert_identifier_mappings(autogen_context: AutogenContext, op: RevertIdentifierMappingsOp) -> str:
    return 'op.revert_identifier_mappings(revision)'


@Operations.implementation_for(AdjustIdentifierMappingsOp) # type: ignore[untyped-decorator]
def adjust_identifier_mappings(operations: Operations, op: AdjustIdentifierMappingsOp) -> None:
    model = get_migration_model(operations.get_context())
    conn = operations.get_bind()

    for (old_index_data, new_index_data) in op.values:
        opts = (
            model.old_index_data == old_index_data,
            model.new_index_data == new_index_data,
            model.migration_id.is_(None))

        if conn.scalar(select(exists().where(*opts))):
            # migration maker environment
            conn.execute(delete(model).where(*opts))
        else:
            # remote environment
            conn.execute(insert(model).values(
                old_index_data=old_index_data,
                new_index_data=new_index_data,
                migration_id=op.revision))


@Operations.implementation_for(RevertIdentifierMappingsOp) # type: ignore[untyped-decorator]
def revert_identifier_mappings(operations: Operations, op: RevertIdentifierMappingsOp) -> None:
    model = get_migration_model(operations.get_context())

    conn = operations.get_bind()
    stmt = (
        delete(model)
        .where(model.migration_id == op.revision)
        .returning(
            model.old_index_data,
            model.new_index_data))

    for row in conn.execute(stmt).mappings():
        conn.execute(insert(model).values(
            old_index_data=row['new_index_data'],
            new_index_data=row['old_index_data']))


def make_process_revision_directives() -> Callable[[AutogenContext, str, list[MigrationScript]], None]:
    def callback(context: AutogenContext, revision: str, directives: list[MigrationScript]) -> None:
        if not directives:
            return

        model = get_migration_model(context)
        stmt = select(
            model.old_index_data,
            model.new_index_data,
        ).where(
            model.migration_id.is_(None),
            model.applied.is_(True),
        )
        rows = context.connection.execute(stmt).fetchall()

        script = directives[0]
        script.upgrade_ops.ops.append(AdjustIdentifierMappingsOp(script.rev_id, *rows))
        script.downgrade_ops.ops.append(RevertIdentifierMappingsOp(script.rev_id))
    return callback
