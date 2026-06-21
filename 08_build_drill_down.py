"""
build_drill_down.py
===================
Reads clubs.csv and club_details.csv and produces a self-contained
drill_down.html — a D3.js interactive network with four levels:

    Confederation → Country → League → Club

Click a node to drill into its children (parent disappears).
Click the background or the breadcrumb trail to navigate back up.
Node size = deduplicated player count at that level.

No server or extra installs needed — just open drill_down.html in a browser.
"""
import csv
import datetime
import json
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from league_dedup import build_canonical_map, canonical_league

MIN_PLAYERS = 1
OUTPUT      = "drill_down.html"
# Also written as index.html so GitHub Pages serves it at the site root (no copy step).
OUTPUTS     = ("drill_down.html", "index.html")
ATLAS_URL   = "https://cdn.jsdelivr.net/npm/world-atlas@2/countries-50m.json"

# Tableau-10 palette. AFC (Asia) and OFC (Oceania) are swapped per request:
# Asia is now yellow, Oceania is now green.
CONFEDERATION_COLOURS = {
    # Okabe-Ito colour-blind-safe qualitative palette (distinguishable under
    # protanopia / deuteranopia / tritanopia). Avoids the old red/green pairing.
    "UEFA":      "#0072b2",   # Europe     — blue
    "AFC":       "#f0e442",   # Asia       — yellow
    "CAF":       "#009e73",   # Africa     — bluish green
    "OFC":       "#56b4e9",   # Oceania    — sky blue
    "CONMEBOL":  "#e69f00",   # S. America — orange
    "CONCACAF":  "#d55e00",   # N/C America — vermillion
    "Unknown":   "#cc79a7",   # reddish purple
}

# Approximate geographic centres [lon, lat] for each confederation
# Hand-set [lon, lat] anchor for each confederation's map label (projected to
# screen and drawn at that point). Tuned to sit over the bloc in clear space.
CONFEDERATION_COORDS = {
    "UEFA":     [15,   52],
    "CAF":      [20,    3],
    "AFC":      [95,   30],
    "CONCACAF": [-98,  30],   # over the Gulf / N. America rather than cramped Central America
    "CONMEBOL": [-60, -15],
    "OFC":      [164, -30],   # Tasman Sea (W of NZ), kept off the right map edge
    "Unknown":  [0,    0],
}

# Approximate country centroids [lon, lat]
COUNTRY_COORDS = {
    # UEFA
    "Albania":[20,41],"Andorra":[1,42],"Armenia":[45,40],
    "Austria":[14,47],"Azerbaijan":[48,40],"Belarus":[28,54],
    "Belgium":[4,51],"Bosnia and Herzegovina":[18,44],"Bosnia & Herzegovina":[18,44],
    "Bulgaria":[25,43],"Croatia":[15,45],"Cyprus":[33,35],
    "Czech Republic":[16,50],"Czechia":[16,50],
    "Denmark":[10,56],"England":[-2,53],"Estonia":[25,59],
    "Faroe Islands":[-7,62],"Finland":[26,64],"France":[2,46],
    "Georgia":[43,42],"Germany":[10,51],"Gibraltar":[-5,36],
    "Greece":[22,39],"Hungary":[19,47],"Iceland":[-19,65],
    "Ireland":[-8,53],"Republic of Ireland":[-8,53],
    "Israel":[35,31],"Italy":[12,43],
    "Kazakhstan":[67,48],"Kosovo":[21,43],
    "Latvia":[25,57],"Liechtenstein":[10,47],"Lithuania":[24,56],
    "Luxembourg":[6,50],"Malta":[14,36],"Moldova":[28,47],
    "Montenegro":[19,43],"Netherlands":[5,52],
    "North Macedonia":[22,42],"Republic of North Macedonia":[22,42],
    "Northern Ireland":[-7,55],"Norway":[9,61],
    "Poland":[20,52],"Portugal":[-8,39],"Romania":[25,46],
    "Russia":[60,62],"San Marino":[12,44],"Scotland":[-4,57],
    "Serbia":[21,44],"Slovakia":[19,49],"Slovenia":[15,46],
    "Spain":[-4,40],"Sweden":[15,62],"Switzerland":[8,47],
    "Turkey":[35,39],"Ukraine":[31,49],"Wales":[-4,52],
    # CONMEBOL
    "Argentina":[-64,-34],"Bolivia":[-65,-17],"Brazil":[-52,-14],
    "Chile":[-71,-36],"Colombia":[-74,5],"Ecuador":[-78,-2],
    "Paraguay":[-58,-23],"Peru":[-75,-9],"Uruguay":[-56,-33],
    "Venezuela":[-67,8],
    # CONCACAF
    "Canada":[-97,56],"Mexico":[-103,24],"United States":[-99,38],
    "Costa Rica":[-84,10],"Cuba":[-80,22],"Haiti":[-72,19],
    "Honduras":[-87,15],"Jamaica":[-77,18],"Panama":[-80,9],
    "Trinidad and Tobago":[-61,11],"Guatemala":[-90,15],
    "El Salvador":[-89,14],"Nicaragua":[-85,13],"Barbados":[-60,13],
    "Belize":[-89,17],"Dominican Republic":[-70,19],"Grenada":[-62,12],
    "Guyana":[-59,5],"Suriname":[-56,4],"Anguilla":[-63,18],
    "Antigua and Barbuda":[-62,17],"Aruba":[-70,12],"Bahamas":[-77,24],
    "Bermuda":[-65,32],"Cayman Islands":[-81,19],
    "Curaçao":[-69,12],"Curacao":[-69,12],"Dominica":[-61,15],
    "French Guiana":[-53,4],"Guadeloupe":[-62,16],"Martinique":[-61,15],
    "Montserrat":[-62,17],"Puerto Rico":[-67,18],
    "Saint Kitts and Nevis":[-63,17],"Saint Lucia":[-61,14],
    "Saint Vincent and the Grenadines":[-61,13],"Sint Maarten":[-63,18],
    "US Virgin Islands":[-65,18],"Bonaire":[-68,12],
    "Turks and Caicos Islands":[-72,22],"British Virgin Islands":[-65,18],
    # CAF
    "Algeria":[2,28],"Angola":[18,-12],"Benin":[2,9],
    "Botswana":[25,-22],"Burkina Faso":[-2,12],"Burundi":[30,-3],
    "Cameroon":[12,6],"Cape Verde":[-24,15],
    "Central African Republic":[21,7],"Chad":[19,15],
    "Comoros":[43,-12],"Congo":[16,-1],
    "DR Congo":[24,-4],"Democratic Republic of the Congo":[24,-4],
    "Democratic Republic of Congo":[24,-4],"Republic of the Congo":[16,-1],
    "Djibouti":[43,12],"Egypt":[31,27],"Equatorial Guinea":[10,2],
    "Eritrea":[40,15],"Eswatini":[32,-27],"Swaziland":[32,-27],
    "Ethiopia":[40,9],"Gabon":[12,-1],"Gambia":[-15,13],
    "Ghana":[-1,8],"Guinea":[-11,11],"Guinea-Bissau":[-15,12],
    "Ivory Coast":[-6,8],"Côte d'Ivoire":[-6,8],
    "Kenya":[38,0],"Lesotho":[28,-30],"Liberia":[-9,6],"Libya":[17,26],
    "Madagascar":[47,-19],"Malawi":[34,-13],"Mali":[-2,18],
    "Mauritania":[-12,20],"Mauritius":[58,-20],"Morocco":[-7,32],
    "Mozambique":[35,-18],"Namibia":[18,-22],"Niger":[8,18],
    "Nigeria":[9,9],"Rwanda":[30,-2],"São Tomé and Príncipe":[7,0],
    "Sao Tome and Principe":[7,0],"Senegal":[-14,14],"Seychelles":[56,-5],
    "Sierra Leone":[-12,9],"Somalia":[46,6],"South Africa":[25,-29],
    "South Sudan":[31,7],"Sudan":[30,16],"Tanzania":[35,-6],
    "United Republic of Tanzania":[35,-6],"Togo":[1,9],
    "Tunisia":[9,34],"Uganda":[32,1],"Zambia":[28,-13],"Zimbabwe":[30,-19],
    # AFC
    "Afghanistan":[68,34],"Australia":[134,-25],"Bahrain":[51,26],
    "Bangladesh":[90,24],"Bhutan":[91,28],"Brunei":[115,5],
    "Cambodia":[105,13],"China":[104,36],"China PR":[104,36],
    "Chinese Taipei":[121,24],"Guam":[145,13],"Hong Kong":[114,22],
    "India":[78,23],"Indonesia":[114,-1],"Iran":[54,32],
    "Iraq":[44,33],"Japan":[138,36],"Jordan":[36,31],
    "Kuwait":[48,29],"Kyrgyzstan":[75,41],"Laos":[103,18],
    "Lebanon":[36,34],"Macau":[114,22],"Malaysia":[110,4],
    "Maldives":[73,3],"Mongolia":[104,47],"Myanmar":[96,19],
    "Nepal":[84,28],"North Korea":[128,40],"Korea DPR":[128,40],
    "Oman":[58,22],"Pakistan":[69,30],"Palestine":[35,32],
    "Philippines":[123,13],"Qatar":[51,25],"Saudi Arabia":[45,24],
    "Singapore":[104,1],"South Korea":[128,37],"Korea Republic":[128,37],
    "Republic of Korea":[128,37],"Sri Lanka":[81,8],"Syria":[39,35],
    "Tajikistan":[71,39],"Thailand":[101,16],"Timor-Leste":[126,-9],
    "East Timor":[126,-9],"Turkmenistan":[58,40],
    "UAE":[54,24],"United Arab Emirates":[54,24],
    "Uzbekistan":[64,41],"Vietnam":[108,14],"Yemen":[48,16],
    # OFC
    "American Samoa":[-171,-14],"Cook Islands":[-160,-21],"Fiji":[178,-18],
    "New Caledonia":[166,-21],"New Zealand":[173,-41],"Papua New Guinea":[144,-6],
    "Samoa":[-172,-14],"Solomon Islands":[160,-10],"Tonga":[-175,-21],
    "Tuvalu":[177,-9],"Vanuatu":[167,-15],
}

CONFEDERATION_MAP = {
    # UEFA
    "Albania":"UEFA","Andorra":"UEFA","Armenia":"UEFA",
    "Austria":"UEFA","Azerbaijan":"UEFA","Belarus":"UEFA",
    "Belgium":"UEFA","Bosnia and Herzegovina":"UEFA","Bosnia & Herzegovina":"UEFA",
    "Bulgaria":"UEFA","Croatia":"UEFA","Cyprus":"UEFA",
    "Czech Republic":"UEFA","Czechia":"UEFA",
    "Denmark":"UEFA","England":"UEFA","Estonia":"UEFA",
    "Faroe Islands":"UEFA","Finland":"UEFA","France":"UEFA",
    "Georgia":"UEFA","Germany":"UEFA","Gibraltar":"UEFA",
    "Greece":"UEFA","Hungary":"UEFA","Iceland":"UEFA",
    "Ireland":"UEFA","Republic of Ireland":"UEFA",
    "Israel":"UEFA","Italy":"UEFA",
    "Kazakhstan":"UEFA","Kosovo":"UEFA",
    "Latvia":"UEFA","Liechtenstein":"UEFA","Lithuania":"UEFA",
    "Luxembourg":"UEFA","Malta":"UEFA","Moldova":"UEFA",
    "Montenegro":"UEFA","Netherlands":"UEFA",
    "North Macedonia":"UEFA","Republic of North Macedonia":"UEFA",
    "Northern Ireland":"UEFA","Norway":"UEFA",
    "Poland":"UEFA","Portugal":"UEFA","Romania":"UEFA","Russia":"UEFA",
    "San Marino":"UEFA","Scotland":"UEFA","Serbia":"UEFA",
    "Slovakia":"UEFA","Slovenia":"UEFA","Spain":"UEFA","Sweden":"UEFA",
    "Switzerland":"UEFA","Turkey":"UEFA","Ukraine":"UEFA","Wales":"UEFA",
    # CONMEBOL
    "Argentina":"CONMEBOL","Bolivia":"CONMEBOL","Brazil":"CONMEBOL",
    "Chile":"CONMEBOL","Colombia":"CONMEBOL","Ecuador":"CONMEBOL",
    "Paraguay":"CONMEBOL","Peru":"CONMEBOL","Uruguay":"CONMEBOL",
    "Venezuela":"CONMEBOL",
    # CONCACAF
    "Anguilla":"CONCACAF","Antigua and Barbuda":"CONCACAF",
    "Aruba":"CONCACAF","Bahamas":"CONCACAF","Barbados":"CONCACAF",
    "Belize":"CONCACAF","Bermuda":"CONCACAF","Bonaire":"CONCACAF",
    "British Virgin Islands":"CONCACAF","Canada":"CONCACAF",
    "Cayman Islands":"CONCACAF","Costa Rica":"CONCACAF","Cuba":"CONCACAF",
    "Curaçao":"CONCACAF","Curacao":"CONCACAF",
    "Dominica":"CONCACAF","Dominican Republic":"CONCACAF",
    "El Salvador":"CONCACAF","French Guiana":"CONCACAF",
    "Grenada":"CONCACAF","Guadeloupe":"CONCACAF","Guatemala":"CONCACAF",
    "Guyana":"CONCACAF","Haiti":"CONCACAF","Honduras":"CONCACAF",
    "Jamaica":"CONCACAF","Martinique":"CONCACAF","Mexico":"CONCACAF",
    "Montserrat":"CONCACAF","Nicaragua":"CONCACAF","Panama":"CONCACAF",
    "Puerto Rico":"CONCACAF","Saint Kitts and Nevis":"CONCACAF",
    "Saint Lucia":"CONCACAF","Saint Vincent and the Grenadines":"CONCACAF",
    "Sint Maarten":"CONCACAF","Suriname":"CONCACAF",
    "Trinidad and Tobago":"CONCACAF","United States":"CONCACAF",
    "US Virgin Islands":"CONCACAF",
    # CAF
    "Algeria":"CAF","Angola":"CAF","Benin":"CAF","Botswana":"CAF",
    "Burkina Faso":"CAF","Burundi":"CAF","Cameroon":"CAF","Cape Verde":"CAF",
    "Central African Republic":"CAF","Chad":"CAF","Comoros":"CAF",
    "Congo":"CAF","DR Congo":"CAF",
    "Democratic Republic of the Congo":"CAF","Democratic Republic of Congo":"CAF",
    "Republic of the Congo":"CAF",
    "Djibouti":"CAF","Egypt":"CAF","Equatorial Guinea":"CAF",
    "Eritrea":"CAF","Eswatini":"CAF","Swaziland":"CAF",
    "Ethiopia":"CAF","Gabon":"CAF","Gambia":"CAF","Ghana":"CAF",
    "Guinea":"CAF","Guinea-Bissau":"CAF",
    "Ivory Coast":"CAF","Côte d'Ivoire":"CAF",
    "Kenya":"CAF","Lesotho":"CAF","Liberia":"CAF","Libya":"CAF",
    "Madagascar":"CAF","Malawi":"CAF","Mali":"CAF",
    "Mauritania":"CAF","Mauritius":"CAF","Morocco":"CAF",
    "Mozambique":"CAF","Namibia":"CAF","Niger":"CAF","Nigeria":"CAF",
    "Rwanda":"CAF","São Tomé and Príncipe":"CAF","Sao Tome and Principe":"CAF",
    "Senegal":"CAF","Seychelles":"CAF","Sierra Leone":"CAF",
    "Somalia":"CAF","South Africa":"CAF","South Sudan":"CAF","Sudan":"CAF",
    "Tanzania":"CAF","United Republic of Tanzania":"CAF",
    "Togo":"CAF","Tunisia":"CAF","Uganda":"CAF","Zambia":"CAF","Zimbabwe":"CAF",
    # AFC
    "Afghanistan":"AFC","Australia":"AFC","Bahrain":"AFC",
    "Bangladesh":"AFC","Bhutan":"AFC","Brunei":"AFC","Cambodia":"AFC",
    "China":"AFC","China PR":"AFC","Chinese Taipei":"AFC",
    "Guam":"AFC","Hong Kong":"AFC","India":"AFC","Indonesia":"AFC",
    "Iran":"AFC","Iraq":"AFC","Japan":"AFC","Jordan":"AFC",
    "Kuwait":"AFC","Kyrgyzstan":"AFC","Laos":"AFC","Lebanon":"AFC",
    "Macau":"AFC","Malaysia":"AFC","Maldives":"AFC","Mongolia":"AFC",
    "Myanmar":"AFC","Nepal":"AFC",
    "North Korea":"AFC","Korea DPR":"AFC",
    "Oman":"AFC","Pakistan":"AFC","Palestine":"AFC","Philippines":"AFC",
    "Qatar":"AFC","Saudi Arabia":"AFC","Singapore":"AFC",
    "South Korea":"AFC","Korea Republic":"AFC","Republic of Korea":"AFC",
    "Sri Lanka":"AFC","Syria":"AFC","Tajikistan":"AFC","Thailand":"AFC",
    "Timor-Leste":"AFC","East Timor":"AFC",
    "Turkmenistan":"AFC",
    "UAE":"AFC","United Arab Emirates":"AFC",
    "Uzbekistan":"AFC","Vietnam":"AFC","Yemen":"AFC",
    # OFC
    "American Samoa":"OFC","Cook Islands":"OFC","Fiji":"OFC",
    "New Caledonia":"OFC","New Zealand":"OFC","Papua New Guinea":"OFC",
    "Samoa":"OFC","Solomon Islands":"OFC","Tonga":"OFC",
    "Tuvalu":"OFC","Vanuatu":"OFC",
}


