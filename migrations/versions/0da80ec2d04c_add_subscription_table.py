"""add subscription table

Revision ID: 0da80ec2d04c
Revises: 600a904ba92a
Create Date: 2026-08-25 11:00:02.478043

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0da80ec2d04c'
down_revision = '600a904ba92a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('subscription',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('plan', sa.String(length=20), nullable=False),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('utr', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=12), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('activated_at', sa.DateTime(), nullable=True),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('subscription', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_subscription_user_id'), ['user_id'], unique=False)

    # ### end Alembic commands ###


def downgrade():
    with op.batch_alter_table('subscription', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_subscription_user_id'))

    op.drop_table('subscription')
    # ### end Alembic commands ###
