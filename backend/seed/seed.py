"""Seeds reference/system data (always) and, unless --no-demo is passed, realistic
SAMPLE DATA opportunities clearly flagged is_sample_data=True (spec §30). Safe to
re-run — each section checks for existing rows before inserting.

Usage (from backend/, with the venv active):
    python -m seed.seed                 # reference data + demo/sample data
    python -m seed.seed --no-demo       # reference data only (for a real deployment)
"""
import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.agency import Agency, AgencyOffice  # noqa: E402
from app.models.alert import Alert  # noqa: E402
from app.models.company import Company, OpportunityCompany  # noqa: E402
from app.models.contact import Contact, OpportunityContact  # noqa: E402
from app.models.enums import (  # noqa: E402
    ActivityType,
    AlertCategory,
    CompanyType,
    ContactRole,
    ContractType,
    GoNoGoOutcome,
    MaturityStage,
    OpportunityCompanyRelationship,
    SetAsideType,
    TaskPriority,
    TaskStatus,
    UserRole,
)
from app.models.forecast import RevenueForecast, RevenueTarget  # noqa: E402
from app.models.opportunity import Opportunity  # noqa: E402
from app.models.pipeline import DEFAULT_STAGES, PipelineStage  # noqa: E402
from app.models.reference import Discipline, NaicsCode  # noqa: E402
from app.models.scoring import ScoringWeightProfile  # noqa: E402
from app.models.task import Task  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.winloss import WinLossReview  # noqa: E402
from app.services.activities import log_activity  # noqa: E402
from app.services.gonogo import get_or_create_review, record_decision, upsert_criteria_scores  # noqa: E402
from app.schemas.gonogo import GoNoGoCriteriaScoreUpsert  # noqa: E402
from app.services.scoring import calculate_score  # noqa: E402

settings = get_settings()
TODAY = date.today()


def _dt(days_from_today: int, hour: int = 17) -> datetime:
    return datetime.combine(TODAY + timedelta(days=days_from_today), datetime.min.time()).replace(
        hour=hour, tzinfo=timezone.utc
    )


def seed_reference_data(db: Session) -> None:
    if db.execute(select(PipelineStage)).scalars().first() is None:
        print("Seeding pipeline stages...")
        for i, name in enumerate(DEFAULT_STAGES):
            db.add(
                PipelineStage(
                    name=name,
                    sort_order=i,
                    is_closed_won=(name == "Won"),
                    is_closed_lost=(name in ("Lost", "No Bid")),
                )
            )
        db.commit()

    if db.execute(select(ScoringWeightProfile)).scalars().first() is None:
        print("Seeding default scoring weight profile...")
        db.add(ScoringWeightProfile(name="Default", is_active=True))
        db.commit()

    if db.execute(select(NaicsCode)).scalars().first() is None:
        print("Seeding NAICS reference codes...")
        codes = [
            (settings.PRINCIPAL_PRIMARY_NAICS, "Engineering Services", True),
            ("541620", "Environmental Consulting Services", True),
            ("541370", "Surveying and Mapping (except Geophysical) Services", True),
            ("541380", "Testing Laboratories", True),
            ("541320", "Landscape Architectural Services", True),
            ("237990", "Other Heavy and Civil Engineering Construction", True),
            ("541690", "Other Scientific and Technical Consulting Services", True),
            ("236220", "Commercial and Institutional Building Construction", False),
            ("541310", "Architectural Services", False),
        ]
        for code, title, is_core in codes:
            db.add(NaicsCode(code=code, title=title, is_core_market=is_core))
        db.commit()

    if db.execute(select(Discipline)).scalars().first() is None:
        print("Seeding technical disciplines...")
        disciplines = [
            ("Civil Engineering", "Engineering"), ("Water/Wastewater Engineering", "Engineering"),
            ("Stormwater & Drainage", "Engineering"), ("Utilities Design", "Engineering"),
            ("Transportation Engineering", "Engineering"), ("Site/Civil Design", "Engineering"),
            ("Structural Engineering", "Engineering"), ("Geotechnical Engineering", "Engineering"),
            ("Environmental Engineering", "Engineering"), ("Surveying & Mapping", "Support"),
            ("Construction Administration", "Support"), ("Architecture", "Design"),
            ("Mechanical Engineering", "Engineering"), ("Electrical Engineering", "Engineering"),
        ]
        for name, category in disciplines:
            db.add(Discipline(name=name, category=category))
        db.commit()

    if db.execute(select(RevenueTarget)).scalars().first() is None:
        db.add(RevenueTarget(period_label=str(TODAY.year), target_amount=3_500_000))
        db.commit()


