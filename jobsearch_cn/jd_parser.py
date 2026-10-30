"""Rule-based extraction of Chinese job descriptions into Job Schema records.

parse_text() splits pasted text into JDs, runs each one through the posting
gate (jobsearch_cn/guard.py) and extracts the fields whose wording is regular
enough for rules: salary, graduation year, days per week, internship length,
education, return offer, employment type, cities, remote work, dates, how the
JD interviews and when it wants you to start, a
labelled or headline title and company, and skills from the vocabulary - read
from the body only, since the title names the job rather than asking for a
skill, and only where the JD asks for them (not "无需 SQL", not "欢迎关注我们的
公众号"), with the skills it offers a choice between ("熟悉 Golang 或 Java",
"Python、R 至少掌握一门"). It reads the copies users actually paste, a BOSS直聘
page with its link lines and "公司｜城市｜薪资｜N天/周｜N个月" tag line included. Every value
cites the snippet it came from (method "rule"). What the rules cannot read
with confidence stays null for an agent or the user to fill in and cite;
nothing is guessed - a publication date or deadline without a year is left
alone, a JD naming two internship lengths gets neither, and a city named only
in passing prose, or as where the interview is, is not taken as the work
location. A start date without a year ("11月1日前到岗") is the one exception:
JDs almost never give the year, so it takes the year that puts the date
nearest the JD's publication date, or the import date. Each record is
validated against the schema before it is returned.
"""

import calendar
import hashlib
import re
from datetime import date, datetime

from jobsearch_cn import guard, schema, vocab

# A line of three or more "=" separates JDs pasted together.
SEPARATOR = re.compile(r"^[ \t]*={3,}[ \t]*$", re.M)

_HAN = f"{chr(0x4E00)}-{chr(0x9FFF)}"
_CLAUSE_END = "，,。；;！!？?\n"
_LIST_MARK = re.compile(r"^(?:\d{1,2}|[a-zA-Z])\s*[.、)）]\s*|^[-*•·]\s*")
_MAX_SNIPPET = 60

_NUMERALS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}

CITIES = (
    "北京", "上海", "广州", "深圳", "杭州", "南京", "苏州", "成都", "武汉", "西安", "重庆", "天津",
    "长沙", "厦门", "合肥", "郑州", "青岛", "济南", "大连", "沈阳", "福州", "珠海", "东莞", "佛山",
    "无锡", "宁波", "昆明", "哈尔滨", "长春", "石家庄", "太原", "南昌", "贵阳", "南宁", "海口",
    "兰州", "乌鲁木齐", "呼和浩特", "常州", "温州", "嘉兴", "绍兴", "金华", "泉州", "中山", "惠州",
    "徐州", "烟台", "潍坊", "洛阳", "香港", "澳门", "台北", "新加坡",
)

# Skills come from the vocabulary (jobsearch_cn/skills.json plus the user's
# data/config/skills.json, see vocab.py), written in canonical spellings. ASCII
# terms match case-insensitively at word edges, with any internal space
# optional (SpringBoot finds "Spring Boot"); the schema's evidence check folds
# case and whitespace the same way.

_N = r"\d+(?:\.\d+)?"
_TO = r"\s*(?:-|~|～|－|—|–|至|到)\s*"
# (pattern, unit, multiplier). Every pattern names its amounts lo and hi.
_SALARY = (
    (re.compile(rf"(?P<lo>{_N})\s*[kK千]?{_TO}(?P<hi>{_N})\s*[kK千](?:\s*/\s*月)?"
                rf"(?:\s*[·・•*xX×]\s*(?P<months>\d{{2}})\s*薪)?"), "CNY/month", 1000),
    (re.compile(rf"(?P<lo>{_N})\s*万?{_TO}(?P<hi>{_N})\s*万\s*元?\s*(?:/|每)\s*月"), "CNY/month", 10000),
    (re.compile(rf"月薪\s*(?P<lo>{_N})\s*万?(?:{_TO}(?P<hi>{_N}))?\s*万"), "CNY/month", 10000),
    (re.compile(rf"年薪\s*(?P<lo>{_N})\s*万?(?:{_TO}(?P<hi>{_N}))?\s*万"), "CNY/year", 10000),
    (re.compile(rf"(?P<lo>{_N})\s*万?{_TO}(?P<hi>{_N})\s*万\s*元?\s*(?:/|每)\s*年"), "CNY/year", 10000),
    (re.compile(rf"(?P<lo>{_N})\s*元?(?:{_TO}(?P<hi>{_N}))?\s*元?\s*(?:/|每)\s*(?:天|日)"), "CNY/day", 1),
    (re.compile(rf"(?:日薪|每天|每日)\s*(?P<lo>{_N})(?:{_TO}(?P<hi>{_N}))?\s*元"), "CNY/day", 1),
    (re.compile(rf"(?P<lo>{_N})\s*元?(?:{_TO}(?P<hi>{_N}))?\s*元?\s*(?:/|每)\s*(?:小时|时)"), "CNY/hour", 1),
    (re.compile(rf"月薪\s*(?P<lo>{_N})(?:{_TO}(?P<hi>{_N}))?\s*元"), "CNY/month", 1),
)
_NEGOTIABLE = re.compile(r"(?:薪资|薪酬|待遇|工资)?\s*面议")
# "全年13薪" written apart from a monthly salary; a range ("13-15薪") is left alone.
_PAY_MONTHS = re.compile(r"(?:全年\s*)?(?<![\d.\-~～－—–至到])(?P<months>\d{2})\s*薪(?![资酬水])")

_YEAR = r"(?:20)?\d{2}"
_GRADUATION = re.compile(
    rf"(?<!第)(?<!\d)(?P<years>{_YEAR}(?:\s*届)?(?:\s*(?:/|、|,|，|和|与|及|或|-|~|～|至|到)\s*{_YEAR}(?:\s*届)?)*)\s*届"
)
_YEAR_RANGE = re.compile(rf"^\s*{_YEAR}\s*(?:-|~|～|至|到)\s*{_YEAR}\s*$")

_DAY = r"[1-7一二两三四五六七]"
_DAYS = (
    re.compile(rf"(?:每周|一周|每星期|每个星期|周)\s*(?:至少|最少|不少于|保证|需要|需|要求|可|能)?\s*"
               rf"(?:到岗|实习|出勤|工作|在岗|坐班)?\s*(?P<d>{_DAY})\s*(?:{_TO}{_DAY})?\s*个?\s*(?:天|日)"),
    re.compile(rf"(?P<d>{_DAY})\s*(?:{_TO}{_DAY})?\s*(?:天|日)\s*/\s*周"),
)

