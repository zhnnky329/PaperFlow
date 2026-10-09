from alembic import context
from app.db import Base

connection = context.config.attributes.get("connection")
if connection is None:
    from app.config import Config
    from sqlalchemy import create_engine

    cfg = Config()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    connection = create_engine("sqlite:///" + str(cfg.data_dir / "paperflow.sqlite3")).connect()
context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
with context.begin_transaction():
    context.run_migrations()
