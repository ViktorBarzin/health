"""add nutrition Food catalog + Diary Entries

Adds the Nutrition core (CONTEXT.md "Food"/"Diary Entry"/"Meal"; issue #21 — the
MyFitnessPal core):

* ``foods`` — the Food catalog. A row with ``user_id IS NULL`` is a **shared**
  Food (the generic whole-foods seed, and later the Open Food Facts cache, #22);
  a non-NULL ``user_id`` is that user's private custom Food (#22). Macros are
  stored **per serving** (one serving = ``serving_size`` of ``serving_unit``).
  Two partial unique indexes key the natural key ``slug`` separately for the
  shared namespace and each user's namespace, since a plain composite unique
  treats NULL user_ids as distinct (same idiom as ``exercises``). ``source`` /
  ``off_id`` / ``brand`` leave room for the OFF + custom-Food slice (#22).
* ``diary_entries`` — a Food logged with a ``quantity`` (number of servings) to
  one ``meal`` of one ``entry_date``, private to its ``user_id``. UUID PK
  (entity-style, matching ``training_sessions`` etc.). The day-view read path is
  ``(user_id, entry_date)``.

One new native enum, ``meal`` (breakfast/lunch/dinner/snack), stored as the enum
*values* (matching the ORM's ``values_callable``); ``create_type=False`` so it is
created explicitly here.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-13 17:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# New enum for this migration (stored as the enum *values*, matching the ORM's
# values_callable). create_type=False so we drive creation explicitly below.
_MEAL_LABELS = ["breakfast", "lunch", "dinner", "snack"]
meal_enum = postgresql.ENUM(*_MEAL_LABELS, name="meal", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    meal_enum.create(bind, checkfirst=True)

    op.create_table(
        'foods',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('slug', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('brand', sa.String(), nullable=True),
        sa.Column('serving_size', sa.Float(), nullable=False),
        sa.Column('serving_unit', sa.String(), nullable=False),
        sa.Column('calories', sa.Float(), nullable=False),
        sa.Column('protein_g', sa.Float(), nullable=False),
        sa.Column('carbs_g', sa.Float(), nullable=False),
        sa.Column('fat_g', sa.Float(), nullable=False),
        sa.Column('source', sa.String(), server_default='custom', nullable=False),
        sa.Column('off_id', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    # Idempotency / natural-key uniqueness, split by namespace (NULLs compare
    # distinct in a plain unique, so the shared namespace needs its own partial
    # index).
    op.create_index(
        'uq_food_global_slug', 'foods', ['slug'], unique=True,
        postgresql_where=sa.text('user_id IS NULL'),
    )
    op.create_index(
        'uq_food_user_slug', 'foods', ['user_id', 'slug'], unique=True,
        postgresql_where=sa.text('user_id IS NOT NULL'),
    )
    op.create_index('ix_foods_user_id', 'foods', ['user_id'], unique=False)

    op.create_table(
        'diary_entries',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('food_id', sa.UUID(), nullable=False),
        sa.Column('entry_date', sa.Date(), nullable=False),
        sa.Column('meal', meal_enum, nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        # RESTRICT: a Food in use can't be hard-deleted out from under an entry.
        sa.ForeignKeyConstraint(['food_id'], ['foods.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    # The day-view read path: this user's entries for a given day.
    op.create_index(
        'ix_diary_entries_user_date', 'diary_entries', ['user_id', 'entry_date'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_diary_entries_user_date', table_name='diary_entries')
    op.drop_table('diary_entries')
    op.drop_index('ix_foods_user_id', table_name='foods')
    op.drop_index('uq_food_user_slug', table_name='foods')
    op.drop_index('uq_food_global_slug', table_name='foods')
    op.drop_table('foods')
    bind = op.get_bind()
    meal_enum.drop(bind, checkfirst=True)
