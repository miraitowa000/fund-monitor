from datetime import datetime, timedelta, timezone


CHINA_TZ = timezone(timedelta(hours=8), name='Asia/Shanghai')


def china_now():
    return datetime.now(CHINA_TZ)


def china_today():
    return china_now().date()


def timestamp_to_china_datetime(timestamp):
    return datetime.fromtimestamp(float(timestamp), tz=CHINA_TZ)
