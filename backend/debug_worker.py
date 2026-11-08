import asyncio
import traceback
from sqlalchemy import select
from app.db import SessionLocal
from app.models import AutomationRule, ApiCredential
from app.services.offers_service import build_market_snapshot
from app.services.rule_cycle import run_rule_cycle
from app.runtime import build_gateway
from app.services import settings_service
from app.enums import AutomationMode

async def debug_worker():
    async with SessionLocal() as session:
        rule = (await session.execute(select(AutomationRule).limit(1))).scalar_one_or_none()
        if not rule:
            print("No rule found")
            return
        
        print(f"Processing rule: {rule.name} ({rule.id})")
        
        cred = await session.get(ApiCredential, rule.credential_id)
        if not cred:
            print("No credential found for rule")
            return
            
        gateway = build_gateway(cred)
        mode = await settings_service.get_setting(session, "mode", AutomationMode.DRY_RUN.value)
        automation_enabled = await settings_service.get_setting(session, "automation_enabled", False)
        emergency_stop = await settings_service.get_setting(session, "emergency_stop", False)
        
        try:
            snapshot = await build_market_snapshot(
                session, gateway, rule, credential_sender_id=cred.sender_id
            )
            print(f"Snapshot: Floor={snapshot.floor_price}, Total={snapshot.total_count}")
            print(f"Offers fetched: {len(snapshot.offers)}")
            for idx, off in enumerate(snapshot.offers):
                print(f"  [{idx}] ID: {off.get('id')}, Amount: {off.get('amount')}, Sender: {off.get('sender_id')}, Scope: {off.get('scope')}")
            
            result = await run_rule_cycle(
                session,
                rule=rule,
                gateway=gateway,
                credential=cred,
                mode_live=(mode == AutomationMode.LIVE.value),
                automation_enabled=automation_enabled,
                emergency_stop=emergency_stop,
                available_balance=Decimal("10.0")
            )
            print(f"Cycle Result: {result.action}, {result.reason}")
            await session.commit()
        except Exception as e:
            print("Caught exception in worker cycle:")
            traceback.print_exc()

if __name__ == "__main__":
    from decimal import Decimal
    asyncio.run(debug_worker())
