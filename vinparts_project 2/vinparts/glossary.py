"""Небольшой словарь EN → RU для названий деталей (без языковой модели).
Не найденное слово остаётся без перевода: это честнее, чем угадывать."""

from __future__ import annotations

GLOSSARY: dict[str, str] = {
    "timing chain": "цепь ГРМ", "chain tensioner": "натяжитель цепи",
    "chain guide": "успокоитель цепи", "guide rail": "направляющая (успокоитель)",
    "tensioning rail": "натяжной башмак", "sprocket": "звёздочка",
    "camshaft adjuster": "фазорегулятор", "camshaft": "распредвал",
    "crankshaft": "коленвал", "toothed belt": "ремень ГРМ", "timing belt": "ремень ГРМ",
    "tensioning roller": "натяжной ролик", "tensioner": "натяжитель", "idler": "обводной ролик",
    "coolant pump": "помпа", "water pump": "помпа", "thermostat": "термостат",
    "coolant": "охлаждающая жидкость", "engine oil": "моторное масло", "oil filter": "масляный фильтр",
    "oil seal": "сальник", "sealing ring": "уплотнительное кольцо", "o-ring": "уплотнительное кольцо",
    "gasket": "прокладка", "seal": "уплотнение", "sealant": "герметик", "bolts": "болты",
    "bolt": "болт", "nuts": "гайки", "nut": "гайка", "screw": "винт", "stud": "шпилька",
    "self-locking": "самоконтрящиеся", "washer": "шайба", "clip": "фиксатор", "hose": "шланг",
    "cover": "крышка", "timing case cover": "крышка блока ГРМ", "valve cover": "клапанная крышка",
    "spark plug": "свеча зажигания", "ignition coil": "катушка зажигания",
    "brake pad": "тормозная колодка", "brake disc": "тормозной диск", "brake fluid": "тормозная жидкость",
    "brake caliper": "суппорт", "clutch": "сцепление", "release bearing": "выжимной подшипник",
    "flywheel": "маховик", "pressure plate": "корзина сцепления", "bearing": "подшипник",
    "drain plug": "сливная пробка", "filter": "фильтр", "belt": "ремень", "pulley": "шкив",
    "vibration damper": "демпфер", "dowel": "штифт", "retaining": "стопорный",
    "locking": "стопорный", "oil": "масло", "circlip": "стопорное кольцо", "pin": "штифт",
    "retaining ring": "стопорное кольцо", "snap ring": "стопорное кольцо", "spacer": "проставка",
    "bracket": "кронштейн", "plug": "пробка", "sealing plug": "заглушка", "cap": "крышка",
    "gasket set": "комплект прокладок", "seal ring": "уплотнительное кольцо",
    "crankshaft seal": "сальник коленвала", "camshaft seal": "сальник распредвала",
    "valve stem seal": "маслосъёмный колпачок", "valve": "клапан", "piston ring": "поршневое кольцо",
    "piston": "поршень", "connecting rod": "шатун", "main bearing": "коренной подшипник",
    "oil pump": "масляный насос", "oil pan": "масляный поддон", "oil cooler": "масляный радиатор",
    "air filter": "воздушный фильтр", "fuel filter": "топливный фильтр", "pollen filter": "салонный фильтр",
    "cabin filter": "салонный фильтр", "dust and pollen filter": "салонный фильтр",
    "drive belt": "приводной ремень", "ribbed belt": "поликлиновой ремень", "v-ribbed belt": "поликлиновой ремень",
    "poly v-belt": "поликлиновой ремень", "belt tensioner": "натяжитель ремня",
    "tensioning element": "натяжной элемент", "adjusting element": "регулирующий элемент",
    "hydraulic tensioner": "гидронатяжитель", "chain wheel": "звёздочка цепи",
    "timing gear": "шестерня ГРМ", "toothed belt pulley": "шкив зубчатого ремня",
    "wheel bolt": "колёсный болт", "wheel bolts": "колёсные болты", "brake line": "тормозная трубка",
    "brake hose": "тормозной шланг", "brake pads": "тормозные колодки", "wear indicator": "датчик износа",
    "wear sensor": "датчик износа", "wheel bearing": "ступичный подшипник", "hub": "ступица",
    "axle nut": "гайка полуоси", "ball joint": "шаровая опора", "tie rod": "рулевая тяга",
    "control arm": "рычаг", "shock absorber": "амортизатор", "spring": "пружина", "boot": "пыльник",
    "dust cover": "пыльник", "gear oil": "трансмиссионное масло", "atf": "жидкость АКПП",
    "transmission fluid": "трансмиссионная жидкость", "dsg oil": "масло DSG", "mechatronic": "мехатроник",
    "turbocharger": "турбокомпрессор", "intercooler": "интеркулер", "egr valve": "клапан EGR",
    "injector": "форсунка", "fuel pump": "топливный насос", "high-pressure pump": "ТНВД",
    "glow plug": "свеча накаливания", "lambda sensor": "лямбда-зонд", "oxygen sensor": "лямбда-зонд",
    "catalytic converter": "катализатор", "exhaust": "выхлоп", "clamp": "хомут", "hose clamp": "хомут шланга",
    "battery": "аккумулятор", "alternator": "генератор", "starter": "стартер", "wiper blade": "щётка стеклоочистителя",
    "wiper": "стеклоочиститель", "fuse": "предохранитель", "bulb": "лампа", "grommet": "втулка",
    "bush": "сайлентблок", "bushing": "втулка", "mount": "опора", "engine mount": "опора двигателя",
    "coolant hose": "патрубок охлаждения", "expansion tank": "расширительный бачок", "radiator": "радиатор",
    "cylinder head gasket": "прокладка ГБЦ", "cylinder head bolts": "болты ГБЦ", "cylinder head": "ГБЦ",
    "sump": "поддон", "intake manifold": "впускной коллектор", "throttle valve": "дроссельная заслонка",
    "balance shaft": "балансирный вал", "oil separator": "маслоотделитель", "pcv valve": "клапан PCV",
}

_KEYS_BY_LENGTH = sorted(GLOSSARY, key=len, reverse=True)


def gloss(part: str) -> str | None:
    """Переводит название детали, подставляя русские слова в порядке появления."""
    text = part.lower()
    spans: list[tuple[int, int, str]] = []
    taken = [False] * len(text)
    for key in _KEYS_BY_LENGTH:
        start = 0
        while True:
            i = text.find(key, start)
            if i < 0:
                break
            j = i + len(key)
            if text[j:j + 1] == "s" and (j + 1 == len(text) or not text[j + 1].isalnum()):
                j += 1  # множественное число: sprockets, rails
            boundary_ok = (i == 0 or not text[i - 1].isalnum()) and (j == len(text) or not text[j].isalnum())
            if boundary_ok and not any(taken[i:j]):
                for k in range(i, j):
                    taken[k] = True
                spans.append((i, j, GLOSSARY[key]))
            start = j
    if not spans:
        return None
    spans.sort()
    return " ".join(ru for _, _, ru in spans)
