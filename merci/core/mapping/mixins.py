from sqlalchemy import BigInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class IdentifierMapping:
    __tablename__ = 'identifier_mappings'

    id: Mapped[int] = mapped_column(primary_key=True)
    input_schema: Mapped[bool] = mapped_column(server_default='false')
    route_method: Mapped[str] = mapped_column(String, nullable=False)
    route_path: Mapped[str] = mapped_column(String, nullable=False)
    module_name: Mapped[str] = mapped_column(String, nullable=False)
    schema_name: Mapped[str] = mapped_column(String, nullable=False)
    field_name: Mapped[str] = mapped_column(String, nullable=False)
    index_data: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    reference_id: Mapped[int]


class IdentifierMappingMigration:
    __tablename__ = 'identifier_mapping_migrations'
    __table_args__ = (
        UniqueConstraint(
            'old_index_data', 'new_index_data', name='unique_index_data_pair'
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    old_index_data: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    new_index_data: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    migration_id: Mapped[str] = mapped_column(String, nullable=True)
    applied: Mapped[bool] = mapped_column(server_default='false')
