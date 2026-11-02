"""
Script to seed, update, and unarchive all subscription plans in production.
- Ensures 'free', 'day_pass', 'pro_monthly', and 'pilot' exist and are active & unarchived.
- Updates Pilot plan to 20 workspaces (instead of 70).
"""

import sys
import os
import json

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import SessionLocal
from app.models import PlanTierConfig, PlanType

CANONICAL_PLANS = [
    {
        "tier_key": PlanType.FREE,
        "name": "Pagewise Free",
        "tagline": "Forever free essentials for single resume building",
        "badge": "FREE FOREVER",
        "base_price_inr": 0,
        "discount_price_inr": 0,
        "discount_percent": 0,
        "billing_period_text": "Forever Free",
        "duration_days": None,
        "resume_limit": 1,
        "export_limit": 1,
        "wiser_ai_limit": 1,
        "wiser_job_help_limit": 1,
        "wiser_ats_limit": 1,
        "custom_template_limit": 1,
        "premium_templates_allowed": 1,
        "features": [
            "1 resume workspace",
            "Unlimited manual editing",
            "1 export per calendar month",
            "1 Wiser AI evaluation allowance",
            "1 standard customizable template",
            "Resume remains saved"
        ],
        "display_order": 1,
        "is_active": True,
        "is_archived": False,
    },
    {
        "tier_key": PlanType.DAY_PASS,
        "name": "Wiser Day Pass",
        "tagline": "Instant 24-hour speed pass with ATS checks & downloads",
        "badge": "24H SPEED PASS",
        "base_price_inr": 49,
        "discount_price_inr": 49,
        "discount_percent": 0,
        "billing_period_text": "₹49 / 24 hours",
        "duration_days": 1,
        "resume_limit": 1,
        "export_limit": 5,
        "wiser_ai_limit": 6,
        "wiser_job_help_limit": 3,
        "wiser_ats_limit": 3,
        "custom_template_limit": 3,
        "premium_templates_allowed": 3,
        "features": [
            "24 hours · 1 resume",
            "1 resume workspace",
            "Unlimited manual editing",
            "3 premium templates",
            "5 exports",
            "3 Wiser Job Help analyses",
            "3 Wiser ATS evaluations",
            "AI improvement suggestions"
        ],
        "display_order": 2,
        "is_active": True,
        "is_archived": False,
    },
    {
        "tier_key": PlanType.PRO_MONTHLY,
        "name": "Pagewise Pro",
        "tagline": "Unrestricted career architecture for active job seekers",
        "badge": "MOST POPULAR",
        "base_price_inr": 199,
        "discount_price_inr": 199,
        "discount_percent": 0,
        "billing_period_text": "₹199 / month",
        "duration_days": 30,
        "resume_limit": 5,
        "export_limit": 30,
        "wiser_ai_limit": 30,
        "wiser_job_help_limit": 15,
        "wiser_ats_limit": 15,
        "custom_template_limit": 999,
        "premium_templates_allowed": 999,
        "features": [
            "5 resume workspaces",
            "Unlimited manual editing",
            "30 exports",
            "15 Wiser Job Help analyses",
            "15 Wiser ATS evaluations",
            "All premium templates",
            "AI improvement suggestions and application",
            "Resume version management",
            "All export formats"
        ],
        "display_order": 3,
        "is_active": True,
        "is_archived": False,
    },
    {
        "tier_key": PlanType.PILOT,
        "name": "PageWise Pilot",
        "tagline": "All premium capabilities unlocked during our early pilot program",
        "badge": "Early Pilot Active",
        "base_price_inr": 0,
        "discount_price_inr": 0,
        "discount_percent": 0,
        "billing_period_text": "Pilot Program (Free)",
        "duration_days": None,
        "resume_limit": 20,  # <-- 20 workspaces instead of 70
        "export_limit": 100,
        "wiser_ai_limit": 100,
        "wiser_job_help_limit": 50,
        "wiser_ats_limit": 50,
        "custom_template_limit": 30,
        "premium_templates_allowed": 999,
        "features": [
            "20 resume workspaces",
            "Unlimited manual editing",
            "100 exports per month",
            "50 Wiser Job Help analyses",
            "50 Wiser ATS evaluations",
            "30 custom templates",
            "All premium layout architectures unlocked",
            "AI improvement suggestions and instant application",
            "Early Pilot Access (No payment required)"
        ],
        "display_order": 0,
        "is_active": True,
        "is_archived": False,
    },
]


