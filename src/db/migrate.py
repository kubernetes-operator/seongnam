"""DB 스키마 마이그레이션 — 직접 실행 가능."""
import asyncio
import asyncpg
import os
import sys


async def migrate() -> None:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("ERROR: DATABASE_URL 환경변수가 설정되지 않았습니다", file=sys.stderr)
        sys.exit(1)

    conn = await asyncpg.connect(dsn)
    try:
        from db.schema import SCHEMA_SQL, CONTINUOUS_AGGREGATE_SQL
        print("스키마 초기화 중...")
        await conn.execute(SCHEMA_SQL)
        print("기본 스키마 완료")

        try:
            await conn.execute(CONTINUOUS_AGGREGATE_SQL)
            print("연속 집계 뷰 완료")
        except Exception as e:
            print(f"연속 집계 건너뜀 (이미 존재 또는 버전 차이): {e}")

        print("마이그레이션 완료")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(migrate())
