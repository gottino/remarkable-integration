#!/usr/bin/env python3
"""
Clean Duplicate Notion Pages

Deletes all pages from the Notion database EXCEPT the ones created in the most recent sync.
Use this to remove duplicate pages while keeping the fresh ones.
"""

import sys
import os
from pathlib import Path

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config import Config
from src.integrations.notion_sync import NotionNotebookSync
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Page IDs to KEEP (from the recent successful sync)
KEEP_PAGES = {
    "263a6c5d-acd0-8158-9070-d446803e8081",  # 10050056623_1_Ermittlungsbogen
    "263a6c5d-acd0-81c4-a4c2-c6d1dd419a33",  # 190819_ESOP_Doodle
    "263a6c5d-acd0-813c-9ca1-ff38d16362ea",  # 2017_mathematik_aufgaben_kg.pdf
    "263a6c5d-acd0-8128-8293-fcd6b2e0511f",  # 2017_mathematik_aufgaben_lg
    "263a6c5d-acd0-8163-b3b8-c0512bff29bf",  # 2020 November - CodeCheck AG | Ledgy
    "263a6c5d-acd0-8182-a4f1-d4b393755dd1",  # 20201119_CodeCheck - KPMG
    "263a6c5d-acd0-81dc-9237-d39d0599b944",  # 20211113 CV English - long Axpo
    "263a6c5d-acd0-81d4-8d66-ebb89c3220be",  # Abilio
    "263a6c5d-acd0-813b-84cd-d11762dc7de5",  # Alex
    "263a6c5d-acd0-81a6-b235-e8187b20801d",  # Amit
    "263a6c5d-acd0-8151-b9f6-c7082b40c8c2",  # Andrea
    "263a6c5d-acd0-812e-9fb7-c8c63f169f72",  # Andrew
    "263a6c5d-acd0-8107-9d45-fd39010789bd",  # Antrag_67
    "263a6c5d-acd0-819d-b3f3-ee5bcb0f4e87",  # Argus
    "263a6c5d-acd0-8141-9f0a-f589461cdfa8",  # Argus Case Studies
    "263a6c5d-acd0-810d-9f1f-fee371463896",  # AufgabenPrüfungsstoffJanuar25
    "263a6c5d-acd0-811a-86c3-e9991acff753",  # Auftrag zur Finanzierungsabwicklung Gabriele.pdf
    "263a6c5d-acd0-8157-8a16-d2c88f466914",  # Axpo
    "263a6c5d-acd0-81ad-9a48-d4729e0aba2f",  # Axpo Intro-Calls
    "263a6c5d-acd0-8150-bc19-fe44a4d8b8a3",  # B2B sales playbook
    "263a6c5d-acd0-81b9-a17d-c28c6e80cf03",  # Bexio
    "263a6c5d-acd0-816b-966d-ebf92b378cf3",  # Board CodeCheck
    "263a6c5d-acd0-817d-80a7-c0d863f2f6f7",  # Boris
    "263a6c5d-acd0-810f-9411-faa72db9d972",  # Branding
    "263a6c5d-acd0-81a5-9d1b-f9a521211c67",  # CAB
    "263a6c5d-acd0-813f-ae8b-fedbf9afa344",  # Carolina
    "263a6c5d-acd0-8115-919d-ee94d6c0e0db",  # Carve out
    "263a6c5d-acd0-819d-a8b9-dcd17010aadc",  # Carve out
    "263a6c5d-acd0-819e-856d-d04f6f7f7128",  # Category Creation
    "263a6c5d-acd0-81d7-a6e3-d07983e0f544",  # Christian
    "263a6c5d-acd0-819e-ba8b-ef536c91013d",  # Christian
    "263a6c5d-acd0-8163-bf8b-e5cb441014ea",  # Circe - Madeline Miller
    "263a6c5d-acd0-8192-9134-ce4d49e31546",  # CodeCheck
    "263a6c5d-acd0-8195-9fba-f1960081f577",  # CodeCheck B2B
    "263a6c5d-acd0-815a-b9bb-d603f07a7835",  # CodeCheck_Rating
    "263a6c5d-acd0-818b-a877-dd74a034cc37",  # Collab Leads
    "263a6c5d-acd0-811b-a75b-fbf75a27f9f3",  # Collab Leads
    "263a6c5d-acd0-817f-b656-fd7008bb47d1",  # Collaboration
    "263a6c5d-acd0-8118-996a-e9ed35a4f225",  # Collaboration
    "263a6c5d-acd0-8152-b284-cabfcf352c0f",  # Daniel
    "263a6c5d-acd0-8172-9fda-d95c6e5b3700",  # Data
    "263a6c5d-acd0-8110-b2dc-dadb6acfedd2",  # Data Platform
    "263a6c5d-acd0-819a-b90b-fd00c6234053",  # David
    "263a6c5d-acd0-812f-9e58-e2afb2ae8462",  # Digital Blueprint
    "263a6c5d-acd0-8134-a8c0-d499202cc4a4",  # Dimitar
    "263a6c5d-acd0-811e-834f-fb8bc100c1df",  # Diversity @Tamedia
    "263a6c5d-acd0-8139-b4a8-d50f34a6cf8b",  # Doodle
    "263a6c5d-acd0-81e1-bc4f-c9c79a396892",  # Doodle Board
    "263a6c5d-acd0-81b2-bbe4-d18503d39a5e",  # Doodle adhoc notes
    "263a6c5d-acd0-8141-b3ef-ffc400511f17",  # EQ_CodeCheck
    "263a6c5d-acd0-8131-bfb3-ec7f737933b0",  # Eight Dates
    "263a6c5d-acd0-81e8-92c5-d3060427e66e",  # Energy Framework
    "263a6c5d-acd0-8133-98c7-cc9c3572234a",  # Evernote - 8 Apr 2018 at 17:34
    "263a6c5d-acd0-8119-acbd-e7358e10b708",  # Finances
    "263a6c5d-acd0-8138-980a-cbaa5fbc5a54",  # Finanzen
    "263a6c5d-acd0-810e-af6c-f3396a7ae364",  # Fiorella
    "263a6c5d-acd0-81b5-b6a3-ea9c6ad72050",  # Frank
    "263a6c5d-acd0-815e-a0a6-e6eda82390c0",  # Future
    "263a6c5d-acd0-8109-b9fa-c123a646c59e",  # Future 2022
    "263a6c5d-acd0-8130-88a0-de75f35cb9da",  # GatewayOne
    "263a6c5d-acd0-8169-813d-c69c3bdce908",  # Gesamtausgabe_Das_Magazin_2017-10-14
    "263a6c5d-acd0-8185-8776-d2dda2c8560d",  # Gesamtausgabe_Das_Magazin_2018-01-27
    "263a6c5d-acd0-815b-9506-f29d4ae76b6d",  # Get to know 1:1s
    "263a6c5d-acd0-8114-8190-e8528e15767c",  # Grundriss Ramosch.pdf
    "263a6c5d-acd0-8100-9eb8-f303b151ac83",  # Hard Thing About Hard Things, The - Ben Horowitz
    "263a6c5d-acd0-81eb-8586-c154678aa2e8",  # Homo Deus - Yuval Noah Harari
    "263a6c5d-acd0-8178-91ca-d937d040028c",  # Info Memo
    "263a6c5d-acd0-8121-8841-c556a2f711c2",  # Interview
    "263a6c5d-acd0-815d-aa39-f89c3d886b2f",  # Investors
    "263a6c5d-acd0-81b4-b688-f4e63fa29183",  # Investors 2019
    "263a6c5d-acd0-81e7-898c-c1834308e26d",  # Jacopo
    "263a6c5d-acd0-812a-a66a-f1909c70c3cd",  # Jacopo
    "263a6c5d-acd0-8136-865a-f6f2919077bc",  # January Tamedia Board
    "263a6c5d-acd0-8178-ae4d-c107c3c9b6f2",  # Jeremy
    "263a6c5d-acd0-815c-b1ad-c7983fc11b4e",  # Justyna
    "263a6c5d-acd0-81e4-8b45-c7c5ba154d0a",  # Krisenstab
    "263a6c5d-acd0-819a-9a81-f94f8764b0ed",  # Känguru 2018 - 2013 Stufe 3 und 4
    "263a6c5d-acd0-81ae-ae91-f9761cb1996e",  # LOB Collab
    "263a6c5d-acd0-81d4-8e02-dff919805800",  # Leadership - LCP
    "263a6c5d-acd0-8126-b6d9-cced4ed41167",  # Leadership course
    "263a6c5d-acd0-8124-b36d-eaa9c5d3ec3d",  # Luisa
    "263a6c5d-acd0-81b6-9dad-c838c9171253",  # Luzerner Todesmelodie - Monika Mansour
    "263a6c5d-acd0-81ac-9815-d1ce6f193560",  # Magdalena
    "263a6c5d-acd0-816b-ad36-fe575f80ac78",  # Mangement Team
    "263a6c5d-acd0-8112-8972-c76f96040f85",  # Manzini_L_amore-ai-tempi-del-Covid-19_9788838940941
    "263a6c5d-acd0-8142-9786-fa2b9df038e7",  # Marketing
    "263a6c5d-acd0-81b8-a18e-c53b5bb0f8ca",  # Markus
    "263a6c5d-acd0-8175-b24a-d71e2a71dc6d",  # Marton
    "263a6c5d-acd0-81cc-9592-c7965e976b27",  # Marton - Design
    "263a6c5d-acd0-8115-9b1a-ea731040ba34",  # Next
    "263a6c5d-acd0-816f-8e89-c9894de11020",  # Notebook
    "263a6c5d-acd0-8129-8c3b-d4a2e1bf2d1f",  # Notebook1
    "263a6c5d-acd0-813c-9e6c-f31df3b3051a",  # Notebook2
    "263a6c5d-acd0-8136-852b-fc32caa052f1",  # Notes: the hard things about hard things
    "263a6c5d-acd0-816c-9ff4-f83d45da6cf0",  # Nuklear
    "263a6c5d-acd0-8116-8663-f2848ff18b3d",  # OKRs
    "263a6c5d-acd0-810a-bea6-c2fe87c4e1ff",  # P.A.R.A.
    "263a6c5d-acd0-8156-85d7-dc03b0755720",  # Pascale
    "263a6c5d-acd0-818f-8b14-fd2c5b63adad",  # Petra
    "263a6c5d-acd0-81cf-a83b-f96e5a2a0787",  # Pitch
    "263a6c5d-acd0-81cb-9d7c-f7630bb3df4b",  # Plan B
    "263a6c5d-acd0-811a-b6b0-f89fae20daf8",  # Planning
    "263a6c5d-acd0-81fd-817a-dda546f15307",  # Play Bigger
    "263a6c5d-acd0-8111-8740-deab5335a407",  # Play Bigger - Al Ramadan, Dave Peterson, Christopher Lochhead & Kevin Maney
    "263a6c5d-acd0-816a-a3ca-f674ac256d12",  # Positionsprofil_MGB_Head Digital Platform & Services
    "263a6c5d-acd0-814f-9c15-f4b53e3a2fc4",  # Product Strategy
    "263a6c5d-acd0-8165-a5a5-e0b9d788ee27",  # Product and target users
    "263a6c5d-acd0-8131-91f5-e026260fe68e",  # Product team
    "263a6c5d-acd0-816a-9f3c-d37903c28f04",  # Rafael
    "263a6c5d-acd0-814d-85db-e0fd32424f18",  # Ramosch
    "263a6c5d-acd0-8137-82c4-d9209b481a4e",  # Raul
    "263a6c5d-acd0-819f-8fdb-d09c258cf180",  # Recruiting
    "263a6c5d-acd0-817a-b5a4-ebf5368f4251",  # Recruiting
    "263a6c5d-acd0-811c-9368-eb4e406f971c",  # Renato
    "263a6c5d-acd0-815c-837b-d158bf432d0e",  # Reset
    "263a6c5d-acd0-81e9-a20a-fa75cf2bb052",  # Retreat 2019
    "263a6c5d-acd0-81cb-baf1-cd99a13afae8",  # Risunki
    "263a6c5d-acd0-81ca-acde-f11903e8da48",  # Risunki S & L
    "263a6c5d-acd0-8160-953a-e416a958b2ce",  # SAP.io
    "263a6c5d-acd0-818f-812d-c25eb1160d66",  # Sales
    "263a6c5d-acd0-81bc-8a8b-d9136770b3fe",  # Sherpany
    "263a6c5d-acd0-8120-887c-ecc330b4e360",  # Silvia
    "263a6c5d-acd0-8118-9632-dfc6960574b4",  # Spezifikation_CEO_Bexio
    "263a6c5d-acd0-812a-8ef2-e98470699154",  # Stargate
    "263a6c5d-acd0-81fe-beea-d52efd616d0b",  # Stargate
    "263a6c5d-acd0-8169-b8af-e27b2159208b",  # Strategy
    "263a6c5d-acd0-815f-8908-e931826b232c",  # Tamedia meetings
    "263a6c5d-acd0-81b9-93e6-fe0275999502",  # Team
    "263a6c5d-acd0-81a9-9d4b-c93ac2e4cc0d",  # Tel Aviv
    "263a6c5d-acd0-817b-babf-d6d7b8e2d10c",  # Test for integration
    "263a6c5d-acd0-8144-8a7c-f03dc20c876c",  # The Scope
    "263a6c5d-acd0-81e3-a04e-c340d2a31590",  # Thomas
    "263a6c5d-acd0-8127-b4ac-e9752f7239aa",  # Thomas Luzi
    "263a6c5d-acd0-8171-ac31-fe3e32718a7b",  # Todos
    "263a6c5d-acd0-8141-9b73-f273eb0554a2",  # Training MTB
    "263a6c5d-acd0-8150-95a1-f493a5e7cad8",  # Untitled
    "263a6c5d-acd0-811e-a819-d28266d34967",  # Vision
    "263a6c5d-acd0-811e-99c6-f758362627ef",  # Vorbefragung März 04-1
    "263a6c5d-acd0-8128-be59-e85bf29f1dc3",  # Wohnung
    "263a6c5d-acd0-81b2-b4ef-e03459cc81b7",  # Yannick
    "263a6c5d-acd0-81e2-bc6c-c172506c9960",  # Yasmine
    "263a6c5d-acd0-8141-807a-e9978fc12bfe",  # Zero to 100
    "263a6c5d-acd0-812b-b94f-e70d0d21ff83",  # cc.tech.board2.0.1
    "263a6c5d-acd0-8178-bad5-cba1ba4fb71e",  # the-data-driven-enterprise-of-2025-final
    "263a6c5d-acd0-816b-9346-e7cb2c12f56b",  # todos
}

