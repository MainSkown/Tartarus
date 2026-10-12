from sqlalchemy import Column, ForeignKey, Index, Integer, MetaData, String, Table, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db.base import Base


def test_constraints_get_deterministic_names() -> None:
    metadata = MetaData(naming_convention=Base.metadata.naming_convention)
    Table("parent", metadata, Column("id", Integer, primary_key=True))
    child = Table(
        "child",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("parent_id", Integer, ForeignKey("parent.id")),
        Column("slug", String),
        UniqueConstraint("slug"),
        Index(None, "slug"),
    )

    ddl = str(CreateTable(child).compile(dialect=postgresql.dialect()))
    index_ddl = str(CreateIndex(next(iter(child.indexes))).compile(dialect=postgresql.dialect()))

    assert "CONSTRAINT pk_child PRIMARY KEY (id)" in ddl
    assert "CONSTRAINT fk_child_parent_id_parent FOREIGN KEY(parent_id)" in ddl
    assert "CONSTRAINT uq_child_slug UNIQUE (slug)" in ddl
    assert "ix_child_slug" in index_ddl