def sync_plans():
    db = SessionLocal()
    try:
        print("=" * 60)
        print("PageWise Studio — Subscription Plans Sync & Pilot Update")
        print("=" * 60)

        for plan in CANONICAL_PLANS:
            key = plan["tier_key"]
            record = db.query(PlanTierConfig).filter(PlanTierConfig.tier_key == key).first()

            features_str = json.dumps(plan["features"])

            if record:
                print(f"[UPDATE] Tier '{key}': setting active=True, archived=False, resumes={plan['resume_limit']}")
                record.name = plan["name"]
                record.tagline = plan["tagline"]
                record.badge = plan["badge"]
                record.base_price_inr = plan["base_price_inr"]
                record.discount_price_inr = plan["discount_price_inr"]
                record.discount_percent = plan["discount_percent"]
                record.billing_period_text = plan["billing_period_text"]
                record.duration_days = plan["duration_days"]
                record.resume_limit = plan["resume_limit"]
                record.export_limit = plan["export_limit"]
                record.wiser_ai_limit = plan["wiser_ai_limit"]
                record.wiser_job_help_limit = plan["wiser_job_help_limit"]
                record.wiser_ats_limit = plan["wiser_ats_limit"]
                record.custom_template_limit = plan["custom_template_limit"]
                record.premium_templates_allowed = plan["premium_templates_allowed"]
                record.features_json = features_str
                record.is_active = True
                record.is_archived = False
                record.display_order = plan["display_order"]
            else:
                print(f"[INSERT] Tier '{key}': creating new tier with resumes={plan['resume_limit']}")
                new_record = PlanTierConfig(
                    tier_key=key,
                    name=plan["name"],
                    tagline=plan["tagline"],
                    badge=plan["badge"],
                    base_price_inr=plan["base_price_inr"],
                    discount_price_inr=plan["discount_price_inr"],
                    discount_percent=plan["discount_percent"],
                    billing_period_text=plan["billing_period_text"],
                    duration_days=plan["duration_days"],
                    resume_limit=plan["resume_limit"],
                    export_limit=plan["export_limit"],
                    wiser_ai_limit=plan["wiser_ai_limit"],
                    wiser_job_help_limit=plan["wiser_job_help_limit"],
                    wiser_ats_limit=plan["wiser_ats_limit"],
                    custom_template_limit=plan["custom_template_limit"],
                    premium_templates_allowed=plan["premium_templates_allowed"],
                    features_json=features_str,
                    is_active=True,
                    is_archived=False,
                    display_order=plan["display_order"],
                )
                db.add(new_record)

        db.commit()

        # Display current active plans
        active_tiers = (
            db.query(PlanTierConfig)
            .filter(PlanTierConfig.is_active == True, PlanTierConfig.is_archived == False)
            .order_by(PlanTierConfig.display_order.asc())
            .all()
        )

        print("\nSuccessfully synced plans in database! Active tiers:")
        print(f"{'Tier Key':<15} {'Name':<18} {'Price (INR)':<12} {'Resumes':<10} {'Exports':<10} {'Wiser AI':<10}")
        print("-" * 75)
        for t in active_tiers:
            p = t.discount_price_inr if t.discount_price_inr is not None else t.base_price_inr
            print(f"{t.tier_key:<15} {t.name:<18} INR {p:<8} {t.resume_limit:<10} {t.export_limit:<10} {t.wiser_ai_limit:<10}")

        print("=" * 60)
        print("ALL PLANS ARE LIVE & UNARCHIVED (Pilot now has 20 workspaces)")
        print("=" * 60)

    except Exception as e:
        db.rollback()
        print(f"[ERROR] Failed to sync plans: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sync_plans()
