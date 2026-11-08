import asyncio
from sqlalchemy import select
from app.db import SessionLocal
from app.models import AutomationRule, ManagedOffer, OperationQueue, ApplicationSetting

async def check():
    async with SessionLocal() as session:
        rules = (await session.execute(select(AutomationRule))).scalars().all()
        print(f"Total Rules: {len(rules)}")
        for r in rules:
            print(f"Rule: {r.name}, Enabled: {r.enabled}, State: {r.state}")
            print(f"  Collection: {r.collection_id}, Models: {r.models}, Scope Mode: {r.scope_mode}")
            print(f"  Next Run: {r.next_run_at}, Last Error: {r.last_error}")

        offers = (await session.execute(select(ManagedOffer))).scalars().all()
        print(f"\nTotal Offers: {len(offers)}")

        ops = (await session.execute(select(OperationQueue))).scalars().all()
        print(f"\nTotal Operations: {len(ops)}")
        for op in ops:
            print(f"Op: {op.operation_type}, State: {op.state}, Error: {op.last_error}")

        settings = (await session.execute(select(ApplicationSetting))).scalars().all()
        print(f"\nSettings:")
        for s in settings:
            print(f"{s.key}: {s.value}")

if __name__ == "__main__":
    asyncio.run(check())
