from sqlalchemy import func, select, update
from sqlalchemy.orm import joinedload

from core.db import Base, engine, session_scope
from core.models import FundGroup, User, UserFund


DEFAULT_GROUP_NAME = '\u9ed8\u8ba4\u5206\u7ec4'
LEGACY_DEFAULT_GROUP_NAMES = {'Default', '\u9ed8\u8ba4', '\u9ed8\u8ba4\u5206\u7ec4'}


def init_database():
    Base.metadata.create_all(bind=engine)


def normalize_fund_code(code):
    return str(code or '').strip().zfill(6)


def _normalize_group_name(group):
    if group.is_default and group.name in LEGACY_DEFAULT_GROUP_NAMES:
        group.name = DEFAULT_GROUP_NAME
    return group.name


def ensure_user(client_id):
    normalized = str(client_id or '').strip()
    if not normalized:
        raise ValueError('Missing client_id')

    with session_scope() as session:
        user = session.execute(select(User).where(User.client_id == normalized)).scalar_one_or_none()
        if user:
            return user.id

        user = User(client_id=normalized, user_type='anonymous', initialized=False)
        session.add(user)
        session.flush()
        return user.id


def ensure_default_group(session, user_id):
    group = session.execute(
        select(FundGroup).where(FundGroup.user_id == user_id, FundGroup.is_default.is_(True))
    ).scalar_one_or_none()
    if group:
        _normalize_group_name(group)
        session.flush()
        return group

    max_sort = session.execute(
        select(func.max(FundGroup.sort_order)).where(FundGroup.user_id == user_id)
    ).scalar_one_or_none()
    group = FundGroup(
        user_id=user_id,
        name=DEFAULT_GROUP_NAME,
        sort_order=(max_sort or 0) + 1,
        is_default=True,
    )
    session.add(group)
    session.flush()
    return group


def list_groups_with_counts(client_id):
    user_id = ensure_user(client_id)
    with session_scope() as session:
        groups = session.execute(
            select(FundGroup)
            .where(FundGroup.user_id == user_id)
            .order_by(FundGroup.sort_order.asc(), FundGroup.id.asc())
        ).scalars().all()
        if not groups:
            ensure_default_group(session, user_id)
            groups = session.execute(
                select(FundGroup)
                .where(FundGroup.user_id == user_id)
                .order_by(FundGroup.sort_order.asc(), FundGroup.id.asc())
            ).scalars().all()

        counts = dict(session.execute(
            select(UserFund.group_id, func.count(UserFund.id))
            .where(UserFund.user_id == user_id)
            .group_by(UserFund.group_id)
        ).all())

        payload = []
        for group in groups:
            payload.append({
                'id': group.id,
                'name': _normalize_group_name(group),
                'sort_order': group.sort_order,
                'is_default': group.is_default,
                'count': int(counts.get(group.id, 0)),
            })
        session.flush()
        return payload


def list_user_funds(client_id):
    user_id = ensure_user(client_id)
    with session_scope() as session:
        funds = session.execute(
            select(UserFund)
            .where(UserFund.user_id == user_id)
            .options(joinedload(UserFund.group))
            .order_by(UserFund.sort_order.asc(), UserFund.id.asc())
        ).scalars().all()

        payload = []
        for fund in funds:
            group_name = ''
            if fund.group:
                group_name = _normalize_group_name(fund.group)
            payload.append({
                'code': fund.fund_code,
                'group_id': fund.group_id,
                'group_name': group_name,
                'sort_order': fund.sort_order,
            })
        session.flush()
        return payload


def get_user_snapshot(client_id):
    user_id = ensure_user(client_id)
    with session_scope() as session:
        user = session.execute(select(User).where(User.id == user_id)).scalar_one()
        groups = list_groups_with_counts(client_id)
        funds = list_user_funds(client_id)
        return {
            'client_id': user.client_id,
            'initialized': bool(user.initialized),
            'groups': groups,
            'funds': funds,
        }


def create_group(client_id, name):
    user_id = ensure_user(client_id)
    normalized_name = str(name or '').strip()
    if not normalized_name:
        raise ValueError('\u5206\u7ec4\u540d\u79f0\u4e0d\u80fd\u4e3a\u7a7a')

    with session_scope() as session:
        existing = session.execute(
            select(FundGroup).where(FundGroup.user_id == user_id, FundGroup.name == normalized_name)
        ).scalar_one_or_none()
        if existing:
            raise ValueError('\u5206\u7ec4\u540d\u79f0\u5df2\u5b58\u5728')

        max_sort = session.execute(
            select(func.max(FundGroup.sort_order)).where(FundGroup.user_id == user_id)
        ).scalar_one_or_none()
        group = FundGroup(
            user_id=user_id,
            name=normalized_name,
            sort_order=(max_sort or 0) + 1,
            is_default=False,
        )
        session.add(group)
        session.flush()
        return {
            'id': group.id,
            'name': group.name,
            'sort_order': group.sort_order,
            'is_default': group.is_default,
            'count': 0,
        }


def rename_group(client_id, group_id, name):
    user_id = ensure_user(client_id)
    normalized_name = str(name or '').strip()
    if not normalized_name:
        raise ValueError('\u5206\u7ec4\u540d\u79f0\u4e0d\u80fd\u4e3a\u7a7a')

    with session_scope() as session:
        group = session.execute(
            select(FundGroup).where(FundGroup.user_id == user_id, FundGroup.id == int(group_id))
        ).scalar_one_or_none()
        if not group:
            raise ValueError('\u5206\u7ec4\u4e0d\u5b58\u5728')
        if group.is_default:
            raise ValueError('\u9ed8\u8ba4\u5206\u7ec4\u4e0d\u652f\u6301\u91cd\u547d\u540d')

        existing = session.execute(
            select(FundGroup).where(
                FundGroup.user_id == user_id,
                FundGroup.name == normalized_name,
                FundGroup.id != group.id,
            )
        ).scalar_one_or_none()
        if existing:
            raise ValueError('\u5206\u7ec4\u540d\u79f0\u5df2\u5b58\u5728')

        group.name = normalized_name
        session.flush()
        return {
            'id': group.id,
            'name': group.name,
            'sort_order': group.sort_order,
            'is_default': group.is_default,
        }


