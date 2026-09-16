"""Seeds the Source Registry (intelligence_sources) with every source named in Phase
2's Wave 1 list, whether or not a connector exists for it yet. See
docs/PHASE2_ARCHITECTURE.md §8 for the reliable-today / needs-research / deferred
triage this list implements.

Idempotent and safe to re-run on every boot, like the rest of seed.py — but unlike
seed_reference_data, re-running this does NOT touch is_enabled, health_status, or any
of the last_*/polling_frequency_hours columns on an existing row: those are runtime
state (written by app.services.intelligence_sync.run_sync) or an administrator's own
choice, never something a redeploy should silently reset. Only the descriptive/config
fields (source_url, notes, connector_key, ...) are refreshed on every run, so editing
this list and redeploying keeps the registry's metadata current without clobbering
anyone's "I turned this on" decision.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ConnectorType, IntelligenceCategory, JurisdictionLevel, SourceHealthStatus
from app.models.intelligence import IntelligenceSource

# Fields refreshed on every re-seed. Deliberately excludes is_enabled, health_status,
# polling_frequency_hours, and every last_*/last_error column.
_UPDATE_ON_RESEED = (
    "organization", "jurisdiction_level", "geographic_coverage", "source_url", "api_url",
    "connector_type", "connector_key", "requires_auth", "auth_notes", "terms_notes",
    "default_intelligence_category", "naics_filter", "notes",
)

FEDERAL = JurisdictionLevel.FEDERAL
STATE = JurisdictionLevel.STATE
LOCAL = JurisdictionLevel.LOCAL
REGIONAL = JurisdictionLevel.REGIONAL

API = ConnectorType.API
MANUAL = ConnectorType.MANUAL

LIVE = IntelligenceCategory.LIVE_OPPORTUNITY
PRE = IntelligenceCategory.PRE_SOLICITATION
SIGNAL = IntelligenceCategory.EARLY_SIGNAL
AWARD = IntelligenceCategory.AWARD_INTELLIGENCE

# Each dict maps directly onto IntelligenceSource columns (name is the upsert key).
# Sources with connector_key set are either working today (SAM.gov) or will be wired
# up in the next stage (USAspending.gov, Grants.gov) — everything else is registered
# with connector_key=None and an honest research note per §8, not a guessed connector.
SOURCES: list[dict] = [
    # --- Federal core: reliable today -------------------------------------------
    dict(
        name="SAM.gov", organization="U.S. General Services Administration",
        jurisdiction_level=FEDERAL, geographic_coverage="Nationwide",
        source_url="https://sam.gov", connector_type=API, connector_key="sam_gov",
        requires_auth=True, auth_notes="Free public API key from an individual's SAM.gov Account Details page.",
        default_intelligence_category=LIVE,
        notes="Solicitations, presolicitations/sources sought, and award notices for federal contract opportunities.",
    ),
    dict(
        name="USAspending.gov", organization="U.S. Treasury / Bureau of the Fiscal Service",
        jurisdiction_level=FEDERAL, geographic_coverage="Nationwide",
        source_url="https://www.usaspending.gov", connector_type=API, connector_key="usaspending",
        requires_auth=False, default_intelligence_category=AWARD,
        notes="Federal award/spending history — who won what, for competitor and incumbent intelligence. Never promoted to a pipeline opportunity.",
    ),
    dict(
        name="Grants.gov", organization="U.S. Health and Human Services (on behalf of all federal grant-making agencies)",
        jurisdiction_level=FEDERAL, geographic_coverage="Nationwide",
        source_url="https://www.grants.gov", connector_type=API, connector_key="grants_gov",
        requires_auth=False, default_intelligence_category=SIGNAL,
        notes="Federal grant funding announcements (infrastructure/water/wastewater/transportation-filtered) — an early signal for the design/engineering RFQs that typically follow a grant award.",
    ),
    # --- Federal core: needs research/nonstandard access --------------------------
    dict(
        name="VA Forecast", organization="U.S. Department of Veterans Affairs, OSDBU",
        jurisdiction_level=FEDERAL, geographic_coverage="Nationwide",
        source_url="https://www.va.gov/osdbu/", connector_type=MANUAL, connector_key=None,
        default_intelligence_category=PRE,
        notes="Published as a downloadable forecast spreadsheet, not an API. Needs a structured-file (XLSX) connector once the current download URL is confirmed.",
    ),
    dict(
        name="Acquisition.gov Agency Forecasts", organization="U.S. General Services Administration / OFPP",
        jurisdiction_level=FEDERAL, geographic_coverage="Nationwide",
        source_url="https://acquisition.gov", connector_type=MANUAL, connector_key=None,
        default_intelligence_category=PRE,
        notes="Procurement forecasts are published per-agency, not through one unified API — needs per-agency research before this is buildable as a single connector.",
    ),
    dict(
        name="DHS/FEMA APFS (Advance Procurement Forecast System)", organization="U.S. Department of Homeland Security / FEMA",
        jurisdiction_level=FEDERAL, geographic_coverage="Nationwide",
        source_url="https://www.fema.gov/about/offices/small-business", connector_type=MANUAL, connector_key=None,
        default_intelligence_category=PRE,
        notes="FEMA's small-business forecast tool — access method needs verification before a connector can be built.",
    ),
    dict(
        name="Air Force / DoD Contract Forecast", organization="U.S. Department of Defense",
        jurisdiction_level=FEDERAL, geographic_coverage="Nationwide",
        source_url=None, connector_type=MANUAL, connector_key=None,
        default_intelligence_category=PRE,
        notes="Forecasts are published per-installation/command, not centrally — needs research into which specific commands are relevant to Principal before this is buildable.",
    ),
    # --- USACE priority districts (spec-named) -------------------------------------
    dict(
        name="USACE New Orleans District", organization="U.S. Army Corps of Engineers",
        jurisdiction_level=FEDERAL, geographic_coverage="Louisiana, southern Mississippi",
        source_url="https://www.mvn.usace.army.mil", connector_type=MANUAL, connector_key=None,
        default_intelligence_category=PRE,
        notes="Principal's single highest-priority USACE district. District-level forecast/contracting page structure needs verification before a connector is built.",
    ),
    dict(
        name="USACE Vicksburg District", organization="U.S. Army Corps of Engineers",
        jurisdiction_level=FEDERAL, geographic_coverage="Mississippi, Louisiana, Arkansas",
        source_url="https://www.mvk.usace.army.mil", connector_type=MANUAL, connector_key=None,
        default_intelligence_category=PRE, notes="Needs connector research — see USACE New Orleans District note.",
    ),
    dict(
        name="USACE Mobile District", organization="U.S. Army Corps of Engineers",
        jurisdiction_level=FEDERAL, geographic_coverage="Alabama, Georgia, Florida panhandle",
        source_url="https://www.sam.usace.army.mil", connector_type=MANUAL, connector_key=None,
        default_intelligence_category=PRE, notes="Needs connector research — see USACE New Orleans District note.",
    ),
    dict(
        name="USACE Memphis District", organization="U.S. Army Corps of Engineers",
        jurisdiction_level=FEDERAL, geographic_coverage="Tennessee, Arkansas, Mississippi, Missouri, Kentucky",
        source_url="https://www.mvm.usace.army.mil", connector_type=MANUAL, connector_key=None,
        default_intelligence_category=PRE, notes="Needs connector research — see USACE New Orleans District note.",
    ),
    dict(
        name="USACE Galveston District", organization="U.S. Army Corps of Engineers",
        jurisdiction_level=FEDERAL, geographic_coverage="Southeast/central Texas",
        source_url="https://www.swg.usace.army.mil", connector_type=MANUAL, connector_key=None,
        default_intelligence_category=PRE, notes="Needs connector research — see USACE New Orleans District note.",
    ),
    dict(
        name="USACE Nashville District", organization="U.S. Army Corps of Engineers",
        jurisdiction_level=FEDERAL, geographic_coverage="Tennessee, Kentucky",
        source_url="https://www.lrn.usace.army.mil", connector_type=MANUAL, connector_key=None,
        default_intelligence_category=PRE, notes="Needs connector research — see USACE New Orleans District note.",
    ),
    dict(
        name="USACE Jacksonville District", organization="U.S. Army Corps of Engineers",
        jurisdiction_level=FEDERAL, geographic_coverage="Florida, Puerto Rico, U.S. Virgin Islands",
        source_url="https://www.saj.usace.army.mil", connector_type=MANUAL, connector_key=None,
        default_intelligence_category=PRE, notes="Needs connector research — see USACE New Orleans District note.",
    ),
    dict(
        name="USACE Civil Works Program", organization="U.S. Army Corps of Engineers",
        jurisdiction_level=FEDERAL, geographic_coverage="Nationwide",
        source_url="https://www.usace.army.mil/Missions/Civil-Works/", connector_type=MANUAL, connector_key=None,
        default_intelligence_category=SIGNAL,
        notes="Civil Works budget/appropriations line items — an early-warning signal for future USACE district solicitations, not itself a procurement feed.",
    ),
    # --- Louisiana core --------------------------------------------------------------
    dict(
        name="Louisiana DOTD Projected Letting", organization="Louisiana Dept. of Transportation and Development",
        jurisdiction_level=STATE, geographic_coverage="Louisiana statewide",
        source_url="https://wwwsp.dotd.la.gov", connector_type=MANUAL, connector_key=None,
        default_intelligence_category=PRE,
        notes="Projected (future) letting list — state highway/bridge/drainage projects. Page structure needs verification before an HTML or structured-file connector is built.",
    ),
    dict(
        name="Louisiana DOTD Posted Advertisements", organization="Louisiana Dept. of Transportation and Development",
        jurisdiction_level=STATE, geographic_coverage="Louisiana statewide",
        source_url="https://wwwsp.dotd.la.gov", connector_type=MANUAL, connector_key=None,
        default_intelligence_category=LIVE,
        notes="Currently-advertised (live) lettings. Same domain as the projected list above — needs the same page-structure verification.",
    ),
    dict(
        name="LaPAC", organization="Louisiana Division of Administration, Office of State Procurement",
        jurisdiction_level=STATE, geographic_coverage="Louisiana statewide",
        source_url="https://www.doa.la.gov", connector_type=MANUAL, connector_key=None,
        default_intelligence_category=LIVE,
        notes="Louisiana's state procurement portal for goods/services/professional contracts. Needs confirmation of the current LaPAC URL and whether it exposes a structured feed.",
    ),
    dict(
        name="CPRA (Coastal Protection and Restoration Authority)", organization="State of Louisiana",
        jurisdiction_level=STATE, geographic_coverage="Louisiana coastal parishes",
        source_url="https://coastal.la.gov", connector_type=MANUAL, connector_key=None,
        default_intelligence_category=PRE,
        notes="Coastal restoration/protection project and procurement listings — high relevance to Principal's disaster-recovery/resilience focus.",
    ),
    dict(
        name="Louisiana CWSRF/DWRLF (Water Pollution & Drinking Water Revolving Loan Funds)",
        organization="Louisiana Dept. of Environmental Quality",
        jurisdiction_level=STATE, geographic_coverage="Louisiana statewide",
        source_url="https://deq.louisiana.gov", connector_type=MANUAL, connector_key=None,
        default_intelligence_category=SIGNAL,
        notes="Published as periodic PDF 'intended use plan' project priority lists, not an API — a strong early signal for water/wastewater design work.",
    ),
    dict(
        name="Louisiana Water Sector Program", organization="State of Louisiana",
        jurisdiction_level=STATE, geographic_coverage="Louisiana statewide",
        source_url=None, connector_type=MANUAL, connector_key=None, default_intelligence_category=SIGNAL,
        notes="Needs research to confirm the specific program/office this refers to and its publication method.",
    ),
    dict(
        name="Louisiana Capital Outlay", organization="Louisiana Division of Administration, Facility Planning and Control",
        jurisdiction_level=STATE, geographic_coverage="Louisiana statewide",
        source_url="https://www.doa.la.gov", connector_type=MANUAL, connector_key=None,
        default_intelligence_category=SIGNAL,
        notes="State capital budget — identifies state building/infrastructure projects before they're individually solicited.",
    ),
    # --- Northshore / Greater New Orleans locals --------------------------------------
    # Jurisdiction=LOCAL, connector_type=MANUAL until each is confirmed to use a common
    # procurement platform (Beacon/Central Bidding/OpenGov/Bonfire/IonWave/BidNet/
    # PlanetBids/Public Purchase) per §8 — that research needs live access this sandbox
    # doesn't have. source_url is left null rather than guessed wherever not confident.
    dict(name="St. Tammany Parish Government", organization="St. Tammany Parish", jurisdiction_level=LOCAL,
         geographic_coverage="St. Tammany Parish, LA", source_url="https://www.stpgov.org",
         connector_type=MANUAL, connector_key=None, default_intelligence_category=LIVE,
         notes="Needs research: identify procurement platform before a connector can be built."),
    dict(name="City of Slidell", organization="City of Slidell", jurisdiction_level=LOCAL,
         geographic_coverage="Slidell, LA", source_url=None,
         connector_type=MANUAL, connector_key=None, default_intelligence_category=LIVE,
         notes="Needs research: confirm current site and procurement platform."),
    dict(name="City of Mandeville", organization="City of Mandeville", jurisdiction_level=LOCAL,
         geographic_coverage="Mandeville, LA", source_url=None,
         connector_type=MANUAL, connector_key=None, default_intelligence_category=LIVE,
         notes="Needs research: confirm current site and procurement platform."),
    dict(name="City of Covington", organization="City of Covington", jurisdiction_level=LOCAL,
         geographic_coverage="Covington, LA", source_url=None,
         connector_type=MANUAL, connector_key=None, default_intelligence_category=LIVE,
         notes="Needs research: confirm current site and procurement platform."),
    dict(name="City of New Orleans", organization="City of New Orleans", jurisdiction_level=LOCAL,
         geographic_coverage="New Orleans, LA", source_url="https://nola.gov",
         connector_type=MANUAL, connector_key=None, default_intelligence_category=LIVE,
         notes="Needs research: identify procurement platform before a connector can be built."),
    dict(name="Sewerage & Water Board of New Orleans (SWBNO)", organization="SWBNO", jurisdiction_level=LOCAL,
         geographic_coverage="New Orleans, LA", source_url="https://www.swbno.org",
         connector_type=MANUAL, connector_key=None, default_intelligence_category=LIVE,
         notes="Very high relevance (water/wastewater/drainage capital program) — prioritize this once local-platform research resumes."),
    dict(name="Port of New Orleans (Port NOLA)", organization="Port of New Orleans", jurisdiction_level=LOCAL,
         geographic_coverage="New Orleans, LA", source_url="https://www.portnola.com",
         connector_type=MANUAL, connector_key=None, default_intelligence_category=LIVE,
         notes="Needs research: identify procurement platform before a connector can be built."),
    dict(name="Louis Armstrong New Orleans International Airport (MSY)", organization="New Orleans Aviation Board",
         jurisdiction_level=LOCAL, geographic_coverage="New Orleans, LA", source_url=None,
         connector_type=MANUAL, connector_key=None, default_intelligence_category=LIVE,
         notes="Needs research: confirm current site and procurement platform."),
    dict(name="Jefferson Parish Government", organization="Jefferson Parish", jurisdiction_level=LOCAL,
         geographic_coverage="Jefferson Parish, LA", source_url="https://www.jeffparish.net",
         connector_type=MANUAL, connector_key=None, default_intelligence_category=LIVE,
         notes="Needs research: identify procurement platform before a connector can be built."),
    dict(name="St. Bernard Parish Government", organization="St. Bernard Parish", jurisdiction_level=LOCAL,
         geographic_coverage="St. Bernard Parish, LA", source_url=None,
         connector_type=MANUAL, connector_key=None, default_intelligence_category=LIVE,
         notes="Needs research: confirm current site and procurement platform."),
    dict(name="St. Charles Parish Government", organization="St. Charles Parish", jurisdiction_level=LOCAL,
         geographic_coverage="St. Charles Parish, LA", source_url=None,
         connector_type=MANUAL, connector_key=None, default_intelligence_category=LIVE,
         notes="Needs research: confirm current site and procurement platform."),
    dict(name="St. John the Baptist Parish Government", organization="St. John the Baptist Parish",
         jurisdiction_level=LOCAL, geographic_coverage="St. John the Baptist Parish, LA", source_url=None,
         connector_type=MANUAL, connector_key=None, default_intelligence_category=LIVE,
         notes="Needs research: confirm current site and procurement platform."),
    dict(name="Plaquemines Parish Government", organization="Plaquemines Parish", jurisdiction_level=LOCAL,
         geographic_coverage="Plaquemines Parish, LA", source_url=None,
         connector_type=MANUAL, connector_key=None, default_intelligence_category=LIVE,
         notes="Needs research: confirm current site and procurement platform."),
    dict(name="Port of South Louisiana", organization="Port of South Louisiana", jurisdiction_level=REGIONAL,
         geographic_coverage="St. John the Baptist / St. Charles / St. James parishes, LA", source_url=None,
         connector_type=MANUAL, connector_key=None, default_intelligence_category=LIVE,
         notes="Needs research: confirm current site and procurement platform."),
    # --- Funding / early-warning sources ---------------------------------------------
    dict(name="Louisiana Watershed Initiative", organization="State of Louisiana", jurisdiction_level=STATE,
         geographic_coverage="Louisiana statewide", source_url="https://watershed.la.gov",
         connector_type=MANUAL, connector_key=None, default_intelligence_category=SIGNAL,
         notes="Regional watershed/flood-mitigation funding — a strong early signal for drainage/stormwater design work."),
    dict(name="Louisiana CDBG-DR (Community Development Block Grant - Disaster Recovery)",
         organization="Louisiana Office of Community Development", jurisdiction_level=STATE,
         geographic_coverage="Louisiana statewide", source_url=None,
         connector_type=MANUAL, connector_key=None, default_intelligence_category=SIGNAL,
         notes="Needs research to confirm the current program URL (has moved across disaster-recovery cycles)."),
    dict(name="GOHSEP (Governor's Office of Homeland Security & Emergency Preparedness)",
         organization="State of Louisiana", jurisdiction_level=STATE, geographic_coverage="Louisiana statewide",
         source_url="https://gohsep.la.gov", connector_type=MANUAL, connector_key=None,
         default_intelligence_category=SIGNAL,
         notes="State-level disaster recovery/mitigation funding administration — early signal for FEMA PA/HMGP-funded work."),
    dict(name="FEMA Public Assistance / HMGP / FMA", organization="Federal Emergency Management Agency",
         jurisdiction_level=FEDERAL, geographic_coverage="Nationwide, LA-priority",
         source_url="https://www.fema.gov", connector_type=MANUAL, connector_key=None,
         default_intelligence_category=SIGNAL,
         notes="Disaster recovery / hazard mitigation / flood mitigation grant programs — formula/state-administered, largely not on Grants.gov."),
    dict(name="USDA Rural Development", organization="U.S. Department of Agriculture", jurisdiction_level=FEDERAL,
         geographic_coverage="Nationwide, rural LA priority", source_url="https://www.rd.usda.gov",
         connector_type=MANUAL, connector_key=None, default_intelligence_category=SIGNAL,
         notes="Rural water/wastewater infrastructure funding. Many RD programs also post through Grants.gov — check for overlap before building a dedicated connector."),
    dict(name="NRCS Programs", organization="USDA Natural Resources Conservation Service", jurisdiction_level=FEDERAL,
         geographic_coverage="Nationwide", source_url="https://www.nrcs.usda.gov",
         connector_type=MANUAL, connector_key=None, default_intelligence_category=SIGNAL,
         notes="Watershed/flood-control program funding — a priority agency for Principal. Check for Grants.gov overlap before building a dedicated connector."),
    dict(name="EPA Water Infrastructure Grants / WIFIA", organization="U.S. Environmental Protection Agency",
         jurisdiction_level=FEDERAL, geographic_coverage="Nationwide", source_url="https://www.epa.gov/wifia",
         connector_type=MANUAL, connector_key=None, default_intelligence_category=SIGNAL,
         notes="Large water infrastructure financing — strong early signal. Check for Grants.gov overlap before building a dedicated connector."),
    dict(name="FAA Airport Improvement Program (AIP)", organization="Federal Aviation Administration",
         jurisdiction_level=FEDERAL, geographic_coverage="Nationwide", source_url="https://www.faa.gov",
         connector_type=MANUAL, connector_key=None, default_intelligence_category=SIGNAL,
         notes="Airport capital funding — relevant to MSY and other regional airport work."),
    dict(name="FHWA Funding Programs", organization="Federal Highway Administration", jurisdiction_level=FEDERAL,
         geographic_coverage="Nationwide", source_url="https://www.fhwa.dot.gov",
         connector_type=MANUAL, connector_key=None, default_intelligence_category=SIGNAL,
         notes="Highway/bridge funding — upstream of DOTD lettings."),
    dict(name="FTA Funding Programs", organization="Federal Transit Administration", jurisdiction_level=FEDERAL,
         geographic_coverage="Nationwide", source_url="https://www.transit.dot.gov",
         connector_type=MANUAL, connector_key=None, default_intelligence_category=SIGNAL,
         notes="Transit infrastructure funding."),
    dict(name="EDA (Economic Development Administration)", organization="U.S. Dept. of Commerce",
         jurisdiction_level=FEDERAL, geographic_coverage="Nationwide", source_url="https://www.eda.gov",
         connector_type=MANUAL, connector_key=None, default_intelligence_category=SIGNAL,
         notes="Regional economic development infrastructure funding."),
    dict(name="Port Infrastructure Development Program (PIDP)", organization="U.S. Maritime Administration",
         jurisdiction_level=FEDERAL, geographic_coverage="Nationwide, LA ports priority",
         source_url="https://www.maritime.dot.gov", connector_type=MANUAL, connector_key=None,
         default_intelligence_category=SIGNAL,
         notes="Port capital funding — relevant to Port NOLA / Port of South Louisiana."),
    dict(name="Congressional Appropriations (Community Project Funding)", organization="U.S. Congress",
         jurisdiction_level=FEDERAL, geographic_coverage="Nationwide", source_url=None,
         connector_type=MANUAL, connector_key=None, default_intelligence_category=SIGNAL,
         notes="Earmarked/community project funding is published per-appropriations-bill, not through a queryable system — tracked via committee publications, not a single connector."),
]


def seed_intelligence_sources(db: Session) -> None:
    for raw_entry in SOURCES:
        # requires_auth is NOT NULL; most entries omit it (implying False). That's fine
        # on a fresh INSERT (the column default applies), but the UPDATE path below sets
        # every _UPDATE_ON_RESEED field explicitly — without this, a re-seed would write
        # an explicit NULL over the column default and violate the constraint. Caught by
        # actually running this script twice against a real database, not just once.
        entry = {"requires_auth": False, **raw_entry}

        existing = db.execute(select(IntelligenceSource).where(IntelligenceSource.name == entry["name"])).scalars().first()
        if existing is None:
            is_working_connector = entry["connector_key"] in ("sam_gov", "usaspending", "grants_gov")
            db.add(IntelligenceSource(is_enabled=is_working_connector, **entry))
        else:
            for field_name in _UPDATE_ON_RESEED:
                setattr(existing, field_name, entry.get(field_name))
    db.commit()
