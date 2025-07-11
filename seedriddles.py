from datetime import datetime
import db  # uses db.db_pool from main.py

riddles = [
    {"riddle_id": 1, "user_id": 1, "question": "I speak without a mouth and hear without ears. I have nobody, but I come alive with wind. What am I?", "answer": "shadow"},
    {"riddle_id": 2, "user_id": 1, "question": "You measure my life in hours and I serve you by expiring. I’m quick when I’m thin and slow when I’m fat. What am I?", "answer": "candle"},
    {"riddle_id": 3, "user_id": 1, "question": "I have cities, but no houses. I have mountains, but no trees. I have water, but no fish. What am I?", "answer": "map"},
    {"riddle_id": 4, "user_id": 1, "question": "What can fill a room but takes up no space?", "answer": "light"},
    {"riddle_id": 5, "user_id": 1, "question": "The more of me you take, the more you leave behind. What am I?", "answer": "footsteps"},
    {"riddle_id": 6, "user_id": 1, "question": "I’m tall when I’m young and short when I’m old. What am I?", "answer": "candle"},
    {"riddle_id": 7, "user_id": 1, "question": "What has many keys but can’t open a single lock?", "answer": "piano"},
    {"riddle_id": 8, "user_id": 1, "question": "The person who makes it, sells it. The person who buys it never uses it. The person who uses it never knows they're using it. What is it?", "answer": "coffin"},
    {"riddle_id": 9, "user_id": 1, "question": "What is seen in the middle of March and April that can’t be seen at the beginning or end of either month?", "answer": "letter 'r'"},
    {"riddle_id": 10, "user_id": 1, "question": "What has a heart that doesn’t beat?", "answer": "artichoke"},
    {"riddle_id": 11, "user_id": 1, "question": "I’m found in socks, scarves and mittens; and often in the paws of playful kittens. What am I?", "answer": "yarn"},
    {"riddle_id": 12, "user_id": 1, "question": "I can be cracked, made, told, and played. What am I?", "answer": "joke"},
    {"riddle_id": 13, "user_id": 1, "question": "I’m light as a feather, yet the strongest man can’t hold me for much longer than a minute. What am I?", "answer": "breath"},
    {"riddle_id": 14, "user_id": 1, "question": "What can run but never walks, has a mouth but never talks, has a head but never weeps, has a bed but never sleeps?", "answer": "river"},
    {"riddle_id": 15, "user_id": 1, "question": "What breaks yet never falls, and what falls yet never breaks?", "answer": "day and night"},
]

async def seed_riddles():
    conn = await asyncpg.connect(
        user='your_db_user',
        password='your_db_password',
        database='your_db_name',
        host='your_db_host'
    )
    now = datetime.utcnow()
    for r in riddles:
        await conn.execute(
            """
            INSERT INTO user_submitted_questions (riddle_id, user_id, question, answer, created_at, posted_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (riddle_id) DO NOTHING
            """,
            r["riddle_id"], r["user_id"], r["question"], r["answer"], now, None
        )
        print(f"Inserted riddle #{r['riddle_id']}")
    await conn.close()