_MONTH_COUNT = r"\d{1,2}|[一二两三四五六七八九十]{1,3}"
_MONTHS = (
    re.compile(rf"(?:实习期|实习时间|实习周期|实习时长|实习)\s*(?:至少|最少|不少于|需满|需要|需|要求|为|满|保证)?\s*"
               rf"(?P<n>{_MONTH_COUNT})\s*个?\s*月"),
    re.compile(rf"(?:至少|最少|不少于|保证)\s*(?:实习|到岗)?\s*(?P<n>{_MONTH_COUNT})\s*个?\s*月"),
    re.compile(rf"(?P<n>{_MONTH_COUNT})\s*个?\s*月\s*(?:及|或)?以上"),
    re.compile(r"(?:实习期|实习时间|实习)\s*(?:至少|不少于|满)?\s*(?P<n>半年|一年)"),
)

_LEVELS = {"大专": "associate", "专科": "associate", "本科": "bachelor", "学士": "bachelor",
           "硕士": "master", "研究生": "master", "博士": "phd"}
_LEVEL_WORD = "(大专|专科|本科|学士|硕士|研究生|博士)"
_EDUCATION_MIN = re.compile(
    rf"{_LEVEL_WORD}(?:研究生)?\s*(?:学历\s*)?(?:及|或)?\s*以上|{_LEVEL_WORD}\s*(?:学历|在读|应届|毕业)"
)
_EDUCATION_PREFERRED = re.compile(
    rf"{_LEVEL_WORD}(?:研究生)?\s*(?:及以上)?\s*(?:学历)?\s*者?\s*(?:优先|为佳)"
)
# Two levels or more to choose from (H20): "本科或硕士及以上学历", "大专/本科学历", "学历：本科或硕士". The
# minimum is the lowest. A bare pair needs a label before it or a qualifier after it, as a single level
# does: "本科或硕士期间的项目经历" asks for nothing.
_LEVEL_ANY = "(?:大专|专科|本科|学士|硕士|研究生|博士)"
_EDUCATION_CHOICE = re.compile(
    rf"(?P<label>学历\s*(?:要求)?\s*[:：]\s*)?{_LEVEL_ANY}(?:研究生)?"
    rf"(?:\s*(?:或者?|/|／|、)\s*{_LEVEL_ANY}(?:研究生)?)+"
    r"(?P<tail>\s*(?:学历\s*)?(?:及|或)?\s*以上|\s*(?:学历|在读|应届|毕业|学生)|\s*(?:均可|皆可|都可以?))?"
)
# A choice the JD prefers: "硕士或博士优先" prefers a master's, the lowest of them.
_PREFERRED_AFTER = re.compile(r"\s*(?:及以上)?\s*(?:学历)?\s*者?\s*(?:优先|为佳)")
# "学历不限", "不设最低学历门槛": no minimum, said outright. "专业不限" is about the major.
_NO_MINIMUM_EDUCATION = re.compile(
    r"学历\s*(?:要求)?\s*[:：]?\s*(?:不限(?!于)|无要求|没有要求|不作要求|不做要求)|不限学历|(?:无|没有)学历要求"
    r"|不设\s*(?:最低)?\s*学历\s*(?:门槛|要求)"
)
_PREFERENCE = re.compile(r"优先|为佳")

_NO_RETURN_OFFER = re.compile(r"(?:不可|不能|无|不提供|没有)\s*转正")
_RETURN_OFFER = re.compile(r"(?:表现(?:优秀|优异|突出)者?\s*)?(?:可|能|有机会|有|提供)\s*转正|转正机会|留用机会")

_INTERNSHIP = re.compile(r"实习生|日常实习|暑期实习|寒假实习|实习岗位|实习期|实习时间")
_CAMPUS = re.compile(r"校园招聘|校招|应届(?:毕业)?生|管培生")
_EXPERIENCED = re.compile(r"社会招聘|社招")

_CITY = re.compile("|".join(sorted(CITIES, key=len, reverse=True)))
_LOCATION_LABEL = re.compile(
    r"(?<!面试)(?<!笔试)(?:(?:工作地点|工作城市|办公地点|工作地址|上班地点|地点|城市)\s*[:：]|base\s*[:：]?)"
    r"\s*(?P<rest>[^\n]{1,60})",
    re.I,
)
# Where the rest of a location line turns to the interview: "工作地点：深圳；面试地点：北京".
_INTERVIEW = re.compile(r"面试|笔试")
_CITY_HEADLINE = re.compile(rf"^(?P<city>{_CITY.pattern})(?:[·・\-|丨/\s]|$)")
# "支持远程面试" is about the interview, not the work.
_NO_REMOTE = re.compile(r"不(?:支持|可|能|接受)\s*远程(?!\s*面)")
_REMOTE = re.compile(r"(?:可|支持|接受)\s*远程(?!\s*面)(?:办公|工作|实习)?|远程(?:办公|工作|实习)|居家办公|\bremote\b", re.I)

# The interview (M2-6c): online (线上、视频、电话面试), in person (现场、线下面试, "到公司面试"), or at a
# place ("面试地点：北京", "面试可在杭州"). Both, with a word of choice in one line ("面试地点：北京，也可视频
# 面试"), is the candidate's choice; both without one is some rounds in person.
_ONLINE_WORD = r"(?:线上|视频|电话|远程|网络|在线)"
_ONSITE_WORD = r"(?:现场|线下)"
_PAIRED = r"\s*(?:或者?|/|／|和|及|与|、|\+|＋)\s*"
_ONLINE_INTERVIEW = re.compile(rf"{_ONLINE_WORD}\s*(?:面试|面谈)|{_ONLINE_WORD}(?={_PAIRED}{_ONSITE_WORD}\s*(?:面试|面谈))"
                               rf"|面试\s*(?:方式|形式|地点)\s*[:：为是]?\s*{_ONLINE_WORD}")
_ONSITE_INTERVIEW = re.compile(rf"(?:{_ONSITE_WORD}|当面|到场)\s*(?:面试|面谈)|(?:到|来)\s*公司\s*(?:面试|面谈)"
                               rf"|{_ONSITE_WORD}(?={_PAIRED}{_ONLINE_WORD}\s*(?:面试|面谈))"
                               rf"|面试\s*(?:方式|形式)\s*[:：为是]?\s*{_ONSITE_WORD}")
