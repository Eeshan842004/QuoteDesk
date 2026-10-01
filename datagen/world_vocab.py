"""Vocabulary for the fictional world. Every brand and equipment model here is invented.

Industry-generic size codes (filter 16x25x1, belt A36/4L360, fuse class RK5) are descriptive standards,
not brands, and are allowed (see docs/DECISIONS.md D3).
"""

COMPANY = "Northbeam Industrial Supply"
COMPANY_DOMAIN = "northbeam-supply.example"

# ---- fictional equipment manufacturers: (brand, code) ----
EQUIPMENT_BRANDS = [
    ("Korvale", "KVL"),
    ("Quellmark", "QMK"),
    ("Talverd", "TVD"),
    ("Ostrine", "OSR"),
    ("Brisova", "BSV"),
    ("Vantrell", "VTR"),
    ("Heskel", "HSK"),
    ("Marrowind", "MRW"),
]

# equipment type code -> (plain name, capacities, compatible catalog categories)
EQUIPMENT_TYPES = {
    "AC": ("AC condenser", [24, 30, 36, 42, 48, 60], ["capacitors", "contactors", "motors"]),
    "HP": ("heat pump", [24, 30, 36, 48, 60], ["capacitors", "contactors", "motors", "thermostats"]),
    "FUR": ("gas furnace", [60, 80, 100, 120], ["motors", "filters", "thermostats", "capacitors"]),
    "AH": ("air handler", [24, 36, 48, 60], ["motors", "filters", "capacitors"]),
    "RTU": ("rooftop unit", [36, 48, 60, 90, 120], ["belts", "filters", "contactors", "capacitors", "motors", "fuses"]),
    "BLR": ("boiler", [80, 120, 150], ["valves", "fuses", "thermostats"]),
    "WIC": ("walk-in cooler", [6, 8, 10], ["motors", "contactors", "thermostats"]),
    "EXF": ("exhaust fan", [12, 16, 20, 24], ["belts", "motors", "fuses"]),
    "WH": ("water heater", [40, 50, 75], ["valves"]),
    "MS": ("mini-split", [9, 12, 18, 24], ["capacitors", "fuses"]),
}
# how many models of each type to create (sums to 40)
EQUIPMENT_TYPE_COUNTS = {"AC": 6, "HP": 5, "FUR": 6, "AH": 4, "RTU": 6, "BLR": 3, "WIC": 3, "EXF": 3, "WH": 2, "MS": 2}
EQUIPMENT_REVS = ["1", "2", "3", "A", "B", "C"]

# which motor / thermostat subtype fits which equipment type
MOTOR_FOR = {"AC": "condenser fan motor", "HP": "condenser fan motor", "RTU": "condenser fan motor",
             "WIC": "condenser fan motor", "FUR": "blower motor", "AH": "blower motor", "EXF": "exhaust fan motor"}
THERMOSTAT_FOR = {"HP": "heat pump", "FUR": "conventional", "BLR": "line voltage", "WIC": "walk-in controller"}
CAPACITOR_FOR = {"AC": "dual run", "HP": "dual run", "RTU": "dual run", "MS": "dual run",
                 "FUR": "single run", "AH": "single run"}

# ---- catalog categories ----
CATEGORIES = ["valves", "fittings", "contactors", "capacitors", "filters",
              "motors", "thermostats", "belts", "fuses", "sealants"]
CATEGORY_CODE = {"valves": "VLV", "fittings": "FTG", "contactors": "CON", "capacitors": "CAP", "filters": "FLT",
                 "motors": "MTR", "thermostats": "TST", "belts": "BLT", "fuses": "FUS", "sealants": "SLT"}
# how customers casually name a category (used for compatibility / previous-order / vague phrasing)
CATEGORY_NOUNS = {
    "valves": ["valve", "valves"], "fittings": ["fittings"], "contactors": ["contactor"],
    "capacitors": ["cap", "capacitor", "run cap"], "filters": ["filters", "air filters"],
    "motors": ["motor", "fan motor"], "thermostats": ["thermostat", "t-stat", "stat"],
    "belts": ["belt", "v-belt"], "fuses": ["fuses"], "sealants": ["sealant", "thread sealant"],
}

SIZES = ['1/2"', '3/4"', '1"', '1-1/4"', '1-1/2"', '2"']
SIZE_WORDS = {'1/2"': "half inch", '3/4"': "three-quarter inch", '1"': "one inch",
              '1-1/4"': "inch and a quarter", '1-1/2"': "inch and a half", '2"': "two inch"}

VALVE_TYPES = ["ball", "gate", "check"]
VALVE_ABBR = {"ball": "BV", "gate": "GV", "check": "CV"}
VALVE_MATERIALS = ["brass", "bronze", "stainless", "PVC"]
VALVE_CONNECTIONS = ["NPT", "sweat", "PEX", "press"]

