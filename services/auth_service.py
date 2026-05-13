import re
from datetime import datetime

from sqlalchemy import select
from werkzeug.security import check_password_hash, generate_password_hash

from core.db import session_scope
from core.models import User
from services.user_fund_service import ensure_user


EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
PHONE_RE = re.compile(r'^1[3-9]\d{9}$')


def normalize_account(account):
    value = str(account or '').strip()
    if '@' in value:
        value = value.lower()
    return value


def validate_account(account):
    normalized = normalize_account(account)
    if EMAIL_RE.match(normalized):
        return normalized, 'email'
    if PHONE_RE.match(normalized):
        return normalized, 'phone'
    raise ValueError('账号格式不正确，请输入正确的手机号或邮箱')


def validate_password(password):
    value = str(password or '')
    if len(value) < 6:
        raise ValueError('密码长度不能少于 6 位')
    if len(value) > 72:
        raise ValueError('密码长度不能超过 72 位')
    return value


def serialize_auth_user(user):
    return {
        'id': user.id,
        'client_id': user.client_id,
        'account': user.username,
        'user_type': user.user_type,
        'registered': user.user_type == 'registered',
        'last_login_at': user.last_login_at.strftime('%Y-%m-%d %H:%M:%S') if user.last_login_at else None,
    }


def get_auth_user_by_client_id(client_id):
    normalized_client_id = str(client_id or '').strip()
    if not normalized_client_id:
        return None

    with session_scope() as session:
        user = session.execute(
            select(User).where(User.client_id == normalized_client_id)
        ).scalar_one_or_none()
        return serialize_auth_user(user) if user else None


def register_account(client_id, account, password):
    normalized_account, account_type = validate_account(account)
    password_value = validate_password(password)
    user_id = ensure_user(client_id)

    with session_scope() as session:
        existing = session.execute(
            select(User).where(User.username == normalized_account, User.id != user_id)
        ).scalar_one_or_none()
        if existing:
            raise ValueError('该账号已注册，请直接登录')

        user = session.execute(select(User).where(User.id == user_id)).scalar_one()
        if user.user_type == 'registered' and user.username and user.username != normalized_account:
            raise ValueError('当前设备已绑定其他账号，请先切换账号后再注册')

        user.username = normalized_account
        user.user_type = 'registered'
        user.password_hash = generate_password_hash(password_value)
        user.last_login_at = datetime.utcnow()
        session.flush()
        result = serialize_auth_user(user)
        result['account_type'] = account_type
        return result


def login_account(account, password):
    normalized_account, account_type = validate_account(account)
    password_value = validate_password(password)

    with session_scope() as session:
        user = session.execute(
            select(User).where(User.username == normalized_account, User.user_type == 'registered')
        ).scalar_one_or_none()
        if not user or not user.password_hash or not check_password_hash(user.password_hash, password_value):
            raise ValueError('账号或密码不正确')

        user.last_login_at = datetime.utcnow()
        session.flush()
        result = serialize_auth_user(user)
        result['account_type'] = account_type
        return result


def require_registered_user_id(client_id):
    normalized_client_id = str(client_id or '').strip()
    if not normalized_client_id:
        raise ValueError('Missing X-Client-Id header')

    with session_scope() as session:
        user = session.execute(
            select(User).where(User.client_id == normalized_client_id)
        ).scalar_one_or_none()
        if not user or user.user_type != 'registered':
            raise PermissionError('请先注册或登录后使用交易功能')
        return user.id