COUNTRY_ISO_MAP = {
    # UEFA
    "Albania":8,"Andorra":20,"Armenia":51,"Austria":40,"Azerbaijan":31,
    "Belarus":112,"Belgium":56,"Bosnia and Herzegovina":70,"Bosnia & Herzegovina":70,
    "Bulgaria":100,"Croatia":191,"Cyprus":196,
    "Czech Republic":203,"Czechia":203,
    "Denmark":208,"England":"gb-eng","Scotland":"gb-sct","Wales":"gb-wls","Northern Ireland":"gb-nir",
    "Estonia":233,"Finland":246,"France":250,"Georgia":268,"Germany":276,
    "Greece":300,"Hungary":348,"Iceland":352,
    "Ireland":372,"Republic of Ireland":372,
    "Israel":376,"Italy":380,"Kazakhstan":398,"Kosovo":None,
    "Latvia":428,"Liechtenstein":438,"Lithuania":440,"Luxembourg":442,
    "Malta":470,"Moldova":498,"Montenegro":499,"Netherlands":528,
    "North Macedonia":807,"Republic of North Macedonia":807,
    "Norway":578,"Poland":616,"Portugal":620,"Romania":642,
    "Russia":643,"San Marino":674,"Serbia":688,"Slovakia":703,
    "Slovenia":705,"Spain":724,"Sweden":752,"Switzerland":756,
    "Turkey":792,"Ukraine":804,"Faroe Islands":234,
    # CONMEBOL
    "Argentina":32,"Bolivia":68,"Brazil":76,"Chile":152,"Colombia":170,
    "Ecuador":218,"Paraguay":600,"Peru":604,"Uruguay":858,"Venezuela":862,
    # CONCACAF
    "Canada":124,"Costa Rica":188,"Cuba":192,"Dominican Republic":214,
    "El Salvador":222,"Guatemala":320,"Haiti":332,"Honduras":340,
    "Jamaica":388,"Mexico":484,"Nicaragua":558,"Panama":591,
    "Trinidad and Tobago":780,"United States":840,"USA":840,
    "Curaçao":531,"Curacao":531,"Belize":84,
    # CAF
    "Algeria":12,"Angola":24,"Benin":204,"Botswana":72,"Burkina Faso":854,
    "Cameroon":120,"Cape Verde":132,"Central African Republic":140,"Chad":148,
    "Comoros":174,"Congo":178,"Republic of the Congo":178,
    "DR Congo":180,"Democratic Republic of the Congo":180,"DRC":180,
    "Djibouti":262,"Egypt":818,"Equatorial Guinea":226,"Eritrea":232,
    "Eswatini":748,"Swaziland":748,"Ethiopia":231,"Gabon":266,"Gambia":270,
    "Ghana":288,"Guinea":324,"Guinea-Bissau":624,
    "Ivory Coast":384,"Côte d'Ivoire":384,
    "Kenya":404,"Lesotho":426,"Liberia":430,"Libya":434,"Madagascar":450,
    "Malawi":454,"Mali":466,"Mauritania":478,"Morocco":504,"Mozambique":508,
    "Namibia":516,"Niger":562,"Nigeria":566,"Rwanda":646,"Senegal":686,
    "Sierra Leone":694,"Somalia":706,"South Africa":710,
    "South Sudan":728,"Sudan":729,"Tanzania":834,
    "United Republic of Tanzania":834,"Togo":768,"Tunisia":788,
    "Uganda":800,"Zambia":894,"Zimbabwe":716,
    # AFC
    "Afghanistan":4,"Australia":36,"Bahrain":48,"Bangladesh":50,
    "Cambodia":116,"China":156,"China PR":156,"Chinese Taipei":158,
    "India":356,"Indonesia":360,"Iran":364,"Iraq":368,"Japan":392,
    "Jordan":400,"Kuwait":414,"Kyrgyzstan":417,"Lebanon":422,
    "Malaysia":458,"Mongolia":496,"Myanmar":104,"Nepal":524,
    "North Korea":408,"Korea DPR":408,"Oman":512,"Pakistan":586,
    "Palestine":275,"Philippines":608,"Qatar":634,"Saudi Arabia":682,
    "Singapore":702,"South Korea":410,"Korea Republic":410,
    "Republic of Korea":410,"Sri Lanka":144,"Syria":760,"Tajikistan":762,
    "Thailand":764,"Turkmenistan":795,"UAE":784,"United Arab Emirates":784,
    "Uzbekistan":860,"Vietnam":704,"Yemen":887,
    # OFC
    "Fiji":242,"New Zealand":554,"Papua New Guinea":598,
    "Samoa":882,"Solomon Islands":90,"Tonga":776,"Vanuatu":548,
}

# ISO 3166-1 numeric -> alpha-2 (lower-case), for the codes used above. Used to
# build flag-image URLs (flagcdn.com/<code>.png). UK home nations already carry
# their flagcdn subdivision codes ("gb-eng" etc.) directly in COUNTRY_ISO_MAP.
NUMERIC_TO_ALPHA2 = {
    8:"al",20:"ad",51:"am",40:"at",31:"az",112:"by",56:"be",70:"ba",100:"bg",
    191:"hr",196:"cy",203:"cz",208:"dk",233:"ee",246:"fi",250:"fr",268:"ge",
    276:"de",300:"gr",348:"hu",352:"is",372:"ie",376:"il",380:"it",398:"kz",
    428:"lv",438:"li",440:"lt",442:"lu",470:"mt",498:"md",499:"me",528:"nl",
    807:"mk",578:"no",616:"pl",620:"pt",642:"ro",643:"ru",674:"sm",688:"rs",
    703:"sk",705:"si",724:"es",752:"se",756:"ch",792:"tr",804:"ua",234:"fo",
    32:"ar",68:"bo",76:"br",152:"cl",170:"co",218:"ec",600:"py",604:"pe",
    858:"uy",862:"ve",124:"ca",188:"cr",192:"cu",214:"do",222:"sv",320:"gt",
    332:"ht",340:"hn",388:"jm",484:"mx",558:"ni",591:"pa",780:"tt",840:"us",
    531:"cw",84:"bz",12:"dz",24:"ao",204:"bj",72:"bw",854:"bf",120:"cm",
    132:"cv",140:"cf",148:"td",174:"km",178:"cg",180:"cd",262:"dj",818:"eg",
    226:"gq",232:"er",748:"sz",231:"et",266:"ga",270:"gm",288:"gh",324:"gn",
    624:"gw",384:"ci",404:"ke",426:"ls",430:"lr",434:"ly",450:"mg",454:"mw",
    466:"ml",478:"mr",504:"ma",508:"mz",516:"na",562:"ne",566:"ng",646:"rw",
    686:"sn",694:"sl",706:"so",710:"za",728:"ss",729:"sd",834:"tz",768:"tg",
    788:"tn",800:"ug",894:"zm",716:"zw",4:"af",36:"au",48:"bh",50:"bd",
    116:"kh",156:"cn",158:"tw",356:"in",360:"id",364:"ir",368:"iq",392:"jp",
    400:"jo",414:"kw",417:"kg",422:"lb",458:"my",496:"mn",104:"mm",524:"np",
    408:"kp",512:"om",586:"pk",275:"ps",608:"ph",634:"qa",682:"sa",702:"sg",
    410:"kr",144:"lk",760:"sy",762:"tj",764:"th",795:"tm",784:"ae",860:"uz",
    704:"vn",887:"ye",242:"fj",554:"nz",598:"pg",882:"ws",90:"sb",776:"to",
    548:"vu",
}


def build_flag_codes():
    """{country/nation name (incl. aliases) -> flagcdn code} for flag images."""
    codes = {}
    for name, iso in COUNTRY_ISO_MAP.items():
        if iso is None:
            continue
        if isinstance(iso, str):                 # UK home nations: gb-eng, gb-sct…
            codes[name] = iso
        elif iso in NUMERIC_TO_ALPHA2:
            codes[name] = NUMERIC_TO_ALPHA2[iso]
    return codes

# Detailed UK home-nation boundaries are loaded from Natural Earth "map subunits"
# at build time (see load_uk_nations) and cached in uk_nations.json. These crude
# hand-drawn rings are only a fallback if that fetch ever fails offline.
UK_NATIONS_FALLBACK = [
    {"hcKey": "gb-eng", "name": "England", "geometry": {"type": "Polygon", "coordinates": [[
        [-5.7,50.0],[-3.8,50.2],[-2.0,50.5],[-0.5,50.6],[1.3,51.1],[1.7,51.5],
        [1.5,52.1],[1.7,52.9],[0.4,53.5],[0.1,54.1],[-1.3,54.7],[-1.8,55.0],[-2.0,55.7],
        [-2.5,55.5],[-3.0,55.0],[-3.5,54.7],[-3.5,54.0],[-3.4,53.3],
        [-3.1,52.9],[-2.9,52.4],[-2.9,51.7],[-3.2,51.4],
        [-4.0,51.2],[-5.0,51.4],[-5.7,50.0]
    ]]}},
    {"hcKey": "gb-sct", "name": "Scotland", "geometry": {"type": "Polygon", "coordinates": [[
        [-2.0,55.7],[-1.9,56.0],[-2.1,57.0],[-1.9,57.7],
        [-3.5,58.6],[-5.2,58.6],[-6.3,58.1],[-5.9,57.2],
        [-6.3,56.4],[-5.4,55.9],[-5.2,55.2],
        [-4.9,55.0],[-4.4,55.1],[-3.3,55.0],[-2.5,55.5],[-2.0,55.7]
    ]]}},
    {"hcKey": "gb-wls", "name": "Wales", "geometry": {"type": "Polygon", "coordinates": [[
        [-2.9,51.7],[-2.9,52.4],[-3.1,52.9],
        [-3.4,53.4],[-4.4,53.4],[-5.3,52.2],
        [-5.0,51.4],[-4.0,51.2],[-3.2,51.4],[-2.9,51.7]
    ]]}},
    {"hcKey": "gb-nir", "name": "Northern Ireland", "geometry": {"type": "Polygon", "coordinates": [[
        [-8.2,54.1],[-6.0,54.0],[-5.4,54.2],[-5.4,55.2],
        [-7.5,55.4],[-8.2,54.7],[-8.2,54.1]
    ]]}},
]


def load_uk_nations(cache="uk_nations.json"):
    """Detailed England/Scotland/Wales/N.Ireland boundaries from Natural Earth
    50m 'map subunits' (the UK split into its four nations). Cached locally so
    later builds need no network; falls back to crude shapes if unavailable."""
    if Path(cache).exists():
        try:
            return json.loads(Path(cache).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    url = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
           "master/geojson/ne_50m_admin_0_map_subunits.geojson")
    targets = {"England": "gb-eng", "Scotland": "gb-sct",
               "Wales": "gb-wls", "Northern Ireland": "gb-nir"}

    def rnd(c):  # round coordinates to 4 dp (~11 m) to keep the embed small
        if isinstance(c[0], (int, float)):
            return [round(c[0], 4), round(c[1], 4)]
        return [rnd(x) for x in c]

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = json.load(urllib.request.urlopen(req, timeout=180))
    except Exception:
        return UK_NATIONS_FALLBACK

    out = []
    for feat in data.get("features", []):
        su = feat.get("properties", {}).get("SUBUNIT")
        if su in targets:
            g = feat["geometry"]
            out.append({"hcKey": targets[su], "name": su,
                        "geometry": {"type": g["type"], "coordinates": rnd(g["coordinates"])}})
    if len(out) < 4:
        return UK_NATIONS_FALLBACK
    order = {"gb-eng": 0, "gb-sct": 1, "gb-wls": 2, "gb-nir": 3}
    out.sort(key=lambda n: order[n["hcKey"]])
    try:
        Path(cache).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return out


def _disambig_keys(player_team_pairs):
    """Map each (player, team) to a unique display key — the name, qualified by
    the national team when the name repeats (e.g. two Emiliano Martínez)."""
    name_counts = Counter(p for p, _ in player_team_pairs)
    used, keys = {}, {}
    for p, t in player_team_pairs:
        if name_counts[p] > 1:
            key = f"{p} ({t})"
            if key in used:
                used[key] += 1
                key = f"{p} ({t} #{used[key]})"
            else:
                used[key] = 1
        else:
            key = p
        keys[(p, t)] = key
    return keys


def _fmt_years(start, end):
    """Format a spell's years from start/end ('' end = ongoing)."""
    if not start:
        return ""
    if not end:
        return start + "–"          # ongoing, e.g. "2022–"
    if end == start:
        return start
    return start + "–" + end