FITTING_TYPES = ["90 elbow", "45 elbow", "tee", "coupling", "union", "reducer", "cap", "male adapter"]
FITTING_SHORT = {"90 elbow": "90", "45 elbow": "45", "tee": "tee", "coupling": "coupling", "union": "union",
                 "reducer": "reducer", "cap": "cap", "male adapter": "MA"}
FITTING_MATERIALS = ["copper", "PVC sch40", "black iron", "galvanized", "CPVC"]
FITTING_MAT_SHORT = {"copper": "cu", "PVC sch40": "pvc", "black iron": "BI", "galvanized": "galv", "CPVC": "cpvc"}

CONTACTOR_POLES = [1, 2, 3]
CONTACTOR_AMPS = [30, 40, 50, 60]
CONTACTOR_COILS = ["24V", "120V", "208/240V"]

CAP_DUAL = ["35/5", "40/5", "45/5", "50/5", "55/5", "60/5", "70/5", "80/5"]
CAP_RUN = ["5", "7.5", "10", "15", "20", "25", "30", "35"]
CAP_START = ["88-106", "108-130", "145-175", "189-227"]
CAP_VOLTS = ["370V", "440V"]

FILTER_SIZES = ["16x20x1", "16x25x1", "20x20x1", "20x25x1", "14x20x1", "12x24x1",
                "16x25x2", "20x25x2", "24x24x2", "16x25x4", "20x25x4", "20x20x4"]
FILTER_MERV = [8, 11, 13]

MOTOR_TYPES = {"condenser fan motor": 8, "blower motor": 8, "exhaust fan motor": 4}
MOTOR_HP = ["1/6", "1/5", "1/4", "1/3", "1/2", "3/4"]
MOTOR_RPM = [825, 1075, 1625]
MOTOR_VOLTS = ["115V", "208-230V"]

THERMOSTAT_TYPES = {
    "conventional": ["non-programmable 1H/1C", "programmable 1H/1C", "programmable 2H/2C", "Wi-Fi 2H/2C"],
    "heat pump": ["heat pump programmable 2H/1C", "heat pump Wi-Fi 3H/2C", "heat pump non-programmable 2H/1C"],
    "line voltage": ["line voltage 120V", "line voltage 240V"],
    "walk-in controller": ["walk-in cooler temperature controller", "walk-in freezer temperature controller"],
}

BELT_SECTIONS = {"A": list(range(26, 69, 2)), "B": list(range(35, 76, 2)),
                 "4L": list(range(340, 601, 20)), "5L": list(range(400, 701, 20))}

FUSE_CLASSES = ["RK5", "CC", "J", "K5"]
FUSE_AMPS = [15, 20, 25, 30, 40, 60]
FUSE_VOLTS = ["250V", "600V"]
FUSE_SPEED = ["time-delay", "fast-acting"]

SEALANTS = [
    # (type, size, unit, base price)
    ("PTFE thread tape", '1/2" x 520"', "roll", 1.9),
    ("PTFE thread tape", '3/4" x 520"', "roll", 2.6),
    ("PTFE thread tape", '1" x 520"', "roll", 3.4),
    ("gas-rated PTFE tape", '1/2" x 260"', "roll", 3.1),
    ("pipe thread sealant", "1 pt can", "each", 11.5),
    ("pipe thread sealant", "4 oz tube", "tube", 6.4),
    ("pipe dope", "8 oz can", "each", 7.9),
    ("clear silicone sealant", "10.1 oz cartridge", "tube", 7.2),
    ("white silicone sealant", "10.1 oz cartridge", "tube", 7.2),
    ("high-temp silicone", "10.1 oz cartridge", "tube", 12.8),
    ("duct mastic", "1 gal pail", "each", 24.0),
    ("duct mastic", "2 gal pail", "each", 41.0),
    ("foil duct tape", '2" x 50 yd', "roll", 13.5),
    ("foil duct tape", '3" x 50 yd', "roll", 18.9),
    ("fire-stop sealant", "10.1 oz cartridge", "tube", 16.5),
    ("plumber's putty", "14 oz tub", "each", 5.3),
    ("anaerobic thread sealant", "50 ml tube", "tube", 14.2),
    ("refrigerant thread sealant", "1.7 oz tube", "tube", 19.6),
    ("butyl sealant tape", '1" x 30 ft', "roll", 9.8),
    ("acrylic caulk", "10.1 oz cartridge", "tube", 4.1),
]
SEALANT_SHORT = {"PTFE thread tape": "PTFE tape", "gas-rated PTFE tape": "yellow gas tape",
                 "pipe thread sealant": "thread sealant", "pipe dope": "pipe dope",
                 "clear silicone sealant": "clear silicone", "white silicone sealant": "white silicone",
                 "high-temp silicone": "hi temp silicone", "duct mastic": "mastic",
                 "foil duct tape": "foil tape", "fire-stop sealant": "firestop",
                 "plumber's putty": "plumbers putty", "anaerobic thread sealant": "anaerobic sealant",
                 "refrigerant thread sealant": "refrigerant sealant", "butyl sealant tape": "butyl tape",
                 "acrylic caulk": "caulk"}

