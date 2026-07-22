import os
import sys
from pathlib import Path

from flask import Flask, Response, abort, request, url_for

from core.settings import build_mysql_uri
from routes import register_blueprints
from services.dca_plan_service import start_dca_plan_scheduler
from services.fund_service import start_background_refresh_thread
from services.fund_transaction_service import start_pending_transaction_confirmation_scheduler
from services.user_fund_service import init_database


def create_app():
    app = Flask(__name__, static_folder='static', template_folder='templates')
    app.config['DB_URI'] = build_mysql_uri()
    app.config['DB_URI_MASKED'] = build_mysql_uri(mask_password=True)
    app.config['ASSET_VERSION'] = _build_asset_version(app.static_folder)

    init_database()
    register_blueprints(app)
    if os.getenv('WERKZEUG_RUN_MAIN') == 'true' or os.getenv('FLASK_DEBUG', '1').strip().lower() in ('0', 'false', 'no'):
        start_background_refresh_thread()
        start_pending_transaction_confirmation_scheduler()
        start_dca_plan_scheduler()

    def asset_url(filename):
        normalized = str(filename or '').lstrip('/')
        if normalized.startswith('static/'):
            normalized = normalized[7:]

        version = '1'
        try:
            asset_path = Path(app.static_folder) / normalized
            version = str(int(asset_path.stat().st_mtime))
        except OSError:
            pass

        return url_for('static', filename=normalized, v=version)

    def js_asset_url(filename):
        normalized = str(filename or '').lstrip('/')
        if normalized.startswith('static/js/'):
            normalized = normalized[10:]
        elif normalized.startswith('js/'):
            normalized = normalized[3:]
        return url_for('js_asset', filename=normalized, v=app.config['ASSET_VERSION'])

    @app.context_processor
    def inject_asset_helpers():
        return {
            'asset_url': asset_url,
            'js_asset_url': js_asset_url,
        }

    @app.route('/assets/js/<path:filename>')
    def js_asset(filename):
        root = Path(app.static_folder) / 'js'
        target = (root / filename).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            abort(404)
        if not target.is_file() or target.suffix != '.js':
            abort(404)

        content = target.read_text(encoding='utf-8')
        content = content.replace('__APP_ASSET_VERSION__', app.config['ASSET_VERSION'])
        return Response(content, mimetype='application/javascript; charset=utf-8')

    @app.after_request
    def apply_cache_headers(response):
        if request.endpoint in ('static', 'js_asset'):
            if request.args.get('v'):
                response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
            else:
                response.headers['Cache-Control'] = 'no-cache'
            return response

        content_type = response.headers.get('Content-Type', '')
        if 'text/html' in content_type:
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response

    return app


def _build_asset_version(static_folder):
    explicit = os.getenv('APP_ASSET_VERSION', '').strip()
    if explicit:
        return explicit

    js_dir = Path(static_folder) / 'js'
    latest_mtime = 0
    try:
        for path in js_dir.rglob('*.js'):
            latest_mtime = max(latest_mtime, int(path.stat().st_mtime))
    except OSError:
        latest_mtime = 0
    return str(latest_mtime or int(Path(__file__).stat().st_mtime))


app = create_app()


if __name__ == '__main__':
    debug_enabled = os.getenv('FLASK_DEBUG', '1').strip().lower() not in ('0', 'false', 'no')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
    print('启动基金监控服务...')
    print('请在浏览器访问 http://127.0.0.1:5000')
    print(f'调试模式: {"on" if debug_enabled else "off"}')
    app.run(
        host='127.0.0.1',
        port=5000,
        debug=debug_enabled,
        use_reloader=debug_enabled,
    )
