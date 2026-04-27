from flask import Blueprint, render_template, request

from core.perf_metrics import snapshot_metrics
from core.settings import ENABLE_PERF_DEBUG_METRICS, PERF_DEBUG_TOKEN
from routes.common import json_response


site_bp = Blueprint('site', __name__)


@site_bp.route('/')
def index():
    return render_template('index.html')


@site_bp.route('/health', methods=['GET'])
def health():
    return 'ok', 200


@site_bp.route('/api/debug/performance', methods=['GET'])
def performance_metrics():
    if not ENABLE_PERF_DEBUG_METRICS:
        return json_response({'error': 'Not found'}, 404)

    if PERF_DEBUG_TOKEN:
        incoming_token = request.headers.get('X-Debug-Token', '').strip()
        if incoming_token != PERF_DEBUG_TOKEN:
            return json_response({'error': 'Forbidden'}, 403)

    return json_response(snapshot_metrics())
