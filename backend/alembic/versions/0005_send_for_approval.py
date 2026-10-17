"""send for approval: 'pending' lifecycle, submitted_by/submitted_at

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('demand_letters', sa.Column('submitted_by', sa.BigInteger(), nullable=True))
    op.add_column('demand_letters', sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        op.f('fk_demand_letters_submitted_by_users'), 'demand_letters', 'users',
        ['submitted_by'], ['id'], ondelete='RESTRICT')
    op.create_index(op.f('ix_demand_letters_submitted_by'), 'demand_letters', ['submitted_by'], unique=False)
    op.drop_constraint(op.f('ck_demand_letters_lifecycle_valid'), 'demand_letters', type_='check')
    op.create_check_constraint(
        op.f('ck_demand_letters_lifecycle_valid'), 'demand_letters',
        "lifecycle in ('draft', 'pending', 'approved')")
    op.create_check_constraint(
        op.f('ck_demand_letters_pending_has_submitter'), 'demand_letters',
        "lifecycle <> 'pending' or (submitted_at is not null and submitted_by is not null)")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f('ck_demand_letters_pending_has_submitter'), 'demand_letters', type_='check')
    op.execute("UPDATE demand_letters SET lifecycle = 'draft' WHERE lifecycle = 'pending'")
    op.drop_constraint(op.f('ck_demand_letters_lifecycle_valid'), 'demand_letters', type_='check')
    op.create_check_constraint(
        op.f('ck_demand_letters_lifecycle_valid'), 'demand_letters',
        "lifecycle in ('draft', 'approved')")
    op.drop_index(op.f('ix_demand_letters_submitted_by'), table_name='demand_letters')
    op.drop_constraint(op.f('fk_demand_letters_submitted_by_users'), 'demand_letters', type_='foreignkey')
    op.drop_column('demand_letters', 'submitted_at')
    op.drop_column('demand_letters', 'submitted_by')
