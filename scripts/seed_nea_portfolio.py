"""
Seed NEA Portfolio Companies
============================

Populates the nea_portfolio table from the NEA website sitemap.
Converts URL slugs to company names and upserts into Supabase.

Usage:
    python scripts/seed_nea_portfolio.py
    python scripts/seed_nea_portfolio.py --dry-run
"""

from __future__ import annotations

import argparse
import re
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# MANUAL OVERRIDES
# Slug -> (company_name, domain, sector) for known tricky names
# =============================================================================

OVERRIDES: dict[str, dict] = {
    # Enterprise
    "cloudflare":               {"company_name": "Cloudflare",              "domain": "cloudflare.com",      "sector": "Enterprise"},
    "databricks":               {"company_name": "Databricks",              "domain": "databricks.com",      "sector": "Enterprise"},
    "merge":                    {"company_name": "Merge",                   "domain": "merge.dev",           "sector": "Enterprise"},
    "pulumi":                   {"company_name": "Pulumi",                  "domain": "pulumi.com",          "sector": "Enterprise"},
    "sana":                     {"company_name": "Sana",                    "domain": "sana.ai",             "sector": "Enterprise"},
    "mongodb":                  {"company_name": "MongoDB",                 "domain": "mongodb.com",         "sector": "Enterprise"},
    "kong":                     {"company_name": "Kong",                    "domain": "konghq.com",          "sector": "Enterprise"},
    "sonatype":                 {"company_name": "Sonatype",                "domain": "sonatype.com",        "sector": "Enterprise"},
    "sciencelogic":             {"company_name": "ScienceLogic",            "domain": "sciencelogic.com",    "sector": "Enterprise"},
    "datarobot":                {"company_name": "DataRobot",               "domain": "datarobot.com",       "sector": "Enterprise"},
    "tigera":                   {"company_name": "Tigera",                  "domain": "tigera.io",           "sector": "Enterprise"},
    "veza":                     {"company_name": "Veza",                    "domain": "veza.com",            "sector": "Enterprise"},
    "safebase":                 {"company_name": "SafeBase",                "domain": "safebase.io",         "sector": "Enterprise"},
    "sentry":                   {"company_name": "Sentry",                  "domain": "sentry.io",           "sector": "Enterprise"},
    "metronome":                {"company_name": "Metronome",               "domain": "metronome.com",       "sector": "Enterprise"},
    "metabase":                 {"company_name": "Metabase",                "domain": "metabase.com",        "sector": "Enterprise"},
    "granica":                  {"company_name": "Granica",                 "domain": "granica.ai",          "sector": "Enterprise"},
    "sundeck":                  {"company_name": "Sundeck",                 "domain": "sundeck.io",          "sector": "Enterprise"},
    "pixiebrix":                {"company_name": "PixieBrix",               "domain": "pixiebrix.com",       "sector": "Enterprise"},
    "zania":                    {"company_name": "Zania",                   "domain": "zania.ai",            "sector": "Enterprise"},
    "second-front":             {"company_name": "Second Front",            "domain": "secondfront.com",     "sector": "Enterprise"},
    "together-ai":              {"company_name": "Together AI",             "domain": "together.ai",         "sector": "Enterprise"},
    "neural-magic":             {"company_name": "Neural Magic",            "domain": "neuralmagic.com",     "sector": "Enterprise"},
    "genmo":                    {"company_name": "Genmo",                   "domain": "genmo.ai",            "sector": "Enterprise"},
    "lizzyai":                  {"company_name": "Lizzy AI",                "domain": "lizzy.ai",            "sector": "Enterprise"},
    "aigen":                    {"company_name": "AiGen",                   "domain": None,                  "sector": "Enterprise"},
    "nuvolo":                   {"company_name": "Nuvolo",                  "domain": "nuvolo.com",          "sector": "Enterprise"},
    "enigma":                   {"company_name": "Enigma",                  "domain": "enigma.com",          "sector": "Enterprise"},
    "attest":                   {"company_name": "Attest",                  "domain": "attest.com",          "sector": "Enterprise"},
    "catalog":                  {"company_name": "Catalog",                 "domain": "catalog.works",       "sector": "Enterprise"},
    "logikcull":                {"company_name": "Logikcull",               "domain": "logikcull.com",       "sector": "Enterprise"},
    "sitetracker":              {"company_name": "Sitetracker",             "domain": "sitetracker.com",     "sector": "Enterprise"},
    "mindtickle":               {"company_name": "Mindtickle",              "domain": "mindtickle.com",      "sector": "Enterprise"},
    "fiscalnote":               {"company_name": "FiscalNote",              "domain": "fiscalnote.com",      "sector": "Enterprise"},
    "appsheet":                 {"company_name": "AppSheet",                "domain": "appsheet.com",        "sector": "Enterprise"},
    "mediaocean":               {"company_name": "Mediaocean",              "domain": "mediaocean.com",      "sector": "Enterprise"},
    "sourcefire":               {"company_name": "Sourcefire",              "domain": None,                  "sector": "Enterprise"},
    "channeladvisor":           {"company_name": "ChannelAdvisor",          "domain": "channeladvisor.com",  "sector": "Enterprise"},
    "hearsay-social":           {"company_name": "Hearsay Social",          "domain": "hearsaysocial.com",   "sector": "Enterprise"},
    "scout-rfp":                {"company_name": "Scout RFP",               "domain": None,                  "sector": "Enterprise"},
    "code42":                   {"company_name": "Code42",                  "domain": "code42.com",          "sector": "Enterprise"},
    "cleversafe":               {"company_name": "Cleversafe",              "domain": None,                  "sector": "Enterprise"},
    "expanse":                  {"company_name": "Expanse",                 "domain": None,                  "sector": "Enterprise"},
    "bitglass":                 {"company_name": "Bitglass",                "domain": None,                  "sector": "Enterprise"},
    "veriflow":                 {"company_name": "Veriflow",                "domain": None,                  "sector": "Enterprise"},

    # Consumer
    "coursera":                 {"company_name": "Coursera",                "domain": "coursera.org",        "sector": "Consumer"},
    "perplexity":               {"company_name": "Perplexity",              "domain": "perplexity.ai",       "sector": "Consumer"},
    "fizz":                     {"company_name": "Fizz",                    "domain": "fizzsocial.com",      "sector": "Consumer"},
    "kindred":                  {"company_name": "Kindred",                 "domain": "kindred.com",         "sector": "Consumer"},
    "patreon":                  {"company_name": "Patreon",                 "domain": "patreon.com",         "sector": "Consumer"},
    "pair":                     {"company_name": "Pair",                    "domain": None,                  "sector": "Consumer"},
    "duolingo":                 {"company_name": "Duolingo",                "domain": "duolingo.com",        "sector": "Consumer"},
    "houzz":                    {"company_name": "Houzz",                   "domain": "houzz.com",           "sector": "Consumer"},
    "evernote":                 {"company_name": "Evernote",                "domain": "evernote.com",        "sector": "Consumer"},
    "groupon":                  {"company_name": "Groupon",                 "domain": "groupon.com",         "sector": "Consumer"},
    "snap":                     {"company_name": "Snap",                    "domain": "snap.com",            "sector": "Consumer"},
    "goop":                     {"company_name": "Goop",                    "domain": "goop.com",            "sector": "Consumer"},
    "wallapop":                 {"company_name": "Wallapop",                "domain": "wallapop.com",        "sector": "Consumer"},
    "beehiiv":                  {"company_name": "Beehiiv",                 "domain": "beehiiv.com",         "sector": "Consumer"},
    "genies":                   {"company_name": "Genies",                  "domain": "genies.com",          "sector": "Consumer"},
    "pocket":                   {"company_name": "Pocket",                  "domain": "getpocket.com",       "sector": "Consumer"},
    "loopt":                    {"company_name": "Loopt",                   "domain": None,                  "sector": "Consumer"},
    "edmodo":                   {"company_name": "Edmodo",                  "domain": None,                  "sector": "Consumer"},
    "care-com":                 {"company_name": "Care.com",                "domain": "care.com",            "sector": "Consumer"},
    "framebridge":              {"company_name": "Framebridge",             "domain": "framebridge.com",     "sector": "Consumer"},
    "moda-operandi":            {"company_name": "Moda Operandi",           "domain": "modaoperandi.com",    "sector": "Consumer"},
    "tamara-mellon":            {"company_name": "Tamara Mellon",           "domain": "tamaramellon.com",    "sector": "Consumer"},
    "mejuri":                   {"company_name": "Mejuri",                  "domain": "mejuri.com",          "sector": "Consumer"},
    "the-yes":                  {"company_name": "The Yes",                 "domain": None,                  "sector": "Consumer"},
    "woebot":                   {"company_name": "Woebot",                  "domain": "woebothealth.com",    "sector": "Consumer"},
    "beachmint":                {"company_name": "BeachMint",               "domain": None,                  "sector": "Consumer"},
    "curalate":                 {"company_name": "Curalate",                "domain": None,                  "sector": "Consumer"},
    "bytedance-toutiao":        {"company_name": "ByteDance",               "domain": "bytedance.com",       "sector": "Consumer"},
    "didi-chuxing":             {"company_name": "Didi Chuxing",            "domain": "didiglobal.com",      "sector": "Consumer"},
    "yubico":                   {"company_name": "Yubico",                  "domain": "yubico.com",          "sector": "Consumer"},
    "travelbank":               {"company_name": "TravelBank",              "domain": "travelbank.com",      "sector": "Consumer"},
    "moonpay":                  {"company_name": "MoonPay",                 "domain": "moonpay.com",         "sector": "Consumer"},

    # Fintech
    "plaid":                    {"company_name": "Plaid",                   "domain": "plaid.com",           "sector": "Fintech"},
    "goodleap":                 {"company_name": "GoodLeap",                "domain": "goodleap.com",        "sector": "Fintech"},
    "robinhood":                {"company_name": "Robinhood",               "domain": "robinhood.com",       "sector": "Fintech"},
    "narmi":                    {"company_name": "Narmi",                   "domain": "narmi.com",           "sector": "Fintech"},
    "braintree":                {"company_name": "Braintree",               "domain": "braintreepayments.com", "sector": "Fintech"},
    "ledge":                    {"company_name": "Ledge",                   "domain": "ledge.ai",            "sector": "Fintech"},
    "upstart":                  {"company_name": "Upstart",                 "domain": "upstart.com",         "sector": "Fintech"},
    "metromile":                {"company_name": "Metromile",               "domain": None,                  "sector": "Fintech"},
    "oanda":                    {"company_name": "OANDA",                   "domain": "oanda.com",           "sector": "Fintech"},
    "vonage":                   {"company_name": "Vonage",                  "domain": "vonage.com",          "sector": "Fintech"},
    "greenlight":               {"company_name": "Greenlight",              "domain": "greenlightcard.com",  "sector": "Fintech"},
    "nitra":                    {"company_name": "Nitra",                   "domain": "nitra.com",           "sector": "Fintech"},
    "raise":                    {"company_name": "Raise",                   "domain": "raise.com",           "sector": "Fintech"},
    "ledgy":                    {"company_name": "Ledgy",                   "domain": "ledgy.com",           "sector": "Fintech"},

    # Digital Health
    "tempus":                   {"company_name": "Tempus",                  "domain": "tempus.com",          "sector": "Digital Health"},
    "strive-health":            {"company_name": "Strive Health",           "domain": "strivehealth.com",    "sector": "Digital Health"},
    "radiology-partners":       {"company_name": "Radiology Partners",      "domain": "radiologypartners.com", "sector": "Digital Health"},
    "marathon":                 {"company_name": "Marathon Health",         "domain": "marathonhealth.com",  "sector": "Digital Health"},
    "curana":                   {"company_name": "Curana Health",           "domain": "curanahealth.com",    "sector": "Digital Health"},
    "comprehensive-pharmacy-services": {"company_name": "Comprehensive Pharmacy Services", "domain": None,  "sector": "Digital Health"},
    "welltok":                  {"company_name": "Welltok",                 "domain": None,                  "sector": "Digital Health"},
    "neuehealth":               {"company_name": "NueHealth",               "domain": "neuehealth.com",      "sector": "Digital Health"},
    "woebot":                   {"company_name": "Woebot",                  "domain": "woebothealth.com",    "sector": "Digital Health"},
    "belong-health":            {"company_name": "Belong Health",           "domain": "belonghealth.com",    "sector": "Digital Health"},
    "habitat-health":           {"company_name": "Habitat Health",          "domain": None,                  "sector": "Digital Health"},
    "liza-health":              {"company_name": "Liza Health",             "domain": None,                  "sector": "Digital Health"},
    "spiras-health":            {"company_name": "Spiras Health",           "domain": None,                  "sector": "Digital Health"},
    "vori-health":              {"company_name": "Vori Health",             "domain": "vorihealth.com",      "sector": "Digital Health"},
    "house-rx":                 {"company_name": "House Rx",                "domain": "houserx.com",         "sector": "Digital Health"},
    "nova-fertility":           {"company_name": "Nova Fertility",          "domain": None,                  "sector": "Digital Health"},
    "more-health":              {"company_name": "More Health",             "domain": None,                  "sector": "Digital Health"},
    "incarey":                  {"company_name": "InCareY",                 "domain": None,                  "sector": "Digital Health"},
    "in-house-health":          {"company_name": "In-House Health",         "domain": None,                  "sector": "Digital Health"},
    "carezone":                 {"company_name": "CareZone",                "domain": None,                  "sector": "Digital Health"},
    "ever-fi":                  {"company_name": "EverFi",                  "domain": "everfi.com",          "sector": "Digital Health"},
    "everfi":                   {"company_name": "EverFi",                  "domain": "everfi.com",          "sector": "Digital Health"},

    # Life Sciences
    "crispr":                   {"company_name": "CRISPR Therapeutics",     "domain": "crisprtx.com",        "sector": "Life Sciences"},
    "intermune":                {"company_name": "InterMune",               "domain": None,                  "sector": "Life Sciences"},
    "xaira-therapeutics":       {"company_name": "Xaira Therapeutics",      "domain": "xaira.com",           "sector": "Life Sciences"},
    "arcellx":                  {"company_name": "Arcellx",                 "domain": "arcellx.com",         "sector": "Life Sciences"},
    "loxo-oncology":            {"company_name": "Loxo Oncology",           "domain": None,                  "sector": "Life Sciences"},
    "formlabs":                 {"company_name": "Formlabs",                "domain": "formlabs.com",        "sector": "Enterprise"},
    "rapid-robotics":           {"company_name": "Rapid Robotics",          "domain": "rapidrobotics.com",   "sector": "Enterprise"},
    "built-robotics":           {"company_name": "Built Robotics",          "domain": "builtrobotics.com",   "sector": "Enterprise"},
    "vimaan-robotics":          {"company_name": "Vimaan",                  "domain": "vimaan.ai",           "sector": "Enterprise"},

    # Other well-known
    "upwork-formerly-odesk":    {"company_name": "Upwork",                  "domain": "upwork.com",          "sector": "Consumer"},
    "juniper-networks":         {"company_name": "Juniper Networks",        "domain": "juniper.net",         "sector": "Enterprise"},
    "semiconductor-manufacturing-international-corporation-smic": {"company_name": "SMIC", "domain": "smics.com", "sector": "Enterprise"},
    "splashtop":                {"company_name": "Splashtop",               "domain": "splashtop.com",       "sector": "Enterprise"},
    "uniphore":                 {"company_name": "Uniphore",                "domain": "uniphore.com",        "sector": "Enterprise"},
    "mashgin":                  {"company_name": "Mashgin",                 "domain": "mashgin.com",         "sector": "Enterprise"},
    "fabric8labs":              {"company_name": "Fabric8Labs",             "domain": "fabric8labs.com",     "sector": "Enterprise"},
    "pilot-ai":                 {"company_name": "Pilot AI",                "domain": None,                  "sector": "Enterprise"},
    "regression-games":         {"company_name": "Regression Games",        "domain": "regression.gg",       "sector": "Consumer"},
    "theorycraft-games":        {"company_name": "Theorycraft Games",       "domain": "theorycraftgames.com","sector": "Consumer"},
    "scratch-music-group":      {"company_name": "Scratch Music Group",     "domain": None,                  "sector": "Consumer"},
    "gen-g":                    {"company_name": "Gen.G",                   "domain": "geng.gg",             "sector": "Consumer"},
    "wheels-up":                {"company_name": "Wheels Up",               "domain": "wheelsup.com",        "sector": "Consumer"},
    "teal":                     {"company_name": "Teal",                    "domain": "tealhq.com",          "sector": "Consumer"},
    "gladly":                   {"company_name": "Gladly",                  "domain": "gladly.com",          "sector": "Enterprise"},
    "swirlds":                  {"company_name": "Swirlds",                 "domain": "swirlds.com",         "sector": "Enterprise"},
    "nginx":                    {"company_name": "NGINX",                   "domain": "nginx.com",           "sector": "Enterprise"},
    "rocket-chat":              {"company_name": "Rocket.Chat",             "domain": "rocket.chat",         "sector": "Enterprise"},
    "ai-squared":               {"company_name": "AI Squared",              "domain": "squared.ai",          "sector": "Enterprise"},
    "blue-cheetah":             {"company_name": "Blue Cheetah",            "domain": None,                  "sector": "Enterprise"},
    "konux":                    {"company_name": "KONUX",                   "domain": "konux.com",           "sector": "Enterprise"},
    "eko":                      {"company_name": "Eko",                     "domain": "ekohealth.com",       "sector": "Digital Health"},
    "senseonics":               {"company_name": "Senseonics",              "domain": "senseonics.com",      "sector": "Digital Health"},
    "eargo":                    {"company_name": "Eargo",                   "domain": "eargo.com",           "sector": "Digital Health"},
    "mojo-vision":              {"company_name": "Mojo Vision",             "domain": "mojo.vision",         "sector": "Enterprise"},
}

