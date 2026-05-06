from __future__ import annotations

MOEX_COMMON_TICKERS = {
    "SBER", "SBERP", "GAZP", "LKOH", "ROSN", "GMKN", "NVTK", "TATN", "TATNP",
    "YDEX", "T", "TCSG", "VTBR", "MOEX", "SNGS", "SNGSP", "CHMF", "NLMK", "MAGN",
    "PLZL", "ALRS", "AFLT", "MTSS", "MGNT", "FIVE", "OZON", "HEAD", "POSI", "VKCO",
    "RUAL", "IRAO", "FEES", "AFKS", "PHOR", "TRNFP", "PIKK", "SMLT", "HYDR", "CBOM",
    "BSPB", "FLOT", "BELU", "FIXP", "MVID", "LSRG", "AQUA", "ETLN", "RTKM", "RTKMP",
    "IMOEX", "RTSI", "RGBI", "MCFTR",
}

RU_COMPANY_ALIASES: dict[str, list[str]] = {
    "SBER": ["Сбер", "Сбербанк", "Sberbank", "Sber"],
    "GAZP": ["Газпром", "Gazprom"],
    "LKOH": ["Лукойл", "Lukoil"],
    "ROSN": ["Роснефть", "Rosneft"],
    "GMKN": ["Норникель", "Норильский никель", "Nornickel"],
    "NVTK": ["Новатэк", "Novatek"],
    "YDEX": ["Яндекс", "Yandex"],
    "T": ["Т-Банк", "Тинькофф", "T-Bank", "Tinkoff"],
    "TCSG": ["Т-Банк", "Тинькофф", "T-Bank", "Tinkoff"],
    "VTBR": ["ВТБ", "VTB"],
    "MOEX": ["Московская биржа", "Мосбиржа", "MOEX"],
    "PLZL": ["Полюс", "Polyus"],
    "ALRS": ["АЛРОСА", "Alrosa"],
    "AFLT": ["Аэрофлот", "Aeroflot"],
    "MTSS": ["МТС", "MTS"],
    "MGNT": ["Магнит", "Magnit"],
    "OZON": ["Ozon", "Озон"],
    "POSI": ["Positive Technologies", "Группа Позитив"],
}


def aliases_for(symbol: str) -> list[str]:
    symbol = symbol.upper()
    return [symbol, *RU_COMPANY_ALIASES.get(symbol, [])]