_INTERVIEW_PLACE = re.compile(
    rf"面试\s*(?:地点|城市|地址)\s*[:：]\s*(?!{_ONLINE_WORD})[^\n，,。；;（(]{{0,40}}"
    rf"|面试\s*(?:可|将|需|须)?\s*(?:在|于)\s*(?:{_CITY.pattern})"
    rf"|(?:在|到|去)\s*(?:{_CITY.pattern})\s*(?:现场|线下)?\s*(?:面试|面谈)"
    rf"|(?:现场|线下)\s*面试\s*[（(]\s*(?:{_CITY.pattern})"
)
_INTERVIEW_CHOICE = re.compile(r"也可|亦可|或者|或|可选|均可|任选|自选")
# Interviews that are the job's own work, not the candidate's: "协助组织现场面试". "面试安排：" is a label.
_INTERVIEW_DUTY = re.compile(r"负责|协助|组织|跟进|对接|邀约|筛选|(?<!面试)安排")
# A way of interviewing the JD rules out: "不支持远程面试", "不接受视频面试".
_INTERVIEW_REFUSED = re.compile(r"不(?:支持|接受|提供|安排|采用|可|能)")

# When to start (M2-6c): as soon as possible, or by a date - "11月1日前到岗", "2027年7月入职",
# "入职时间：11月底前". A month alone is its last day. A start from a date on ("11月1日后到岗",
# "11月起") is no deadline, "11月前" alone could mean October or November, and a date the JD only
# prefers ("…前到岗者优先") is no requirement: none of these is read.
_START_WORD = r"(?:到岗|入职|报到|上岗)"
_START_ASAP = re.compile(rf"(?:尽快|尽早|立即|立刻|马上|随时)\s*(?:能|可以?)?\s*{_START_WORD}"
                         rf"|{_START_WORD}\s*(?:时间|日期)\s*[:：]?\s*(?:尽快|越快越好|随时)")
_START_DATE = r"(?:(?P<y>20\d{2})\s*年\s*)?(?P<m>\d{1,2})\s*月(?:\s*(?P<d>\d{1,2})\s*[日号]|\s*份)?\s*(?P<end>底|末)?"
_START_BY = (
    re.compile(rf"{_START_DATE}\s*(?P<before>之前|以前|前)?\s*(?:须|需要?|能|可以?)?\s*{_START_WORD}"),
    re.compile(rf"{_START_WORD}\s*(?:时间|日期)\s*[:：]\s*(?:为\s*)?{_START_DATE}\s*(?P<before>之前|以前|前)?"
               r"(?!\s*(?:\d|之后|以后|后|起))"),
)

_YMD = r"(?P<y>20\d{2})\s*[-/.年]\s*(?P<m>\d{1,2})\s*[-/.月]\s*(?P<d>\d{1,2})\s*日?"
_PUBLISHED = re.compile(rf"(?:发布时间|发布日期|发布于|更新时间|更新于)\s*[:：]?\s*{_YMD}")
_DEADLINE_AFTER = re.compile(rf"(?:截止日期|截止时间|报名截止|投递截止|网申截止|截止)\s*(?:日期|时间)?\s*[:：为至]?\s*{_YMD}")
_DEADLINE_BEFORE = re.compile(rf"{_YMD}\s*前?\s*截止")

