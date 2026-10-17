"""advertisements: ad status and ad assignee on approved letters

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('demand_letters', sa.Column('ad_status', sa.Text(), server_default='Not started', nullable=False))
    op.add_column('demand_letters', sa.Column('ad_assigned_to', sa.Text(), nullable=True))
    op.add_column('demand_letters', sa.Column('ad_updated_by', sa.BigInteger(), nullable=True))
    op.add_column('demand_letters', sa.Column('ad_updated_at', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        op.f('fk_demand_letters_ad_updated_by_users'), 'demand_letters', 'users',
        ['ad_updated_by'], ['id'], ondelete='RESTRICT')
    op.create_index(op.f('ix_demand_letters_ad_updated_by'), 'demand_letters', ['ad_updated_by'], unique=False)
    op.create_check_constraint(
        op.f('ck_demand_letters_ad_status_valid'), 'demand_letters',
        "ad_status in ('Not started', 'In progress', 'Done')")
    op.create_check_constraint(
        op.f('ck_demand_letters_ad_assigned_to_length'), 'demand_letters',
        "ad_assigned_to is null or length(ad_assigned_to) <= 200")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f('ck_demand_letters_ad_assigned_to_length'), 'demand_letters', type_='check')
    op.drop_constraint(op.f('ck_demand_letters_ad_status_valid'), 'demand_letters', type_='check')
    op.drop_index(op.f('ix_demand_letters_ad_updated_by'), table_name='demand_letters')
    op.drop_constraint(op.f('fk_demand_letters_ad_updated_by_users'), 'demand_letters', type_='foreignkey')
    op.drop_column('demand_letters', 'ad_updated_at')
    op.drop_column('demand_letters', 'ad_updated_by')
    op.drop_column('demand_letters', 'ad_assigned_to')
    op.drop_column('demand_letters', 'ad_status')