def seed_admin_user(db: Session, email: str, full_name: str, password: str) -> User:
    existing = db.execute(select(User).where(User.email == email.lower())).scalars().first()
    if existing:
        return existing
    print(f"Seeding administrator account for {email}...")
    user = User(
        email=email.lower(), full_name=full_name, hashed_password=hash_password(password),
        role=UserRole.ADMINISTRATOR, title="Administrator",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def seed_demo_data(db: Session, admin: User) -> None:
    if db.execute(select(Opportunity).where(Opportunity.is_sample_data.is_(True))).scalars().first() is not None:
        print("Sample data already present — skipping.")
        return

    print("Seeding SAMPLE DATA (agencies, companies, contacts, opportunities)...")
    stages = {s.name: s for s in db.execute(select(PipelineStage)).scalars().all()}

    # --- Agencies -----------------------------------------------------------------
    usace = Agency(name="U.S. Army Corps of Engineers", short_name="USACE", agency_type="federal", priority_tier=1, is_sample_data=True)
    va = Agency(name="Department of Veterans Affairs", short_name="VA", agency_type="federal", priority_tier=1, is_sample_data=True)
    fema = Agency(name="Federal Emergency Management Agency", short_name="FEMA", agency_type="federal", priority_tier=1, is_sample_data=True)
    nrcs = Agency(name="USDA Natural Resources Conservation Service", short_name="NRCS", agency_type="federal", priority_tier=1, is_sample_data=True)
    air_force = Agency(name="Department of the Air Force", short_name="AF", agency_type="federal", priority_tier=1, is_sample_data=True)
    baton_rouge = Agency(name="City of Baton Rouge / Parish of East Baton Rouge", short_name="EBR", agency_type="municipal", priority_tier=2, is_sample_data=True)
    jefferson_parish = Agency(name="Jefferson Parish Department of Engineering", short_name="Jefferson Parish", agency_type="parish-county", priority_tier=2, is_sample_data=True)
    db.add_all([usace, va, fema, nrcs, air_force, baton_rouge, jefferson_parish])
    db.flush()

    offices = {
        "usace_no": AgencyOffice(agency_id=usace.id, name="New Orleans District", city="New Orleans", state="LA"),
        "usace_vicksburg": AgencyOffice(agency_id=usace.id, name="Vicksburg District", city="Vicksburg", state="MS"),
        "usace_mobile": AgencyOffice(agency_id=usace.id, name="Mobile District", city="Mobile", state="AL"),
        "va_cfm": AgencyOffice(agency_id=va.id, name="Office of Construction & Facilities Management", city="Washington", state="DC"),
        "fema_r6": AgencyOffice(agency_id=fema.id, name="Region 6", city="Denton", state="TX"),
        "nrcs_la": AgencyOffice(agency_id=nrcs.id, name="Louisiana State Office", city="Alexandria", state="LA"),
        "afcec": AgencyOffice(agency_id=air_force.id, name="Air Force Civil Engineer Center", city="Tyndall AFB", state="FL"),
    }
    db.add_all(offices.values())
    db.flush()

    # --- Companies ------------------------------------------------------------------
    principal = Company(
        name="Principal Engineering, Inc.", company_type=CompanyType.OWN_FIRM, is_sdvosb=True,
        is_small_business=True, headquarters_city="Baton Rouge", headquarters_state="LA",
        technical_specialties="Civil, water/wastewater, stormwater, utilities, site/civil engineering",
        is_sample_data=True,
    )
    architecture_partner = Company(
        name="Delta Architecture Group", company_type=CompanyType.TEAMING_PARTNER, headquarters_city="New Orleans",
        headquarters_state="LA", technical_specialties="Architecture, VA healthcare facility design", is_sample_data=True,
    )
    geotech_partner = Company(
        name="Gulf Coast Geotechnical Services", company_type=CompanyType.TEAMING_PARTNER, headquarters_city="Mobile",
        headquarters_state="AL", technical_specialties="Geotechnical engineering, soils testing", is_sample_data=True,
    )
    survey_partner = Company(
        name="Crescent City Surveying & Mapping", company_type=CompanyType.TEAMING_PARTNER, is_sdvosb=True,
        headquarters_city="New Orleans", headquarters_state="LA", technical_specialties="Land surveying, mapping",
        is_sample_data=True,
    )
    sdvosb_competitor = Company(
        name="Patriot Environmental Solutions", company_type=CompanyType.COMPETITOR, is_sdvosb=True,
        headquarters_city="Houston", headquarters_state="TX", technical_specialties="Environmental engineering, SDVOSB set-asides",
        is_sample_data=True,
    )
    large_prime = Company(
        name="National Infrastructure Engineers, Inc.", company_type=CompanyType.COMPETITOR, headquarters_city="Atlanta",
        headquarters_state="GA", technical_specialties="Large federal A/E prime, multiple IDIQs", is_sample_data=True,
    )
    eight_a_firm = Company(
        name="Riverbend Environmental Partners", company_type=CompanyType.TEAMING_PARTNER, is_eight_a=True,
        is_small_business=True, headquarters_city="Jackson", headquarters_state="MS",
        technical_specialties="Environmental assessment, remediation", is_sample_data=True,
    )
    db.add_all([principal, architecture_partner, geotech_partner, survey_partner, sdvosb_competitor, large_prime, eight_a_firm])
    db.flush()

    # --- Contacts -------------------------------------------------------------------
    contacts = [
        Contact(full_name="Marcus Webb", organization="USACE New Orleans District", title="Contracting Officer",
                email="sample.contact+mwebb@example.gov", phone="504-555-0101", agency_id=usace.id,
                agency_office_id=offices["usace_no"].id, role=ContactRole.CONTRACTING_OFFICER, relationship_strength=4),
        Contact(full_name="Dana Ruiz", organization="Department of Veterans Affairs", title="Small Business Specialist",
                email="sample.contact+druiz@example.gov", phone="202-555-0114", agency_id=va.id,
                role=ContactRole.SMALL_BUSINESS_SPECIALIST, relationship_strength=3),
        Contact(full_name="Terrence Boudreaux", organization="Jefferson Parish", title="Parish Engineer",
                email="sample.contact+tboudreaux@example.gov", phone="504-555-0122", agency_id=jefferson_parish.id,
                role=ContactRole.MUNICIPAL_OFFICIAL, relationship_strength=5),
        Contact(full_name="Alicia Chen", organization="FEMA Region 6", title="Program Manager",
                email="sample.contact+achen@example.gov", phone="940-555-0177", agency_id=fema.id,
                agency_office_id=offices["fema_r6"].id, role=ContactRole.PROGRAM_MANAGER, relationship_strength=2),
        Contact(full_name="Robert Ainsley", organization="Delta Architecture Group", title="Principal Architect",
                email="sample.contact+rainsley@example.com", phone="504-555-0188", company_id=architecture_partner.id,
                role=ContactRole.TEAMING_PARTNER_CONTACT, relationship_strength=4),
    ]
    db.add_all(contacts)
    db.flush()

    # --- Opportunities ----------------------------------------------------------------
    def make_opp(**kwargs) -> Opportunity:
        defaults = dict(
            status="active", is_sample_data=True, source="Sample Data", source_url=None,
            retrieved_at=datetime.now(timezone.utc), confidence="unverified",
            created_by_id=admin.id, assigned_user_id=admin.id,
        )
        defaults.update(kwargs)
        opp = Opportunity(**defaults)
        opp.is_sdvosb_setaside = opp.set_aside == SetAsideType.SDVOSB
        db.add(opp)
        db.flush()
        log_activity(db, opp.id, ActivityType.CREATED, "Opportunity created (sample data)")
        return opp

    opp1 = make_opp(
        title="VA Medical Center Utility Infrastructure Replacement", agency_id=va.id,
        agency_office_id=offices["va_cfm"].id, solicitation_number="36C10G25R0031",
        location_city="Alexandria", location_state="LA", naics_code="541330", psc_code="C219",
        set_aside=SetAsideType.SDVOSB, contract_type=ContractType.AE_BROOKS_ACT,
        estimated_value_low=2_000_000, estimated_value_high=3_500_000, estimated_fee=310_000,
        contract_duration_months=18, proposal_due_at=_dt(21), questions_due_at=_dt(10),
        site_visit_at=_dt(5), description="Replacement of aging potable water, sanitary sewer, and electrical utility infrastructure serving the VA Medical Center campus, including civil site design and construction administration.",
        scope_summary="Civil utility design, water and wastewater system replacement, construction administration for a VA medical facility.",
        opportunity_source_label="SAM.gov", pipeline_stage_id=stages["Capture"].id,
        maturity_stage=MaturityStage.SOLICITATION_RELEASED,
    )
    opp2 = make_opp(
        title="Civil Engineering Services IDIQ, New Orleans District", agency_id=usace.id,
        agency_office_id=offices["usace_no"].id, solicitation_number="W912P8-26-R-0014",
        location_city="New Orleans", location_state="LA", naics_code="541330", psc_code="C219",
        set_aside=SetAsideType.SMALL_BUSINESS, contract_type=ContractType.IDIQ,
        estimated_value_low=5_000_000, estimated_value_high=15_000_000, estimated_fee=900_000,
        contract_duration_months=60, proposal_due_at=_dt(38), questions_due_at=_dt(24), industry_day_at=_dt(-6),
        description="Multiple-award IDIQ for civil engineering design services supporting flood risk management, hurricane protection, and levee infrastructure within the New Orleans District.",
        scope_summary="Civil/site design, hydraulic and hydrology studies, flood control infrastructure, task-order based IDIQ.",
        opportunity_source_label="SAM.gov", pipeline_stage_id=stages["Teaming"].id,
        maturity_stage=MaturityStage.SOLICITATION_RELEASED,
    )
    opp3 = make_opp(
        title="Hurricane Recovery Infrastructure Assessment & Design", agency_id=fema.id,
        agency_office_id=offices["fema_r6"].id, solicitation_number=None,
        location_city="Lake Charles", location_state="LA", naics_code="541330", psc_code="C214",
        set_aside=SetAsideType.UNRESTRICTED, contract_type=ContractType.OTHER,
        estimated_value_low=1_000_000, estimated_value_high=2_200_000, estimated_fee=180_000,
        contract_duration_months=12, sources_sought_due_at=_dt(9),
        description="Anticipated disaster-recovery infrastructure assessment and design services following recent federally declared severe weather events; funding obligated under a FEMA Public Assistance grant.",
        scope_summary="Disaster-recovery civil infrastructure assessment, drainage and road repair design, FEMA-funded.",
        opportunity_source_label="Agency Forecast", pipeline_stage_id=stages["Researching"].id,
        maturity_stage=MaturityStage.SOURCES_SOUGHT_RFI,
    )
    opp4 = make_opp(
        title="Watershed Engineering & Erosion Control Design", agency_id=nrcs.id,
        agency_office_id=offices["nrcs_la"].id, solicitation_number="NRCS-LA-26-0007",
        location_city="Alexandria", location_state="LA", naics_code="541330", psc_code="C219",
        set_aside=SetAsideType.SMALL_BUSINESS, contract_type=ContractType.AE_BROOKS_ACT,
        estimated_value_low=400_000, estimated_value_high=700_000, estimated_fee=95_000,
        contract_duration_months=10, proposal_due_at=_dt(27),
        description="Watershed engineering, erosion control, and small dam rehabilitation design services for NRCS flood-control structures in central Louisiana.",
        scope_summary="Watershed hydrology, erosion control, hydraulic structure design.",
        opportunity_source_label="SAM.gov", pipeline_stage_id=stages["Proposal Development"].id,
        maturity_stage=MaturityStage.SOLICITATION_RELEASED,
    )
    opp5 = make_opp(
        title="Citywide Drainage Improvement Program, Phase 3", agency_id=baton_rouge.id,
        solicitation_number="EBR-DPW-26-118", location_city="Baton Rouge", location_state="LA",
        naics_code="541330", psc_code="C219", set_aside=SetAsideType.UNRESTRICTED,
        contract_type=ContractType.AE_BROOKS_ACT, estimated_value_low=250_000, estimated_value_high=450_000,
        estimated_fee=60_000, contract_duration_months=8, proposal_due_at=_dt(16),
        description="Design services for Phase 3 of the citywide stormwater drainage improvement program, including hydraulic modeling and outfall design.",
        scope_summary="Stormwater drainage design, hydraulic modeling, capital improvement program.",
        opportunity_source_label="Referral", pipeline_stage_id=stages["Submitted"].id,
        maturity_stage=MaturityStage.PROPOSAL_SUBMITTED,
    )
    opp6 = make_opp(
        title="Parish Water Distribution System Replacement", agency_id=jefferson_parish.id,
        solicitation_number="JP-ENG-26-044", location_city="Metairie", location_state="LA",
        naics_code="541330", psc_code="C219", set_aside=SetAsideType.SDVOSB,
        contract_type=ContractType.AE_BROOKS_ACT, estimated_value_low=3_000_000, estimated_value_high=4_500_000,
        estimated_fee=420_000, contract_duration_months=24, proposal_due_at=_dt(-3),
        description="Design of a parish-wide potable water distribution system replacement, restricted to SDVOSB firms under the parish's small-business initiative.",
        scope_summary="Water distribution system replacement, utility design.",
        opportunity_source_label="SAM.gov", pipeline_stage_id=stages["Interview"].id,
        maturity_stage=MaturityStage.INTERVIEW_NEGOTIATION,
    )
    opp7 = make_opp(
        title="Wastewater Treatment Plant Rehabilitation — Task Order", agency_id=usace.id,
        agency_office_id=offices["usace_vicksburg"].id, solicitation_number="W912EE-26-F-0022",
        location_city="Vicksburg", location_state="MS", naics_code="541330", psc_code="C219",
        set_aside=SetAsideType.UNRESTRICTED, contract_type=ContractType.TASK_ORDER,
        estimated_value_low=800_000, estimated_value_high=1_100_000, estimated_fee=140_000,
        contract_duration_months=14, proposal_due_at=_dt(45),
        description="Task order under an existing MATOC vehicle for wastewater treatment plant rehabilitation design at a federal facility.",
        scope_summary="Wastewater treatment plant rehabilitation, mechanical and civil design.",
        opportunity_source_label="SAM.gov", pipeline_stage_id=stages["Solicitation Released"].id,
        maturity_stage=MaturityStage.SOLICITATION_RELEASED,
    )
    opp8 = make_opp(
        title="Tyndall AFB Civil Infrastructure Resilience Design", agency_id=air_force.id,
        agency_office_id=offices["afcec"].id, solicitation_number="FA8025-26-R-0009",
        location_city="Tyndall AFB", location_state="FL", naics_code="541330", psc_code="C219",
        set_aside=SetAsideType.SDVOSB, contract_type=ContractType.AE_BROOKS_ACT,
        estimated_value_low=1_500_000, estimated_value_high=2_500_000, estimated_fee=260_000,
        contract_duration_months=16, proposal_due_at=_dt(33),
        description="Civil infrastructure resilience design supporting continued hurricane-recovery rebuilding at Tyndall Air Force Base, including site/civil and stormwater design.",
        scope_summary="Site/civil design, stormwater management, disaster-recovery resilience, military installation.",
        opportunity_source_label="SAM.gov", pipeline_stage_id=stages["Go/No-Go"].id,
        maturity_stage=MaturityStage.SOLICITATION_RELEASED,
    )
    opp9 = make_opp(
        title="Civil Engineering IDIQ Recompete — Mobile District", agency_id=usace.id,
        agency_office_id=offices["usace_mobile"].id, solicitation_number=None,
        location_city="Mobile", location_state="AL", naics_code="541330", psc_code="C219",
        set_aside=SetAsideType.UNRESTRICTED, contract_type=ContractType.IDIQ,
        estimated_value_low=8_000_000, estimated_value_high=20_000_000, estimated_fee=1_200_000,
        contract_duration_months=60, incumbent_company_id=large_prime.id,
        incumbent_notes="Currently held by National Infrastructure Engineers, Inc.; base + option periods expected to run through mid-2027.",
        description="Anticipated recompete of the Mobile District's civil engineering design IDIQ, currently held by a large national A/E prime.",
        scope_summary="Civil/site design IDIQ, likely recompete of an existing large-prime vehicle.",
        opportunity_source_label="Agency Forecast", pipeline_stage_id=stages["Researching"].id,
        maturity_stage=MaturityStage.PROCUREMENT_FORECAST,
    )
    opp10 = make_opp(
        title="VA Outpatient Clinic Site/Civil Design (Sources Sought)", agency_id=va.id,
        solicitation_number="36C25726Q0088", location_city="Shreveport", location_state="LA",
        naics_code="541330", psc_code="C219", set_aside=SetAsideType.SDVOSB,
        contract_type=ContractType.AE_BROOKS_ACT, estimated_fee=None, sources_sought_due_at=_dt(12),
        description="Sources Sought notice for site/civil design services supporting a new VA outpatient clinic; no estimated value published yet.",
        scope_summary="Site/civil design for a new VA outpatient clinic; early-stage sources sought.",
        opportunity_source_label="SAM.gov", pipeline_stage_id=stages["Signal Detected"].id,
        maturity_stage=MaturityStage.SOURCES_SOUGHT_RFI,
    )
    opp11 = make_opp(
        title="Regional Airport Drainage & Pavement Support (Subconsultant)", agency_id=baton_rouge.id,
        solicitation_number=None, location_city="Baton Rouge", location_state="LA",
        naics_code="541330", psc_code="C219", set_aside=SetAsideType.UNRESTRICTED,
        contract_type=ContractType.OTHER, estimated_value_low=1_200_000, estimated_value_high=1_800_000,
        estimated_fee=75_000, contract_duration_months=12, proposal_due_at=_dt(19),
        description="Regional airport authority pavement and drainage improvement program; Principal is pursuing a civil/drainage subconsultant role under a larger aviation-focused prime.",
        scope_summary="Airport drainage and pavement support, pursuing as subconsultant rather than prime.",
        internal_notes="Pursuing as subconsultant to a regional aviation engineering prime — Principal scope limited to drainage/civil.",
        opportunity_source_label="Referral", pipeline_stage_id=stages["Capture"].id,
        maturity_stage=MaturityStage.SOLICITATION_RELEASED,
    )
    opp12 = make_opp(
        title="Small Municipal Facility Parking Lot Resurfacing Design", agency_id=baton_rouge.id,
        solicitation_number="EBR-DPW-26-055", location_city="Baton Rouge", location_state="LA",
        naics_code="236220", psc_code="C219", set_aside=SetAsideType.UNRESTRICTED,
        contract_type=ContractType.OTHER, estimated_value_low=60_000, estimated_value_high=90_000,
        estimated_fee=12_000, contract_duration_months=3, proposal_due_at=_dt(6),
        description="Minor design services for parking lot resurfacing at a municipal facility — outside Principal's core civil/water focus.",
        scope_summary="Parking lot resurfacing design — limited strategic fit.",
        opportunity_source_label="SAM.gov", pipeline_stage_id=stages["Signal Detected"].id,
        maturity_stage=MaturityStage.SOLICITATION_RELEASED,
    )
    opp13 = make_opp(
        title="Levee Rehabilitation Design-Bid-Build Support", agency_id=usace.id,
        agency_office_id=offices["usace_no"].id, solicitation_number="W912P8-25-R-0091",
        location_city="New Orleans", location_state="LA", naics_code="541330", psc_code="C219",
        set_aside=SetAsideType.SDVOSB, contract_type=ContractType.AE_BROOKS_ACT,
        estimated_value_low=900_000, estimated_value_high=1_400_000, estimated_fee=165_000,
        contract_duration_months=11, proposal_due_at=_dt(-30),
        description="Design support for levee rehabilitation following recent high-water events.",
        scope_summary="Levee/flood control rehabilitation design.",
        opportunity_source_label="SAM.gov", pipeline_stage_id=stages["Won"].id,
        maturity_stage=MaturityStage.AWARDED,
    )
    opp14 = make_opp(
        title="Municipal Wastewater Lift Station Upgrade", agency_id=jefferson_parish.id,
        solicitation_number="JP-ENG-25-201", location_city="Metairie", location_state="LA",
        naics_code="541330", psc_code="C219", set_aside=SetAsideType.SMALL_BUSINESS,
        contract_type=ContractType.AE_BROOKS_ACT, estimated_value_low=500_000, estimated_value_high=750_000,
        estimated_fee=80_000, contract_duration_months=9, proposal_due_at=_dt(-60),
        incumbent_company_id=sdvosb_competitor.id,
        description="Lift station upgrade design; Principal was not selected for this pursuit.",
        scope_summary="Wastewater lift station upgrade design.",
        opportunity_source_label="SAM.gov", pipeline_stage_id=stages["Lost"].id,
        maturity_stage=MaturityStage.AWARDED,
    )

    # Teaming / competitor relationships
    db.add_all([
        OpportunityCompany(opportunity_id=opp1.id, company_id=architecture_partner.id, relationship_type=OpportunityCompanyRelationship.TEAMING_PARTNER, rationale="VA facility work typically requires architecture-of-record; Delta has prior VA healthcare experience."),
        OpportunityCompany(opportunity_id=opp1.id, company_id=sdvosb_competitor.id, relationship_type=OpportunityCompanyRelationship.LIKELY_COMPETITOR, rationale="Patriot has pursued multiple VA SDVOSB set-asides in the Gulf South in the past two years."),
        OpportunityCompany(opportunity_id=opp2.id, company_id=geotech_partner.id, relationship_type=OpportunityCompanyRelationship.TEAMING_PARTNER, rationale="Levee/flood-control IDIQ scope requires ongoing geotechnical support."),
        OpportunityCompany(opportunity_id=opp2.id, company_id=large_prime.id, relationship_type=OpportunityCompanyRelationship.HISTORICAL_COMPETITOR, rationale="National Infrastructure Engineers has held similar USACE IDIQs in this district before."),
        OpportunityCompany(opportunity_id=opp6.id, company_id=survey_partner.id, relationship_type=OpportunityCompanyRelationship.TEAMING_PARTNER, rationale="Water distribution design requires updated topographic survey of the parish system."),
        OpportunityCompany(opportunity_id=opp9.id, company_id=large_prime.id, relationship_type=OpportunityCompanyRelationship.INCUMBENT, rationale="Confirmed current holder of the IDIQ expected to recompete."),
        OpportunityCompany(opportunity_id=opp3.id, company_id=eight_a_firm.id, relationship_type=OpportunityCompanyRelationship.TEAMING_PARTNER, rationale="FEMA disaster-recovery scope includes environmental assessment work Riverbend specializes in."),
        OpportunityCompany(opportunity_id=opp14.id, company_id=sdvosb_competitor.id, relationship_type=OpportunityCompanyRelationship.CONFIRMED_COMPETITOR, rationale="Patriot was the awardee on this pursuit per the agency's award notice."),
    ])

    # Contact associations
    db.add_all([
        OpportunityContact(opportunity_id=opp2.id, contact_id=contacts[0].id, role_on_opportunity=ContactRole.CONTRACTING_OFFICER),
        OpportunityContact(opportunity_id=opp1.id, contact_id=contacts[1].id, role_on_opportunity=ContactRole.SMALL_BUSINESS_SPECIALIST),
        OpportunityContact(opportunity_id=opp6.id, contact_id=contacts[2].id, role_on_opportunity=ContactRole.MUNICIPAL_OFFICIAL),
        OpportunityContact(opportunity_id=opp3.id, contact_id=contacts[3].id, role_on_opportunity=ContactRole.PROGRAM_MANAGER),
        OpportunityContact(opportunity_id=opp1.id, contact_id=contacts[4].id, role_on_opportunity=ContactRole.TEAMING_PARTNER_CONTACT),
    ])
    db.flush()

    # Revenue forecasts
    forecast_specs = [
        (opp1, 3_500_000, 100, 310_000, 55, 40, "Federal Facilities"),
        (opp2, 15_000_000, 20, 900_000, 35, 70, "Water/Wastewater"),
        (opp3, 2_200_000, 100, 180_000, 30, 60, "Disaster Recovery"),
        (opp4, 700_000, 100, 95_000, 65, 50, "Water/Wastewater"),
        (opp5, 450_000, 100, 60_000, 70, 20, "Stormwater/Drainage"),
        (opp6, 4_500_000, 100, 420_000, 75, 15, "Water/Wastewater"),
        (opp7, 1_100_000, 100, 140_000, 60, 55, "Water/Wastewater"),
        (opp8, 2_500_000, 100, 260_000, 45, 65, "Federal Facilities"),
        (opp9, 20_000_000, 15, 1_200_000, 15, 400, "Transportation"),
        (opp11, 1_800_000, 30, 75_000, 50, 45, "Transportation"),
        (opp13, 1_400_000, 100, 165_000, 100, -30, "Water/Wastewater"),
        (opp14, 750_000, 100, 80_000, 0, -60, "Water/Wastewater"),
    ]
    for opp, total, share, fee, prob, award_offset, market in forecast_specs:
        db.add(RevenueForecast(
            opportunity_id=opp.id, total_contract_value=total, principal_share_pct=share, estimated_fee=fee,
            win_probability_pct=prob, expected_award_date=TODAY + timedelta(days=award_offset), market_sector=market,
        ))

    # Go/No-Go reviews — a couple in progress, one decided
    review2 = get_or_create_review(db, opp2.id)
    upsert_criteria_scores(db, review2, [
        GoNoGoCriteriaScoreUpsert(criterion="Strategic alignment", score=5),
        GoNoGoCriteriaScoreUpsert(criterion="SDVOSB advantage", score=3, notes="Small business set-aside, not SDVOSB-restricted."),
        GoNoGoCriteriaScoreUpsert(criterion="Teaming strength", score=4),
    ])

    review8 = get_or_create_review(db, opp8.id)
    upsert_criteria_scores(db, review8, [
        GoNoGoCriteriaScoreUpsert(criterion="Strategic alignment", score=5),
        GoNoGoCriteriaScoreUpsert(criterion="SDVOSB advantage", score=5),
        GoNoGoCriteriaScoreUpsert(criterion="Schedule", score=4),
        GoNoGoCriteriaScoreUpsert(criterion="Proposal effort", score=3),
    ])
    record_decision(db, review8, GoNoGoOutcome.GO, "Strong SDVOSB fit; proceed to teaming.", admin)

    review13 = get_or_create_review(db, opp13.id)
    record_decision(db, review13, GoNoGoOutcome.GO, "Won — historical decision recorded for reference.", admin)

    # Win/Loss reviews for closed opportunities
    db.add(WinLossReview(
        opportunity_id=opp13.id, outcome="won", winner_company_id=principal.id, award_amount=1_350_000,
        decision_date=TODAY - timedelta(days=30), why_won_lost="Strong SDVOSB position and prior USACE New Orleans District past performance.",
        recorded_by_id=admin.id,
    ))
    db.add(WinLossReview(
        opportunity_id=opp14.id, outcome="lost", winner_company_id=sdvosb_competitor.id, award_amount=720_000,
        decision_date=TODAY - timedelta(days=60),
        why_won_lost="Competitor had stronger local past performance with the parish on lift station work.",
        debrief_notes="No formal debrief was offered by the parish.",
        technical_weaknesses="Proposal lacked a named local O&M subconsultant.",
        recorded_by_id=admin.id,
    ))

    # Tasks
    db.add_all([
        Task(opportunity_id=opp1.id, title="Call Dana Ruiz re: SDVOSB set-aside confirmation", owner_id=admin.id,
             due_date=TODAY, priority=TaskPriority.HIGH, status=TaskStatus.OPEN, created_by_id=admin.id),
        Task(opportunity_id=opp2.id, title="Confirm geotechnical teaming commitment from Gulf Coast Geotechnical",
             owner_id=admin.id, due_date=TODAY - timedelta(days=1), priority=TaskPriority.URGENT,
             status=TaskStatus.OPEN, created_by_id=admin.id),
        Task(opportunity_id=opp4.id, title="Finalize SF330 Section E resumes for watershed engineers", owner_id=admin.id,
             due_date=TODAY + timedelta(days=2), priority=TaskPriority.HIGH, status=TaskStatus.IN_PROGRESS, created_by_id=admin.id),
        Task(opportunity_id=opp6.id, title="Prepare interview presentation for parish water distribution project",
             owner_id=admin.id, due_date=TODAY + timedelta(days=1), priority=TaskPriority.URGENT,
             status=TaskStatus.OPEN, created_by_id=admin.id),
        Task(opportunity_id=opp8.id, title="Schedule Go/No-Go leadership review for Tyndall AFB pursuit", owner_id=admin.id,
             due_date=TODAY, priority=TaskPriority.MEDIUM, status=TaskStatus.OPEN, created_by_id=admin.id),
        Task(opportunity_id=opp9.id, title="Research National Infrastructure Engineers' current IDIQ ceiling/obligations",
             owner_id=admin.id, due_date=TODAY + timedelta(days=10), priority=TaskPriority.MEDIUM,
             status=TaskStatus.OPEN, created_by_id=admin.id),
        Task(opportunity_id=opp10.id, title="Draft Sources Sought response", owner_id=admin.id,
             due_date=TODAY + timedelta(days=5), priority=TaskPriority.MEDIUM, status=TaskStatus.OPEN, created_by_id=admin.id),
        Task(opportunity_id=None, title="Review USACE Mobile District procurement forecast for Q1", owner_id=admin.id,
             due_date=TODAY + timedelta(days=14), priority=TaskPriority.LOW, status=TaskStatus.OPEN, created_by_id=admin.id),
    ])

    # Alerts
    db.add_all([
        Alert(user_id=None, category=AlertCategory.NEW_MATCHING_OPPORTUNITY,
              title="New SDVOSB opportunity: Tyndall AFB Civil Infrastructure Resilience Design",
              body="SDVOSB set-aside, estimated fee $260,000.", opportunity_id=opp8.id),
        Alert(user_id=None, category=AlertCategory.DEADLINE_APPROACHING,
              title="Proposal due in 3 days: Parish Water Distribution System Replacement",
              body="Interview stage — confirm presentation materials are ready.", opportunity_id=opp6.id),
        Alert(user_id=None, category=AlertCategory.NEW_SOURCES_SOUGHT,
              title="New Sources Sought: VA Outpatient Clinic Site/Civil Design",
              body="SDVOSB set-aside — response due soon.", opportunity_id=opp10.id),
    ])

    db.commit()

    # Score every sample opportunity so the dashboard/list are populated immediately.
    for opp in [opp1, opp2, opp3, opp4, opp5, opp6, opp7, opp8, opp9, opp10, opp11, opp12, opp13, opp14]:
        calculate_score(db, opp)
    db.commit()
    print(f"Seeded {14} SAMPLE DATA opportunities.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-demo", action="store_true", help="Skip SAMPLE DATA opportunities/companies/contacts")
    parser.add_argument("--admin-email", default="ericmcvicker14@gmail.com")
    parser.add_argument("--admin-name", default="Eric McVicker")
    parser.add_argument("--admin-password", default=None, help="If omitted, a random password is generated and printed once")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        seed_reference_data(db)

        password = args.admin_password
        generated = False
        if password is None:
            import secrets
            password = secrets.token_urlsafe(12)
            generated = True

        admin = seed_admin_user(db, args.admin_email, args.admin_name, password)

        if not args.no_demo:
            seed_demo_data(db, admin)

        if generated:
            print("\n" + "=" * 70)
            print(f"Administrator login created:\n  email:    {args.admin_email}\n  password: {password}")
            print("This password is shown only once and is NOT stored anywhere in the repo.")
            print("Log in and note it somewhere safe (a password manager) right away.")
            print("=" * 70)
    finally:
        db.close()


if __name__ == "__main__":
    main()