_TITLE_LABEL = re.compile(r"(?m)^\s*(?:职位名称|岗位名称|招聘职位|招聘岗位|职位|岗位)\s*[:：]\s*(?P<v>[^\n，,。；;]{2,40})")
_JOB_WORD = re.compile(
    r"实习|工程师|开发|算法|研究员|研发|产品|运营|设计|分析|经理|专员|助理|顾问|测试|架构师|科学家"
    r"|管培生|培训生|储备干部|销售|编辑|策划|主管|总监"
    r"|intern|engineer|developer|scientist|manager|analyst|designer",
    re.I,
)
_NOT_TITLE = re.compile(r"职责|要求|描述|介绍|福利|地点|薪资|待遇|公司|任职|职位信息|岗位信息|[:：]")
# A headline is a job name, not a sentence: a clause break or a requirement word
# outside brackets marks prose ("后端开发实习生（日常实习，可转正）" is still a title).
# Skills are not read from the title, so prose taken for one would lose its skills.
_PROSE = re.compile(r"[，,。；;！!？?]|负责|熟悉|熟练|掌握|了解|精通|具备|经验|能力")
_BRACKETED = re.compile(r"（[^（）]*）|\([^()]*\)|【[^【】]*】|\[[^\[\]]*\]")
# A copy can open with "标签：值" lines above the title: 职位链接：https://…, 采集日期：2026-10-28.
_LABEL_LINE = re.compile(r"^[^:：，,。；;！!？?\s][^:：，,。；;！!？?]{0,9}[:：]")
# How far into a copy to look for an unlabelled title: a whole-page copy puts
# navigation first, and the title beside its salary ("java开发实习生 130-150元/天").
_HEAD_LINES = 30
# The tag line of a BOSS直聘 copy, "<公司>｜<城市>｜350-400元/天｜5天/周｜3个月｜本科": cells
# split on ｜ or |, one of them a weekly-days tag. The first cell is the company unless it
# is a tag itself (shixiseng's "150-200/天 | 上海 | …" starts with the salary); a bare
# "N个月" cell is the internship length, read only here.
_TAG_SEP = re.compile(r"\s*[｜|]\s*")
_PIPE = re.compile(r"[｜|]")
_DAYS_TAG = re.compile(rf"^{_DAY}(?:{_TO}{_DAY})?\s*(?:天|日)\s*/\s*周$")
_MONTHS_TAG = re.compile(rf"^(?P<n>{_MONTH_COUNT})\s*个?\s*月$")
_CITY_TAG_PART = rf"(?:{_CITY.pattern})(?:[·・\-][{_HAN}A-Za-z0-9]{{1,8}})*"
_CITY_TAG = re.compile(rf"{_CITY_TAG_PART}(?:\s*[/／、,，]\s*{_CITY_TAG_PART})*")
_NOT_COMPANY = re.compile(r"^(?:\d|不限|经验|学历|大专|专科|本科|硕士|研究生|博士|实习|全职|兼职|校招|社招|远程)")
# A whole-page copy lays the same tags out with spaces, "杭州 5天/周 6个月 本科". Such a
# line counts only when every cell is a tag word, so a sentence that mentions "5天/周" or
# "3个月" ("可以 5天/周 到岗 3个月 内入职") is not one. It names no company.
_TAG_WORD = re.compile(
    rf"(?:{_CITY.pattern})(?:[·・\-][{_HAN}A-Za-z0-9]{{1,8}})*|[{_HAN}]{{1,6}}(?:区|县)"
    rf"|{_DAY}(?:{_TO}{_DAY})?\s*(?:天|日)\s*/\s*周|(?:{_MONTH_COUNT})\s*个?\s*月(?:及?以上)?"
    r"|(?:大专|专科|本科|学士|硕士|研究生|博士)(?:及以上)?|学历不限|经验不限|在校/应届|应届生?"
    r"|\d{1,2}(?:-\d{1,2})?年(?:以上|以内)?|(?:20)?\d{2}届|日常实习|暑期实习|实习|全职|兼职|校招|社招|可?远程|可转正"
)
# A skill a clause rules out is not asked for: "无需 SQL 基础", "不要求 Rust 或 C++", "也不负责公众号运营".
_NEGATION = re.compile(r"不要求|无需|无须|不需要|不需|不必|不用|不负责|不涉及|不承担|非必须|不是必须|不作要求|不做要求")
# Skills the JD offers a choice between (H16). A run is skills joined only by 、 / 或 or
# 或者 (a "语言", "框架" after a skill allowed). It is a choice when 或 joins it, or when a
# marker - 任一, 之一, 二选一, 至少掌握一门 - sits within _MARK_REACH characters of it in the
# same clause with nothing between that starts another statement (和/及/与/并, 是/为: "Python、Java
# 是核心技术栈之一" describes, it does not offer). 、 and / alone list skills all wanted
# ("HTML/CSS/JavaScript"); a run followed by 专业 names majors, not skills.
_JOIN = re.compile(r"\s*(?:语言|框架|软件|工具)?\s*(?:、|/|／|或者|或)\s*")
_ALT_MARK = re.compile(
    r"任选其一|[二三四多]选一|其中之一|之一|其一|任一|(?:任意|其中)一[种门项个款]|一[种门项个款]即可"
    r"|至少\s*(?:熟练)?(?:掌握|熟悉|精通|使用|会用|会)?\s*(?:其中)?\s*一[种门项个款]"
)
_MARK_REACH = 15
_MARK_BREAK = re.compile(r"[和及与并是为]")
_MAJOR_AFTER = re.compile(r"\s*(?:等)?\s*(?:相关)?\s*专业")
_MAJOR_BEFORE = re.compile(r"专业\s*[:：]?\s*$")
# A term in a list of majors is no skill (H20): "统计学或市场营销相关专业", "专业：计算机、统计学". The same
# term asking for knowledge still is: "熟悉统计学方法", "具备统计学专业知识".
_MAJOR_WORD = r"[一-鿿A-Za-z]{1,12}?"
_MAJOR_JOIN = r"\s*(?:、|/|／|或者|或|和|及|与)\s*"
_MAJOR_TAIL = re.compile(
    rf"(?:{_MAJOR_JOIN}{_MAJOR_WORD})*\s*(?:等)?\s*(?:相关)?\s*专业(?!\s*(?:知识|技能|能力|素养|术语|工具|软件))"
)
_MAJOR_LEAD = re.compile(rf"专业\s*(?:要求|背景|方向)?\s*(?:为|是|[:：])\s*(?:{_MAJOR_WORD}{_MAJOR_JOIN})*$")
# A platform name is a skill when the JD asks for it, not when it points the reader at the
# company's own channel ("欢迎关注我们的公众号", "动态见我们的 B站") or describes the company
# in its introduction. A follow verb alone is a duty: "关注小红书热点".
_PLATFORMS = frozenset(("公众号", "小红书", "抖音", "微博", "视频号", "B站", "知乎", "快手"))
_FOLLOW = re.compile(r"关注|订阅|扫码|详见|动态见|了解更多")
_OURS = re.compile(r"我们|本公司|官方|更多|招聘(?:信息|通知|动态)")
# "PS：" opening a line starts a postscript ("PS：简历请注明到岗时间"); that PS is not Photoshop.
_AFTER_POSTSCRIPT = re.compile(r"[ \t]*[:：]")
_INTRO = re.compile(r"(?m)^[ \t]*[【\[]?\s*(?:公司介绍|公司简介|企业介绍|企业简介|关于我们|公司概况)\s*[】\]]?\s*(?:[:：]|$)")
_SECTION = re.compile(
    r"(?m)^[ \t]*[【\[]?\s*(?:职位描述|职位详情|岗位描述|岗位职责|工作职责|职位职责|工作内容|任职要求|岗位要求|职位要求"
    r"|任职资格|技能要求|工作地点|工作地址|薪资福利|福利待遇|职位福利|岗位福利)\s*[】\]]?\s*(?:[:：]|$)"
)
_HEADER_END = re.compile(r"^(?:看过该职位的人还看了|相关职位|推荐职位|热门职位|公司基本信息)\s*[:：]?\s*$")
_HEADER_PROSE = re.compile(r"^(?:请|可以|需要|需|要求|保证|欢迎|至少)|到岗|入职|连续")
_COMPANY_LABEL = re.compile(r"(?m)^\s*(?:公司名称|企业名称|招聘单位|公司|企业)\s*[:：]\s*(?P<v>[^\n，,。；;]{2,40})")
# A legal-entity name that is the whole line, or is followed only by a separator
# and a place ("示例科技有限公司 · 广州"). A sentence that runs on after the name
# ("加入示例科技有限公司，你将…") is prose, not a header.
_COMPANY_HEAD = re.compile(
    rf"^(?P<v>[{_HAN}A-Za-z0-9（）()·&]{{2,40}}?(?:股份有限公司|有限责任公司|有限公司|集团))(?=\s*$|\s*[·・|丨\-])"
)


def _skill_pattern(term: str) -> re.Pattern:
    escaped = re.escape(term).replace(r"\ ", r"\s*")
    if term.isascii():
        escaped = rf"(?<![A-Za-z0-9+#.]){escaped}(?![A-Za-z0-9+#])"
    return re.compile(escaped, re.I)


def _skill_patterns(vocabulary) -> list:
    # (term, pattern, key): key is what the term compares as, one for every same_as spelling.
    # Longest first, so "Spring Boot" claims its text before "Spring" and "Golang" before "Go".
    return sorted(((term, _skill_pattern(term), vocabulary.key(term)) for term in vocabulary.terms),
                  key=lambda item: -len(item[0]))


_BUILTIN_PATTERNS = None


def _builtin_patterns() -> list:
    global _BUILTIN_PATTERNS
    if _BUILTIN_PATTERNS is None:
        _BUILTIN_PATTERNS = _skill_patterns(vocab.load())
    return _BUILTIN_PATTERNS