# All slugs from NEA sitemap
ALL_SLUGS = [
    "polyserve", "repros-therapeutics", "eroom", "ursa", "bestow", "goqii",
    "mashgin", "splashtop", "radiology-partners", "brenig", "kong",
    "grand-junction", "xaira-therapeutics", "ohai", "abcuro", "uniphore",
    "swiftype", "cardionomic", "teal", "dandelion", "tempest-therapeutics",
    "crispr", "patreon", "greenlight", "framebridge", "fiscalnote",
    "silicon-spice", "dermira", "technical-communities", "more-health",
    "vertiflex", "mindtickle", "vori-health", "mobius-management-systems",
    "origin-medsystems", "mediaocean", "conceptus", "sana", "motricity",
    "vuclip", "revelle-aesthetics", "subtext", "simsolid", "luxtera",
    "carezone", "lemonade-io", "some-spider-studios", "goji-solutions",
    "mayhem", "vixs-systems", "xsky", "narmi", "sonatype",
    "magenta-medical", "novast-holdings-limited", "aciex", "kira",
    "groupon", "ifonly", "coursera", "rapid-robotics", "stablix",
    "comprehensive-pharmacy-services", "branch", "nimble-collective",
    "echopass-corporation", "ulink", "habitat-health", "evenly", "nuelle",
    "euclid-analytics", "imara", "velocloud", "goop", "myfit", "niara",
    "chaos", "woebot", "parc-place", "rocket", "blue-ocean",
    "amerigroup-corporation", "bytedance-toutiao", "davita-nephrolife",
    "argon-networks", "flox", "regulus-therapeutics", "channeladvisor",
    "bethesda-research-labs", "zania", "uunet", "fugue",
    "upwork-formerly-odesk", "rocket-chat", "shape-therapeutics",
    "nefeli-networks", "sundeck", "simplerose", "wheels-up",
    "ra-pharmaceuticals", "beachmint", "globallogic", "pair",
    "sorriso-pharmaceuticals", "infogear-technology", "sitetracker",
    "pionyr-immunotherapeutics", "neoteris", "cohere-technologies",
    "clementia", "mimosa-networks", "vimaan-robotics", "envisia-therapeutics",
    "topia", "lizzyai", "vitae-pharmaceuticals", "sunesis", "savara",
    "semiconductor-manufacturing-international-corporation-smic",
    "exploramed", "centrexion-therapeutics", "quantum-bridge-communications",
    "everfi", "perplexity", "progress-software", "august", "sentry",
    "luminary", "curalate", "rf-monolithics", "missmalini", "edmodo",
    "zenas-biopharma", "monte-rosa-therapeutics", "ascend-communications",
    "decru", "nuvolo", "genmo", "enigma", "pixiebrix", "therachon",
    "sciencelogic", "care-com", "wheelhouse", "bitglass",
    "tracon-pharmaceuticals", "transvascular", "expanse", "neuehealth",
    "moonpay", "kindred", "nitra", "didi-chuxing", "regression-games",
    "mirna-therapeutics", "placemeter", "korro", "fabric8labs", "nrc",
    "canopy", "indio", "transcept-pharmaceuticals", "psyadon-pharmaceuticals",
    "robinhood", "mejuri", "logikcull", "galera-therapeutics", "evident-id",
    "veza", "gst-clinics", "surface-oncology", "novatium", "sierra-atlantic",
    "fisker-automotive", "safebase", "adaptimmune", "pinnacle-engines",
    "chg-healthcare", "upstart", "loxo-oncology", "snagfilms", "xcel",
    "engine-yard", "juniper-networks", "moximed", "pure-energies",
    "vantage-oncology", "comanche", "u-s-renal-care",
    "magma-design-automation", "immunex-corporation", "hos", "attest",
    "diatide", "vonage", "cuponation", "cleversafe", "applix",
    "pacific-light-hologram", "geltex-pharmaceuticals", "minimum",
    "amplyx-pharmaceuticals", "sentons", "clearmetal", "alexza-pharmaceuticals",
    "the-climate-corporation", "com21", "epizyme", "oanda", "cardurion",
    "lattice-engines", "ravel", "swirlds", "gridpoint", "koudai",
    "orexigen-therapeutics", "advanced-cardiovascular", "allay-therapeutics",
    "lxa", "blue-cheetah", "retrieve", "splicebio", "spine-wave", "catalog",
    "formlabs", "the-yes", "scratch-music-group", "eargo",
    "portauthority", "pcorder", "marker-therapeutics", "gynecare", "topera",
    "house-rx", "nova-fertility", "tigera", "exent-technologies", "salix",
    "geron", "granica", "foresight", "innerworkings", "iridex-corporation",
    "hearsay-social", "desire2learn", "pyxis", "sun-edison", "inhibitex",
    "senseonics", "turi", "data-domain", "lianlian", "gladly", "plusmo",
    "liza-health", "metabase", "gravel", "lumos-pharma", "mojo-vision",
    "ardelyx", "wallapop", "trading-dynamics", "sitime", "gen-g",
    "cascadian-therapeutics", "eko", "datarobot", "hdmessaging", "ledgy",
    "alfred", "databricks", "travelbank", "spreadtrum-communications",
    "gaikai", "pilot-ai", "picaboo", "moda-operandi", "sourcefire",
    "strongbridge-biopharma", "genies", "beehiiv", "appsheet",
    "alteon-websystems", "nextnav", "luminary-micro", "theorycraft-games",
    "welltok", "3ware", "zuoyebang", "eventup", "infinity-pharmaceuticals",
    "duolingo", "lexicon-pharmaceuticals", "landit", "aigen", "intermune",
    "neutral-tandem", "mission-critical-software", "together-ai", "cyence",
    "lithium-technologies", "cyras-systems", "elion", "wayport", "yubico",
    "nginx", "dots-technology-corp", "bridgepoint-medical", "konux",
    "pocket", "veriflow", "metronome", "built-robotics", "sci-solutions",
    "houzz", "matroid", "socialradar", "goodguide", "red-ridge-bio",
    "tempus", "iopipe", "endotex", "belong-health", "seattle-genetics",
    "advertising-com", "netsolve", "vistagen-therapeutics", "zoomdata",
    "loopt", "ai-squared", "second-front", "acrivon-therapeutics",
    "hyperfair", "snap", "arcellx", "incarey", "enzytech", "candy",
    "in-house-health", "hygeia-medical-services-group", "new-wave-foods",
    "spiration", "tamara-mellon", "ajax-vascular", "evernote", "firestorm",
    "code42", "spiras-health", "silicon-graphics", "e2o-communications",
    "raise", "genetic-therapy-inc", "51offer", "neural-magic",
    "intact-vascular", "patientkeeper", "union", "fineground-networks",
    "metromile", "fire1", "hemosense", "devices-for-vascular-intervention",
    "virtela", "scout-rfp", "phase-forward", "zhone-technologies", "nevro",
    "cvrx", "plaid", "goodleap", "robinhood", "narmi", "braintree", "ledge",
    "cloudflare", "databricks", "merge", "pulumi", "mongodb", "sentry",
    "kong", "sonatype", "sciencelogic", "datarobot", "tigera", "veza",
    "safebase", "metronome", "metabase", "granica", "sundeck", "pixiebrix",
    "zania", "second-front", "together-ai", "neural-magic", "genmo",
    "nuvolo", "enigma", "sitetracker", "mindtickle", "fiscalnote",
    "appsheet", "mediaocean", "channeladvisor", "hearsay-social",
    "code42", "expanse", "bitglass", "veriflow", "coursera", "perplexity",
    "fizz", "kindred", "patreon", "pair", "duolingo", "houzz", "evernote",
    "groupon", "snap", "goop", "wallapop", "beehiiv", "genies", "pocket",
    "loopt", "edmodo", "care-com", "framebridge", "moda-operandi",
    "tamara-mellon", "mejuri", "the-yes", "woebot", "beachmint", "curalate",
    "bytedance-toutiao", "didi-chuxing", "yubico", "travelbank", "moonpay",
    "upwork-formerly-odesk", "upstart", "metromile", "oanda", "vonage",
    "greenlight", "nitra", "raise", "ledgy", "tempus", "radiology-partners",
    "welltok", "neuehealth", "belong-health", "habitat-health", "liza-health",
    "spiras-health", "vori-health", "house-rx", "nova-fertility",
    "more-health", "incarey", "in-house-health", "carezone", "eko",
    "senseonics", "eargo", "mojo-vision", "xaira-therapeutics", "arcellx",
    "loxo-oncology", "formlabs", "rapid-robotics", "built-robotics",
    "vimaan-robotics", "splashtop", "uniphore", "mashgin", "fabric8labs",
    "regression-games", "theorycraft-games", "scratch-music-group", "gen-g",
    "wheels-up", "teal", "gladly", "swirlds", "nginx", "rocket-chat",
    "ai-squared", "blue-cheetah", "konux", "juniper-networks",
    "semiconductor-manufacturing-international-corporation-smic", "lizzyai",
    "aigen", "pilot-ai", "fizz",
]


