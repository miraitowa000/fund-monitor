from flask import jsonify, request

from services.auth_service import require_registered_user_id


def add_cors_headers(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-Client-Id')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response


def json_response(payload, status=200):
    response = jsonify(payload)
    response.status_code = status
    return add_cors_headers(response)


def get_client_id():
    client_id = request.headers.get('X-Client-Id', '').strip()
    return client_id or None


def require_client_id():
    client_id = get_client_id()
    if not client_id:
        return None, json_response({'error': 'Missing X-Client-Id header'}, 400)
    return client_id, None


def require_registered_user():
    client_id, error = require_client_id()
    if error:
        return None, None, error
    try:
        user_id = require_registered_user_id(client_id)
        return client_id, user_id, None
    except PermissionError as exc:
        return client_id, None, json_response({'error': str(exc)}, 401)
    except ValueError as exc:
        return None, None, json_response({'error': str(exc)}, 400)
