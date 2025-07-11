from datetime import datetime
import db  # uses db.db_pool shared by main.py
import asyncpg

async def alter_riddle_id_to_autoincrement():
    async with db.db_pool.acquire() as conn:
        try:
            # Create sequence if it doesn't exist
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
            print("✅ Sequence ensured")

            # Set default to nextval of sequence
            await conn.execute("""
                ALTER TABLE user_submitted_questions
                ALTER COLUMN riddle_id SET DEFAULT nextval('user_submitted_questions_riddle_id_seq');
            """)
            print("✅ Set default of riddle_id to nextval of sequence")

            # Make riddle_id NOT NULL (required for primary key)
            await conn.execute("""
                ALTER TABLE user_submitted_questions
                ALTER COLUMN riddle_id SET NOT NULL;
            """)
            print("✅ Set riddle_id NOT NULL")

            # Add primary key constraint if missing
            try:
                await conn.execute("""
                    ALTER TABLE user_submitted_questions
                    ADD CONSTRAINT user_submitted_questions_pkey PRIMARY KEY (riddle_id);
                """)
                print("✅ Primary key constraint added")
            except asyncpg.exceptions.DuplicateObjectError:
                print("⚠️ Primary key constraint already exists, skipping")

            # Sync sequence with max current riddle_id
            max_id = await conn.fetchval("SELECT COALESCE(MAX(riddle_id), 0) FROM user_submitted_questions;")
            await conn.execute(f"SELECT setval('user_submitted_questions_riddle_id_seq', {max_id}, true);")
            print(f"✅ Sequence synced to max riddle_id = {max_id}")

        except Exception as e:
            print(f"❌ Error altering riddle_id to autoincrement: {e}")

# If you want to run this standalone for testing:
if __name__ == "__main__":
    import asyncio
    asyncio.run(alter_riddle_id_to_autoincrement())
