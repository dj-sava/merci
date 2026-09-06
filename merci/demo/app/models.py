from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

import merci


class Base(DeclarativeBase): # type: ignore[misc]
    pass


class Role(Base):
    __tablename__ = 'roles'

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)


class IdentifierMapping(merci.IdentifierMapping, Base):
    reference_id: Mapped[int] = mapped_column(Integer, ForeignKey('roles.id'), nullable=True)
    reference: Mapped['Role'] = relationship('Role')


class IdentifierMappingMigration(merci.IdentifierMappingMigration, Base):
    pass