def split_jds(text: str) -> list[str]:
    """The JDs in a paste, split on lines of three or more "=".

    Line endings are normalised first: a file saved on Windows ends its lines
    with CRLF, and the stray CR would keep "===" from matching as a line.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return [part.strip() for part in SEPARATOR.split(text) if part.strip()]


def job_id(text: str) -> str:
    """A content fingerprint: the same JD text always gets the same id."""
    digest = hashlib.sha1(schema.normalize_for_match(text).encode("utf-8")).hexdigest()
    return f"job_{digest[:12]}"


def parse_text(text: str, *, source_type: str = "paste", site=None, url=None, now=None, vocabulary=None):
    """Parse text holding one or more JDs. Returns (records, warnings).

    Raises ValueError when url is given for more than one JD: a URL names a
    single posting. vocabulary is a vocab.Vocabulary; the built-in one by default.
    """
    patterns = _skill_patterns(vocabulary) if vocabulary is not None else _builtin_patterns()
    parts = split_jds(text)
    if url is not None and len(parts) > 1:
        raise ValueError(f"--url names one posting, but the input holds {len(parts)} JDs")
    imported_at = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
    records, warnings = [], []
    for number, part in enumerate(parts, 1):
        cleaned, findings = guard.check(part)
        if not cleaned:
            continue
        if len(cleaned) > schema.MAX_RAW_TEXT:
            warnings.append({"segment": number, "kind": "too_long",
                             "message": f"JD {number} is longer than {schema.MAX_RAW_TEXT} characters; skipped"})
            continue
        record = build_record(cleaned, findings, source_type=source_type, site=site, url=url,
                              imported_at=imported_at, skill_patterns=patterns)
        if record["guard"]["verdict"] == "warn":
            warnings.append({"segment": number, "kind": "guard", "message": findings["verdict"],
                             "excerpts": list(findings["instruction_like"])})
        records.append(record)
    if not records:
        warnings.append({"segment": None, "kind": "empty", "message": "no JD text found"})
    return records, warnings


def build_record(text: str, findings: dict, *, source_type: str, site, url, imported_at: str,
                 skill_patterns=None) -> dict:
    """One schema record from one cleaned JD."""
    evidence = {}

    def cite(path, found):
        value, snippets = found
        if value is not None and value != []:
            evidence[path] = {"text": snippets[0] if len(snippets) == 1 else snippets, "method": "rule"}
        return value

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    found_title, title_span = _title(text, lines)
    title = cite("title", found_title)
    headline = _line_at(text, title_span[0]) if title_span else (lines[0] if lines else "")
    tag, piped = _tag_cells(lines, headline if title_span else None)
    hits = _skill_hits(text, skill_patterns or _builtin_patterns(), skip=title_span)
    published = _dated(text, (_PUBLISHED,))
    # A start date without a year is dated from the JD's own publication date, else the import date.
    reference = date.fromisoformat(published[0] or imported_at[:10])
    record = {
        "schema_version": schema.SCHEMA_VERSION,
        "id": job_id(text),
        "source": {"type": source_type, "site": site, "url": url, "imported_at": imported_at},
        "title": title,
        "company": cite("company", _company(text, lines, tag if piped else [])),
        "cities": cite("cities", _cities(text, lines, tag)) or [],
        "remote": cite("remote", _remote(text)),
        "employment_type": cite("employment_type", _employment_type(text, headline)),
        "salary": cite("salary", _salary(text)),
        "requirements": {
            "graduation": cite("requirements.graduation", _graduation(text)),
            "days_per_week": cite("requirements.days_per_week", _days_per_week(text)),
            "min_months": cite("requirements.min_months", _min_months(text, tag)),
            "education": cite("requirements.education", _education(text, tag)),
            "skills": cite("requirements.skills", _skills(text, hits)) or [],
            "skill_alternatives": cite("requirements.skill_alternatives", _alternatives(text, hits)) or [],
            "start": cite("requirements.start", _start(text, reference)),
        },
        "interview": cite("interview", _interview(text)),
        "return_offer": cite("return_offer", _return_offer(text)),
        "published_at": cite("published_at", published),
        "deadline": cite("deadline", _dated(text, (_DEADLINE_AFTER, _DEADLINE_BEFORE), same_line=True)),
        "status": "new",
        "evidence": evidence,
        "guard": guard.summary(findings),
        "raw_text": text,
    }
    errors = schema.validate(record)
    if errors:
        raise RuntimeError("jd_parser built an invalid record (a parser bug): " + "; ".join(errors))
    return record


_NOTHING = (None, None)


def _number(text: str):
    """A whole number in digits or Chinese numerals up to 99; None when it is neither."""
    if text.isdecimal():
        return int(text)
    if "十" in text:
        tens, _, ones = text.partition("十")
        high = _NUMERALS.get(tens) if tens else 1
        low = _NUMERALS.get(ones) if ones else 0
        return None if high is None or low is None else high * 10 + low
    return _NUMERALS.get(text)


def _amount(value: float):
    return int(value) if value.is_integer() else round(value, 2)


def _clause_bounds(text: str, start: int, end: int):
    """Where the clause around text[start:end] begins and ends."""
    left = start
    while left > 0 and text[left - 1] not in _CLAUSE_END:
        left -= 1
    right = end
    while right < len(text) and text[right] not in _CLAUSE_END:
        right += 1
    return left, right


def _clause(text: str, start: int, end: int) -> str:
    """The clause around text[start:end], list marker dropped; the match itself if the clause is long."""
    left, right = _clause_bounds(text, start, end)
    clause = _LIST_MARK.sub("", text[left:right].strip())
    return clause if len(clause) <= _MAX_SNIPPET else text[start:end].strip()


def _offset(text: str, lines: list, index: int) -> int:
    """Where lines[index] starts in text; lines are text's non-blank lines, stripped, in order."""
    position, length = 0, 0
    for line in lines[:index + 1]:
        position = text.find(line, position + length)
        length = len(line)
    return position


def _line_at(text: str, position: int) -> str:
    start = text.rfind("\n", 0, position) + 1
    end = text.find("\n", position)
    return text[start:len(text) if end < 0 else end].strip()


def _earliest(patterns, text: str):
    """The leftmost match of any pattern (ties go to the earlier pattern)."""
    best = None
    for pattern in patterns:
        match = pattern.search(text)
        if match and (best is None or match.start() < best.start()):
            best = match
    return best


def _title(text: str, lines: list):
    """The title with its citation, and the span of text it takes up (no skills are read there).

    A labelled title wins. Otherwise the headline - the first line below any leading
    "标签：值" lines - or, further down a whole-page copy, a line that is a title followed
    by its salary.
    """
    match = _TITLE_LABEL.search(text)
    if match:
        value = match["v"].strip()
        return (value, [value]), (match.start("v"), match.start("v") + len(value))
    first = next((i for i, line in enumerate(lines) if not _LABEL_LINE.match(line)), len(lines))
    for index in range(first, min(len(lines), _HEAD_LINES)):
        line = lines[index]
        salary = _earliest((pattern for pattern, _, _ in _SALARY), line)
        priced = salary is not None and salary.start() > 0
        if index > first and not priced:
            continue
        headline = line[:salary.start()].strip() if priced else line
        if (len(headline) <= 40 and _JOB_WORD.search(headline) and not _NOT_TITLE.search(headline)
                and not _PROSE.search(_BRACKETED.sub("", headline))):
            start = _offset(text, lines, index)
            return (headline, [headline]), (start, start + len(headline))
    return _NOTHING, None