def delete_group(client_id, group_id):
    user_id = ensure_user(client_id)

    with session_scope() as session:
        group = session.execute(
            select(FundGroup).where(FundGroup.user_id == user_id, FundGroup.id == int(group_id))
        ).scalar_one_or_none()
        if not group:
            raise ValueError('\u5206\u7ec4\u4e0d\u5b58\u5728')
        if group.is_default:
            raise ValueError('\u9ed8\u8ba4\u5206\u7ec4\u4e0d\u80fd\u5220\u9664')

        default_group = ensure_default_group(session, user_id)
        moved_count = session.execute(
            select(func.count(UserFund.id)).where(UserFund.user_id == user_id, UserFund.group_id == group.id)
        ).scalar_one()

        session.execute(
            update(UserFund)
            .where(UserFund.user_id == user_id, UserFund.group_id == group.id)
            .values(group_id=default_group.id)
        )

        session.delete(group)
        session.flush()
        return {
            'deleted': True,
            'moved_count': int(moved_count),
            'target_group_id': default_group.id,
            'target_group_name': _normalize_group_name(default_group),
        }


def add_or_update_user_fund(client_id, fund_code, group_id=None):
    user_id = ensure_user(client_id)
    code = normalize_fund_code(fund_code)
    if not code.isdigit() or len(code) != 6:
        raise ValueError('\u57fa\u91d1\u4ee3\u7801\u683c\u5f0f\u4e0d\u6b63\u786e')

    with session_scope() as session:
        if group_id is not None:
            group = session.execute(
                select(FundGroup).where(FundGroup.user_id == user_id, FundGroup.id == int(group_id))
            ).scalar_one_or_none()
            if not group:
                raise ValueError('\u5206\u7ec4\u4e0d\u5b58\u5728')
        else:
            group = ensure_default_group(session, user_id)

        fund = session.execute(
            select(UserFund).where(UserFund.user_id == user_id, UserFund.fund_code == code)
        ).scalar_one_or_none()
        if fund:
            fund.group_id = group.id if group else None
            session.flush()
            return {
                'code': fund.fund_code,
                'group_id': fund.group_id,
                'group_name': _normalize_group_name(group) if group else '',
                'updated': True,
            }

        max_sort = session.execute(
            select(func.max(UserFund.sort_order)).where(UserFund.user_id == user_id)
        ).scalar_one_or_none()
        fund = UserFund(
            user_id=user_id,
            group_id=group.id if group else None,
            fund_code=code,
            sort_order=(max_sort or 0) + 1,
        )
        session.add(fund)
        user = session.execute(select(User).where(User.id == user_id)).scalar_one()
        user.initialized = True
        session.flush()
        return {
            'code': fund.fund_code,
            'group_id': fund.group_id,
            'group_name': _normalize_group_name(group) if group else '',
            'updated': False,
        }


def move_user_fund(client_id, fund_code, group_id):
    user_id = ensure_user(client_id)
    code = normalize_fund_code(fund_code)

    with session_scope() as session:
        fund = session.execute(
            select(UserFund).where(UserFund.user_id == user_id, UserFund.fund_code == code)
        ).scalar_one_or_none()
        if not fund:
            raise ValueError('\u57fa\u91d1\u4e0d\u5b58\u5728')

        group = session.execute(
            select(FundGroup).where(FundGroup.user_id == user_id, FundGroup.id == int(group_id))
        ).scalar_one_or_none()
        if not group:
            raise ValueError('\u76ee\u6807\u5206\u7ec4\u4e0d\u5b58\u5728')

        fund.group_id = group.id
        session.flush()
        return {
            'code': fund.fund_code,
            'group_id': fund.group_id,
            'group_name': _normalize_group_name(group),
        }


def delete_user_fund(client_id, fund_code):
    user_id = ensure_user(client_id)
    code = normalize_fund_code(fund_code)

    with session_scope() as session:
        fund = session.execute(
            select(UserFund).where(UserFund.user_id == user_id, UserFund.fund_code == code)
        ).scalar_one_or_none()
        if not fund:
            return False
        session.delete(fund)
        return True


def bootstrap_user_funds(client_id, codes):
    user_id = ensure_user(client_id)
    normalized_codes = []
    seen = set()
    for code in codes or []:
      normalized = normalize_fund_code(code)
      if normalized in seen or not normalized.isdigit() or len(normalized) != 6:
          continue
      seen.add(normalized)
      normalized_codes.append(normalized)

    with session_scope() as session:
        current_count = session.execute(
            select(func.count(UserFund.id)).where(UserFund.user_id == user_id)
        ).scalar_one()
        if current_count > 0:
            user = session.execute(select(User).where(User.id == user_id)).scalar_one()
            user.initialized = True
            session.flush()
            return {'imported': 0, 'skipped': len(normalized_codes), 'already_initialized': True}

        default_group = ensure_default_group(session, user_id)
        for index, code in enumerate(normalized_codes, start=1):
            session.add(UserFund(
                user_id=user_id,
                group_id=default_group.id,
                fund_code=code,
                sort_order=index,
            ))
        user = session.execute(select(User).where(User.id == user_id)).scalar_one()
        user.initialized = True
        session.flush()
        return {'imported': len(normalized_codes), 'skipped': 0, 'already_initialized': False}
