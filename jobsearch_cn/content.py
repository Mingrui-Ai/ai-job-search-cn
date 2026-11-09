"""Generic rejection of whole-section UI placeholders; accepted text is unchanged."""

import re
import unicodedata

# Whole-section UI notices may put the object before or after the status. A status
# signal is also required, so short duties such as "加载数据" remain valid content.
_DESCRIPTION_HEADINGS = re.compile(
    r"职位描述|岗位描述|职位详情|岗位详情|岗位职责|工作职责|工作内容|任职要求|任职资格|岗位要求|职位要求|"
    # Bound modifier lookback so repeated "job " in a long JD is still linear to scan.
    r"\b(?:(?:job|position|role|candidate|key|main|required|preferred|minimum|basic|essential|desired)[\s_-]+){0,4}"
    r"(?:descriptions?|details?|responsibilities|requirements|qualifications|duties|skills|overview|summary)\b", re.I)
_UI_OBJECT = ("职位|岗位|工作|描述|详情|要求|内容|信息|数据|页面|网络|系统|服务器|请求|jobs?|positions?|descriptions?|"
              "details?|requirements?|content|data|pages?|information|network|system|server|requests?")
_UI_STATE = ("正在|加载|载入|读取|获取|中|失败|错误|异常|暂无|超时|loading|loaded|load|failed|failure|error|"
             "unavailable|unable|couldnot|couldnt|cannot|cant|timeout|timedout|somethingwentwrong")
_UI_PROMPT = ("请|您|稍候|稍后|稍等|片刻|一下|一会儿?|一小会|几|秒钟?|分钟|耐心|等待|刷新|重试|再试|重新|为您|抱歉|"
              "点击|please|wait|waiting|a|an|the|your|this|for|while|we|are|is|be|to|of|and|just|moments?|seconds?|"
              "minutes?|few|short|little|bit|refresh|reload|retry|try|again|later|sorry")
_PLACEHOLDER_DESCRIPTION = re.compile(f"(?:{_UI_OBJECT}|{_UI_STATE}|{_UI_PROMPT})+", re.I)
_UI_STATUS_SIGNAL = re.compile(
    r"正在(?:为您)?(?:加载|载入|读取|获取)|(?:加载|载入|读取|获取)中|失败|错误|异常|超时|"
    r"请(?:您)?(?:稍候|稍后|稍等|耐心|等待|刷新|重试)|稍候|稍后|稍等|暂无|"
    r"loading|failed|failure|error|unavailable|unable|couldnot|couldnt|cannot|cant|pleasewait|waiting|wait(?:for)?a?moment|"
    r"justamoment|refresh|reload|retry|tryagain|timeout|timedout|somethingwentwrong", re.I)

def placeholder_description(content: str) -> bool:
    """Recognise an entire loading notice, not these words embedded in real duties."""
    # Only the check is normalised; accepted JD text is saved verbatim. Match headings
    # before removing separators so English word boundaries remain meaningful.
    normalized = unicodedata.normalize("NFKC", content)
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Cf")
    body = _DESCRIPTION_HEADINGS.sub("", normalized)
    compact = "".join(char for char in body.casefold() if char.isalpha())
    return not compact or bool(_UI_STATUS_SIGNAL.search(compact) and _PLACEHOLDER_DESCRIPTION.fullmatch(compact))