def _tag_cells(lines: list, headline=None):
    """Prefer the title's header, then strictly delimited tags anywhere.

    Navigation may push a tag line past line 30. Anchor to the selected title,
    not the page's first line; with no title, retain the bounded opening scan.
    If the header has no row, a full-page copy may put it below the body.
    Only fullwidth-pipe rows qualify there; whitespace rows stay in the header.
    """
    candidates = lines[lines.index(headline) + 1:] if headline else lines[:_HEAD_LINES]
    for line in candidates:
        if _SECTION.match(line) or _INTRO.match(line) or _HEADER_END.match(line):
            break
        cells, piped = _tag_row(line)
        if cells:
            return cells, piped
        if _PROSE.search(line) or _NEGATION.search(line) or _HEADER_PROSE.search(line):
            break
    for line in lines:
        if "｜" in line and "|" not in line:
            cells, piped = _tag_row(line)
            if cells:
                return cells, piped
    return [], False


def _tag_row(line: str):
    """Require a weekly-days tag and tag-only cells, except an optional company."""
    piped = bool(_PIPE.search(line))
    cells = _TAG_SEP.split(line) if piped else line.split()
    if len(cells) >= 3 and any(_DAYS_TAG.fullmatch(cell) for cell in cells):
        tags = cells[1:] if piped and _company_cell(cells[0]) else cells
        if all(_TAG_WORD.fullmatch(cell) or _CITY_TAG.fullmatch(cell) or _is_salary(cell)
               or _EDUCATION_MIN.fullmatch(cell) or _EDUCATION_PREFERRED.fullmatch(cell) for cell in tags):
            return cells, piped
    return [], False


def _is_salary(cell: str) -> bool:
    return any(pattern.fullmatch(cell) for pattern, _, _ in _SALARY)


def _company_cell(cell: str) -> bool:
    return (2 <= len(cell) <= 40 and not _NOT_COMPANY.match(cell) and not _CITY_HEADLINE.match(cell)
            and not _PROSE.search(cell) and not _NEGATION.search(cell) and not _LABEL_LINE.match(cell)
            and not _HEADER_PROSE.search(cell)
            and not _TAG_WORD.fullmatch(cell) and not _CITY_TAG.fullmatch(cell) and not _is_salary(cell)
            and not _SECTION.fullmatch(cell) and not _INTRO.fullmatch(cell))


def _company(text: str, lines: list, tag: list):
    match = _COMPANY_LABEL.search(text)
    if match:
        value = match["v"].strip()
        return value, [value]
    # A header line near the top, or near the bottom where a BOSS直聘 copy puts
    # the company; _COMPANY_HEAD only accepts a line that is a name, not prose.
    for line in lines[:6] + lines[-3:]:
        match = _COMPANY_HEAD.match(line)
        if match:
            return match["v"], [match["v"]]
    # Failing a legal name, the first cell of the tag line, often a short name ("示例云帆科技").
    if tag and _company_cell(tag[0]):
        return tag[0], [tag[0]]
    return _NOTHING


def _cities(text: str, lines: list, tag: list):
    cities, snippets = [], []
    for match in _LOCATION_LABEL.finditer(text):
        rest, snippet = match["rest"], match.group(0).strip()
        interview = _INTERVIEW.search(rest)
        if interview:
            rest = rest[:interview.start()]
            snippet = text[match.start():match.start("rest") + interview.start()].strip().rstrip("，,；;、/（( ")
        # An address can repeat its city (district, then full postal address).
        # Deduplicate this match as well as cities from earlier location labels.
        found = [city for city in dict.fromkeys(_CITY.findall(rest)) if city not in cities]
        if found:
            cities += found
            snippets.append(snippet)
    if not cities:
        for cell in tag:
            if _CITY_TAG.fullmatch(cell):
                # Match only the start of each city tag: a district/street can
                # itself contain another city's name ("广州·南京路").
                found = [_CITY.match(part.strip()).group(0) for part in re.split(r"[/／、,，]", cell)]
                cities.extend(city for city in found if city not in cities)
                snippets.append(cell)
    if not cities:
        for line in lines[:6]:
            match = _CITY_HEADLINE.match(line)
            if match:
                cities.append(match["city"])
                snippets.append(line if len(line) <= _MAX_SNIPPET else match["city"])
                break
    return (cities, snippets) if cities else _NOTHING


def _remote(text: str):
    match = _NO_REMOTE.search(text)
    if match:
        return False, [match.group(0)]
    match = _REMOTE.search(text)
    return (True, [match.group(0)]) if match else _NOTHING


def _interview(text: str):
    """How the JD interviews: online, in person (and where), either at the candidate's choice, or a mix."""
    mentions = []  # (kind, match, cities)
    for kind, pattern in (("online", _ONLINE_INTERVIEW), ("onsite", _ONSITE_INTERVIEW), ("onsite", _INTERVIEW_PLACE)):
        for match in pattern.finditer(text):
            left, _ = _clause_bounds(text, match.start(), match.end())
            if any(stop.search(text, left, match.start()) for stop in (_NEGATION, _INTERVIEW_REFUSED, _INTERVIEW_DUTY)):
                continue
            mentions.append((kind, match, _CITY.findall(match.group(0)) if pattern is _INTERVIEW_PLACE else []))
    if not mentions:
        return _NOTHING
    kinds = {kind for kind, _, _ in mentions}
    mode = kinds.pop() if len(kinds) == 1 else "either" if _offers_a_choice(text, mentions) else "mixed"
    cities = list(dict.fromkeys(city for _, _, found in mentions for city in found))
    snippets = [_clause(text, match.start(), match.end()) for _, match, _ in sorted(mentions, key=lambda m: m[1].start())]
    return {"mode": mode, "cities": cities}, list(dict.fromkeys(snippets))


def _offers_a_choice(text: str, mentions: list) -> bool:
    """Whether one line names both kinds with a word of choice from the first to the end of the last one's clause."""
    lines = {}
    for kind, match, _ in mentions:
        lines.setdefault(text.count("\n", 0, match.start()), []).append((kind, match))
    for found in lines.values():
        if {kind for kind, _ in found} == {"online", "onsite"}:
            start = min(match.start() for _, match in found)
            last = max((match for _, match in found), key=lambda match: match.end())
            if _INTERVIEW_CHOICE.search(text, start, _clause_bounds(text, last.start(), last.end())[1]):
                return True
    return False