def slug_to_name(slug: str) -> str:
    """Convert a URL slug to a human-readable company name."""
    # Replace hyphens with spaces and title case
    name = slug.replace("-", " ").title()
    # Fix common abbreviations
    for old, new in [
        ("Ai ", "AI "), (" Ai", " AI"), ("Ai$", "AI"),
        ("Io", "IO"), ("Rfp", "RFP"), ("Dna", "DNA"),
        ("Rna", "RNA"), ("51Offer", "51offer"),
    ]:
        name = re.sub(old, new, name)
    return name.strip()


def build_portfolio_records() -> list[dict]:
    """Build list of portfolio records from slugs + overrides."""
    seen_slugs = set()
    records = []

    for slug in ALL_SLUGS:
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        if slug in OVERRIDES:
            override = OVERRIDES[slug]
            record = {
                "slug": slug,
                "company_name": override["company_name"],
                "domain": override.get("domain"),
                "sector": override.get("sector"),
                "is_active": True,
            }
        else:
            record = {
                "slug": slug,
                "company_name": slug_to_name(slug),
                "domain": None,
                "sector": None,
                "is_active": True,
            }

        records.append(record)

    return records


def seed(dry_run: bool = False):
    """Seed nea_portfolio table."""
    records = build_portfolio_records()
    print(f"Built {len(records)} portfolio company records")

    if dry_run:
        print("\n[DRY RUN] First 20 records:")
        for r in records[:20]:
            print(f"  {r['slug']:<50} -> {r['company_name']}")
        print(f"\n[DRY RUN] Would upsert {len(records)} records to nea_portfolio")
        return

    from core.clients import get_supabase
    supabase = get_supabase()

    # M1b: enrich each record with canonical_entity_id (best-effort)
    try:
        from core.canonical_bridge import resolve_canonical_entity_id
        for r in records:
            cid = resolve_canonical_entity_id(domain=r.get("domain"), name=r.get("company_name"))
            if cid:
                r["canonical_entity_id"] = cid
    except Exception as _ex:
        print(f"  WARN canonical_bridge unavailable, seeding without canonical_entity_id: {_ex}")

    # Upsert in batches of 50
    batch_size = 50
    total_upserted = 0

    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        try:
            supabase.table("nea_portfolio").upsert(
                batch,
                on_conflict="slug"
            ).execute()
            total_upserted += len(batch)
            print(f"  Upserted batch {i // batch_size + 1}: {len(batch)} records")
        except Exception as e:
            print(f"  ERROR on batch {i // batch_size + 1}: {e}")

    print(f"\nDone. {total_upserted}/{len(records)} records upserted to nea_portfolio.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed NEA portfolio companies into Supabase")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to DB")
    args = parser.parse_args()

    seed(dry_run=args.dry_run)