# ---- customers (fictional; domains use the reserved .example TLD) ----
CUSTOMER_COMPANIES = [
    ("Pinecrest Mechanical", "pinecrest-mech"), ("Harbor Point HVAC", "harborpoint-hvac"),
    ("Redfield Plumbing & Heating", "redfield-ph"), ("Ironbridge Facilities", "ironbridge-fac"),
    ("Summit Ridge Property Mgmt", "summitridge-pm"), ("Blue Heron Refrigeration", "blueheron-refrig"),
    ("Coldwater Service Co", "coldwater-svc"), ("Maple Row Contractors", "maplerow"),
    ("Granite Peak Electric", "granitepeak-elec"), ("Tidewater Building Services", "tidewater-bldg"),
    ("Northgate Maintenance", "northgate-maint"), ("Cedar Hollow HVAC", "cedarhollow"),
    ("Lakeshore Comfort Systems", "lakeshore-comfort"), ("Silverline Mechanical", "silverline-mech"),
    ("Oakmont Facilities Group", "oakmont-fg"), ("Riverbend Plumbing", "riverbend-plumb"),
    ("Brightfield Apartments", "brightfield-apts"), ("Westvale Schools Maintenance", "westvale-schools"),
    ("Copperleaf Hotels Engineering", "copperleaf-hotels"), ("Stonebrook Medical Facilities", "stonebrook-med"),
]
FIRST_NAMES = ["Dana", "Marcus", "Priya", "Tomas", "Jen", "Luis", "Keisha", "Brandon", "Mei", "Oscar",
               "Rachel", "Dwayne", "Aisha", "Greg", "Nora", "Victor", "Hannah", "Rafael", "Tina", "Sam",
               "Carla", "Devon", "Ivan", "Leah", "Andre", "Beth", "Chris", "Farah", "Jake", "Monique"]
LAST_NAMES = ["Okafor", "Brennan", "Castillo", "Nguyen", "Halvorsen", "Pruitt", "Delgado", "Kowalski",
              "Ferreira", "Lindqvist", "Mbeki", "Sato", "Whitaker", "Romero", "Adebayo", "Gallagher",
              "Petrov", "Oyelaran", "Marchetti", "Szabo", "Quinlan", "Dubois", "Haddad", "Iverson"]
TITLES = ["Service Manager", "Purchasing", "Facilities Tech", "Owner", "Lead Technician",
          "Maintenance Supervisor", "Project Manager", "Office Manager", "Chief Engineer", "Dispatcher"]
TIER_DISCOUNT = {"A": 0.15, "B": 0.10, "C": 0.05}
VOLUME_BREAKS = [{"min_qty": 10, "extra_discount": 0.03}, {"min_qty": 50, "extra_discount": 0.07}]

# ---- real brand denylist (tests + datagen filter). Never appear in our world or emails. ----
REAL_BRANDS_STRICT = [
    "Trane", "Lennox", "Rheem", "Ruud", "Daikin", "Mitsubishi", "Fujitsu", "Bryant", "Amana",
    "Tempstar", "American Standard", "Honeywell", "Resideo", "Emerson", "Copeland", "White-Rodgers",
    "Ecobee", "Johnson Controls", "Danfoss", "Genteq", "Fasco", "A.O. Smith", "Bradford White",
    "Nibco", "Sharkbite", "SharkBite", "Uponor", "Viega", "Oatey", "Rectorseal", "Teflon", "Loctite",
    "Permatex", "Square D", "Schneider Electric", "Siemens", "Bussmann", "Littelfuse", "Mersen",
    "Ferraz", "Grainger", "Ferguson", "Johnstone", "Supco", "Aprilaire", "Filtrete", "Nordic Pure",
    "Camfil", "Goodyear", "Grundfos", "Bell & Gossett", "Weil-McLain", "Navien", "Rinnai", "Noritz",
    "Lochinvar", "Reznor", "Greenheck", "Baldor", "Hubbell", "Leviton", "Cutler-Hammer",
    "Allen-Bradley", "Romex", "ProPress", "Frigidaire", "Whirlpool", "Kohler", "Milwaukee Tool",
    "Carrier Corporation", "Goodman Manufacturing", "York International", "Heil", "Payne Heating",
]
# short/common-word brands: checked only in the world files (case-sensitive), not in free email text
REAL_BRANDS_AMBIGUOUS = ["Carrier", "Goodman", "York", "Nest", "GE", "LG", "ABB", "Eaton", "Watts",
                         "Mueller", "Apollo", "Titan", "Packard", "Mars", "Gates", "Browning", "Dayton",
                         "Taco", "Armstrong", "Burnham", "Modine", "WEG", "Marathon", "Leeson", "Century",
                         "Regal", "Samsung", "Flanders", "AAF", "Fenner", "3M", "Eaton"]