def _start(text: str, reference: date):
    """When the JD wants you to start: by a date, as soon as possible, or both. Two different dates: neither."""
    asap, dates = [], {}
    for match in _START_ASAP.finditer(text):
        left, _ = _clause_bounds(text, match.start(), match.end())
        if not _NEGATION.search(text, left, match.start()):
            asap.append(_clause(text, match.start(), match.end()))
    for pattern in _START_BY:
        for match in pattern.finditer(text):
            left, right = _clause_bounds(text, match.start(), match.end())
            if _NEGATION.search(text, left, match.start()) or _PREFERENCE.search(text, left, right):
                continue
            by = _start_by(match, reference)
            if by:
                dates.setdefault(by, _clause(text, match.start(), match.end()))
    if len(dates) > 1:
        dates = {}
    if not dates and not asap:
        return _NOTHING
    return {"by": next(iter(dates), None), "asap": bool(asap)}, list(dict.fromkeys([*dates.values(), *asap]))


def _start_by(match, reference: date):
    """The date a start-by match names; a month is its last day. Without a year, the one nearest the reference."""
    month, day = int(match["m"]), int(match["d"]) if match["d"] else None
    if not 1 <= month <= 12 or (day is None and match["before"] and not match["end"]):
        return None  # "11月前到岗": before November, or by its end?
    year = int(match["y"]) if match["y"] else _nearest_year(month, 15 if day is None else day, reference)
    try:
        return date(year, month, calendar.monthrange(year, month)[1] if day is None else day).isoformat()
    except ValueError:
        return None


def _nearest_year(month: int, day: int, reference: date) -> int:
    """The year that puts a month and day nearest the reference date; the later one on a tie."""
    best = None
    for year in (reference.year - 1, reference.year, reference.year + 1):
        try:
            when = date(year, month, day)
        except ValueError:  # 29 February
            continue
        key = (abs((when - reference).days), when < reference)
        if best is None or key < best[0]:
            best = (key, year)
    return best[1] if best else reference.year


def _employment_type(text: str, headline: str):
    """From the title's own line first ("…实习生", "【校招】…"), then anywhere in the JD."""
    for pattern, kind in ((re.compile("实习"), "internship"), (_CAMPUS, "campus"), (_EXPERIENCED, "experienced")):
        if pattern.search(headline):
            return kind, [headline if len(headline) <= _MAX_SNIPPET else pattern.search(headline).group(0)]
    for pattern, kind in ((_INTERNSHIP, "internship"), (_CAMPUS, "campus"), (_EXPERIENCED, "experienced")):
        match = pattern.search(text)
        if match:
            return kind, [match.group(0)]
    return _NOTHING


def _salary(text: str):
    best = None
    for pattern, unit, scale in _SALARY:
        for match in pattern.finditer(text):
            low = float(match["lo"])
            high = float(match["hi"]) if match["hi"] else low
            if 0 < low <= high:
                if best is None or match.start() < best[0].start():
                    best = (match, unit, scale, low, high)
                break
    if best:
        match, unit, scale, low, high = best
        months = match.groupdict().get("months")
        months = int(months) if months and 12 <= int(months) <= 24 else None
        snippets = [match.group(0).strip()]
        if months is None and unit == "CNY/month":
            paid = _pay_months(text, match)
            if paid:
                months = int(paid["months"])
                snippets.append(paid.group(0).strip())
        value = {"min": _amount(low * scale), "max": _amount(high * scale), "unit": unit,
                 "months": months, "negotiable": False}
        return value, snippets
    match = _NEGOTIABLE.search(text)
    if match:
        value = {"min": None, "max": None, "unit": None, "months": None, "negotiable": True}
        return value, [match.group(0).strip()]
    return _NOTHING


def _pay_months(text: str, salary):
    """The "全年13薪" on the monthly salary's own line, unless it follows a 转正 (another offer's pay).

    On another line it may belong to another offer too, so it is left for an agent.
    """
    start = text.rfind("\n", 0, salary.start()) + 1
    end = text.find("\n", salary.end())
    for match in _PAY_MONTHS.finditer(text, start, len(text) if end < 0 else end):
        if "转正" in text[salary.end():match.start()]:
            return None
        if 12 <= int(match["months"]) <= 24:
            return match
    return None


def _graduation(text: str):
    for match in _GRADUATION.finditer(text):
        found = re.findall(r"(?:20)?(\d{2})", match["years"])
        years = sorted({2000 + int(two) for two in found})
        if _YEAR_RANGE.match(match["years"]) and len(years) == 2:
            years = list(range(years[0], years[1] + 1))
        if not years or years[0] < 2015 or years[-1] > 2040:
            continue
        clause = _clause(text, match.start(), match.end())
        return {"years": years, "strict": not _PREFERENCE.search(clause)}, [clause]
    return _NOTHING


def _days_per_week(text: str):
    match = _earliest(_DAYS, text)
    if match:
        days = _number(match["d"])
        if days and 1 <= days <= 7:
            return days, [match.group(0).strip()]
    return _NOTHING


def _min_months(text: str, tag: list):
    found = []
    for match in sorted((m for p in _MONTHS for m in p.finditer(text)), key=lambda m: m.start()):
        if "试用" in text[max(0, match.start() - 5):match.start()]:
            continue
        if re.search("经验|经历", _clause(text, match.start(), match.end())):
            continue
        count = {"半年": 6, "一年": 12}.get(match["n"]) or _number(match["n"])
        if count and 1 <= count <= 36:
            found.append((count, match.group(0).strip()))
    for cell in tag:
        match = _MONTHS_TAG.match(cell)
        count = _number(match["n"]) if match else None
        if count and 1 <= count <= 36:
            found.append((count, cell))
    if not found or len({count for count, _ in found}) > 1:
        # Several lengths - a platform's "3个月及以上" beside the job's "连续实习4个月以上" - are
        # left for an agent to read the job's own.
        return _NOTHING
    count, snippet = found[0]
    return count, [snippet]


def _education(text: str, tag: list):
    lowest = preferred = None
    snippets = []
    order = schema.EDUCATION_LEVELS
    candidates = []  # (start, end, level, snippet): the first one not a preference is the minimum
    choices = []  # (start, end, level, snippet) of every choice, for the preference too
    for match in _EDUCATION_CHOICE.finditer(text):
        level = min((_LEVELS[word] for word in re.findall(_LEVEL_WORD, match.group(0))), key=order.index)
        choices.append((match.start(), match.end(), level, match.group(0).strip()))
        if match["label"] or match["tail"]:
            candidates.append(choices[-1])
    for match in _EDUCATION_MIN.finditer(text):
        if not any(start <= match.start() < end for start, end, _, _ in candidates):
            candidates.append((match.start(), match.end(), _LEVELS[match.group(1) or match.group(2)],
                               match.group(0).strip()))
    for _, end, level, snippet in sorted(candidates):
        if _PREFERENCE.search(text[end:end + 4]):
            continue  # "硕士及以上学历优先" states a preference, not a minimum
        lowest = level
        snippets.append(snippet)
        break
    if lowest is None:
        match = _NO_MINIMUM_EDUCATION.search(text)
        if match:
            lowest = schema.NO_MINIMUM
            snippets.append(match.group(0).strip())
    if lowest is None:
        for cell in tag:
            if cell in _LEVELS:
                lowest = _LEVELS[cell]
                snippets.append(cell)
                break
    wanted = [(start, level, text[start:after.end()].strip()) for start, end, level, _ in choices
              for after in [_PREFERRED_AFTER.match(text, end)] if after]
    wanted += [(match.start(), _LEVELS[match.group(1)], match.group(0).strip())
               for match in _EDUCATION_PREFERRED.finditer(text)
               if not any(start <= match.start() < end for start, end, _, _ in choices)]
    if wanted:
        _, level, snippet = min(wanted)
        if lowest in (None, schema.NO_MINIMUM) or order.index(level) >= order.index(lowest):
            preferred = level
            snippets.append(snippet)
    if lowest is None and preferred is None:
        return _NOTHING
    return {"min": lowest, "preferred": preferred}, snippets


