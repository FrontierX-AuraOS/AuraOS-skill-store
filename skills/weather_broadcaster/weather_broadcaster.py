"""
Weather Broadcaster Skill — fetch real-time weather for the current location,
format it as a natural spoken Chinese broadcast, and deliver it via TTS.
天气播报技能——获取当前位置的实时天气，整理成自然口语化中文播报稿并通过语音合成播报。
"""

import json
from urllib.request import urlopen, Request
from urllib.error import URLError


# ── location helpers ──────────────────────────────────────────────

def _get_location() -> dict | None:
    """Resolve approximate city / coordinates from the client's public IP.

    Uses ip-api.com (free tier, no key).  Returns *None* on any failure so the
    caller can fall back to a hard-coded default.
    """
    try:
        req = Request(
            "http://ip-api.com/json/?fields=status,city,regionName,country,lat,lon",
            headers={"User-Agent": "AuraOS/1.0"},
        )
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        if data.get("status") == "success":
            return {
                "city": data.get("city", "未知城市"),
                "region": data.get("regionName", ""),
                "country": data.get("country", ""),
                "lat": data.get("lat"),
                "lon": data.get("lon"),
            }
    except Exception:
        pass
    return None


# ── weather helpers ───────────────────────────────────────────────

_WMO_WEATHER: dict[int, str] = {
    0: "晴朗", 1: "大部晴朗", 2: "多云", 3: "阴天",
    45: "有雾", 48: "有雾凇",
    51: "小毛毛雨", 53: "中毛毛雨", 55: "大毛毛雨",
    56: "小冻毛毛雨", 57: "大冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "小冻雨", 67: "大冻雨",
    71: "小雪", 73: "中雪", 75: "大雪",
    77: "雪粒",
    80: "小阵雨", 81: "中阵雨", 82: "大阵雨",
    85: "小阵雪", 86: "大阵雪",
    95: "雷暴", 96: "雷暴伴小冰雹", 99: "雷暴伴大冰雹",
}

_WIND_DIRS = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]


def _wind_dir_text(degrees: float) -> str:
    return _WIND_DIRS[round(degrees / 45) % 8]


def _fetch_weather(lat: float, lon: float) -> dict:
    """Call Open-Meteo (free, no API key required) for current conditions."""
    url = (
        "https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        "&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
        "weather_code,wind_speed_10m,wind_direction_10m,wind_gusts_10m"
        "&timezone=auto"
    )
    req = Request(url, headers={"User-Agent": "AuraOS/1.0"})
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _build_broadcast(city: str, loc_source: str, current: dict) -> str:
    """Compose a natural-sounding spoken broadcast from the raw API payload."""
    temp = current["temperature_2m"]
    feels = current["apparent_temperature"]
    humidity = current["relative_humidity_2m"]
    wind_speed = current["wind_speed_10m"]
    wind_dir = current["wind_direction_10m"]
    wind_gusts = current.get("wind_gusts_10m", 0)
    code = current["weather_code"]
    weather = _WMO_WEATHER.get(code, f"未知天气(code:{code})")

    # build the core bulletin
    lines = [
        "各位好，欢迎收听今天的天气播报！☀️",
        "",
        f"📌 播报地点：{city}（{loc_source}）",
        f"🌡️ 当前气温：{temp}°C，体感温度 {feels}°C",
        f"☁️ 天气状况：{weather}",
        f"💧 相对湿度：{humidity}%",
        f"🌬️ 风力风向：{_wind_dir_text(wind_dir)}风 {wind_speed} 级",
    ]
    if wind_gusts > 0:
        lines.append(f"    📈 阵风可达 {wind_gusts} 级")

    # ── lifestyle tips ──
    tips: list[str] = []
    if temp > 35:
        tips.append("天气炎热，出门记得防晒和补水哦！")
    elif temp > 30:
        tips.append("天气较热，建议穿轻薄透气的衣物。")
    elif temp < 5:
        tips.append("天冷注意保暖，出门记得穿厚外套！")
    elif temp < 15:
        tips.append("温度偏凉，建议加件外套。")

    rain_codes = {51, 53, 55, 61, 63, 65, 80, 81, 82, 95, 96, 99}
    snow_codes = {71, 73, 75, 77, 85, 86}

    if code in rain_codes:
        tips.append("今天有雨，出门记得带伞！🌂")
    if code in snow_codes:
        tips.append("有雪，注意路滑，开车小心！❄️")
    if humidity > 80:
        tips.append("湿度较大，体感可能会有些闷热。")

    if tips:
        lines.append("")
        lines.append("💡 生活提醒：" + " ".join(tips))

    lines.append("")
    lines.append("以上就是今天的天气播报，祝您有美好的一天！🌈")
    return "\n".join(lines)


# ── entry point ────────────────────────────────────────────────────

async def run(agent, task: str = "") -> str:
    """Fetch weather and broadcast it through the robot's speaker.

    Parameters
    ----------
    agent : LocalAgent
        The running agent instance providing ``_pipeline.speak`` and
        ``_tools`` access.
    task : str
        Optional natural-language hint from the model (e.g. a city name or
        extra instruction).  Currently reserved for future use.

    Returns
    -------
    str
        A JSON string with the weather summary so the model can show it in
        the chat as well.
    """

    # 1. resolve location ──────────────────────────────────────────
    loc = _get_location()
    if loc and loc.get("lat") is not None:
        city = loc["city"]
        lat, lon = loc["lat"], loc["lon"]
        loc_source = "IP自动定位"
    else:
        city = "北京"
        lat, lon = 39.9042, 116.4074
        loc_source = "默认城市（北京，定位未成功）"

    # 2. fetch weather ──────────────────────────────────────────────
    try:
        weather_data = _fetch_weather(lat, lon)
    except URLError as exc:
        err = f"❌ 获取天气数据失败：网络请求错误，请检查网络连接后重试。\n详情：{exc}"
        await agent._pipeline.speak(err)
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    except Exception as exc:
        err = f"❌ 获取天气数据时出现异常：{exc}"
        await agent._pipeline.speak(err)
        return json.dumps({"error": str(exc)}, ensure_ascii=False)

    # 3. build & speak broadcast ────────────────────────────────────
    current = weather_data["current"]
    broadcast = _build_broadcast(city, loc_source, current)

    try:
        await agent._pipeline.speak(broadcast)
    except Exception as exc:
        # If TTS fails we still return data so the model can display text
        return json.dumps({
            "city": city,
            "temperature": current["temperature_2m"],
            "feels_like": current["apparent_temperature"],
            "weather": _WMO_WEATHER.get(current["weather_code"], "未知"),
            "humidity": current["relative_humidity_2m"],
            "wind_speed": current["wind_speed_10m"],
            "wind_direction": _wind_dir_text(current["wind_direction_10m"]),
            "broadcast_text": broadcast,
            "tts_error": str(exc),
        }, ensure_ascii=False)

    return json.dumps({
        "city": city,
        "temperature": current["temperature_2m"],
        "feels_like": current["apparent_temperature"],
        "weather": _WMO_WEATHER.get(current["weather_code"], "未知"),
        "humidity": current["relative_humidity_2m"],
        "wind_speed": current["wind_speed_10m"],
        "wind_direction": _wind_dir_text(current["wind_direction_10m"]),
        "broadcast_text": broadcast,
    }, ensure_ascii=False)