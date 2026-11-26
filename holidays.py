"""Statutory and commonly observed festivals for the calendar companion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal, Mapping, NotRequired, TypedDict

from china_holiday_dates import CHINA_FESTIVAL_DATES, CHINA_MOVABLE_DATES
from japan_festival_dates import JAPAN_SETSUBUN_DAYS, JAPAN_SETSUBUN_PUBLISHED_THROUGH, JAPAN_TSUKIMI_DATES


HOLIDAY_REGIONS = ("off", "cn", "jp")
_MOVABLE_OFFICIAL_THROUGH = 2027
_Category = Literal["public", "traditional", "popular", "observance"]
_DateStatus = Literal["official", "forecast", "unavailable", "not_occurring"]


class _HolidayEntry(TypedDict):
    id: str
    label: str
    message: str
    date: str | None
    dateStatus: _DateStatus
    category: _Category
    additionalDates: NotRequired[list[str]]


@dataclass(frozen=True)
class _DateTable:
    years: Mapping[int, str | tuple[str, ...]]
    confirmed_through: int = _MOVABLE_OFFICIAL_THROUGH


@dataclass(frozen=True)
class _Holiday:
    id: str
    label: str
    message: str
    # Fixed MM-DD, (month, weekday, occurrence), statutory column or local calendar table.
    rule: str | tuple[int, int, int] | int | _DateTable
    category: _Category = "public"


def _china_festival(column: int) -> _DateTable:
    return _DateTable({year: values[column] for year, values in CHINA_FESTIVAL_DATES.items()})


_CN_NEW_YEAR_EVES = _DateTable({
    year: (date.fromisoformat(f"{year}-{days[0]}") - timedelta(days=1)).strftime("%m-%d")
    for year, days in CHINA_MOVABLE_DATES.items()
})
_JP_SETSUBUN = _DateTable({year: f"02-{day:02d}" for year, day in JAPAN_SETSUBUN_DAYS.items()},
                         confirmed_through=JAPAN_SETSUBUN_PUBLISHED_THROUGH)


# China State Council Order No. 795, effective from 2025:
# https://app.www.gov.cn/govdata/gov/202411/12/521605/article.html
_CN = (
    _Holiday("cn.new_year", "元旦", "迎接公历新年，庆祝新一年的开始。", "01-01"),
    _Holiday("cn.spring_festival", "春节", "农历正月初一，辞旧迎新，也是家人团聚、互道祝福的日子。", 0),
    _Holiday("cn.qingming", "清明节", "在清明节气缅怀先人，也有扫墓祭祖和踏青的习俗。", 1),
    _Holiday("cn.labor_day", "劳动节", "向各行各业的劳动者致意，感谢他们的付出。", "05-01"),
    _Holiday("cn.dragon_boat", "端午节", "农历五月初五，常以包粽子和赛龙舟延续传统。", 2),
    _Holiday("cn.mid_autumn", "中秋节", "农历八月十五，人们赏月、分享月饼，寄托团圆之意。", 3),
    _Holiday("cn.national_day", "国庆节", "纪念中华人民共和国成立。", "10-01"),
    # Chinese festival customs and special-group holidays. Descriptions are original summaries.
    # https://wwj.beijing.gov.cn/bjww/resource/cms/article/bjww_362762/10864871/2020091610081023913.pdf
    # https://zfxxgk.ndrc.gov.cn/web/iteminfo.jsp?id=465
    # https://www.moe.gov.cn/jyb_xwfb/s5147/202606/t20260601_1438425.html
    _Holiday("cn.new_year_eve", "除夕", "农历一年的最后一天。家人常团聚吃年夜饭、守岁，辞旧迎新。", _CN_NEW_YEAR_EVES, "traditional"),
    _Holiday("cn.lantern_festival", "元宵节", "农历正月十五，常吃元宵或汤圆、赏花灯、猜灯谜，也有团圆之意。", _china_festival(0), "traditional"),
    _Holiday("cn.longtaitou", "龙抬头", "农历二月初二，寄托迎春纳吉的愿望。一些地方有理发或吃龙须面的习惯。", _china_festival(1), "traditional"),
    _Holiday("cn.qixi", "七夕（中国传统）", "农历七月初七，源于牛郎织女相会的传说，过去有乞巧习俗，如今也常被用来表达爱意。", _china_festival(2), "traditional"),
    _Holiday("cn.double_ninth", "重阳节", "农历九月初九，传统活动包括登高、赏菊和吃重阳糕，现代也常借此问候长辈。", _china_festival(3), "traditional"),
    _Holiday("cn.laba", "腊八节", "农历十二月初八，许多地方会喝腊八粥。民间也常把它当作准备过年的信号。", _china_festival(4), "traditional"),
    _Holiday("cn.winter_solstice", "冬至", "冬至是二十四节气之一。北方不少地方吃饺子，南方一些地方吃汤圆，习惯因地而异。", _china_festival(5), "traditional"),
    _Holiday("cn.valentines_day", "情人节（西方）", "公历 2 月 14 日。在中国，不少情侣会约会或送玫瑰、巧克力，表达对彼此的心意。", "02-14", "popular"),
    _Holiday("cn.womens_day", "三八妇女节", "向女性致意，关注女性在社会生活中的贡献与权益。部分单位会组织节日活动。", "03-08", "observance"),
    _Holiday("cn.youth_day", "五四青年节", "纪念五四运动。学校和青年团体常举办主题活动，鼓励年轻人参与社会、发挥所长。", "05-04", "observance"),
    _Holiday("cn.mothers_day", "母亲节", "5 月第二个星期日。人们常以问候、送花或陪伴感谢母亲。", (5, 6, 2), "observance"),
    _Holiday("cn.childrens_day", "六一儿童节", "6 月 1 日。许多校园会办演出、游园会或游戏，家长也常给孩子安排活动。", "06-01", "observance"),
    _Holiday("cn.fathers_day", "父亲节", "6 月第三个星期日。人们常打电话、送礼物或陪父亲吃顿饭，表达感谢。", (6, 6, 3), "observance"),
    _Holiday("cn.teachers_day", "教师节", "9 月 10 日。学生和毕业生常向老师送上贺卡或问候，感谢他们的教导。", "09-10", "observance"),
    _Holiday("cn.halloween", "万圣夜", "10 月 31 日晚，一些城市的商圈、乐园和聚会会有南瓜灯、变装等主题活动。", "10-31", "popular"),
    _Holiday("cn.christmas", "圣诞节", "12 月 25 日。部分商圈和街区会布置圣诞树与灯饰，有人相约聚会或互赠小礼物。", "12-25", "popular"),
)

# Japan Cabinet Office, including the February 11 National Foundation Day decree:
# https://www8.cao.go.jp/chosei/shukujitsu/gaiyou.html
_JP = (
    _Holiday("jp.new_year", "元日", "日本正月的第一天。常见的过年方式有新年首次参拜、吃御节料理和互道新年好。", "01-01"),
    _Holiday("jp.coming_of_age", "成人日", "祝贺踏入成年的年轻人。许多地方会举行仪式，也有人为此穿振袖或正装。", (1, 0, 2)),
    _Holiday("jp.foundation_day", "建国纪念日", "纪念国家的建立。", "02-11"),
    _Holiday("jp.emperor_birthday", "天皇诞辰", "庆祝日本在位天皇的生日。", "02-23"),
    _Holiday("jp.vernal_equinox", "春分日", "欣赏春日自然。春分也是春彼岸的中日，一些家庭会在前后扫墓、追念亲人。", 0),
    _Holiday("jp.showa_day", "昭和日", "回顾日本昭和时期的动荡与复兴，思考未来。", "04-29"),
    _Holiday("jp.constitution_day", "宪法纪念日", "纪念日本宪法施行，寄望国家继续发展。", "05-03"),
    _Holiday("jp.greenery_day", "绿之日", "亲近大自然，感谢它带给生活的馈赠。", "05-04"),
    _Holiday("jp.childrens_day", "儿童节（こどもの日）", "5 月 5 日，祝愿孩子健康成长。日本端午的习俗也保留下来，例如挂鲤鱼旗、摆五月人偶和吃柏饼。", "05-05"),
    _Holiday("jp.marine_day", "海之日", "感谢大海的惠泽，祝愿海洋国家日本繁荣。", (7, 0, 3)),
    _Holiday("jp.mountain_day", "山之日", "走近山林，感念山岳带给人们的益处。", "08-11"),
    _Holiday("jp.respect_for_aged", "敬老日", "感谢长者多年来对社会的贡献，祝愿他们健康长寿。", (9, 0, 3)),
    _Holiday("jp.autumnal_equinox", "秋分日", "敬念祖先，追思离世的亲人。", 1),
    _Holiday("jp.sports_day", "体育日", "享受运动，在运动中尊重彼此，让生活更健康。", (10, 0, 2)),
    _Holiday("jp.culture_day", "文化日", "珍视自由与和平，鼓励文化发展。", "11-03"),
    _Holiday("jp.labor_thanksgiving", "勤劳感谢日", "尊重劳动，珍惜生产成果，并向彼此致谢。", "11-23"),
    # Seasonal customs and popular celebrations as observed in Japan.
    # https://www.irodori.jpf.go.jp/assets/data/TIPS_all.pdf
    # https://www.jinjahoncho.or.jp/omatsuri/obon/
    # https://www.jinjahoncho.or.jp/omairi/shichigosan/
    _Holiday("jp.setsubun", "节分", "立春前一天，常撒豆祈求驱厄迎福，也有吃惠方卷的习惯。", _JP_SETSUBUN, "traditional"),
    _Holiday("jp.valentines_day", "情人节（西方）", "公历 2 月 14 日。在日本送巧克力很常见，可以表达爱意、友情或感谢，也有人买给自己。", "02-14", "popular"),
    _Holiday("jp.hinamatsuri", "雏祭（女儿节）", "3 月 3 日，又叫桃之节句。家人会摆雏人偶，祝愿女孩平安健康地成长。", "03-03", "traditional"),
    _Holiday("jp.white_day", "白色情人节（回礼日）", "3 月 14 日，日本常在这天用糖果、点心等回礼，回应一个月前收到的心意。", "03-14", "popular"),
    _Holiday("jp.mothers_day", "母亲节", "5 月第二个星期日。日本常以康乃馨或小礼物向母亲表达感谢。", (5, 6, 2), "observance"),
    _Holiday("jp.fathers_day", "父亲节", "6 月第三个星期日。人们常送小礼物或和父亲共度一段时间，表达感谢。", (6, 6, 3), "observance"),
    _Holiday("jp.tanabata", "七夕（日本传统）", "多在公历 7 月 7 日过七夕。人们把写着心愿的短册挂在竹枝上。仙台等地在 8 月举办七夕祭。", "07-07", "traditional"),
    _Holiday("jp.obon", "盂兰盆节（御盆）", "迎念祖先、与家人团聚，有些地方会跳盆踊。以常见的 8 月 15 日提醒，部分地方在 7 月或按旧历过节。", "08-15", "traditional"),
    _Holiday("jp.tsukimi", "十五夜（月见）", "按旧历赏中秋名月，常用芒草装饰，供上月见团子，也借此感谢秋收。", _DateTable(JAPAN_TSUKIMI_DATES), "traditional"),
    _Holiday("jp.halloween", "万圣夜", "10 月 31 日晚，一些主题乐园和商圈会办变装活动，人们也会用南瓜装饰营造节日气氛。", "10-31", "popular"),
    _Holiday("jp.shichi_go_san", "七五三", "11 月 15 日庆祝孩子平安长大。家人常在前后择日到神社参拜，为三岁、五岁或七岁的孩子祈福。", "11-15", "traditional"),
    _Holiday("jp.christmas", "圣诞节", "日本的圣诞季常有冬日灯饰、圣诞蛋糕和送礼，平安夜也常约会、聚餐或吃炸鸡。", "12-25", "popular"),
    _Holiday("jp.new_year_eve", "大晦日（公历跨年夜）", "12 月 31 日，是日本辞旧迎新的日子。有人会吃跨年荞麦面，听寺院敲除夜钟。", "12-31", "traditional"),
)

# The National Astronomical Observatory of Japan gives projected equinox
# dates in local time. Only dates published in the official almanac are final.
# https://www.nao.ac.jp/faq/a0301.html
# https://eco.mtk.nao.ac.jp/koyomi/yoko/2025/rekiyou251.html
_JP_EQUINOX_DAYS = {
    2025: (20, 23),
    2026: (20, 23),
    2027: (21, 23),
    2028: (20, 22),
    2029: (20, 23),
    2030: (20, 23),
    2031: (21, 23),
    2032: (20, 22),
    2033: (20, 23),
    2034: (20, 23),
    2035: (21, 23),
    2036: (20, 22),
    2037: (20, 23),
    2038: (20, 23),
    2039: (21, 23),
    2040: (20, 22),
    2041: (20, 23),
    2042: (20, 23),
    2043: (21, 23),
    2044: (20, 22),
    2045: (20, 22),
    2046: (20, 23),
    2047: (21, 23),
    2048: (20, 22),
    2049: (20, 22),
    2050: (20, 23),
}

_HOLIDAYS = {"off": (), "cn": _CN, "jp": _JP}
HOLIDAY_IDS = frozenset(holiday.id for holidays in _HOLIDAYS.values() for holiday in holidays)


def _movable_month_day(region: str, year: int, column: int) -> str | None:
    if region == "cn":
        dates = CHINA_MOVABLE_DATES.get(year)
        return dates[column] if dates is not None else None
    days = _JP_EQUINOX_DAYS.get(year)
    if days is None:
        return None
    month = 3 if column == 0 else 9
    return f"{month:02d}-{days[column]:02d}"


def holiday_catalog(region: str, year: int) -> list[_HolidayEntry]:
    """Return each named holiday and the date status under the checked-in rules."""
    if region not in _HOLIDAYS:
        raise ValueError("请选择支持的节日地区。")
    entries: list[_HolidayEntry] = []
    for holiday in _HOLIDAYS[region]:
        rule = holiday.rule
        status: _DateStatus = "official"
        if isinstance(rule, str):
            month_days = (rule,)
        elif isinstance(rule, tuple):
            month, weekday, ordinal = rule
            first_day = date(year, month, 1)
            day = 1 + ((weekday - first_day.weekday()) % 7) + 7 * (ordinal - 1)
            month_days = (f"{month:02d}-{day:02d}",)
        elif isinstance(rule, _DateTable):
            value = rule.years.get(year)
            month_days = (value,) if isinstance(value, str) else (value or ())
            if value is None:
                status = "unavailable"
            elif not month_days:
                status = "not_occurring"
            elif year > rule.confirmed_through:
                status = "forecast"
        else:
            month_day = _movable_month_day(region, year, rule)
            month_days = (month_day,) if month_day else ()
            if month_day is None:
                status = "unavailable"
            elif year > _MOVABLE_OFFICIAL_THROUGH:
                status = "forecast"
        dates = [f"{year:04d}-{month_day}" for month_day in month_days]
        entry: _HolidayEntry = {
            "id": holiday.id,
            "label": holiday.label,
            "message": holiday.message,
            "date": dates[0] if dates else None,
            "dateStatus": status,
            "category": holiday.category,
        }
        if len(dates) > 1:
            entry["additionalDates"] = dates[1:]
        entries.append(entry)
    return sorted(entries, key=lambda entry: entry["date"] or "9999-99-99")


__all__ = ["HOLIDAY_IDS", "HOLIDAY_REGIONS", "holiday_catalog"]