def _return_offer(text: str):
    match = _NO_RETURN_OFFER.search(text)
    if match:
        return False, [match.group(0)]
    match = _RETURN_OFFER.search(text)
    return (True, [match.group(0)]) if match else _NOTHING


def _dated(text: str, patterns, *, same_line=False):
    # Deadline patterns allow whitespace around the date. Restrict their
    # search to one physical line so a publication date cannot borrow the
    # next line's "截止", including through the date pattern's own whitespace.
    for part in text.splitlines() if same_line else [text]:
        match = _earliest(patterns, part)
        if not match:
            continue
        try:
            value = date(int(match["y"]), int(match["m"]), int(match["d"])).isoformat()
        except ValueError:
            return _NOTHING
        return value, [match.group(0).strip()]
    return _NOTHING


def _skill_hits(text: str, patterns, skip=None) -> list:
    """(match, term, key) wherever the JD asks for a vocabulary term, in text order; none in skip (the title)."""
    claimed, hits = ([skip] if skip else []), []
    intro = _intro_spans(text)
    for term, pattern, key in patterns:
        for match in pattern.finditer(text):
            if any(match.start() < end and start < match.end() for start, end in claimed):
                continue
            claimed.append((match.start(), match.end()))
            if _asked(text, term, match, intro):
                hits.append((match, term, key))
    return sorted(hits, key=lambda hit: hit[0].start())


def _skills(text: str, hits: list):
    """Vocabulary terms in order of first appearance."""
    first_seen = {}
    for match, term, _ in hits:
        first_seen.setdefault(term, match)
    if not first_seen:
        return _NOTHING
    snippets = []
    for match in first_seen.values():
        clause = _clause(text, match.start(), match.end())
        if clause not in snippets:
            snippets.append(clause)
    return list(first_seen), snippets


def _alternatives(text: str, hits: list):
    """Groups of skills the JD offers a choice between, each with the clauses that offer it.

    A run counts when it names two skills or more ("Go 或 Golang" is one skill). Choices
    that share a skill, a same_as spelling included, are one group: "熟悉 Python 或 Java；
    熟悉 Java 或 Go" is [Python, Java, Go], citing both clauses. A group keeps every
    spelling the JD used, so each one appears in a clause that is cited.
    """
    groups = []  # each [terms, keys, clauses], in the order first offered
    for run in _runs(text, hits):
        if not _offered_as_choice(text, run):
            continue
        terms, keys = list(dict.fromkeys(term for _, term, _ in run)), {key for _, _, key in run}
        if len(keys) < 2:
            continue
        clause = _clause(text, run[0][0].start(), run[-1][0].end())
        joined = [group for group in groups if group[1] & keys]
        if not joined:
            groups.append([terms, keys, [clause]])
            continue
        first = joined[0]
        for group in joined[1:] + [[terms, keys, [clause]]]:
            first[0] += [term for term in group[0] if term not in first[0]]
            first[1] |= group[1]
            first[2] += [c for c in group[2] if c not in first[2]]
        groups = [group for group in groups if not any(group is other for other in joined[1:])]
    if not groups:
        return _NOTHING
    snippets = []
    for _, _, clauses in groups:
        snippets += [clause for clause in clauses if clause not in snippets]
    return [terms for terms, _, _ in groups], snippets


def _runs(text: str, hits: list) -> list:
    """Hits joined only by 、 / 或 或者, each run with the joins between its hits."""
    runs = []
    for hit in hits:
        previous = runs[-1][-1][0] if runs else None
        if previous is not None and _JOIN.fullmatch(text, previous.end(), hit[0].start()):
            runs[-1].append(hit)
        else:
            runs.append([hit])
    return [run for run in runs if len(run) >= 2]


def _offered_as_choice(text: str, run: list) -> bool:
    start, end = run[0][0].start(), run[-1][0].end()
    if _MAJOR_AFTER.match(text, end) or _MAJOR_BEFORE.search(text, max(0, start - 8), start):
        return False
    if any("或" in text[a[0].end():b[0].start()] for a, b in zip(run, run[1:])):
        return True
    left, right = _clause_bounds(text, start, end)
    for mark in _ALT_MARK.finditer(text, left, right):
        if mark.start() >= end:
            gap = text[end:mark.start()]
        elif mark.end() <= start:
            gap = text[mark.end():start]
        else:
            continue
        if len(gap) <= _MARK_REACH and not _MARK_BREAK.search(gap):
            return True
    return False


def _asked(text: str, term: str, match, intro: list) -> bool:
    """Whether the JD asks for the skill it names here: not ruled out, not just the company's channel."""
    left, right = _clause_bounds(text, match.start(), match.end())
    if _NEGATION.search(text, left, match.start()):
        return False
    if _MAJOR_TAIL.match(text, match.end(), right) or _MAJOR_LEAD.search(text[left:match.start()]):
        return False  # a major, not a skill
    if term == "PS" and _postscript(text, match):
        return False
    if term in _PLATFORMS:
        clause = text[left:right]
        if _FOLLOW.search(clause) and _OURS.search(clause):
            return False
        if any(start <= match.start() < end for start, end in intro):
            return False
    return True


def _postscript(text: str, match) -> bool:
    """Whether a PS is the "PS：" that opens a line, a postscript."""
    line_start = text.rfind("\n", 0, match.start()) + 1
    return not text[line_start:match.start()].strip() and _AFTER_POSTSCRIPT.match(text, match.end()) is not None


def _intro_spans(text: str) -> list:
    """Where a company introduction runs: from its heading to the next section heading."""
    spans = []
    for intro in _INTRO.finditer(text):
        section = _SECTION.search(text, intro.end())
        spans.append((intro.start(), section.start() if section else len(text)))
    return spans
