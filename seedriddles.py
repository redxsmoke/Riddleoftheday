"""
from datetime import datetime
import db  # uses db.db_pool shared by main.py
import asyncpg

async def alter_riddle_id_pk_and_autoincrement():
    async with db.db_pool.acquire() as conn:
        try:
            # Drop existing PK (replace the constraint name if different)
            await conn.execute("""
                ALTER TABLE user_submitted_questions
                DROP CONSTRAINT IF EXISTS user_submitted_questions_pkey;
            """)
            print("✅ Dropped existing primary key constraint (if any)")

            # Add primary key on riddle_id
            await conn.execute("""
                ALTER TABLE user_submitted_questions
                ADD CONSTRAINT user_submitted_questions_pkey PRIMARY KEY (riddle_id);
            """)
            print("✅ Added primary key on riddle_id")

            # Create sequence if not exists
            await conn.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_class
                        WHERE relkind = 'S' AND relname = 'user_submitted_questions_riddle_id_seq'
                    ) THEN
                        CREATE SEQUENCE user_submitted_questions_riddle_id_seq;
                    END IF;
                END
                $$;
            """)
            print("✅ Created sequence for riddle_id if it didn't exist")

            # Set default to nextval of sequence
            await conn.execute("""
                ALTER TABLE user_submitted_questions
                ALTER COLUMN riddle_id SET DEFAULT nextval('user_submitted_questions_riddle_id_seq');
            """)
            print("✅ Set default of riddle_id to use sequence")

            # Ensure riddle_id is NOT NULL
            await conn.execute("""
                ALTER TABLE user_submitted_questions
                ALTER COLUMN riddle_id SET NOT NULL;
            """)
            print("✅ Set riddle_id column to NOT NULL")

            # Sync sequence with current max riddle_id
            max_id = await conn.fetchval("SELECT COALESCE(MAX(riddle_id), 0) FROM user_submitted_questions;")
            await conn.execute(f"SELECT setval('user_submitted_questions_riddle_id_seq', {max_id}, true);")
            print(f"✅ Sequence synced to max riddle_id = {max_id}")

        except Exception as e:
            print(f"❌ Error altering riddle_id to autoincrement and PK: {e}")
"""