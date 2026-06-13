"""add recipes + recipe ingredients

Adds the Recipe model (CONTEXT.md "Recipe"; issue #22 — barcode/OFF/custom Foods
+ Recipes). A **Recipe is a Food** (a ``foods`` row with ``source='recipe'``), so
it is loggable/searchable/totalled exactly like any other Food and needs nothing
new on the diary side. Two tables back the "composed of other Foods" part:

* ``recipes`` — one row per Recipe, 1:1 with its backing Food (``food_id``
  UNIQUE, CASCADE). Holds ``yield_servings`` and the owner ``user_id`` (so the
  Export scopes it on user_id directly).
* ``recipe_ingredients`` — one ingredient per row: the ingredient ``food_id``
  (RESTRICT — can't delete a Food used as an ingredient) and the ``quantity``
  (servings of that Food in the whole Recipe), plus a display ``position``.

Per-serving macros are computed (Σ ingredient macros ÷ yield) and stored on the
backing Food at write time (compute-on-write), so no macro columns live here.

No enum changes; ``source`` stays a plain string on ``foods`` ('generic' / 'off'
/ 'custom' / 'recipe').

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-13 18:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'recipes',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('food_id', sa.UUID(), nullable=False),
        sa.Column('yield_servings', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        # 1:1 with the backing Food; deleting the Food removes the Recipe.
        sa.ForeignKeyConstraint(['food_id'], ['foods.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('food_id', name='uq_recipes_food_id'),
    )
    op.create_index('ix_recipes_user_id', 'recipes', ['user_id'], unique=False)

    op.create_table(
        'recipe_ingredients',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('recipe_id', sa.UUID(), nullable=False),
        sa.Column('food_id', sa.UUID(), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['recipe_id'], ['recipes.id'], ondelete='CASCADE'),
        # RESTRICT: a Food used as an ingredient can't be deleted out from under
        # the Recipe (mirrors diary_entries → foods).
        sa.ForeignKeyConstraint(['food_id'], ['foods.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_recipe_ingredients_recipe_id', 'recipe_ingredients', ['recipe_id'],
        unique=False,
    )
    op.create_index(
        'ix_recipe_ingredients_food_id', 'recipe_ingredients', ['food_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_recipe_ingredients_food_id', table_name='recipe_ingredients')
    op.drop_index('ix_recipe_ingredients_recipe_id', table_name='recipe_ingredients')
    op.drop_table('recipe_ingredients')
    op.drop_index('ix_recipes_user_id', table_name='recipes')
    op.drop_table('recipes')