def main():
    """Clean duplicate pages, keeping only the latest ones."""
    try:
        # Load configuration
        config = Config()
        
        # Check if Notion is enabled
        if not config.get('integrations.notion.enabled'):
            logger.error("❌ Notion integration is not enabled in config")
            return
        
        # Get Notion credentials
        notion_token = config.get('integrations.notion.api_token')
        database_id = config.get('integrations.notion.database_id')
        
        if not notion_token or not database_id:
            logger.error("❌ Notion API token or database ID not configured")
            return
        
        # Initialize Notion sync client
        notion_sync = NotionNotebookSync(
            notion_token=notion_token,
            database_id=database_id,
            verify_ssl=False  # For corporate networks
        )
        
        logger.info("🧹 Starting duplicate page cleanup...")
        logger.info(f"📄 Notion database: {database_id}")
        logger.info(f"🔒 Protecting {len(KEEP_PAGES)} recent pages from deletion")
        
        # Get all pages in the database (including archived ones)
        all_pages = []
        has_more = True
        start_cursor = None
        
        while has_more:
            query_params = {"database_id": database_id}
            if start_cursor:
                query_params["start_cursor"] = start_cursor
                
            response = notion_sync.client.databases.query(**query_params)
            all_pages.extend(response["results"])
            has_more = response["has_more"]
            start_cursor = response.get("next_cursor")
        
        pages_to_delete = []
        pages_to_keep = []
        
        for page in all_pages:
            page_id = page["id"]
            if page_id in KEEP_PAGES:
                pages_to_keep.append(page_id)
            else:
                pages_to_delete.append(page)
        
        logger.info(f"📊 Found {len(all_pages)} total pages")
        logger.info(f"🔒 Keeping {len(pages_to_keep)} recent pages")
        logger.info(f"🗑️ Will delete {len(pages_to_delete)} duplicate/old pages")
        
        if not pages_to_delete:
            logger.info("✅ No duplicate pages to delete")
            return
        
        # Delete duplicate pages
        deleted_count = 0
        for page in pages_to_delete:
            try:
                page_id = page["id"]
                title = "Unknown"
                
                # Try to get page title for logging
                if "properties" in page and "Name" in page["properties"]:
                    title_prop = page["properties"]["Name"]
                    if "title" in title_prop and title_prop["title"]:
                        title = title_prop["title"][0]["text"]["content"]
                
                # Check if page is already archived
                if page.get("archived", False):
                    logger.info(f"📁 Already archived: {title}")
                else:
                    notion_sync.client.pages.update(page_id=page_id, archived=True)
                    logger.info(f"🗑️ Archived duplicate: {title}")
                deleted_count += 1
                
            except Exception as e:
                logger.error(f"❌ Failed to delete page {page_id}: {e}")
        
        logger.info(f"✅ Cleanup completed! Archived {deleted_count} duplicate pages")
        logger.info(f"🔒 Kept {len(pages_to_keep)} recent pages intact")
        
    except Exception as e:
        logger.error(f"❌ Cleanup failed: {e}")
        raise

if __name__ == "__main__":
    main()