def load_clubs_csv(path="clubs.csv", spells_path="club_spells.csv"):
    """Return (club_players, player_nation, player_career, player_first,
    player_current, player_spells).

    Prefers club_spells.csv (true chronological spells) so that the FIRST and
    CURRENT club are the first/last *spell*, not the first/last *unique* slug,
    and so the career timeline can show each spell's years + loan status.
    Falls back to clubs.csv (slug-only) if spells are absent.
    """
    club_players: dict[str, set] = defaultdict(set)
    player_nation: dict[str, str] = {}
    player_career: dict[str, list] = {}      # unique slugs in order (for "all" + counts)
    player_first: dict[str, str] = {}
    player_current: dict[str, str] = {}      # current PARENT club (loans excluded)
    player_current_loans: dict[str, list] = {}  # parent club + any ongoing loan clubs
    player_spells: dict[str, list] = {}      # ordered [{slug, years, loan}] for timeline

    if Path(spells_path).exists():
        with open(spells_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        order, spells = [], {}               # (player,team) -> [{slug,end,years,loan}]
        for r in rows:
            pt = (r["Player"], r["Team"])
            if pt not in spells:
                spells[pt] = []
                order.append(pt)
            spells[pt].append({
                "slug":  r["ClubSlug"].strip(),
                "start": (r.get("StartYear") or "").strip(),
                "end":   (r.get("EndYear") or "").strip(),
                "years": (r.get("Years") or "").strip(),
                "loan":  (r.get("Loan") or "").strip().lower() == "yes",
            })
        keys = _disambig_keys(order)
        for pt in order:
            key = keys[pt]
            sp = [s for s in spells[pt] if s["slug"]]
            if not sp:
                continue
            slugs = [s["slug"] for s in sp]
            uniq, seen = [], set()
            for s in slugs:
                if s not in seen:
                    seen.add(s)
                    uniq.append(s)
            # CURRENT PARENT = last ongoing (open-ended, e.g. "2025–") NON-loan
            # spell — a player out on loan is counted at the club that owns him,
            # not the loan destination. Fall backs: last non-loan spell, last
            # ongoing spell, else last spell.
            ongoing      = [s for s in sp if not s["end"]]
            ong_nonloan  = [s for s in ongoing if not s["loan"]]
            nonloan_all  = [s for s in sp if not s["loan"]]
            if ong_nonloan:    parent = ong_nonloan[-1]["slug"]
            elif nonloan_all:  parent = nonloan_all[-1]["slug"]
            elif ongoing:      parent = ongoing[-1]["slug"]
            else:              parent = slugs[-1]
            loans_now = [s["slug"] for s in ongoing if s["loan"] and s["slug"] != parent]
            player_nation[key] = pt[1]
            player_career[key] = uniq
            player_first[key] = slugs[0]
            player_current[key] = parent
            player_current_loans[key] = [parent] + loans_now
            player_spells[key] = [{"slug": s["slug"], "start": s["start"],
                                   "end": s["end"], "loan": s["loan"]} for s in sp]
            for s in uniq:
                club_players[s].add(key)
        return (club_players, player_nation, player_career, player_first,
                player_current, player_current_loans, player_spells)

    # Fallback: clubs.csv (unique slugs only; current = last unique slug)
    club_cols = [f"Club {i}" for i in range(1, 19)]
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    keys = _disambig_keys([(r["Player"], r.get("Team", "")) for r in rows])
    for row in rows:
        key = keys[(row["Player"], row.get("Team", ""))]
        player_nation[key] = row.get("Team", "")
        career = [row[c].strip() for c in club_cols if row.get(c) and row[c].strip()]
        player_career[key] = career
        if career:
            player_first[key] = career[0]
            player_current[key] = career[-1]
            player_current_loans[key] = [career[-1]]   # no loan info in fallback
        player_spells[key] = [{"slug": s, "start": "", "end": "", "loan": False} for s in career]
        for slug in career:
            club_players[slug].add(key)
    return (club_players, player_nation, player_career, player_first,
            player_current, player_current_loans, player_spells)


def data_updated_str(files=("players.csv", "clubs.csv", "club_spells.csv", "club_details.csv")):
    """Human date of the most recently refreshed source data file (footer stamp)."""
    mtimes = [Path(f).stat().st_mtime for f in files if Path(f).exists()]
    if not mtimes:
        return ""
    d = datetime.date.fromtimestamp(max(mtimes))
    return f"{d.day} {d.strftime('%b %Y')}"        # e.g. "21 Jun 2026"


def load_player_urls(path="players.csv"):
    """Map {(player name, nation): Wikipedia URL} from players.csv."""
    urls = {}
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                urls[((r.get("Player") or "").strip(),
                      (r.get("Nation") or "").strip())] = (r.get("WikiURL") or "").strip()
    except FileNotFoundError:
        pass
    return urls


def load_player_bio(path="player_bio.csv"):
    """Map {(player name, team): {'pos','dob'}} from player_bio.csv (position + DOB)."""
    bio = {}
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                bio[((r.get("Player") or "").strip(), (r.get("Team") or "").strip())] = {
                    "pos": (r.get("Position") or "").strip(),
                    "dob": (r.get("DOB") or "").strip(),
                }
    except FileNotFoundError:
        pass
    return bio


def position_group(pos):
    """Bucket a specific position into GK / DEF / MID / FWD (FIFA-style code)."""
    p = (pos or "").lower()
    if not p:
        return ""
    if "keeper" in p:
        return "GK"
    if "back" in p or "defender" in p or "sweeper" in p:
        return "DEF"
    if "midfield" in p:
        return "MID"
    if any(w in p for w in ("forward", "striker", "winger", "wing", "attacker")):
        return "FWD"
    return ""


def build_player_details(player_nation, player_career, details, player_spells=None,
                         player_urls=None, player_bio=None):
    """Build {player_name: {nation, conf, url, pos, dob, career: [...]}}.

    Uses the per-spell data (years + loan) when available, so the career timeline
    shows each spell separately (e.g. a loan then a permanent move to the same
    club appear as two steps). Falls back to unique slugs without years/loan.
    """
    player_spells = player_spells or {}
    player_urls = player_urls or {}
    player_bio = player_bio or {}
    result = {}
    for player, career_slugs in player_career.items():
        nation = player_nation.get(player, "")
        # Prefer the ordered spell list; otherwise use the unique-slug career.
        items = player_spells.get(player) or [{"slug": s, "start": "", "end": "", "loan": False}
                                              for s in career_slugs]
        # Resolve each spell to a display club, then merge consecutive spells at
        # the same club with the same loan status (folds reserve+senior and
        # split-season duplicates) while keeping loan vs permanent distinct.
        career = []
        for it in items:
            d = details.get(it["slug"])
            name    = (d["Name"] if (d and d["Name"]) else it["slug"].replace("_", " ")).strip()
            league  = (d["League"] or "").strip() if d else ""
            country = (d["Country"] or "").strip() if d else ""
            loan    = bool(it.get("loan"))
            if career and career[-1]["name"] == name and career[-1]["loan"] == loan:
                career[-1]["end"] = it.get("end", "")          # extend the span
                if league:  career[-1]["league"] = league      # prefer senior info
                if country: career[-1]["country"] = country
            else:
                career.append({"name": name, "league": league, "country": country,
                               "start": it.get("start", ""), "end": it.get("end", ""),
                               "loan": loan})
        for c in career:
            c["years"] = _fmt_years(c.pop("start", ""), c.pop("end", ""))
        bio = player_bio.get((player.split(" (")[0], nation), {})
        result[player] = {
            "nation": nation,
            "conf":   CONFEDERATION_MAP.get(nation, ""),
            "url":    player_urls.get((player.split(" (")[0], nation), ""),
            "pos":    bio.get("pos", ""),
            "grp":    position_group(bio.get("pos", "")),
            "dob":    bio.get("dob", ""),
            "career": career,
        }
    return result


def load_details(path="club_details.csv"):
    details = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            details[row["Slug"]] = row
    return details


def load_league_levels(path="league_levels.csv"):
    """Return {(country, league): level or None} from league_levels.csv.
    Missing file degrades gracefully (all levels None)."""
    levels = {}
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                lv = (row.get("Level") or "").strip()
                levels[((row.get("Country") or "").strip(),
                        (row.get("League") or "").strip())] = int(lv) if lv else None
    except FileNotFoundError:
        pass
    return levels


def load_youth_leagues(path="league_levels.csv"):
    """Return {(country, league)} for youth / reserve development competitions.

    Derived from league_levels.csv: a league with no pyramid Level whose note
    (RawLevel) flags it as youth/reserve — e.g. MLS Next, A-League Youth. These
    sit below the senior pyramid (their own 'Youth' tier, above 'Dissolved').
    Adding another youth league only needs its 06_league_levels.py override note
    to mention 'youth' or 'reserve'; no change here."""
    youth = set()
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                lvl = (row.get("Level") or "").strip()
                raw = (row.get("RawLevel") or "").lower()
                if not lvl and ("youth" in raw or "reserve" in raw):
                    youth.add(((row.get("Country") or "").strip(),
                               (row.get("League") or "").strip()))
    except FileNotFoundError:
        pass
    return youth


def load_dissolved_clubs(path="dissolved_clubs.json"):
    """Map {club slug: dissolution year} from the Wikipedia infobox 'Dissolved'
    field. These clubs are grouped into a 'Dissolved clubs' league per country."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return {slug: (info.get("year") or "") for slug, info in raw.items()}
    except (OSError, ValueError):
        return {}


DISSOLVED_CLUBS = load_dissolved_clubs()
DISSOLVED_LEAGUE = "Dissolved clubs"
YOUTH_LEAGUES = load_youth_leagues()


def build_hierarchy(club_players, player_nation, details, league_levels=None,
                    loan_at=None, loan_from=None, current_at=None):
    """
    Build the 4-level hierarchy with deduplicated player counts.

    Deduplication rules:
    - Clubs: different slugs that share the same display name within the same
      (country, league) are merged — their player sets are unioned. This fixes
      cases like Manchester_City vs Manchester_City_F.C.
    - League total: union of all player sets for clubs in that league.
    - Country total: union of league player sets.
    - Confederation total: union of country player sets.
    - Leagues carry their pyramid `level` (tier) from league_levels.csv.
    - `loan_at` {slug: {keys}} flags players present at a club on loan (used by
      the "current incl. loans" view) so the UI can show a "loan" tag.
    - `loan_from` {key: parent_club_name} adds the owning club to a loan tag.
    - `current_at` {slug: {keys}} flags players who *currently* play for a club
      (used by the "all clubs" view) so the UI can show a "current" tag.
    """
    league_levels = league_levels or {}
    loan_at = loan_at or {}
    loan_from = loan_from or {}
    current_at = current_at or {}
    # Canonical league names: merge same-league-different-name entries (e.g.
    # Argentina "Liga Profesional" / "Primera División") using the shared
    # league_dedup logic so the map matches league_levels.csv.
    canon_slug, canon_league, _ = build_canonical_map(details.values())

    # (country, league, display_name) -> set of players
    name_players: dict[tuple, set] = defaultdict(set)
    loan_players: dict[tuple, set] = defaultdict(set)      # of those, who are on loan here
    current_players: dict[tuple, set] = defaultdict(set)   # of those, who play here now
    dissolved_year: dict[tuple, str] = {}      # (country, name) -> dissolution year

    for slug, players in club_players.items():
        d = details.get(slug)
        if not d:
            continue
        country     = (d["Country"] or "Unknown").strip()
        raw_league  = (d["League"]  or "Unknown").strip()
        league_slug = (d.get("LeagueSlug") or "").strip()
        name    = (d["Name"]    or slug.replace("_", " ")).strip()
        if slug in DISSOLVED_CLUBS:
            league = DISSOLVED_LEAGUE       # group defunct clubs separately, per country
            if DISSOLVED_CLUBS[slug]:
                dissolved_year[(country, name)] = DISSOLVED_CLUBS[slug]
        else:
            league = canonical_league(country, raw_league, league_slug,
                                      canon_slug, canon_league)
        name_players[(country, league, name)] |= players
        if slug in loan_at:
            loan_players[(country, league, name)] |= (loan_at[slug] & players)
        if slug in current_at:
            current_players[(country, league, name)] |= (current_at[slug] & players)

    # Group into conf -> country -> league -> clubs
    struct: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for (country, league, name), players in name_players.items():
        count = len(players)
        if count < MIN_PLAYERS:
            continue
        conf = CONFEDERATION_MAP.get(country, "Unknown")
        loaned = loan_players.get((country, league, name), set())
        current = current_players.get((country, league, name), set())
        def _entry(p):
            e = {"n": p, "t": player_nation.get(p, "")}
            if p in loaned:                       # on loan here (current-incl-loans view)
                e["l"] = 1
                if loan_from.get(p):
                    e["lf"] = loan_from[p]        # owning club, shown on hover
            if p in current:                      # currently plays here (all-clubs view)
                e["c"] = 1
            return e
        club_entry = {
            "name":    name,
            "count":   count,
            "players": players,
            # sorted by surname (last word); l/lf=loan(+owner), c=current here
            "playersList": sorted(
                [_entry(p) for p in players],
                key=lambda x: x["n"].split()[-1],
            ),
        }
        if league == DISSOLVED_LEAGUE and (country, name) in dissolved_year:
            club_entry["dissolved"] = dissolved_year[(country, name)]
        struct[conf][country][league].append(club_entry)

    result = []
    for conf in sorted(struct):
        conf_players: set = set()
        countries = []
        for country in sorted(struct[conf]):
            country_players: set = set()
            leagues = []
            for league in sorted(struct[conf][country]):
                clubs = struct[conf][country][league]
                league_players: set = set()
                for c in clubs:
                    league_players |= c["players"]
                country_players |= league_players
                leagues.append({
                    "name":         league,
                    "country":      country,
                    "totalPlayers": len(league_players),
                    "level":        league_levels.get((country, league)),
                    **({"youth": True} if (country, league) in YOUTH_LEAGUES else {}),
                    "clubs": sorted(
                        [{"name": c["name"], "count": c["count"],
                          "players": c["playersList"],
                          **({"dissolved": c["dissolved"]} if "dissolved" in c else {})}
                         for c in clubs],
                        key=lambda x: -x["count"],
                    ),
                })
            conf_players |= country_players
            countries.append({
                "country":      country,
                "totalPlayers": len(country_players),
                "coords":       COUNTRY_COORDS.get(country, [0, 0]),
                "isoCode":      COUNTRY_ISO_MAP.get(country),
                "leagues":      sorted(leagues, key=lambda l: -l["totalPlayers"]),
            })
        result.append({
            "confederation": conf,
            "colour":        CONFEDERATION_COLOURS.get(conf, "#888888"),
            "totalPlayers":  len(conf_players),
            "coords":        CONFEDERATION_COORDS.get(conf, [0, 0]),
            "countries":     sorted(countries, key=lambda c: -c["totalPlayers"]),
        })

    return result


def validate_players(data, player_details):
    """Guard against same-named players being merged or given the wrong profile.

    1. Every player shown at a club must have that club in their own career
       (a wrong-profile merge — e.g. two 'Emiliano Martínez' — breaks this).
    2. Reports players who share a base name so collisions are always visible.
    """
    career_clubs = {k: {c["name"] for c in v.get("career", [])}
                    for k, v in player_details.items()}
    wrong_profile, no_detail = [], []
    for conf in data:
        for co in conf["countries"]:
            for lg in co["leagues"]:
                for cl in lg["clubs"]:
                    for p in cl["players"]:
                        key = p["n"]
                        if key not in player_details:
                            no_detail.append((cl["name"], key))
                        elif cl["name"] not in career_clubs[key]:
                            wrong_profile.append((cl["name"], key))

    shared = defaultdict(list)
    for key in player_details:
        shared[key.split(" (")[0]].append(key)
    shared = {b: ks for b, ks in shared.items() if len(ks) > 1}

    print(f"  Players:        {len(player_details)} unique")
    if shared:
        print(f"  Shared names disambiguated: {len(shared)}")
        for b, ks in sorted(shared.items()):
            print(f"    - {b}: {', '.join(sorted(ks))}")
    if no_detail or wrong_profile:
        print(f"  !! PLAYER INTEGRITY PROBLEM: {len(no_detail)} missing profiles, "
              f"{len(wrong_profile)} wrong-profile rosters")
        for cl, k in (no_detail + wrong_profile)[:10]:
            print(f"       {k} @ {cl}")
    else:
        print("  Player profiles: OK (every club roster matches the player's own career)")


def validate_country_coverage(data):
    """Check every squad country can be drawn on the choropleth.

    Fetches the same world atlas the page uses and reports any country that
    would render empty:
      - no ISO code mapped (COUNTRY_ISO_MAP miss),
      - ISO code absent from the atlas,
      - ISO code shared by several atlas geometries (collision — the page keeps
        the largest, so this is informational only).
    Network is best-effort: if the atlas can't be fetched the check is skipped.
    """
    countries = [c for d in data for c in d["countries"]]
    uk = {"gb-eng", "gb-sct", "gb-wls", "gb-nir"}

    print("\n-- Map coverage check --")

    # Countries with no ISO mapping at all — these never render, no network needed.
    no_iso = [(c["country"], c["totalPlayers"]) for c in countries if c["isoCode"] is None]

    try:
        req = urllib.request.Request(ATLAS_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            atlas = json.load(resp)
        geoms = atlas["objects"]["countries"]["geometries"]
        id_counts = Counter(int(g["id"]) for g in geoms if str(g.get("id", "")).isdigit())
    except Exception as e:                       # offline / CDN down — degrade gracefully
        print(f"  (skipped atlas cross-check — could not fetch atlas: {e})")
        if no_iso:
            print(f"  WARNING: {len(no_iso)} country(ies) have no ISO mapping and will not render:")
            for nm, pl in sorted(no_iso, key=lambda x: -x[1]):
                print(f"    - {nm} ({pl} players)")
        else:
            print("  (no un-mapped countries; atlas cross-check unavailable)")
        return

    atlas_ids = set(id_counts)
    dup_ids   = {k for k, v in id_counts.items() if v > 1}

    not_in_atlas, collisions = [], []
    for c in countries:
        iso = c["isoCode"]
        if iso in uk or iso is None:
            continue
        if iso not in atlas_ids:
            not_in_atlas.append((c["country"], c["totalPlayers"], iso))
        elif iso in dup_ids:
            others = [g.get("properties", {}).get("name") for g in geoms
                      if str(g.get("id", "")).isdigit() and int(g["id"]) == iso]
            collisions.append((c["country"], iso, others))

    broken = no_iso + not_in_atlas
    if broken:
        print(f"  WARNING: {len(broken)} country(ies) will NOT render:")
        for nm, pl in sorted(no_iso, key=lambda x: -x[1]):
            print(f"    - {nm} ({pl} players) -- no ISO code mapped")
        for nm, pl, iso in sorted(not_in_atlas, key=lambda x: -x[1]):
            print(f"    - {nm} ({pl} players) -- ISO {iso} not in atlas")
    else:
        renderable = len([c for c in countries if c["isoCode"] not in uk])
        print(f"  OK - all {renderable} countries have a matching atlas polygon.")

    if collisions:
        print(f"  Note: {len(collisions)} country(ies) share an atlas id with another territory")
        print(f"        (handled by keeping the largest landmass):")
        for nm, iso, others in collisions:
            extra = [o for o in others if o and o != nm]
            print(f"    - {nm} (id {iso:03d}) also: {', '.join(extra) or 'n/a'}")


def main():
    (club_players, player_nation, player_career, player_first,
     player_current, player_current_loans, player_spells) = load_clubs_csv()
    details      = load_details()
    league_levels = load_league_levels()
    player_urls     = load_player_urls()
    player_bio      = load_player_bio()
    player_details  = build_player_details(player_nation, player_career, details,
                                           player_spells, player_urls, player_bio)

    # Career-filter views of the hierarchy:
    #   all            — a player counts at EVERY club in their career
    #   current        — current PARENT club only (a loanee counts at his owner)
    #   current_loans  — parent club AND any club he is currently loaned to
    #   first          — first senior club only
    # All come from the true chronological spell order (returns handled).
    cp_first, cp_current = defaultdict(set), defaultdict(set)
    cp_current_loans = defaultdict(set)
    loan_at = defaultdict(set)            # slug -> players present there on loan
    loan_from = {}                        # key  -> owning (parent) club name
    for key, slug in player_first.items():
        cp_first[slug].add(key)
    for key, slug in player_current.items():
        cp_current[slug].add(key)
    for key, slugs in player_current_loans.items():
        for slug in slugs:
            cp_current_loans[slug].add(key)
        parent_d = details.get(slugs[0])
        parent_name = (parent_d["Name"] if parent_d and parent_d["Name"]
                       else slugs[0].replace("_", " ")) if slugs else ""
        for slug in slugs[1:]:           # slugs[0] is the parent club; rest are loans
            loan_at[slug].add(key)
            loan_from[key] = parent_name
    data_all           = build_hierarchy(club_players,     player_nation, details, league_levels,
                                         current_at=cp_current)
    data_current       = build_hierarchy(cp_current,       player_nation, details, league_levels)
    data_current_loans = build_hierarchy(cp_current_loans, player_nation, details, league_levels,
                                         loan_at=loan_at, loan_from=loan_from)
    data_first         = build_hierarchy(cp_first,         player_nation, details, league_levels)
    data         = data_all   # used by the build-time summary / validation below

    data_json       = json.dumps({"all": data_all, "current": data_current,
                                  "current_loans": data_current_loans,
                                  "first": data_first}, ensure_ascii=False)
    players_json    = json.dumps(player_details, ensure_ascii=False)
    uk_nations_json = json.dumps(load_uk_nations(), ensure_ascii=False)
    dissolved_league_json = json.dumps(DISSOLVED_LEAGUE, ensure_ascii=False)
    flag_codes_json = json.dumps(build_flag_codes(), ensure_ascii=False)
    data_updated    = data_updated_str()
    footer_html     = (f'<div id="datasource">Data: Wikipedia · updated {data_updated}</div>'
                       if data_updated else "")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>FIFA World Cup 2026 Club Network</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0d1c35; color: #eee; font-family: sans-serif; overflow: hidden; }}
  #canvas {{ width: 100vw; height: 100vh; cursor: default; }}
  .node circle {{ cursor: pointer; transition: opacity 0.15s; }}
  .node circle:hover {{ opacity: 0.75; }}
  .node text {{ pointer-events: none; fill: #fff;
                text-shadow: 0 0 4px #000, 0 0 4px #000; }}
  #breadcrumb {{
    position: fixed; top: 12px; left: 50%;
    transform: translateX(-50%);
    background: rgba(0,0,0,0.75); padding: 7px 16px;
    border-radius: 20px; font-size: 13px;
    white-space: nowrap; z-index: 10;
  }}
  .bc-link {{ color: #aad4ff; cursor: pointer; text-decoration: underline; }}
  .bc-link:hover {{ color: #fff; }}
  .bc-current {{ color: #fff; font-weight: bold; }}
  .bc-sep {{ color: #666; margin: 0 5px; }}
  #title {{
    position: fixed; top: 12px; left: 16px; z-index: 11; max-width: calc(100vw - 32px);
    display: flex; align-items: center; gap: 11px;
    background: linear-gradient(135deg, rgba(26,44,78,0.93), rgba(9,16,32,0.90));
    padding: 9px 17px 9px 13px; border-radius: 12px;
    border: 1px solid rgba(255,255,255,0.12);
    box-shadow: 0 8px 26px rgba(0,0,0,0.5);
  }}
  /* World Cup trophy mark (icons8 image) */
  #title .t-mark {{
    width: 24px; height: 24px; flex-shrink: 0; display: block;
    filter: drop-shadow(0 1px 2px rgba(0,0,0,0.45));
  }}
  #title .t-main {{
    font-size: 20px; font-weight: 800; letter-spacing: 0.2px; color: #fff;
    white-space: nowrap; line-height: 1;
  }}
  #title .t-accent {{ color: #8ab4ff; font-weight: 800; }}
  #right-col {{
    position: fixed; top: 12px; right: 16px; z-index: 11;
    display: flex; flex-direction: column; gap: 10px; align-items: stretch;
  }}
  #filter {{
    background: rgba(0,0,0,0.75); padding: 10px 14px;
    border-radius: 8px; font-size: 12px;
  }}
  #filter {{ width: 230px; }}
  #filter label {{
    display: flex; align-items: flex-start; gap: 7px;
    margin: 5px 0; cursor: pointer; line-height: 1.3;
  }}
  #filter input {{ margin-top: 2px; accent-color: #9cf; cursor: pointer; }}
  #filter .f-note {{
    margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.14);
    font-size: 11px; color: #bcd; line-height: 1.45;
  }}
  #filter .f-note b {{ color: #fff; }}
  h3 {{ font-size: 13px; margin-bottom: 6px; }}
  /* Country flags (flagcdn images) */
  img.flag {{
    height: 12px; width: 16px; object-fit: cover; vertical-align: -1px;
    margin-right: 5px; border-radius: 2px; box-shadow: 0 0 0 1px rgba(0,0,0,0.35);
    flex-shrink: 0;
  }}
  #tooltip {{
    position: fixed; pointer-events: none;
    background: rgba(0,0,0,0.88); padding: 8px 12px;
    border-radius: 6px; font-size: 12px; line-height: 1.6;
    display: none; max-width: 240px; z-index: 20;
  }}
  /* ── Search ─────────────────────────────────────────────────────────────── */
  #search {{
    position: fixed; top: 50px; left: 50%; transform: translateX(-50%);
    z-index: 25; width: 420px; max-width: calc(100vw - 32px);
  }}
  #search-input {{
    width: 100%; padding: 8px 12px; border-radius: 8px;
    border: 1px solid rgba(255,255,255,0.22); background: rgba(0,0,0,0.82);
    color: #eee; font-size: 13px; outline: none;
  }}
  #search-input::placeholder {{ color: #889; }}
  #search-input:focus {{ border-color: #9cf; }}
  #search-results {{
    margin-top: 5px; background: rgba(8,14,28,0.98);
    border: 1px solid rgba(255,255,255,0.12); border-radius: 8px;
    max-height: 56vh; overflow-y: auto; display: none;
    box-shadow: 0 10px 34px rgba(0,0,0,0.55);
  }}
  #search-results.open {{ display: block; }}
  .sr-item {{
    display: flex; align-items: center; gap: 8px; padding: 7px 11px;
    cursor: pointer; border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 13px;
  }}
  .sr-item:last-child {{ border-bottom: none; }}
  .sr-item.active, .sr-item:hover {{ background: rgba(255,255,255,0.10); }}
  /* name on its own line; context (league · country / nation) underneath */
  .sr-main {{ flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: 1px; }}
  .sr-label {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .sr-sub {{ color: #889; font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .sr-type {{
    flex-shrink: 0; align-self: center; font-size: 9px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.04em; color: #0c1a12;
    border-radius: 4px; padding: 1px 5px; background: #8aa;
  }}
  .sr-type.player {{ background: #c9a0dc; }}
  .sr-type.club {{ background: #e0b34d; }}
  .sr-type.league {{ background: #9cc3e0; }}
  .sr-type.country {{ background: #8fd3a6; }}
  .sr-empty {{ padding: 9px 12px; color: #889; font-size: 12px; }}
  #sidebar {{
    position: fixed; top: 62px; left: 16px;
    background: rgba(0,0,0,0.75); padding: 10px 14px;
    border-radius: 8px; font-size: 12px; width: 270px;
    max-height: calc(100vh - 76px); overflow-y: auto; z-index: 10;
  }}
  #sidebar h3 {{ font-size: 13px; margin-bottom: 8px; display: flex; align-items: baseline; gap: 8px; }}
  #sidebar h3 .sb-h-count {{
    margin-left: auto; font-size: 10px; font-weight: normal; color: #9aa;
    text-transform: uppercase; letter-spacing: 0.03em;
  }}
  #sb-leagues-box {{
    margin-top: 12px; padding-top: 10px;
    border-top: 1px solid rgba(255,255,255,0.14);
  }}
  .sb-row {{
    display: flex; align-items: baseline;
    padding: 4px 0; border-bottom: 1px solid rgba(255,255,255,0.06);
    gap: 6px;
  }}
  .sb-row.sb-link {{ cursor: pointer; border-radius: 4px; }}
  .sb-row.sb-link:hover {{ background: rgba(255,255,255,0.09); }}
  .sb-rank {{ color: #666; width: 26px; flex-shrink: 0; text-align: right; font-size: 11px; }}
  .sb-name {{ flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .sb-row.sb-tie .sb-name {{ color: #9ab; font-style: italic; }}
  .sb-count {{
    color: #aaa; font-size: 11px; flex-shrink: 0;
    background: rgba(255,255,255,0.08); border-radius: 10px;
    padding: 1px 6px;
  }}
  .sb-league {{
    display: block; color: #666; font-size: 10px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }}
  #zoom-ctrl {{
    position: fixed; bottom: 16px; right: 16px;
    display: flex; flex-direction: column; gap: 5px; z-index: 10;
  }}
  #datasource {{
    position: fixed; bottom: 8px; left: 50%; transform: translateX(-50%);
    z-index: 9; pointer-events: none; white-space: nowrap;
    font-size: 10px; color: #cdd6e3;
    background: rgba(0,0,0,0.42); padding: 2px 9px; border-radius: 8px;
  }}
  #zoom-ctrl button {{
    width: 34px; height: 34px; background: rgba(0,0,0,0.75);
    color: #eee; border: 1px solid rgba(255,255,255,0.2);
    border-radius: 6px; font-size: 18px; cursor: pointer;
    line-height: 1; display: flex; align-items: center; justify-content: center;
  }}
  #zoom-ctrl button:hover {{ background: rgba(80,80,80,0.9); }}
  #zoom-ctrl button[title] {{ font-size: 14px; }}
  /* ── Player detail card ──────────────────────────────────────────── */
  #player-detail {{
    position: fixed; top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    width: min(440px, 90vw); max-height: 80vh; overflow-y: auto;
    background: #16213a; color: #eee;
    border: 1px solid rgba(255,255,255,0.12); border-radius: 14px;
    padding: 22px 26px; z-index: 30; display: none;
    box-shadow: 0 12px 40px rgba(0,0,0,0.55);
  }}
  #player-detail .pd-name {{ font-size: 22px; font-weight: bold; margin-bottom: 4px; }}
  #player-detail .pd-nation {{
    display: inline-block; font-size: 13px; margin-bottom: 16px;
    padding: 3px 10px; border-radius: 12px; background: rgba(255,255,255,0.1);
  }}
  #player-detail .pd-conf {{ color: #aab; font-size: 11px; margin-left: 4px; }}
  #player-detail .pd-bio {{ font-size: 12.5px; color: #cdd6e3; margin: 5px 0 2px; }}
  #player-detail .pd-section {{
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em;
    color: #8a9; margin: 6px 0 10px;
  }}
  .pd-timeline {{ position: relative; margin-left: 8px; }}
  .pd-step {{ position: relative; padding: 0 0 16px 22px; }}
  .pd-step::before {{   /* node dot — centred on the connecting line */
    content: ""; position: absolute; left: 0; top: 5px;
    width: 10px; height: 10px; border-radius: 50%;
    background: var(--conf-col, #6cf);
  }}
  .pd-step:not(:last-child)::after {{   /* connecting line */
    content: ""; position: absolute; left: 4px; top: 16px;
    width: 2px; height: calc(100% - 13px); background: rgba(255,255,255,0.18);
  }}
  /* Loan spells: magenta dot (+ the 'loan' badge) set them apart. Magenta sits
     outside the confederation palette, so it never clashes with a nation's node
     colour (the amber it replaced was too close to AFC's yellow). */
  .pd-step-loan::before {{ background: #e368bb; }}
  .pd-club {{ font-size: 14px; font-weight: 600; }}
  .pd-clublink {{
    cursor: pointer; text-decoration: underline;
    text-decoration-color: rgba(255,255,255,0.25); text-underline-offset: 2px;
  }}
  .pd-clublink:hover {{ color: var(--conf-col, #6cf); text-decoration-color: var(--conf-col, #6cf); }}
  #player-detail .pd-wiki {{
    font-size: 12px; margin-left: 10px; color: #7fb2ff;
    text-decoration: none; white-space: nowrap; vertical-align: middle;
  }}
  #player-detail .pd-wiki:hover {{ text-decoration: underline; }}
  .pd-meta {{ font-size: 11px; color: #9aa; margin-top: 1px; }}
  .pd-loan {{
    font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em;
    color: #2a0820; background: #e368bb; border-radius: 4px;
    padding: 1px 5px; margin-left: 6px; vertical-align: middle;
  }}
  #player-detail .pd-close {{
    position: absolute; top: 12px; right: 14px; cursor: pointer;
    font-size: 20px; color: #889; line-height: 1; border: none; background: none;
  }}
  #player-detail .pd-close:hover {{ color: #fff; }}
  #player-detail .pd-hint {{ font-size: 11px; color: #778; margin-top: 14px; }}
  /* ── Player list (alphabetical by surname) ───────────────────────────── */
  #player-list {{
    position: fixed; top: 58px; left: 50%; transform: translateX(-50%);
    width: min(440px, 92vw); max-height: calc(100vh - 86px); overflow-y: auto;
    background: #16213a; color: #eee;
    border: 1px solid rgba(255,255,255,0.12); border-radius: 12px;
    z-index: 25; display: none; box-shadow: 0 12px 40px rgba(0,0,0,0.5);
  }}
  #player-list .pl-head {{
    position: sticky; top: 0; background: #16213a; z-index: 1;
    display: flex; align-items: baseline; gap: 8px;
    font-size: 15px; font-weight: bold; padding: 14px 18px 10px;
    border-bottom: 1px solid rgba(255,255,255,0.12); border-radius: 12px 12px 0 0;
  }}
  #player-list .pl-count {{ margin-left: auto; color: #9cf; font-weight: normal; font-size: 13px; }}
  #player-list .pl-sortbar {{
    padding: 7px 18px; font-size: 11px; color: #9aa;
    border-bottom: 1px solid rgba(255,255,255,0.06);
  }}
  #player-list .pl-sortbar select {{
    font-size: 11px; margin-left: 5px; cursor: pointer;
    background-color: #e7ecf3; color: #15203a;            /* dark text on a light control */
    border: 1px solid rgba(0,0,0,0.25); border-radius: 5px; padding: 2px 6px;
  }}
  #player-list .pl-sortbar select option {{ background-color: #ffffff; color: #15203a; }}
  #player-list .pl-rows {{ padding: 4px 0 8px; }}
  #player-list .pl-row {{
    display: flex; align-items: baseline; gap: 8px;
    padding: 6px 18px; cursor: pointer; font-size: 13px;
  }}
  #player-list .pl-row:hover {{ background: rgba(255,255,255,0.07); }}
  #player-list .pl-name b {{ font-weight: 700; }}
  #player-list .pl-nat {{ margin-left: auto; color: #9aa; font-size: 11px; white-space: nowrap; }}
  #player-list .pl-loan, #player-list .pl-cur {{
    font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em;
    border-radius: 4px; padding: 0 5px; align-self: center; cursor: default;
  }}
  #player-list .pl-loan {{ color: #2a0820; background: #e368bb; }}   /* loan = magenta (avoids AFC-yellow clash) */
  /* FIFA-style position code, colour-coded (palette shared with confederations) */
  /* Position-badge colours, shared by the player list + profile (FIFA-style). */
  .pos-GK  {{ background: #e69f00; color: #1a1500; }}   /* orange */
  .pos-DEF {{ background: #f0e442; color: #1a1500; }}   /* yellow */
  .pos-MID {{ background: #009e73; color: #06231a; }}   /* green, dark text (readable) */
  .pos-FWD {{ background: #0072b2; color: #ffffff; }}   /* blue   */
  #player-list .pl-pos {{
    flex-shrink: 0; align-self: center; width: 30px; text-align: center;
    font-size: 9px; font-weight: 700; letter-spacing: 0.02em;
    border-radius: 3px; padding: 1px 0;
  }}
  #player-list .pl-pos-none {{ background: none; }}                     /* unknown: keep column aligned */
  #player-detail .pd-posb {{
    display: inline-block; font-size: 9px; font-weight: 700; letter-spacing: 0.02em;
    border-radius: 3px; padding: 1px 5px; margin-right: 6px; vertical-align: 1px;
  }}
  #player-list .pl-cur  {{ color: #06281a; background: #5fd39a; }}   /* current = green */

  /* ── Mobile chrome (hidden on desktop) ──────────────────────────────────── */
  #mobile-actions {{ display: none; }}
  #m-scrim {{ display: none; }}

  /* ── Mobile layout: full-screen map, panels become slide-in drawers ─────── */
  @media (max-width: 700px) {{
    /* Compact title: trophy + "Club Network" only (the long prefix is hidden) */
    #title {{ top: 8px; left: 8px; padding: 7px 11px; gap: 7px; max-width: calc(100vw - 150px); }}
    #title .t-mark {{ width: 20px; height: 20px; }}
    #title .t-main {{ font-size: 14px; }}
    #title .t-pre {{ display: none; }}

    /* Floating action buttons, top-right */
    #mobile-actions {{
      display: flex; gap: 7px;
      position: fixed; top: 8px; right: 8px; z-index: 29;
    }}
    #mobile-actions button {{
      width: 38px; height: 38px; border-radius: 9px; padding: 0;
      background: linear-gradient(135deg, rgba(26,44,78,0.95), rgba(9,16,32,0.92));
      border: 1px solid rgba(255,255,255,0.14); color: #eee;
      font-size: 16px; cursor: pointer; display: flex;
      align-items: center; justify-content: center;
      box-shadow: 0 6px 18px rgba(0,0,0,0.45); -webkit-tap-highlight-color: transparent;
    }}
    #mobile-actions button.on {{ background: #2d6cff; border-color: #6f9bff; color: #fff; }}
    body.lists-empty #mb-lists {{ display: none; }}

    /* Breadcrumb: own row under the title, horizontally scrollable */
    #breadcrumb {{
      top: 52px; left: 8px; right: 8px; transform: none;
      max-width: none; text-align: left; overflow-x: auto;
      -webkit-overflow-scrolling: touch; scrollbar-width: none;
    }}
    #breadcrumb::-webkit-scrollbar {{ display: none; }}

    /* Search collapses to an icon — full-width bar only when toggled open */
    #search {{
      top: 52px; left: 8px; right: 8px; width: auto; max-width: none;
      transform: none; opacity: 0; pointer-events: none; transition: opacity 0.15s;
    }}
    body.m-search #search {{ opacity: 1; pointer-events: auto; }}
    body.m-search #breadcrumb {{ display: none; }}

    /* Top-lists sidebar -> left drawer */
    #sidebar {{
      top: 0; left: 0; bottom: 0; height: 100%; max-height: none;
      width: min(84vw, 330px); border-radius: 0; padding-top: 54px;
      transform: translateX(-104%); transition: transform 0.22s ease; z-index: 28;
    }}
    body.m-lists #sidebar {{ transform: none; }}

    /* Count filter -> right drawer */
    #right-col {{
      top: 0; right: 0; bottom: 0; width: min(84vw, 330px);
      transform: translateX(104%); transition: transform 0.22s ease; z-index: 28;
    }}
    #filter {{ width: 100%; height: 100%; border-radius: 0; padding-top: 54px; overflow-y: auto; font-size: 13px; }}
    body.m-filter #right-col {{ transform: none; }}

    /* Tap-away scrim behind the open drawer / search */
    #m-scrim {{ position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 27; }}
    body.m-lists #m-scrim, body.m-filter #m-scrim {{ display: block; }}
    body.m-search #m-scrim {{ display: block; background: transparent; }}

    /* Larger touch targets for zoom, slimmer footer */
    #zoom-ctrl {{ bottom: 10px; right: 10px; gap: 7px; }}
    #zoom-ctrl button {{ width: 40px; height: 40px; }}
    #datasource {{ font-size: 9px; bottom: 4px; }}
  }}
</style>
</head>
<body>
<svg id="canvas"></svg>
<div id="breadcrumb"></div>
<div id="search">
  <input id="search-input" type="text" autocomplete="off" spellcheck="false"
         placeholder="Search players, clubs, leagues, countries…">
  <div id="search-results"></div>
</div>
<div id="tooltip"></div>
<div id="title">
  <img class="t-mark" src="https://img.icons8.com/color/96/world-cup.png" alt="" width="24" height="24">
  <span class="t-main"><span class="t-pre">FIFA World Cup 2026 </span><span class="t-accent">Club Network</span></span>
</div>
<div id="mobile-actions">
  <button id="mb-search" onclick="toggleMobile('search')" aria-label="Search" title="Search">&#128269;</button>
  <button id="mb-lists" onclick="toggleMobile('lists')" aria-label="Top clubs and leagues" title="Top lists">&#9776;</button>
  <button id="mb-filter" onclick="toggleMobile('filter')" aria-label="Count filter" title="Count players by">&#9881;</button>
</div>
<div id="m-scrim" onclick="closeMobilePanels()"></div>
<div id="sidebar">
  <div id="sb-clubs-box"><h3>Top 10 Clubs</h3><div id="sb-list"></div></div>
  <div id="sb-leagues-box"><h3>Top Leagues</h3><div id="sb-leagues"></div></div>
</div>
<div id="player-detail"></div>
<div id="player-list"></div>
<div id="zoom-ctrl">
  <button onclick="ctrlZoomIn()" title="Zoom in">+</button>
  <button onclick="ctrlZoomOut()" title="Zoom out">−</button>
  <button onclick="ctrlFit()" title="Fit to screen">⊡</button>
</div>
{footer_html}
<div id="right-col">
  <div id="filter">
    <h3>Count players by</h3>
    <label><input type="radio" name="cf" value="all" checked onchange="setFilter('all')"> All clubs (whole career)</label>
    <label><input type="radio" name="cf" value="current" onchange="setFilter('current')"> Current club</label>
    <label><input type="radio" name="cf" value="current_loans" onchange="setFilter('current_loans')"> Current club (incl. loans)</label>
    <label><input type="radio" name="cf" value="first" onchange="setFilter('first')"> First senior club</label>
    <div id="filter-note" class="f-note"></div>
  </div>
</div>

<script src="https://d3js.org/d3.v7.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/topojson-client@3/dist/topojson-client.min.js"></script>
<script>
// Career-filter datasets; RAW points at the active one.
const DATA = {data_json};
let RAW = DATA.all;
let FILTER = "all";

// Wording for each filter so counts never read as "current squad" by accident.
const FILTERS = {{
  all: {{
    label: "All clubs (whole career)",
    note: "Counts every squad player who has played here at <b>any point in their career</b>, not just current squads.",
  }},
  current: {{
    label: "Current club",
    note: "Each player's <b>current club</b>. A player out on loan is counted at his <b>parent club</b>, not the club he is loaned to.",
  }},
  current_loans: {{
    label: "Current club (incl. loans)",
    note: "Like Current club, but a player out on loan <b>also appears at the club he is loaned to</b>.",
  }},
  first: {{
    label: "First senior club",
    note: "Counts only players whose <b>first senior club</b> was here (youth/academy clubs are not counted).",
  }},
}};

// Phrase for a node's player count, matching the active filter.
function herePhrase(count) {{
  const p = count === 1 ? "player" : "players";
  if (FILTER === "current" || FILTER === "current_loans") return count + " " + p + " currently here";
  if (FILTER === "first")   return count + " " + p + " made their senior debut here";
  return count + " " + p + (count === 1 ? " has" : " have") + " played here";
}}
// Basis word for the player-list header.
function basisWord() {{
  return FILTER === "current"       ? "current club"
       : FILTER === "current_loans" ? "current club, incl. loans"
       : FILTER === "first"         ? "first senior club"
       : "whole career";
}}
// Shorter basis for compact headings.
function basisShort() {{
  return FILTER === "current"       ? "current"
       : FILTER === "current_loans" ? "current + loans"
       : FILTER === "first"         ? "first senior"
       : "career";
}}

// ── Mobile drawers ──────────────────────────────────────────────────────────
// On phones the top-lists sidebar, the count filter and search are hidden behind
// floating buttons; only one panel is open at a time (body gets m-lists/m-filter/
// m-search). On desktop these classes are inert (the media query never applies).
function syncMobileButtons() {{
  const b = document.body;
  const set = (id, on) => {{ const el = document.getElementById(id); if (el) el.classList.toggle("on", on); }};
  set("mb-search", b.classList.contains("m-search"));
  set("mb-lists",  b.classList.contains("m-lists"));
  set("mb-filter", b.classList.contains("m-filter"));
}}
function closeMobilePanels() {{
  document.body.classList.remove("m-search", "m-lists", "m-filter");
  syncMobileButtons();
}}
function toggleMobile(which) {{
  const cls = "m-" + which;
  const wasOpen = document.body.classList.contains(cls);
  document.body.classList.remove("m-search", "m-lists", "m-filter");
  if (!wasOpen) document.body.classList.add(cls);
  syncMobileButtons();
  if (which === "search" && !wasOpen) {{
    const inp = document.getElementById("search-input");
    if (inp) setTimeout(() => inp.focus(), 60);
  }}
}}

const PLAYER_DETAILS = {players_json};

// ── Canvas ────────────────────────────────────────────────────────────────
const W = window.innerWidth, H = window.innerHeight;
const svg = d3.select("#canvas").attr("viewBox", `0 0 ${{W}} ${{H}}`);

// Ocean fill sits behind everything and never moves
svg.append("rect").attr("class","ocean-bg").attr("width", W).attr("height", H).attr("fill", "#0d1c35");

// gBg:     graticule (choropleth mode only)
// gMap:    individual country fill paths — choropleth colours, interactive
// gBorder: country border lines on top of fills
// gLabels: confederation centroid labels (choropleth mode only)
// g:       force-simulation nodes (league / club levels only)
const gBg      = svg.append("g");
const gMap     = svg.append("g");
const gBorder  = svg.append("g");
const gLabels  = svg.append("g");
const gClabels = svg.append("g");   // country name + flag labels (collision-filtered)
const g        = svg.append("g");
const countryPathMap = new Map();  // ISO numeric code → SVGPathElement

const tip = document.getElementById("tooltip");

// ── Geo projection — equirectangular (flat rectangular grid) ──────────────
const baseScale = W / (2 * Math.PI);
const baseTx    = W / 2;
const baseTy    = H / 2 + 20;

const projection = d3.geoEquirectangular()
  .scale(baseScale)
  .translate([baseTx, baseTy]);
const pathGen = d3.geoPath(projection);

// (Ocean gridlines/graticule intentionally omitted for a cleaner map.)

let worldTopology = null;  // stored for confederation boundary computation

// Disputed/partly-recognised areas the atlas draws as their own polygon, mapped
// to the parent country they should be coloured/clicked as (by ISO numeric id).
// Matched on the geometry's properties.name. Crimea is usually NOT a separate
// feature (it sits inside Russia/Ukraine, both UEFA-blue) so it's a no-op then.
const aliasPaths = [];     // disputed-area <path>s that inherit a parent's colour
// Numeric-ISO areas to recolour as a parent country (own ISO id in the atlas).
// Deliberately empty: we only merge a territory into a parent where there is a
// clear international/UN consensus on sovereignty. Western Sahara (732) is NOT
// merged into Morocco — the UN lists it as a non-self-governing territory whose
// status is unresolved, so it stays a distinct (neutral, no-data) territory.
const ISO_REASSIGN = {{}};
// Non-numeric disputed geometries to recolour as their parent — only cases with
// broad international consensus on sovereignty (cf. UN resolutions):
const DISPUTED_PARENT = [
  [/n\\.?\\s*cyprus|northern cyprus/i, 196],  // "N. Cyprus" (recognised only by Turkey) -> Cyprus
  [/crimea/i, 804],                            // (carved out of Russia below) -> Ukraine
];
function disputedParentId(name) {{
  if (!name) return null;
  for (const [re, id] of DISPUTED_PARENT) if (re.test(name)) return id;
  return null;
}}

function redrawMapPaths() {{
  gBg.selectAll(".geo-bg").attr("d", pathGen);
  gMap.selectAll(".country-fill").attr("d", pathGen);
  gBorder.selectAll(".geo-border,.conf-boundary,.country-boundary").attr("d", pathGen);
}}

// Shared event handlers for all country paths
function onCountryClick(event) {{
  event.stopPropagation();
  if (this._countryNode) drillInto(this._countryNode);
  else if (this._confNode) drillInto(this._confNode);
}}
// World view only: brighten every country in a confederation so hovering shows
// the whole bloc is selectable. Operates on the flat conf-coloured paths
// (el._confNode set); a no-op at country level (choropleth shades, _confNode null).
let _hoverConf = null;
function highlightConf(confNode) {{
  if (_hoverConf === confNode) return;
  _hoverConf = confNode;
  countryPathMap.forEach(el => {{
    if (!el._confNode) return;
    d3.select(el).attr("fill", el._confNode === confNode
      ? darken(el._confNode.colour, 0.45) : el._confNode.colour);
  }});
}}
function onCountryMousemove(event) {{
  const el = this;
  if (el._countryNode) {{                 // confederation selected -> per-country tooltip
    const n = el._countryNode;
    tip.innerHTML = `<b>${{flagImg(n.label)}}${{n.label}}</b><br>${{herePhrase(n.total)}}<br><i style="color:#888">Click to view leagues</i>`;
    tip.style.display = "block";
    tip.style.left = (event.clientX + 16) + "px";
    tip.style.top = Math.min(event.clientY - 8, window.innerHeight - tip.offsetHeight - 10) + "px";
  }} else if (el._confNode) {{            // world view -> highlight the bloc, no tooltip
    highlightConf(el._confNode);
    tip.style.display = "none";
  }} else {{
    tip.style.display = "none";
  }}
}}
function onCountryMouseleave() {{ tip.style.display = "none"; highlightConf(null); }}

// Helper: look up path element by ISO code, with UK home-nations fallback
function getCountryPath(iso) {{
  if (countryPathMap.has(iso)) return countryPathMap.get(iso);
  if (iso === "gb-eng" || iso === "gb-sct" || iso === "gb-wls" || iso === "gb-nir")
    return countryPathMap.get(826);  // fallback if Highcharts data didn't load
  return undefined;
}}

// Coverage self-check: after the atlas loads, report any squad country that has
// no polygon to colour (missing ISO mapping, or ISO absent from the atlas).
function checkMapCoverage() {{
  const missing = [];
  let total = 0;
  RAW.forEach(conf => conf.countries.forEach(co => {{
    total++;
    if (co.isoCode == null)            missing.push(`${{co.country}} — no ISO code mapped`);
    else if (!getCountryPath(co.isoCode)) missing.push(`${{co.country}} — ISO ${{co.isoCode}} not found on map`);
  }}));
  if (missing.length)
    console.warn(`[map coverage] ${{missing.length}} of ${{total}} countries will NOT render:\\n  ` + missing.join("\\n  "));
  else
    console.info(`[map coverage] OK — all ${{total}} squad countries have a map polygon.`);
}}

// UK home nations embedded directly (no CDN dependency).
// Simplified polygons at ~110 m scale — accurate enough at world-map zoom.
const UK_NATIONS = {uk_nations_json};
const DISSOLVED_LEAGUE = {dissolved_league_json};
const FLAG_CODES = {flag_codes_json};

// ── Flags (flagcdn.com images) ─────────────────────────────────────────────
function flagCode(name) {{ return FLAG_CODES[(name || "").trim()] || null; }}
// Inline flag image for HTML panels (sidebar, breadcrumb, player list/detail).
function flagImg(name, cls) {{
  const c = flagCode(name);
  if (!c) return "";
  return `<img class="flag${{cls ? " " + cls : ""}}" loading="lazy" alt="" `
       + `src="https://flagcdn.com/w20/${{c}}.png" `
       + `srcset="https://flagcdn.com/w40/${{c}}.png 2x" `
       + `onerror="this.style.display='none'">`;
}}
// Append a flag <image> to a D3 selection (SVG node labels). w:h kept at 4:3.
function flagSvg(sel, name, x, y, h) {{
  const c = flagCode(name);
  if (!c) return;
  sel.append("image")
    .attr("href", `https://flagcdn.com/w40/${{c}}.png`)
    .attr("x", x).attr("y", y - h / 2)
    .attr("height", h).attr("width", h * 4 / 3)
    .attr("preserveAspectRatio", "xMidYMid meet")
    .style("pointer-events", "none");
}}

function addUKNationPaths() {{
  const features = UK_NATIONS.map(n => {{
    const f = {{
      type: "Feature",
      properties: {{ "hc-key": n.hcKey, name: n.name }},
      geometry: JSON.parse(JSON.stringify(n.geometry))   // copy (may reverse below)
    }};
    // d3-geo needs CLOCKWISE exterior rings. If geoArea reports more than a
    // hemisphere (2π), the winding is inverted → reverse every ring (handles
    // both Polygon and MultiPolygon, e.g. Scotland's many islands).
    if (d3.geoArea(f) > 2 * Math.PI) {{
      const g = f.geometry;
      if (g.type === "Polygon") g.coordinates.forEach(r => r.reverse());
      else if (g.type === "MultiPolygon")
        g.coordinates.forEach(poly => poly.forEach(r => r.reverse()));
    }}
    return f;
  }});
  gMap.selectAll("path.uk-nation")
    .data(features).enter().append("path")
    .attr("class","country-fill uk-nation")
    .attr("d", pathGen)
    .attr("fill","#c6ccd3").attr("stroke","none").attr("visibility","hidden")
    .each(function(d) {{ countryPathMap.set(d.properties["hc-key"], this); }})
    .on("click", onCountryClick)
    .on("mousemove", onCountryMousemove)
    .on("mouseleave", onCountryMouseleave);
}}

// UK home nations are added synchronously — always available when render() runs
addUKNationPaths();

// Load world atlas async (50m resolution, better coastlines).
// Prefer a vendored local copy (drop countries-50m.json next to this HTML) —
// works offline / on locked-down networks — and fall back to the CDN.
// UK (826) excluded — replaced by the four embedded home-nation polygons above
d3.json("countries-50m.json")
  .catch(() => d3.json("https://cdn.jsdelivr.net/npm/world-atlas@2/countries-50m.json"))
  .then(world => {{
    worldTopology = world;
    const features = topojson.feature(world, world.objects.countries).features
      .filter(f => +f.id !== 826);

    // Carve the Crimea peninsula out of Russia's geometry and re-tag it as a
    // "Crimea" feature, which the disputed-area alias machinery then colours and
    // makes clickable as Ukraine. (In this atlas Crimea sits inside Russia 643.)
    (function reassignCrimea() {{
      const ru = features.find(f => +f.id === 643);
      if (!ru || !ru.geometry) return;
      const polys = ru.geometry.type === "MultiPolygon" ? ru.geometry.coordinates
                  : ru.geometry.type === "Polygon" ? [ru.geometry.coordinates] : [];
      const inCrimea = ring => {{
        let x0=Infinity,x1=-Infinity,y0=Infinity,y1=-Infinity;
        for (const p of ring) {{ if(p[0]<x0)x0=p[0]; if(p[0]>x1)x1=p[0]; if(p[1]<y0)y0=p[1]; if(p[1]>y1)y1=p[1]; }}
        const cx=(x0+x1)/2, cy=(y0+y1)/2;
        return cx>32 && cx<37 && cy>44 && cy<46.5 && (x1-x0)<6 && (y1-y0)<4;
      }};
      const crimea=[], rest=[];
      polys.forEach(poly => (inCrimea(poly[0]) ? crimea : rest).push(poly));
      if (!crimea.length) {{
        console.info("[crimea] no separate Crimea polygon found inside Russia (643) "
                   + "— it may be merged into the mainland or already part of Ukraine.");
        return;
      }}
      ru.geometry = {{ type:"MultiPolygon", coordinates: rest }};
      features.push({{ type:"Feature", id:"crimea", properties:{{name:"Crimea"}},
                      geometry:{{ type:"MultiPolygon", coordinates: crimea }} }});
      console.info(`[crimea] carved ${{crimea.length}} polygon(s) out of Russia -> coloured as Ukraine.`);
    }})();

    gMap.selectAll("path.country-fill:not(.uk-nation)")
      .data(features).enter().append("path")
      .attr("class","country-fill")
      .attr("d", pathGen)
      .attr("fill","#c6ccd3").attr("stroke","none").attr("visibility","hidden")
      .each(function(d) {{
        const id = +d.id;
        if (Number.isFinite(id) && ISO_REASSIGN[id]) {{   // e.g. W. Sahara (732) -> Morocco
          this._aliasOf = ISO_REASSIGN[id]; aliasPaths.push(this);
          return;
        }}
        if (!Number.isFinite(id)) {{       // no ISO id (Somaliland, Kosovo, N. Cyprus…)
          const pid = disputedParentId(d.properties && d.properties.name);
          if (pid) {{ this._aliasOf = pid; aliasPaths.push(this); }}   // colour as parent
          return;
        }}
        // Some ISO ids appear on more than one geometry — e.g. 036 is shared by
        // mainland Australia AND the tiny "Ashmore and Cartier Is." reef. Keep the
        // largest-area polygon so the country itself is what gets coloured.
        const prev = countryPathMap.get(id);
        const area = d3.geoArea(d);
        if (!prev || area > (prev.__geoArea || 0)) {{
          this.__geoArea = area;
          countryPathMap.set(id, this);
        }}
      }})
      .on("click", onCountryClick)
      .on("mousemove", onCountryMousemove)
      .on("mouseleave", onCountryMouseleave);

    gBorder.append("path")
      .datum(topojson.mesh(world, world.objects.countries, (a,b) => a !== b))
      .attr("class","geo-border")
      .attr("fill","none")
      .attr("stroke","rgba(70,84,99,0.45)")
      .attr("stroke-width", 0.5)
      .attr("visibility","hidden");

    redrawMapPaths();
    checkMapCoverage();   // warn in console if any squad country lacks a polygon
    if (geoMode) {{
      const mapVis = "visible";
      gBg.selectAll(".geo-bg").attr("visibility", mapVis);
      gMap.selectAll(".country-fill").attr("visibility", mapVis);
      gBorder.selectAll(".geo-border").attr("visibility", mapVis);
      paintChoropleth(currentNodes);
      // Re-fit now that the atlas is loaded: the initial (transition) fit fires
      // before the map arrives and doesn't stick, leaving the world view zoomed
      // in with North America behind the panels. A synchronous fit is reliable.
      fitToCoords(getChoroplethCoords(currentNodes), false);
    }}
  }})
  .catch(() => {{
    // Atlas CDN unavailable — UK nations still work (embedded above)
    redrawMapPaths();
    if (geoMode) {{ paintChoropleth(currentNodes); fitToCoords(getChoroplethCoords(currentNodes), false); }}
  }});

// ── Zoom ─────────────────────────────────────────────────────────────────
// geoMode=true  → choropleth map view (confederation / country levels)
//                 update projection directly on every zoom event
// geoMode=false → free-simulation view (league / club levels)
//                 apply CSS transform to the node group
let geoMode = false;
let _clabTimer = null;

const zoomBehaviour = d3.zoom().scaleExtent([0.3, 60])
  .on("zoom", e => {{
    if (geoMode) {{
      projection
        .scale(baseScale * e.transform.k)
        .translate([baseTx + e.transform.x, baseTy + e.transform.y]);
      redrawMapPaths();
      // Reposition confederation labels bound with [lon,lat] datum
      gLabels.selectAll("text").attr("transform", function() {{
        const c = d3.select(this).datum();
        const p = c ? projection(c) : null;
        return p ? `translate(${{p[0]}},${{p[1]}})` : "translate(-9999,-9999)";
      }});
      // Country labels: follow live, then recompute which fit once the gesture settles.
      repositionCountryLabels();
      clearTimeout(_clabTimer);
      _clabTimer = setTimeout(() => renderCountryLabels(currentNodes), 90);
    }} else {{
      g.attr("transform", e.transform);
    }}
  }});
svg.call(zoomBehaviour);

// ── Choropleth helpers ────────────────────────────────────────────────────
// Compute fill colour: t=0 → pale tint of confColor, t=1 → deep dark shade
function choroplethFill(confColor, t) {{
  const c  = d3.hsl(confColor);
  const lo = d3.hsl(c.h, Math.max(0.3, c.s * 0.5),  0.72);
  const hi = d3.hsl(c.h, Math.min(1.0, c.s * 1.05), 0.26);
  return d3.interpolateHsl(lo, hi)(Math.sqrt(t)).toString();
}}

// Return the list of [lon,lat] coords for all active countries in nodes
function getChoroplethCoords(nodes) {{
  if (!nodes.length) return [];
  if (nodes[0].type === "confederation")
    return nodes.flatMap(n => n._data.countries.map(c => c.coords));
  if (nodes[0].type === "country")
    return nodes.map(n => n._data.coords);
  return [];
}}

// Paint (or repaint) the country fills based on current-level data
function paintChoropleth(nodes) {{
  _hoverConf = null;                 // drop any stale hover-highlight state
  // Reset every country path: clear fill, stroke, and node references
  countryPathMap.forEach(el => {{
    el._confNode = null; el._coData = null; el._countryNode = null;
    d3.select(el).attr("fill", "#c6ccd3").attr("stroke", "none").style("cursor", "default");
  }});
  aliasPaths.forEach(el => {{
    el._confNode = null; el._coData = null; el._countryNode = null;
    d3.select(el).attr("fill", "#c6ccd3").attr("stroke", "none").style("cursor", "default");
  }});
  // Remove any previously drawn boundary overlays
  gBorder.selectAll(".conf-boundary,.country-boundary").remove();

  if (!nodes.length) return;
  const type = nodes[0].type;
  const mapVis = geoMode ? "visible" : "hidden";

  if (type === "confederation") {{
    // Flat uniform colour per confederation; black boundary around each bloc
    nodes.forEach(confNode => {{
      // Fill each member country
      confNode._data.countries.forEach(co => {{
        if (!co.isoCode) return;
        const el = getCountryPath(co.isoCode);
        if (!el) return;
        d3.select(el).attr("fill", confNode.colour).style("cursor", "pointer");
        el._confNode = confNode;
        el._coData   = co;
      }});

      // Draw merged outer boundary for this confederation using the topology
      if (worldTopology) {{
        // Numeric ISO codes for countries in this confederation (excludes UK home nations)
        const confIsoNums = new Set(
          confNode._data.countries
            .map(co => co.isoCode)
            .filter(iso => typeof iso === "number")
        );
        // Also include UK (826) for UEFA so the boundary covers the British Isles
        if (confNode._data.countries.some(co =>
            ["gb-eng","gb-sct","gb-wls","gb-nir"].includes(co.isoCode))) {{
          confIsoNums.add(826);
        }}
        const geoms = worldTopology.objects.countries.geometries
          .filter(g => confIsoNums.has(+g.id));
        if (geoms.length) {{
          try {{
            const merged = topojson.merge(worldTopology, geoms);
            gBorder.append("path")
              .datum(merged)
              .attr("class", "conf-boundary")
              .attr("d", pathGen)
              .attr("fill", "none")
              .attr("stroke", "#000")
              .attr("stroke-width", 1.2)
              .attr("stroke-linejoin", "round")
              .attr("visibility", mapVis);
          }} catch(e) {{}}
        }}
      }}
    }});

  }} else if (type === "country") {{
    const confColor = nodes[0]._confColour;
    const maxP = d3.max(nodes, n => n.total) || 1;
    // For shared ISO codes pick the country with most players
    const best = new Map();
    nodes.forEach(n => {{
      const iso = n._data.isoCode;
      if (!iso) return;
      if (!best.has(iso) || n.total > best.get(iso).total) best.set(iso, n);
    }});
    best.forEach((coNode, iso) => {{
      const el = getCountryPath(iso);
      if (!el) return;
      d3.select(el)
        .attr("fill", choroplethFill(confColor, coNode.total / maxP))
        .attr("stroke", "#000")
        .attr("stroke-width", 0.7)
        .style("cursor", "pointer");
      el._countryNode = coNode;
    }});
  }}

  // Disputed areas inherit their parent country's fill + click/hover behaviour
  // (e.g. Western Sahara -> Morocco, Northern Cyprus -> Cyprus).
  aliasPaths.forEach(el => {{
    const parent = countryPathMap.get(el._aliasOf);
    if (!parent) return;
    el._confNode = parent._confNode; el._coData = parent._coData; el._countryNode = parent._countryNode;
    const ps = d3.select(parent);
    d3.select(el).attr("fill", ps.attr("fill")).attr("stroke", ps.attr("stroke"))
      .attr("stroke-width", ps.attr("stroke-width"))
      .style("cursor", parent._confNode || parent._countryNode ? "pointer" : "default");
  }});
}}

// ── Fit helpers ───────────────────────────────────────────────────────────
// Zoom to frame a list of [lon,lat] coords (used for choropleth auto-fit)
function fitToCoords(coordsList, withTransition) {{
  const savedSc = projection.scale(), savedTr = projection.translate();
  projection.scale(baseScale).translate([baseTx, baseTy]);
  const pts = coordsList
    .filter(c => c && (c[0] !== 0 || c[1] !== 0))
    .map(c => projection(c)).filter(Boolean);
  projection.scale(savedSc).translate(savedTr);
  if (!pts.length) return;
  // On phones the side panels are hidden behind buttons, so the map can use the
  // full width; reserve only a little top room for the title + breadcrumb.
  const isMobile = W <= 700;
  const pad = isMobile ? 58 : 80;   // extra room so edge labels (CONCACAF) don't clip
  const x0 = d3.min(pts, p=>p[0]) - pad, x1 = d3.max(pts, p=>p[0]) + pad;
  const y0 = d3.min(pts, p=>p[1]) - pad, y1 = d3.max(pts, p=>p[1]) + pad;
  // Reserve screen space for the title / Top-10 panels on the left (and a little
  // on top) so the map fits to the RIGHT of them — i.e. zoom out a touch and
  // shift right so North America isn't hidden behind the panels.
  const marginL = isMobile ? 8 : Math.min(340, W * 0.36);   // no left panels on mobile
  const marginT = isMobile ? 96 : 40;                        // clear title + breadcrumb
  const ZOOM_OUT = isMobile ? 1.0 : 0.94;                    // use the full width on mobile
  const k  = Math.min((W - marginL) / (x1-x0), (H - marginT) / (y1-y0), 20) * ZOOM_OUT;
  const cx = (x0+x1)/2, cy = (y0+y1)/2;
  const tx = (W + marginL) / 2 - baseTx + k * (baseTx - cx);
  const ty = (H + marginT) / 2 - baseTy + k * (baseTy - cy);
  const target = d3.zoomIdentity.translate(tx, ty).scale(k);
  if (withTransition === false) svg.call(zoomBehaviour.transform, target);
  else svg.transition().duration(450).call(zoomBehaviour.transform, target);
}}

// ── Zoom control buttons ──────────────────────────────────────────────────
function ctrlZoomIn()  {{ svg.transition().duration(300).call(zoomBehaviour.scaleBy, 1.7); }}
function ctrlZoomOut() {{ svg.transition().duration(300).call(zoomBehaviour.scaleBy, 1/1.7); }}
function ctrlFit() {{
  if (geoMode) {{
    fitToCoords(getChoroplethCoords(currentNodes), true);
  }} else {{
    const ns = g.selectAll(".node").data();
    if (!ns.length) return;
    const isLeagueFit = currentNodes[0] && currentNodes[0].type === "league";
    // Deterministic grid/pyramid nodes carry a label half-width (_half); include
    // it so wide labels never clip. The league view also needs extra left room
    // for its tier labels.
    const hasHalf = ns.some(d => d._half != null);
    const pad = (hasHalf) ? 110 : 80;
    const leftPad = isLeagueFit ? 180 : pad;
    const hw = d => (d._half != null) ? Math.max(d.r, d._half) : d.r;
    const x0 = d3.min(ns, d => (d.x||0) - hw(d)) - leftPad;
    const x1 = d3.max(ns, d => (d.x||0) + hw(d)) + pad;
    const y0 = d3.min(ns, d => (d.y||0) - d.r) - pad;
    const y1 = d3.max(ns, d => (d.y||0) + d.r) + pad;
    const k  = Math.min(W / (x1-x0), H / (y1-y0), 5);
    const cx = (x0+x1)/2, cy = (y0+y1)/2;
    svg.transition().duration(450).call(
      zoomBehaviour.transform,
      d3.zoomIdentity.translate(W/2, H/2).scale(k).translate(-cx, -cy)
    );
  }}
}}

// ── Simulation ────────────────────────────────────────────────────────────
// forceTierY lets the league view lock each league onto its pyramid-tier row;
// it is disabled (strength 0) for every other level.
let tierYof = () => H / 2;
const sim = d3.forceSimulation()
  .force("charge",  d3.forceManyBody().strength(d => -Math.max(120, d.r * 5)))
  .force("center",  d3.forceCenter(W / 2, H / 2).strength(0.15))
  .force("collide", d3.forceCollide().radius(d => d.r + 3).iterations(4))
  .force("tierX",   d3.forceX(W / 2).strength(0))
  .force("tierY",   d3.forceY(d => tierYof(d)).strength(0))
  .alphaDecay(0.03);

// ── Colour helpers ────────────────────────────────────────────────────────
function lighten(hex, amt) {{
  try {{ return d3.color(hex).brighter(amt).formatHex(); }} catch(e) {{ return hex; }}
}}
function darken(hex, amt) {{
  try {{ return d3.color(hex).darker(amt).formatHex(); }} catch(e) {{ return hex; }}
}}

// Level colour derivation. Use the bold confederation colour (matching the map)
// for league/club nodes; only a slight lift per level so depth still reads.
function levelColour(confColour, type) {{
  if (type === "confederation") return confColour;
  if (type === "country")  return confColour;
  if (type === "league")   return confColour;
  if (type === "club")     return lighten(confColour, 0.35);
  return lighten(confColour, 0.7);   // player
}}

// ── Sizing (scaled to the max within each visible set) ────────────────────
function nodeRadius(type, total, levelMax) {{
  const [mn, mx] = {{
    confederation: [8,  32],
    country:       [4,  22],
    league:        [7,  55],
    club:          [4,  45],
    player:        [12, 30],
  }}[type] || [6, 40];
  const t = levelMax > 0 ? Math.sqrt(total) / Math.sqrt(levelMax) : 0;
  return mn + t * (mx - mn);
}}

// ── Geo helpers ───────────────────────────────────────────────────────────
function geoXY(coords) {{
  // Returns [x, y] in screen space, or null if projection fails
  if (!coords || (coords[0] === 0 && coords[1] === 0)) return null;
  try {{ return projection(coords); }} catch(e) {{ return null; }}
}}

// ── Map labels (flag + country name, with collision hiding) ─────────────────
// Candidate countries to label, drawn from the visible choropleth nodes.
function labelCandidates(nodes) {{
  const out = [];
  if (!nodes.length) return out;
  if (nodes[0].type === "confederation")
    nodes.forEach(cf => cf._data.countries.forEach(co =>
      out.push({{name: co.country, coords: co.coords, total: co.totalPlayers}})));
  else if (nodes[0].type === "country")
    nodes.forEach(n => out.push({{name: n.label, coords: n._data.coords, total: n.total}}));
  return out.filter(c => c.coords && (c.coords[0] !== 0 || c.coords[1] !== 0));
}}

// Place flag+name labels greedily by player count; skip any that would overlap
// one already placed. Hidden countries still show on hover. Only shown once a
// confederation is selected (country level) — the world view stays uncluttered.
// Re-run on zoom so more appear as you zoom in.
function renderCountryLabels(nodes) {{
  gClabels.selectAll("*").remove();
  if (!geoMode || !nodes.length || nodes[0].type !== "country") return;
  const placed = [], PAD = 3;
  const hits = b => placed.some(p =>
    !(b.x1 < p.x0 - PAD || b.x0 > p.x1 + PAD || b.y1 < p.y0 - PAD || b.y0 > p.y1 + PAD));

  labelCandidates(nodes)
    .sort((a, b) => b.total - a.total)        // most players first = highest priority
    .forEach(c => {{
      const p = geoXY(c.coords); if (!p) return;
      const x = p[0], y = p[1];
      if (x < -30 || x > W + 30 || y < -30 || y > H + 30) return;   // off-screen
      const fw = flagCode(c.name) ? 15 : 0, gap = fw ? 4 : 0;
      const w = fw + gap + c.name.length * 6.1, h = 14;
      const box = {{x0: x - w/2, y0: y - h/2, x1: x + w/2, y1: y + h/2}};
      if (hits(box)) return;
      placed.push(box);
      // group positioned by transform (datum=coords) so zoom/pan can re-project it
      const grp = gClabels.append("g").datum(c.coords).attr("class", "clab")
        .attr("transform", `translate(${{x}},${{y}})`).style("pointer-events", "none");
      if (fw) flagSvg(grp, c.name, -w / 2, 0, 11);
      grp.append("text")
        .attr("x", -w / 2 + fw + gap).attr("y", 0).attr("dy", "0.35em")
        .style("font-size", "11px").style("font-weight", "600").style("fill", "#0a1626")
        .style("stroke", "rgba(255,255,255,0.92)").style("stroke-width", "3px")
        .style("stroke-linejoin", "round").style("paint-order", "stroke")
        .text(c.name);
    }});
}}

// Cheap follow during a zoom/pan gesture: re-project each placed label's anchor
// without recomputing collisions (those are refreshed shortly after, on settle).
function repositionCountryLabels() {{
  gClabels.selectAll("g.clab").attr("transform", function() {{
    const p = geoXY(d3.select(this).datum());
    return p ? `translate(${{p[0]}},${{p[1]}})` : "translate(-9999,-9999)";
  }});
}}

// ── Node builders ─────────────────────────────────────────────────────────
function makeConfNodes() {{
  const mx = d3.max(RAW, d => d.totalPlayers) || 1;
  return RAW.map(d => {{
    const pos = geoXY(d.coords);
    return {{
      id:    "conf__" + d.confederation,
      label: d.confederation,
      type:  "confederation",
      colour: d.colour,
      total: d.totalPlayers,
      r:     nodeRadius("confederation", d.totalPlayers, mx),
      _data: d,
      x: pos ? pos[0] : W / 2,
      y: pos ? pos[1] : H / 2,
    }};
  }});
}}

function makeCountryNodes(confNode) {{
  const countries = confNode._data.countries;
  const mx = d3.max(countries, c => c.totalPlayers) || 1;
  const base = confNode.colour;
  return countries.map(co => {{
    const pos = geoXY(co.coords);
    return {{
      id:    "country__" + co.country,
      label: co.country,
      type:  "country",
      colour: levelColour(base, "country"),
      total: co.totalPlayers,
      r:     nodeRadius("country", co.totalPlayers, mx),
      _data: co,
      _confColour: base,
      x: pos ? pos[0] : W / 2,
      y: pos ? pos[1] : H / 2,
    }};
  }});
}}

function makeLeagueNodes(countryNode) {{
  const leagues = countryNode._data.leagues;
  const mx = d3.max(leagues, l => l.totalPlayers) || 1;
  const base = countryNode._confColour;
  return leagues.map(lg => ({{
    id:     "league__" + lg.name,
    label:  lg.name,
    type:   "league",
    colour: levelColour(base, "league"),
    total:  lg.totalPlayers,
    level:  (lg.level === null || lg.level === undefined) ? null : lg.level,
    youth:  !!lg.youth,
    country: lg.country || "",
    r:      nodeRadius("league", lg.totalPlayers, mx),
    _data:  lg,
    _confColour: base,
  }}));
}}

function makeClubNodes(leagueNode) {{
  const clubs = leagueNode._data.clubs;
  const mx = d3.max(clubs, c => c.count) || 1;
  const base = leagueNode._confColour;
  return clubs.map(cl => ({{
    id:     "club__" + cl.name,
    label:  cl.name,
    type:   "club",
    colour: levelColour(base, "club"),
    total:  cl.count,
    country: leagueNode.country || "",
    r:      nodeRadius("club", cl.count, mx),
    _data:  cl,
    _confColour: base,
  }}));
}}

function makePlayerNodes(clubNode) {{
  // One node per player who has this club in their career path
  const players = clubNode._data.players || [];   // [{{n: name, t: nation}}]
  const base = clubNode._confColour;
  // Size by career length (well-travelled players appear larger)
  const careerLen = p => (PLAYER_DETAILS[p.n] && PLAYER_DETAILS[p.n].career.length) || 1;
  const mx = d3.max(players, careerLen) || 1;
  return players.map(p => ({{
    id:     "player__" + clubNode.label + "__" + p.n,
    label:  p.n,
    type:   "player",
    colour: levelColour(base, "player"),
    total:  careerLen(p),                 // = number of clubs in career
    nation: p.t,
    r:      nodeRadius("player", careerLen(p), mx),
    _data:  p,
    _confColour: base,
  }}));
}}

function makePlayerDetailNode(playerNode) {{
  const det = PLAYER_DETAILS[playerNode.label]
            || {{ nation: playerNode.nation, conf: "", career: [] }};
  return {{
    id:     "detail__" + playerNode.label,
    label:  playerNode.label,
    type:   "playerDetail",
    colour: playerNode.colour,
    _confColour: playerNode._confColour,
    _data:  det,
  }};
}}

// ── Navigation stack ──────────────────────────────────────────────────────
// Each frame: {{ label, nodes }}  (nodes = what was showing before drilling in)
let navStack = [];
let currentNodes = makeConfNodes();

// Children of a node (one level down), or null for a leaf.
function makeChildren(node) {{
  if (node.type === "confederation") return makeCountryNodes(node);
  if (node.type === "country")       return makeLeagueNodes(node);
  if (node.type === "league")        return makeClubNodes(node);
  if (node.type === "club")          return makePlayerNodes(node);
  if (node.type === "player")        return [makePlayerDetailNode(node)];
  return null;  // playerDetail: leaf
}}

function drillInto(node) {{
  const children = makeChildren(node);
  if (!children) return;

  // For free-simulation levels, seed child positions near the parent
  const isChoroplethChildren = children.length &&
    (children[0].type === "confederation" || children[0].type === "country");
  if (!isChoroplethChildren) {{
    const cx = W / 2, cy = H / 2;
    children.forEach(n => {{
      n.x = cx + (Math.random() - 0.5) * 120;
      n.y = cy + (Math.random() - 0.5) * 120;
    }});
  }}

  navStack.push({{ label: node.label, nodes: currentNodes }});
  currentNodes = children;
  updateBreadcrumb();
  render(currentNodes);
}}

// toDepth: index of the stack frame to pop back to (0 = all the way back)
function drillUp(toDepth) {{
  if (navStack.length === 0) return;
  const target = (toDepth !== undefined) ? toDepth : navStack.length - 1;
  while (navStack.length > target) {{
    currentNodes = navStack.pop().nodes;
  }}
  updateBreadcrumb();
  render(currentNodes);
}}

// ── Breadcrumb ────────────────────────────────────────────────────────────
function updateBreadcrumb() {{
  const bc = document.getElementById("breadcrumb");
  const parts = [{{ label: "All", depth: 0 }}];
  navStack.forEach((f, i) => parts.push({{ label: f.label, depth: i + 1 }}));
  // navStack order is fixed: 0=confederation, 1=country, 2=league, 3=club, 4=player.
  const countryCtx = navStack[1] ? navStack[1].label : null;

  bc.innerHTML = parts.map((p, i) => {{
    const j = i - 1;                       // navStack index for this crumb
    const flag = (j === 1) ? flagImg(p.label)          // the country crumb
               : (j === 2) ? flagImg(countryCtx)       // the league crumb
               : "";
    const isLast = i === parts.length - 1;
    const sep = i > 0 ? '<span class="bc-sep">›</span>' : "";
    if (isLast) {{
      return sep + `<span class="bc-current">${{flag}}${{p.label}}</span>`;
    }}
    return sep + `<span class="bc-link" onclick="drillUp(${{p.depth}})">${{flag}}${{p.label}}</span>`;
  }}).join(" ");
}}

// ── Sidebar ───────────────────────────────────────────────────────────────
function extractClubs(nodes) {{
  // Flatten all clubs reachable from the current visible nodes.
  // Map: name -> {{count, league}} — keeps highest count if name appears twice.
  const map = new Map();
  function addClub(name, count, league, country) {{
    const ex = map.get(name);
    if (!ex || count > ex.count) map.set(name, {{count, league: league || "", country: country || ""}});
  }}
  for (const n of nodes) {{
    if (n.type === "confederation") {{
      for (const co of n._data.countries)
        for (const lg of co.leagues)
          for (const cl of lg.clubs) addClub(cl.name, cl.count, lg.name, co.country);
    }} else if (n.type === "country") {{
      for (const lg of n._data.leagues)
        for (const cl of lg.clubs) addClub(cl.name, cl.count, lg.name, n.label);
    }} else if (n.type === "league") {{
      for (const cl of n._data.clubs) addClub(cl.name, cl.count, n._data.name, n.country);
    }} else if (n.type === "club") {{
      addClub(n.label, n.total, "", n.country);
    }}
  }}
  return [...map.entries()]
    .map(([name, {{count, league, country}}]) => ({{name, count, league, country}}))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}}

// Top countries by deduplicated player count, drawn from the visible nodes.
// Top leagues by deduplicated player count, drawn from the visible nodes.
// Keyed by country|league so same-named leagues in different countries stay apart.
function extractLeagues(nodes) {{
  const map = new Map();
  const add = (name, total, country) => {{
    const key = country + "|" + name;
    const ex = map.get(key);
    if (!ex || total > ex.total) map.set(key, {{name, total, country}});
  }};
  for (const n of nodes) {{
    if (n.type === "confederation")
      for (const co of n._data.countries)
        for (const lg of co.leagues) add(lg.name, lg.totalPlayers, co.country);
    else if (n.type === "country")
      for (const lg of n._data.leagues) add(lg.name, lg.totalPlayers, n.label);
    else if (n.type === "league")
      add(n.label, n.total, n.country);
  }}
  return [...map.values()]
    .sort((a, b) => b.total - a.total || a.name.localeCompare(b.name));
}}

// Turn a value-sorted list into ranked display rows. Equal values share a rank,
// shown as "=N" (competition ranking). Aim for BASE rows but never split a tie:
// extend up to MAX to finish the tie at the cut-off; if that tie is too big to
// list, collapse it into one "<n> clubs" summary row instead.
function rankRows(items, valueOf) {{
  const BASE = 10, MAX = 13, out = [];
  let i = 0;
  while (i < items.length) {{
    let j = i;
    while (j < items.length && valueOf(items[j]) === valueOf(items[i])) j++;
    const size = j - i, rankStr = (size > 1 ? "=" : "") + (i + 1);
    if (out.length + size <= BASE) {{                 // whole tie fits within target
      for (let k = i; k < j; k++) out.push({{rankStr, item: items[k], value: valueOf(items[k])}});
      i = j;
      continue;
    }}
    if (out.length < BASE) {{                          // this tie straddles the cut-off
      if (out.length + size <= MAX)                   // small enough to list in full
        for (let k = i; k < j; k++) out.push({{rankStr, item: items[k], value: valueOf(items[k])}});
      else                                            // too many tied -> summarise
        out.push({{rankStr, summary: size, value: valueOf(items[i])}});
    }}
    break;
  }}
  return out;
}}

function updateSidebar(nodes) {{
  const level = nodes.length ? nodes[0].type : "";
  const sb = document.getElementById("sidebar");
  const showClubs   = ["confederation", "country", "league", "club"].includes(level);
  const showLeagues = ["confederation", "country"].includes(level);  // hides once a country is selected
  document.getElementById("sb-clubs-box").style.display   = showClubs   ? "block" : "none";
  document.getElementById("sb-leagues-box").style.display = showLeagues ? "block" : "none";
  if (!showClubs && !showLeagues) {{
    sb.style.display = "none";
    document.body.classList.add("lists-empty");
    document.body.classList.remove("m-lists");   // nothing to show -> close drawer
    syncMobileButtons();
    return;
  }}
  document.body.classList.remove("lists-empty");
  sb.style.display = "block";
  document.querySelector("#sb-clubs-box h3").innerHTML   =
    `<span>Top Clubs · ${{basisShort()}}</span><span class="sb-h-count">Players</span>`;
  document.querySelector("#sb-leagues-box h3").innerHTML =
    `<span>Top Leagues · ${{basisShort()}}</span><span class="sb-h-count">Players</span>`;

  if (showClubs) {{
    const clubRows = rankRows(extractClubs(nodes), c => c.count);
    const elc = document.getElementById("sb-list");
    elc.innerHTML = clubRows.map((r, i) => r.summary
        ? `<div class="sb-row sb-tie">
            <span class="sb-rank">${{r.rankStr}}</span>
            <span class="sb-name">${{r.summary}} clubs</span>
            <span class="sb-count">${{r.value}}</span>
          </div>`
        : `<div class="sb-row sb-link" data-i="${{i}}" title="Show ${{esc(r.item.name)}}">
            <span class="sb-rank">${{r.rankStr}}</span>
            <span class="sb-name">
              ${{flagImg(r.item.country)}}${{esc(r.item.name)}}${{r.item.league ? `<span class="sb-league">${{esc(r.item.league)}}</span>` : ""}}
            </span>
            <span class="sb-count">${{r.item.count}}</span>
          </div>`
      ).join("");
    elc.querySelectorAll(".sb-link").forEach(row => {{
      const r = clubRows[+row.dataset.i];
      row.onclick = () => {{ closeMobilePanels(); gotoClubInView(r.item.country, r.item.name); }};
    }});
  }}
  if (showLeagues) {{
    const lgRows = rankRows(extractLeagues(nodes), l => l.total);
    const ellg = document.getElementById("sb-leagues");
    ellg.innerHTML = lgRows.map((r, i) => r.summary
        ? `<div class="sb-row sb-tie">
            <span class="sb-rank">${{r.rankStr}}</span>
            <span class="sb-name">${{r.summary}} leagues</span>
            <span class="sb-count">${{r.value}}</span>
          </div>`
        : `<div class="sb-row sb-link" data-i="${{i}}" title="Show ${{esc(r.item.name)}}">
            <span class="sb-rank">${{r.rankStr}}</span>
            <span class="sb-name">
              ${{flagImg(r.item.country)}}${{esc(r.item.name)}}<span class="sb-league">${{esc(r.item.country)}}</span>
            </span>
            <span class="sb-count">${{r.item.total}}</span>
          </div>`
      ).join("");
    ellg.querySelectorAll(".sb-link").forEach(row => {{
      const r = lgRows[+row.dataset.i];
      row.onclick = () => {{ closeMobilePanels(); gotoLeague(r.item.country, r.item.name); }};
    }});
  }}
}}

// ── Player list (alphabetical, surname-aware) ──────────────────────────────
// Nations that write the family name first (so the leading token is the surname).
const FAMILY_FIRST_NATIONS = new Set([
  "Korea Republic", "South Korea", "Korea DPR", "North Korea",
  "China", "China PR", "Hong Kong", "Chinese Taipei"
]);
// Nations where players are universally known by their first name / nickname
// (Brazilian football naming), so we sort on the leading token.
const FIRST_NAME_NATIONS = new Set(["Brazil"]);
// Name suffixes to skip when locating a Western surname.
const NAME_SUFFIX = new Set(["jr", "jr.", "junior", "ii", "iii", "iv", "v",
                             "filho", "neto", "sobrinho", "sr", "sr."]);
// Surname particles to fold into the surname (e.g. "van Dijk", "de Bruyne").
const NAME_PARTICLE = new Set(["van", "von", "de", "der", "den", "des", "du",
  "di", "da", "das", "dos", "del", "della", "la", "le", "el", "al", "bin",
  "ben", "ibn", "mac", "mc", "o", "ter", "ten", "te", "af", "av", "vande", "vander"]);

function _strip(s) {{
  return s.normalize("NFD").replace(/[\\u0300-\\u036f]/g, "").toLowerCase()
          .replace(/\\.$/, "");
}}

// Returns {{ key, html }} — `key` sorts the list; `html` is the name in its
// natural display order with the sort token (surname / family name / nickname)
// bolded in place, so it reads normally but is easy to scan.
function playerSortName(name, nation) {{
  const bare = name.replace(/\\s*\\([^)]*\\)\\s*$/, "").trim();   // drop "(Nation)"
  const toks = bare.split(/\\s+/);
  let start, end;
  if (toks.length === 1 || FAMILY_FIRST_NATIONS.has(nation) || FIRST_NAME_NATIONS.has(nation)) {{
    start = 0; end = 0;                          // mononym / family-first / nickname
  }} else {{
    // Western: surname = last token (skipping suffixes), absorbing particles
    end = toks.length - 1;
    while (end > 0 && NAME_SUFFIX.has(_strip(toks[end]))) end--;
    start = end;
    while (start > 0 && NAME_PARTICLE.has(_strip(toks[start - 1]))) start--;
  }}
  const key  = _strip(toks.slice(start, end + 1).join(" "));
  const pre  = toks.slice(0, start).join(" ");
  const mid  = toks.slice(start, end + 1).join(" ");
  const post = toks.slice(end + 1).join(" ");
  let html = "<b>" + esc(mid) + "</b>";          // bold the sort token, in place
  if (pre)  html = esc(pre) + " " + html;
  if (post) html = html + " " + esc(post);
  return {{ key, html }};
}}

let plSort = "name";                                   // "name" | "pos" | "nation"
const POS_RANK = {{ GK: 0, DEF: 1, MID: 2, FWD: 3 }};   // GK -> DEF -> MID -> FWD
function plPosRank(name) {{
  const g = (PLAYER_DETAILS[name] || {{}}).grp;
  return (g in POS_RANK) ? POS_RANK[g] : 4;            // unknown positions last
}}

function renderPlayerList(nodes) {{
  const panel = document.getElementById("player-list");
  const parent = navStack.length ? navStack[navStack.length - 1].label : "";
  const rows = nodes.map(n => ({{ n, s: playerSortName(n.label, n.nation) }}));
  const byName = (a, b) => a.s.key.localeCompare(b.s.key) || a.n.label.localeCompare(b.n.label);
  if (plSort === "pos")
    rows.sort((a, b) => plPosRank(a.n.label) - plPosRank(b.n.label) || byName(a, b));
  else if (plSort === "nation")
    rows.sort((a, b) => (a.n.nation || "").localeCompare(b.n.nation || "") || byName(a, b));
  else
    rows.sort(byName);

  const opt = (v, t) => `<option value="${{v}}"${{plSort === v ? " selected" : ""}}>${{t}}</option>`;
  panel.innerHTML =
    `<div class="pl-head">${{esc(parent)}}`
    + `<span class="pl-count">${{nodes.length}} player${{nodes.length === 1 ? "" : "s"}} · ${{basisWord()}}</span></div>`
    + `<div class="pl-sortbar">Sort by <select id="pl-sort">`
    +   opt("name", "Name") + opt("pos", "Position") + opt("nation", "Nation")
    + `</select></div>`
    + `<div class="pl-rows">`
    + rows.map((r, i) => {{
        const pd = r.n._data || {{}};
        let tag = "";
        if (pd.c) {{
          tag = `<span class="pl-cur" title="currently plays here">current</span>`;
        }} else if (pd.l) {{
          const t = pd.lf ? "on loan · from " + esc(pd.lf) : "on loan";
          tag = `<span class="pl-loan" title="${{t}}">loan</span>`;
        }}
        const grp = (PLAYER_DETAILS[r.n.label] || {{}}).grp || "";
        const posBadge = grp ? `<span class="pl-pos pos-${{grp}}">${{grp}}</span>` : `<span class="pl-pos pl-pos-none"></span>`;
        return `<div class="pl-row" data-i="${{i}}">`
          + posBadge
          + `<span class="pl-name">${{r.s.html}}</span>`
          + tag
          + (r.n.nation ? `<span class="pl-nat">${{flagImg(r.n.nation)}}${{esc(r.n.nation)}}</span>` : "")
          + `</div>`;
      }}).join("")
    + `</div>`;

  const sel = document.getElementById("pl-sort");
  if (sel) sel.onchange = e => {{ plSort = e.target.value; renderPlayerList(currentNodes); }};
  panel.querySelectorAll(".pl-row").forEach(row => {{
    row.onclick = () => drillInto(rows[+row.dataset.i].n);
  }});
  panel.scrollTop = 0;
}}

// ── Player detail card ────────────────────────────────────────────────────
function esc(s) {{
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}}

// Current age from an ISO date of birth ("YYYY-MM-DD"); computed live so it
// stays accurate without re-building. null if missing/unparseable.
function ageFromDob(dob) {{
  if (!dob) return null;
  const d = new Date(dob);
  if (isNaN(d.getTime())) return null;
  const now = new Date();
  let a = now.getFullYear() - d.getFullYear();
  const m = now.getMonth() - d.getMonth();
  if (m < 0 || (m === 0 && now.getDate() < d.getDate())) a--;
  return (a >= 14 && a < 60) ? a : null;
}}

function renderPlayerDetail(node) {{
  const det = node._data || {{ nation: "", conf: "", career: [] }};
  const panel = document.getElementById("player-detail");
  const col = node._confColour || "#6cf";
  const career = det.career || [];

  const steps = career.map((c, i) => {{
    const meta = [c.years && esc(c.years), c.league && esc(c.league),
                  c.country && esc(c.country)].filter(Boolean).join(" · ");
    const loan = c.loan ? ` <span class="pd-loan">loan</span>` : "";
    return `<div class="pd-step${{c.loan ? ' pd-step-loan' : ''}}">
      <div class="pd-club"><span class="pd-clublink" data-ci="${{i}}" title="Show this club">${{esc(c.name)}}</span>${{loan}}</div>
      ${{meta ? `<div class="pd-meta">${{meta}}</div>` : ""}}
    </div>`;
  }}).join("");
  const nClubs = new Set(career.map(c => c.name)).size;
  const wiki = det.url
    ? `<a class="pd-wiki" href="${{esc(det.url)}}" target="_blank" rel="noopener">Wikipedia ↗</a>`
    : "";
  const age = ageFromDob(det.dob);
  const grpBadge = det.grp ? `<span class="pd-posb pos-${{det.grp}}">${{det.grp}}</span>` : "";
  const bioParts = [det.pos && esc(det.pos), age != null ? "Age " + age : ""].filter(Boolean);
  const bio = (grpBadge || bioParts.length)
    ? `<div class="pd-bio">${{grpBadge}}${{bioParts.join(" · ")}}</div>` : "";

  panel.style.setProperty("--conf-col", col);
  panel.innerHTML = `
    <button class="pd-close" onclick="drillUp()" title="Back">&times;</button>
    <div class="pd-name">${{esc(node.label)}}</div>
    <div class="pd-nation">${{flagImg(det.nation)}}${{esc(det.nation || "—")}}<span class="pd-conf">${{esc(det.conf || "")}}</span></div>
    ${{bio}}
    ${{wiki}}
    <div class="pd-section">Career path · ${{nClubs}} club${{nClubs === 1 ? "" : "s"}}</div>
    <div class="pd-timeline">${{steps || '<div class="pd-meta">No career data available</div>'}}</div>
    <div class="pd-hint">Click a club to see its players · &times; or background to go back</div>
  `;

  // Clicking a club in the timeline jumps to that club's player list.
  panel.querySelectorAll(".pd-clublink").forEach(el => {{
    el.onclick = () => {{
      const c = career[+el.dataset.ci];
      navigateToClub(c.country, c.league, c.name);
    }};
  }});
}}

// Jump straight to a club's player list (used by the career-timeline links).
// The timeline shows a player's WHOLE career, so navigate in the "all" view
// where every career club exists; find the league that actually holds the club
// (covers dissolved clubs, which live under a "Dissolved clubs" league).
function navigateToClub(country, league, name) {{
  // From the career timeline (full career), so jump in the "all" view.
  if (FILTER !== "all") {{ FILTER = "all"; RAW = DATA.all; updateFilterUI(); }}
  if (!gotoClubInView(country, name)) drillUp(0);   // not present -> world view
}}

// Drill to a club's player list within the CURRENT filter (used by the sidebar).
// Finds the confederation + the league that actually contains the club.
function gotoClubInView(country, name) {{
  for (const cf of RAW) for (const co of cf.countries) {{
    if (co.country !== country) continue;
    for (const lg of co.leagues)
      if (lg.clubs.some(c => c.name === name)) {{
        gotoPath([cf.confederation, country, lg.name, name]);
        return true;
      }}
  }}
  return false;
}}

// Drill to a country's leagues (the pyramid) within the current filter.
function gotoCountry(country) {{
  for (const cf of RAW) for (const co of cf.countries)
    if (co.country === country) {{ gotoPath([cf.confederation, country]); return true; }}
  return false;
}}

// Rebuild the nav stack by drilling a sequence of node labels, then render.
function gotoPath(labels) {{
  navStack = [];
  currentNodes = makeConfNodes();
  for (const label of labels) {{
    const node = currentNodes.find(n => n.label === label);
    const kids = node && makeChildren(node);
    if (!kids || !kids.length) break;
    const isChoro = kids[0].type === "confederation" || kids[0].type === "country";
    if (!isChoro) kids.forEach(n => {{ n.x = W/2 + (Math.random()-0.5)*120;
                                       n.y = H/2 + (Math.random()-0.5)*120; }});
    navStack.push({{ label: node.label, nodes: currentNodes }});
    currentNodes = kids;
  }}
  updateBreadcrumb();
  render(currentNodes);
}}

// ── Render ────────────────────────────────────────────────────────────────
function render(nodes) {{
  sim.stop();
  g.selectAll("*").remove();

  const isDetail = nodes.length > 0 && nodes[0].type === "playerDetail";
  const isPlayerList = nodes.length > 0 && nodes[0].type === "player";
  const isChoropleth = !isDetail && nodes.length > 0 &&
    (nodes[0].type === "confederation" || nodes[0].type === "country");

  // Reset zoom to identity when switching between map and simulation modes
  if (isChoropleth !== geoMode) {{
    geoMode = isChoropleth;
    svg.call(zoomBehaviour.transform, d3.zoomIdentity);
  }} else {{
    geoMode = isChoropleth;
  }}

  const mapVis = isChoropleth ? "visible" : "hidden";
  gBg.selectAll(".geo-bg").attr("visibility", mapVis);
  gMap.selectAll(".country-fill").attr("visibility", mapVis);
  // include the confederation/country boundary overlays so they don't linger
  // behind a node view when you jump straight here via a pop-out hyperlink.
  gBorder.selectAll(".geo-border, .conf-boundary, .country-boundary").attr("visibility", mapVis);
  gLabels.attr("visibility", mapVis);
  gClabels.attr("visibility", mapVis);

  // Light base map in choropleth mode, dark canvas otherwise
  svg.select("rect.ocean-bg").attr("fill", isChoropleth ? "#ecf2f7" : "#0d1c35");
  document.body.style.background = isChoropleth ? "#ecf2f7" : "#0d1c35";

  // Overlay panel visibility
  document.getElementById("player-detail").style.display = isDetail ? "block" : "none";
  document.getElementById("player-list").style.display = isPlayerList ? "block" : "none";

  if (isDetail) {{
    renderPlayerDetail(nodes[0]);

  }} else if (isPlayerList) {{
    renderPlayerList(nodes);

  }} else if (isChoropleth) {{
    // ── Confederation labels ──────────────────────────────────────────────
    gLabels.selectAll("*").remove();
    gLabels.attr("visibility", mapVis);
    if (nodes[0].type === "confederation") {{
      nodes.forEach(confNode => {{
        const coords = confNode._data.coords;
        if (!coords || (coords[0] === 0 && coords[1] === 0)) return;
        const pos = projection(coords);
        if (!pos) return;
        gLabels.append("text")
          .datum(coords)  // stored so zoom handler can reproject
          .attr("transform", `translate(${{pos[0]}},${{pos[1]}})`)
          .attr("text-anchor", "middle").attr("dy", "0.35em")
          .style("font-size", W <= 700 ? "12px" : "18px").style("font-weight", "800")
          .style("letter-spacing", W <= 700 ? "0.2px" : "0.5px")
          .style("fill", "#0a1626")
          // crisp white outline around the glyphs (reads on any colour)
          .style("stroke", "rgba(255,255,255,0.92)")
          .style("stroke-width", W <= 700 ? "3px" : "4px")
          .style("stroke-linejoin", "round")
          .style("paint-order", "stroke")
          .style("pointer-events", "none")
          .text(`${{confNode.label}} (${{confNode.total}})`);
      }});
    }}

    // ── Choropleth map view (confederation / country levels) ─────────────
    paintChoropleth(nodes);
    renderCountryLabels(nodes);
    fitToCoords(getChoroplethCoords(nodes), true);

  }} else {{
    // ── Node view (league pyramid / club grid / player) ───────────────────
    g.attr("transform", null);
    const isLeague = nodes.length > 0 && nodes[0].type === "league";
    const isClub   = nodes.length > 0 && nodes[0].type === "club";

    // Full node label (no truncation). In the league pyramid the column
    // spacing below is derived from this text, so long names just widen the row.
    const nodeLabelText = d => {{
      if (d.type === "player") return d.label;
      return d.label + " (" + d.total + ")";
    }};

    // League view: deterministic national pyramid — one row per tier (Level 1
    // at the top; below the numbered tiers come, in order, "Unranked", "Youth"
    // and "Dissolved"). Columns within a row are spaced so that neither the
    // circles nor their labels can overlap.
    let leagueRowY = null;
    if (isLeague) {{
      // Bottom (non-numeric) categories, top-to-bottom.
      const keyOf = n => {{
        if (n.level != null) return String(n.level);
        if (n.label === DISSOLVED_LEAGUE) return "__dissolved";
        if (n.youth) return "__youth";
        return "__unranked";
      }};
      const labelOf = k => ({{ __unranked: "Unranked", __youth: "Youth",
                               __dissolved: "Dissolved" }}[k] || ("Tier " + k));
      const lvls = [...new Set(nodes.map(n => n.level).filter(v => v != null))]
                     .sort((a, b) => a - b);
      const present = new Set(nodes.map(keyOf));
      const order = lvls.map(String)
        .concat(["__unranked", "__youth", "__dissolved"].filter(k => present.has(k)));
      const ROW = 175;
      const y0 = H / 2 - ((order.length - 1) * ROW) / 2;
      leagueRowY = k => y0 + order.indexOf(k) * ROW;

      const rows = new Map(order.map(k => [k, []]));
      nodes.forEach(n => rows.get(keyOf(n)).push(n));
      rows.forEach(arr => arr.sort((a, b) => b.total - a.total));

      // Place each row's leagues left-to-right, centred, with gaps wide enough
      // for both circle and label (half-width ≈ chars * 3.6px at 12px font).
      order.forEach(k => {{
        const arr = rows.get(k);
        const y = leagueRowY(k);
        arr.forEach(n => (n._half = Math.max(n.r + 6, nodeLabelText(n).length * 3.6)));
        const gaps = [];
        let span = 0;
        for (let i = 1; i < arr.length; i++) {{
          const gap = arr[i - 1]._half + arr[i]._half + 16;
          gaps.push(gap); span += gap;
        }}
        let x = W / 2 - span / 2;
        arr.forEach((n, i) => {{ if (i) x += gaps[i - 1]; n.x = x; n.y = y; }});
      }});

      // Tier guide lines + labels (inside g so they pan/zoom with the nodes)
      const leftX  = d3.min(nodes, d => d.x - d.r) - 30;
      const rightX = d3.max(nodes, d => d.x + d.r) + 40;
      const gl = g.append("g").attr("class", "tier-guides");
      order.forEach(k => {{
        const y = leagueRowY(k);
        gl.append("line")
          .attr("x1", leftX - 70).attr("x2", rightX).attr("y1", y).attr("y2", y)
          .attr("stroke", "rgba(255,255,255,0.07)").attr("stroke-width", 1);
        gl.append("text").attr("class", "tier-label")
          .attr("x", leftX).attr("y", y).attr("dy", "0.35em").attr("text-anchor", "end")
          .style("font-size", "13px").style("font-weight", "bold")
          .style("fill", "rgba(255,255,255,0.55)").style("pointer-events", "none")
          .text(labelOf(k));
      }});
    }}

    // Club view: alphabetical grid — clubs sorted A→Z and flowed left-to-right,
    // top-to-bottom (like reading text) so a specific club is easy to find.
    if (isClub) {{
      const sorted = nodes.slice().sort((a, b) =>
        a.label.localeCompare(b.label, undefined, {{ sensitivity: "base" }}));
      const GAP = 28;
      sorted.forEach(n => (n._half = Math.max(n.r + 6, nodeLabelText(n).length * 3.6)));
      const maxR = d3.max(sorted, n => n.r);
      const ROW_H = 2 * maxR + 56;                 // node + label + breathing room
      const totalW = d3.sum(sorted, n => 2 * n._half + GAP);
      // Aim for a roughly square overall block, but never narrower than one club
      const wTarget = Math.max(d3.max(sorted, n => 2 * n._half),
                               Math.sqrt(totalW * ROW_H));

      const rows = [[]];
      let rowW = 0;
      sorted.forEach(n => {{
        const w = 2 * n._half + GAP;
        if (rowW + w > wTarget && rows[rows.length - 1].length) {{
          rows.push([]); rowW = 0;
        }}
        rows[rows.length - 1].push(n);
        rowW += w;
      }});

      let y = H / 2 - ((rows.length - 1) * ROW_H) / 2;
      rows.forEach(row => {{
        const span = d3.sum(row, n => 2 * n._half + GAP) - GAP;
        let x = W / 2 - span / 2;
        row.forEach(n => {{ n.x = x + n._half; n.y = y; x += 2 * n._half + GAP; }});
        y += ROW_H;
      }});
    }}

    // Everything except a player-detail card can be drilled into further
    const hasChildren = n => n.type !== "playerDetail";

    const nodeSel = g.selectAll(".node")
      .data(nodes, d => d.id)
      .enter().append("g").attr("class", "node")
      .call(d3.drag()
        .on("start", (e, d) => {{ if (d.type === "league" || d.type === "club") return; if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }})
        .on("drag",  (e, d) => {{ if (d.type === "league" || d.type === "club") return; d.fx = e.x; d.fy = e.y; }})
        .on("end",   (e, d) => {{ if (d.type === "league" || d.type === "club") return; if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }}))
      .on("click", (e, d) => {{ e.stopPropagation(); drillInto(d); }})
      .on("mousemove", (e, d) => {{
        let html;
        if (d.type === "player") {{
          html = `<b>${{d.label}}</b>`
               + (d.nation ? `<br><span style="color:#aaa">${{d.nation}}</span>` : "")
               + `<br>Clubs in career: ${{d.total}}`
               + `<br><i style="color:#8a9">Click for career path</i>`;
        }} else if (d.type === "club") {{
          html = `<b>${{d.label}}</b><br>${{herePhrase(d.total)}}`
               + (d._data.dissolved ? `<br><span style="color:#e0a86a">Dissolved ${{d._data.dissolved}}</span>` : "")
               + `<br><i style="color:#aaa">Click to see players</i>`;
        }} else if (d.type === "league") {{
          const tier = (d.level != null) ? ("Tier " + d.level + " in pyramid")
                     : (d.label === DISSOLVED_LEAGUE) ? "Dissolved clubs"
                     : d.youth ? "Youth / development league (below senior pyramid)"
                     : "Unranked";
          html = `<b>${{d.label}}</b><br>${{herePhrase(d.total)}}`
               + `<br><span style="color:#9cf">${{tier}}</span>`
               + `<br><i style="color:#aaa">Click to see clubs</i>`;
        }} else {{
          html = `<b>${{d.label}}</b><br>${{herePhrase(d.total)}}`
               + `<br><i style="color:#aaa">Click to expand</i>`;
        }}
        tip.innerHTML = html;
        tip.style.display = "block";
        tip.style.left = (e.clientX + 16) + "px";
        tip.style.top  = Math.min(e.clientY - 8, window.innerHeight - tip.offsetHeight - 10) + "px";
      }})
      .on("mouseleave", () => {{ tip.style.display = "none"; }});

    nodeSel.append("circle")
      .attr("r",    d => d.r)
      .attr("fill", d => d.colour)
      .attr("stroke", d => lighten(d.colour, 1.2))
      .attr("stroke-width", 1.5);

    nodeSel.filter(hasChildren)
      .append("text")
      .attr("class", "node-indicator")
      .attr("dy", "0.35em")
      .attr("text-anchor", "middle")
      .style("font-size", d => Math.max(10, d.r * 0.45) + "px")
      .style("fill", "rgba(255,255,255,0.35)")
      .text("▼");

    nodeSel.append("text")
      .attr("class", "node-label")
      .attr("dy", d => d.r + 14)
      .attr("text-anchor", "middle")
      .style("font-size", d => {{
        if (d.type === "player") return "13px";
        if (d.type === "league") return "12px";
        if (d.type === "club") return "14px";
        return "15px";
      }})
      .style("font-weight", "normal")
      .text(nodeLabelText);

    // League labels (pyramid) get their country flag to the left of the text.
    // Position from the *actual* rendered text width so the gap is tight.
    nodeSel.filter(d => d.type === "league")
      .each(function(d) {{
        const txt = d3.select(this).select("text.node-label").node();
        const tw = txt ? txt.getComputedTextLength() : nodeLabelText(d).length * 6;
        flagSvg(d3.select(this), d.country, -tw / 2 - 16 - 3, d.r + 10, 12);
      }});

    // Players get a second line showing their national team
    nodeSel.filter(d => d.type === "player" && d.nation)
      .append("text")
      .attr("class", "node-label")
      .attr("dy", d => d.r + 28)
      .attr("text-anchor", "middle")
      .style("font-size", "10px")
      .style("fill", "rgba(255,255,255,0.6)")
      .text(d => d.nation);

    // Dissolved clubs get a second line showing the dissolution year
    nodeSel.filter(d => d.type === "club" && d._data.dissolved)
      .append("text")
      .attr("class", "node-label")
      .attr("dy", d => d.r + 28)
      .attr("text-anchor", "middle")
      .style("font-size", "10px")
      .style("fill", "#e0a86a")
      .text(d => "dissolved " + d._data.dissolved);

    if (isLeague || isClub) {{
      // Deterministic layout — no simulation; place nodes and fit immediately
      sim.stop();
      sim.on("tick", null);
      sim.on("end.autofit", null);
      g.selectAll(".node").attr("transform", d => `translate(${{d.x}},${{d.y}})`);
      ctrlFit();
    }} else {{
      sim.nodes(nodes);
      sim.force("charge").strength(d => -Math.max(120, d.r * 5));
      sim.force("center").strength(0.15);
      sim.force("collide").radius(d => d.r + 3);
      sim.force("tierX").strength(0);
      sim.force("tierY").strength(0);
      sim.alpha(0.9).restart();
      sim.on("tick", () => {{
        g.selectAll(".node").attr("transform", d => `translate(${{d.x}},${{d.y}})`);
      }});
      sim.on("end.autofit", () => {{ ctrlFit(); sim.on("end.autofit", null); }});
    }}
  }}

  updateSidebar(nodes);
}}

// Click background (svg) to go back one level
svg.on("click", () => {{ if (navStack.length > 0) drillUp(); }});

// ── Career filter ─────────────────────────────────────────────────────────
function updateFilterUI() {{
  const note = document.getElementById("filter-note");
  if (note) note.innerHTML = FILTERS[FILTER].note;
}}
function setFilter(f) {{
  if (!DATA[f] || f === FILTER) {{ FILTER = f; updateFilterUI(); return; }}
  // Remember where we are (the drill path of labels) so we can stay there
  // instead of resetting to the world view when the dataset changes.
  const path = navStack.map(fr => fr.label);
  FILTER = f;
  RAW = DATA[f];
  buildSearchIndex();            // index reflects the active filter's clubs/leagues
  navStack = [];
  currentNodes = makeConfNodes();
  // Replay the path against the new dataset, as far as it still exists.
  for (const label of path) {{
    const node = currentNodes.find(n => n.label === label);
    const kids = node && makeChildren(node);
    if (!kids || !kids.length) break;   // level absent in this view -> stop here
    const isChoro = kids[0].type === "confederation" || kids[0].type === "country";
    if (!isChoro) kids.forEach(n => {{ n.x = W/2 + (Math.random()-0.5)*120;
                                       n.y = H/2 + (Math.random()-0.5)*120; }});
    navStack.push({{ label: node.label, nodes: currentNodes }});
    currentNodes = kids;
  }}
  updateBreadcrumb();
  render(currentNodes);
  updateFilterUI();
}}

// ── Search (players, clubs, leagues, countries) ────────────────────────────
function norm(s) {{
  return (s || "").normalize("NFD").replace(/[\\u0300-\\u036f]/g, "").toLowerCase();
}}
function confColour(conf) {{
  for (const cf of DATA.all) if (cf.confederation === conf) return cf.colour;
  return "#6cf";
}}
let SEARCH_INDEX = [];
function buildSearchIndex() {{
  const idx = [];
  for (const cf of RAW) for (const co of cf.countries) {{
    idx.push({{type:"country", label: co.country, sub: cf.confederation, country: co.country}});
    for (const lg of co.leagues) {{
      idx.push({{type:"league", label: lg.name, sub: co.country, country: co.country, league: lg.name}});
      for (const cl of lg.clubs)
        idx.push({{type:"club", label: cl.name, sub: lg.name + " · " + co.country,
                   country: co.country, league: lg.name, name: cl.name}});
    }}
  }}
  for (const key in PLAYER_DETAILS) {{
    const pd = PLAYER_DETAILS[key];
    idx.push({{type:"player", label: key.replace(/\\s*\\([^)]*\\)\\s*$/, ""),
               sub: pd.nation || "", playerKey: key}});
  }}
  idx.forEach(e => e._n = norm(e.label));
  SEARCH_INDEX = idx;
}}

const TYPE_ORDER = {{ country: 0, league: 1, club: 2, player: 3 }};
function doSearch(q) {{
  const n = norm(q.trim());
  if (!n) return [];
  const hits = [];
  for (const e of SEARCH_INDEX) {{
    const i = e._n.indexOf(n);
    if (i >= 0) hits.push({{e, starts: i === 0 ? 1 : 0}});
  }}
  hits.sort((a, b) =>
    (b.starts - a.starts) ||
    (a.e.label.length - b.e.label.length) ||
    (TYPE_ORDER[a.e.type] - TYPE_ORDER[b.e.type]) ||
    a.e.label.localeCompare(b.e.label));
  return hits.slice(0, 15).map(h => h.e);
}}

let srResults = [], srActive = -1;
function renderSearch() {{
  const box = document.getElementById("search-results");
  const q = document.getElementById("search-input").value;
  srResults = doSearch(q);
  srActive = -1;
  if (!q.trim()) {{ box.classList.remove("open"); box.innerHTML = ""; return; }}
  if (!srResults.length) {{
    box.classList.add("open");
    box.innerHTML = `<div class="sr-empty">No matches for “${{esc(q)}}”</div>`;
    return;
  }}
  const flagName = e => e.type === "player" ? e.sub : e.country;
  box.innerHTML = srResults.map((e, i) =>
    `<div class="sr-item" data-i="${{i}}" title="${{esc(e.label)}}">`
    + flagImg(flagName(e))
    + `<span class="sr-main">`
    +   `<span class="sr-label">${{esc(e.label)}}</span>`
    +   (e.sub ? `<span class="sr-sub">${{esc(e.sub)}}</span>` : "")
    + `</span>`
    + `<span class="sr-type ${{e.type}}">${{e.type}}</span>`
    + `</div>`).join("");
  box.classList.add("open");
  box.querySelectorAll(".sr-item").forEach(el => {{
    // mousedown (not click) so selection fires before the input loses focus
    el.onmousedown = ev => {{ ev.preventDefault(); selectResult(srResults[+el.dataset.i]); }};
  }});
}}

function selectResult(e) {{
  if (!e) return;
  closeSearch(true);
  if      (e.type === "country") gotoCountry(e.country);
  else if (e.type === "league")  gotoLeague(e.country, e.league);
  else if (e.type === "club")    gotoClubInView(e.country, e.name);
  else if (e.type === "player")  showPlayerDetail(e.playerKey);
}}

function closeSearch(clear) {{
  const box = document.getElementById("search-results");
  box.classList.remove("open");
  document.body.classList.remove("m-search");   // also collapse the mobile search bar
  syncMobileButtons();
  if (clear) {{
    document.getElementById("search-input").value = "";
    box.innerHTML = ""; srResults = []; srActive = -1;
  }}
}}

// Drill to a league's clubs within the current filter (used by search).
function gotoLeague(country, league) {{
  for (const cf of RAW) for (const co of cf.countries)
    if (co.country === country && co.leagues.some(l => l.name === league)) {{
      gotoPath([cf.confederation, country, league]); return true;
    }}
  return false;
}}

// Open a player's profile card directly (filter-independent).
function showPlayerDetail(key) {{
  const pd = PLAYER_DETAILS[key];
  if (!pd) return;
  const node = {{ id: "detail__" + key, label: key, type: "playerDetail",
                 _confColour: confColour(pd.conf), _data: pd, nation: pd.nation }};
  navStack.push({{ label: key, nodes: currentNodes }});
  currentNodes = [node];
  updateBreadcrumb();
  render(currentNodes);
}}

(function initSearch() {{
  const input = document.getElementById("search-input");
  const box = document.getElementById("search-results");
  input.addEventListener("input", renderSearch);
  input.addEventListener("focus", () => {{ if (input.value.trim()) renderSearch(); }});
  input.addEventListener("keydown", ev => {{
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {{
      ev.preventDefault();
      if (!srResults.length) return;
      srActive = (srActive + (ev.key === "ArrowDown" ? 1 : -1) + srResults.length) % srResults.length;
      [...box.children].forEach((c, i) => c.classList.toggle("active", i === srActive));
      const act = box.children[srActive]; if (act) act.scrollIntoView({{block: "nearest"}});
    }} else if (ev.key === "Enter") {{
      if (srResults.length) selectResult(srResults[srActive >= 0 ? srActive : 0]);
    }} else if (ev.key === "Escape") {{
      closeSearch(true); input.blur();
    }}
  }});
  document.addEventListener("mousedown", ev => {{
    if (!document.getElementById("search").contains(ev.target)) box.classList.remove("open");
  }});
}})();

// Kick off
buildSearchIndex();
updateFilterUI();
updateBreadcrumb();
render(currentNodes);
</script>
</body>
</html>"""

    for out in OUTPUTS:
        Path(out).write_text(html, encoding="utf-8")
    print(f"Done. Wrote {', '.join(OUTPUTS)} — open drill_down.html locally; "
          f"index.html is the GitHub Pages copy.")

    all_countries = [c for d in data for c in d["countries"]]
    all_leagues   = [l for c in all_countries for l in c["leagues"]]
    all_clubs     = [cl for l in all_leagues for cl in l["clubs"]]
    print(f"  Confederations: {len(data)}")
    print(f"  Countries:      {len(all_countries)}")
    print(f"  Leagues:        {len(all_leagues)}")
    print(f"  Clubs:          {len(all_clubs)}")

    validate_players(data, player_details)
    validate_country_coverage(data)


if __name__ == "__main__":
    main()
