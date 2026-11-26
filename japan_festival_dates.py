"""Japan Standard Time dates for movable cultural observances."""

# Setsubun is the day before Risshun, the beginning-of-spring solar term.
# Every row was checked against both events in the NAOJ long-term ephemeris:
# https://eco.mtk.nao.ac.jp/cgi-bin/koyomi/cande/phenomena_sy.cgi?year=2028
# The first three rows were also checked against published annual almanacs:
# https://eco.mtk.nao.ac.jp/koyomi/yoko/2025/rekiyou252.html
# https://eco.mtk.nao.ac.jp/koyomi/yoko/2026/rekiyou262.html
# https://eco.mtk.nao.ac.jp/koyomi/yoko/2027/rekiyou272.html
JAPAN_SETSUBUN_PUBLISHED_THROUGH = 2027

JAPAN_SETSUBUN_DAYS: dict[int, int] = {
    2025: 2,
    2026: 3,
    2027: 3,
    2028: 3,
    2029: 2,
    2030: 3,
    2031: 3,
    2032: 3,
    2033: 2,
    2034: 3,
    2035: 3,
    2036: 3,
    2037: 2,
    2038: 3,
    2039: 3,
    2040: 3,
    2041: 2,
    2042: 3,
    2043: 3,
    2044: 3,
    2045: 2,
    2046: 3,
    2047: 3,
    2048: 3,
    2049: 2,
    2050: 3,
}

# The dates come from the NAOJ table's moon-viewing column.
# Japan discontinued the official lunisolar calendar. The 2033 row has two possible
# dates (September 8 and October 7), so this table omits that ambiguous year.
# https://eco.mtk.nao.ac.jp/koyomi/wiki/C3E6BDA9A4CECCBEB7EEA4C8A4CF2FCCBEB7EEC9ACA4BAA4B7A4E2CBFEB7EEA4CAA4E9A4BA.html
# https://www.nao.ac.jp/astro/sky/2026/09-topics03.html
JAPAN_TSUKIMI_DATES: dict[int, str] = {
    2025: "10-06",
    2026: "09-25",
    2027: "09-15",
    2028: "10-03",
    2029: "09-22",
    2030: "09-12",
    2031: "10-01",
    2032: "09-19",
    2034: "09-27",
    2035: "09-16",
    2036: "10-04",
    2037: "09-24",
    2038: "09-13",
    2039: "10-02",
    2040: "09-21",
    2041: "09-10",
    2042: "09-28",
    2043: "09-17",
    2044: "10-05",
    2045: "09-25",
    2046: "09-15",
    2047: "10-04",
    2048: "09-22",
    2049: "09-11",
    2050: "09-30",
}
